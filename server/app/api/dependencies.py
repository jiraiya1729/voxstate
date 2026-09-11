from functools import lru_cache

import boto3
from botocore.config import Config
from cartesia import AsyncCartesia

from app.calls.service import CallLifecycleService, CallService
from app.core.settings import get_settings
from app.db.database import Database
from app.voice.bedrock import BedrockLanguageModel, BedrockRuntimeClient
from app.voice.cartesia_stt import CartesiaSTTProvider
from app.voice.cartesia_tts import CartesiaSpeechSynthesizer
from app.voice.sessions import ActiveCallRegistry, MediaSessionService
from app.voice.twilio import TwilioTelephonyGateway, TwilioWebhookVerifier


@lru_cache
def get_database() -> Database:
    settings = get_settings()
    return Database.from_url(str(settings.database_url))


@lru_cache
def get_telephony_gateway() -> TwilioTelephonyGateway:
    settings = get_settings()
    return TwilioTelephonyGateway(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token.get_secret_value(),
        from_number=settings.twilio_phone_number,
        public_base_url=str(settings.public_base_url),
    )


@lru_cache
def get_twilio_webhook_verifier() -> TwilioWebhookVerifier:
    settings = get_settings()
    return TwilioWebhookVerifier(
        auth_token=settings.twilio_auth_token.get_secret_value(),
        public_base_url=str(settings.public_base_url),
    )


@lru_cache
def get_active_call_registry() -> ActiveCallRegistry:
    return ActiveCallRegistry()


@lru_cache
def get_cartesia_client() -> AsyncCartesia:
    settings = get_settings()
    return AsyncCartesia(api_key=settings.cartesia_api_key.get_secret_value())


@lru_cache
def get_stt_provider() -> CartesiaSTTProvider:
    return CartesiaSTTProvider(get_cartesia_client())


@lru_cache
def get_bedrock_runtime_client() -> BedrockRuntimeClient:
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
    settings = get_settings()
    return BedrockLanguageModel(
        client=get_bedrock_runtime_client(),
        model_id=settings.bedrock_model_id,
        timeout_seconds=20.0,
    )


@lru_cache
def get_speech_synthesizer() -> CartesiaSpeechSynthesizer:
    settings = get_settings()
    return CartesiaSpeechSynthesizer(
        client=get_cartesia_client(),
        voice_id=settings.cartesia_voice_id,
    )


def get_media_session_service() -> MediaSessionService:
    return MediaSessionService(
        database=get_database(),
        registry=get_active_call_registry(),
        stt_provider=get_stt_provider(),
        language_model=get_language_model(),
        speech_synthesizer=get_speech_synthesizer(),
    )


def get_call_service() -> CallService:
    return CallService(
        database=get_database(),
        telephony=get_telephony_gateway(),
    )


def get_call_lifecycle_service() -> CallLifecycleService:
    return CallLifecycleService(database=get_database())


async def close_application_dependencies() -> None:
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
