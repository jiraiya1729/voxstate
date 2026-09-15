"""Dependency wiring for the FastAPI app.

This file builds shared database, provider, call, agent, routing, transfer, and live
media-session services used by route handlers.
"""

from functools import lru_cache

import boto3
from botocore.config import Config
from cartesia import AsyncCartesia

from app.agents.routing import RoutingService
from app.agents.service import AgentService
from app.calls.inbound import InboundCallService
from app.calls.lifecycle_service import CallLifecycleService
from app.calls.outbound import CallService
from app.calls.transfers import TransferService
from app.core.settings import get_settings
from app.db.database import Database
from app.voice.providers.bedrock import BedrockLanguageModel, BedrockRuntimeClient
from app.voice.providers.cartesia_stt import CartesiaSTTProvider
from app.voice.providers.cartesia_tts import CartesiaSpeechSynthesizer
from app.voice.runtime import AgentRuntimeFactory
from app.voice.sessions.service import ActiveCallRegistry, MediaSessionService
from app.voice.twilio.gateway import TwilioTelephonyGateway, TwilioWebhookVerifier


@lru_cache
def get_database() -> Database:
    # Shared SQLAlchemy/Supabase database wrapper for service transactions.
    settings = get_settings()
    return Database.from_url(str(settings.database_url))


@lru_cache
def get_telephony_gateway() -> TwilioTelephonyGateway:
    # Outbound Twilio command gateway: starts and updates calls through Twilio.
    settings = get_settings()
    return TwilioTelephonyGateway(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token.get_secret_value(),
        from_number=settings.twilio_phone_number,
        public_base_url=str(settings.public_base_url),
    )


@lru_cache
def get_twilio_webhook_verifier() -> TwilioWebhookVerifier:
    # Inbound Twilio request verifier: checks webhook and media signatures.
    settings = get_settings()
    return TwilioWebhookVerifier(
        auth_token=settings.twilio_auth_token.get_secret_value(),
        public_base_url=str(settings.public_base_url),
    )


@lru_cache
def get_active_call_registry() -> ActiveCallRegistry:
    # In-memory registry for live Twilio media streams in this process.
    return ActiveCallRegistry()


@lru_cache
def get_cartesia_client() -> AsyncCartesia:
    # Shared Cartesia SDK client reused by STT and TTS adapters.
    settings = get_settings()
    return AsyncCartesia(api_key=settings.cartesia_api_key.get_secret_value())


@lru_cache
def get_stt_provider() -> CartesiaSTTProvider:
    # Provider adapter that opens Cartesia streaming STT sessions.
    return CartesiaSTTProvider(get_cartesia_client())


@lru_cache
def get_bedrock_runtime_client() -> BedrockRuntimeClient:
    # Low-level AWS Bedrock SDK client reused by language-model adapters.
    settings = get_settings()
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=5,
            read_timeout=20,
            retries={"mode": "standard", "total_max_attempts": 2},
            tcp_keepalive=True,
        ),
    )


@lru_cache
def get_language_model() -> BedrockLanguageModel:
    # Default app-level LLM adapter used when a call is not pinned to an agent.
    settings = get_settings()
    return BedrockLanguageModel(
        client=get_bedrock_runtime_client(),
        model_id=settings.bedrock_model_id,
        timeout_seconds=20.0,
    )


@lru_cache
def get_speech_synthesizer() -> CartesiaSpeechSynthesizer:
    # Default app-level TTS adapter used when a call is not pinned to an agent.
    settings = get_settings()
    return CartesiaSpeechSynthesizer(
        client=get_cartesia_client(),
        voice_id=settings.cartesia_voice_id,
    )


@lru_cache
def get_agent_runtime_factory() -> AgentRuntimeFactory:
    # Builds per-agent voice runtimes from stored agent config and shared clients.
    return AgentRuntimeFactory(
        bedrock_client=get_bedrock_runtime_client(),
        cartesia_client=get_cartesia_client(),
    )


def get_media_session_service() -> MediaSessionService:
    # Live media use case: binds Twilio streams to STT, LLM, TTS, and playback.
    return MediaSessionService(
        database=get_database(),
        registry=get_active_call_registry(),
        stt_provider=get_stt_provider(),
        language_model=get_language_model(),
        speech_synthesizer=get_speech_synthesizer(),
        runtime_factory=get_agent_runtime_factory(),
    )


def get_call_service() -> CallService:
    # Outbound call use case: creates a call record and asks Twilio to dial.
    return CallService(
        database=get_database(),
        telephony=get_telephony_gateway(),
    )


def get_call_lifecycle_service() -> CallLifecycleService:
    # Provider lifecycle use case: applies Twilio status callbacks to calls.
    return CallLifecycleService(database=get_database())


def get_agent_service() -> AgentService:
    # Agent CRUD use case for API routes.
    return AgentService(get_database())


def get_routing_service() -> RoutingService:
    # Deterministic inbound-call routing use case.
    return RoutingService(get_database())


def get_inbound_call_service() -> InboundCallService:
    # Inbound Twilio call use case: route destination and persist the call.
    return InboundCallService(database=get_database(), routing=get_routing_service())


def get_transfer_service() -> TransferService:
    # Transfer use case for live agent handoff and Twilio human handoff.
    return TransferService(
        database=get_database(),
        registry=get_active_call_registry(),
        runtime_factory=get_agent_runtime_factory(),
        telephony=get_telephony_gateway(),
    )


async def close_application_dependencies() -> None:
    # Shutdown hook for cached resources that own sockets, pools, or live sessions.
    if get_active_call_registry.cache_info().currsize:
        await get_active_call_registry().close_all()

    if get_bedrock_runtime_client.cache_info().currsize:
        get_bedrock_runtime_client().close()

    if get_cartesia_client.cache_info().currsize:
        await get_cartesia_client().close()

    if get_database.cache_info().currsize:
        await get_database().close()

    get_database.cache_clear()
    get_telephony_gateway.cache_clear()
    get_twilio_webhook_verifier.cache_clear()
    get_active_call_registry.cache_clear()
    get_cartesia_client.cache_clear()
    get_stt_provider.cache_clear()
    get_bedrock_runtime_client.cache_clear()
    get_language_model.cache_clear()
    get_speech_synthesizer.cache_clear()
    get_agent_runtime_factory.cache_clear()
