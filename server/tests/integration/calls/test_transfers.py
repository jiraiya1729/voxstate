from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

import pytest
from sqlalchemy import select

from app.agents.schemas import AgentCreate
from app.agents.service import AgentService
from app.calls.models import CallTransfer
from app.calls.repository import CallRepository
from app.calls.telephony import TelephonyProviderError
from app.calls.transfers import (
    TransferConflictError,
    TransferProviderError,
    TransferService,
)
from app.db.database import Database
from app.voice.conversation.response import ConversationSession, Message
from app.voice.runtime import AgentRuntime
from app.voice.sessions.service import ActiveCallRegistry, ActiveCallSession


class Transcriber:
    closed = False

    async def send_audio(self, audio: bytes) -> None:
        pass

    async def close(self) -> bool:
        self.closed = True
        return True


class Model:
    async def generate(self, *, system_prompt: str, messages: Sequence[Message]) -> str:
        return "ok"


class Observer:
    async def on_response(self, call_id, text, **kwargs):
        return None

    async def interrupt(self, call_id):
        return False


class Synthesizer:
    async def synthesize(
        self, text: str, *, on_audio: Callable[[bytes], Awaitable[None]]
    ) -> None:
        await on_audio(b"voice")


class RuntimeFactory:
    def build(self, agent) -> AgentRuntime:
        return AgentRuntime(agent.system_prompt, Model(), Synthesizer())


class Gateway:
    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.transfers: list[tuple[str, str, UUID]] = []

    async def transfer_call(
        self, *, provider_call_id: str, to_number: str, transfer_id: UUID
    ) -> None:
        self.transfers.append((provider_call_id, to_number, transfer_id))
        if self.failure:
            raise TelephonyProviderError(self.failure)


async def discard(audio: bytes) -> None:
    pass


async def create_agent(database: Database, name: str):
    return await AgentService(database).create(
        AgentCreate(
            name=name,
            system_prompt=f"{name} prompt",
            bedrock_model_id=f"model-{name}",
            cartesia_voice_id=f"voice-{name}",
        )
    )


async def active_call(database: Database, registry: ActiveCallRegistry, agent_id: UUID):
    async with database.session() as session:
        call = await CallRepository(session).create(
            to_phone_number="+15555550401", agent_id=agent_id
        )
        await CallRepository(session).mark_provider_accepted(
            call_id=call.id, provider_call_id="CA401"
        )
    conversation = ConversationSession(
        call_id=call.id,
        language_model=Model(),
        response_observer=Observer(),
        system_prompt="source",
    )
    active = ActiveCallSession(
        call_id=call.id,
        provider_call_id="CA401",
        stream_sid="MZ401",
        transcriber=Transcriber(),
        conversation=conversation,
        active_agent_id=agent_id,
        visited_agent_ids={agent_id},
        audio_sink=discard,
    )
    await registry.register(active)
    return call, active


@pytest.mark.asyncio
async def test_agent_transfer_is_persisted_idempotent_and_loop_safe(
    database: Database,
) -> None:
    source = await create_agent(database, "Source")
    target = await create_agent(database, "Target")
    registry = ActiveCallRegistry()
    call, active = await active_call(database, registry, source.id)
    service = TransferService(
        database=database,
        registry=registry,
        runtime_factory=RuntimeFactory(),
        telephony=Gateway(),
    )
    result = await service.transfer_to_agent(
        call_id=call.id, target_agent_id=target.id, idempotency_key="agent-1"
    )
    replay = await service.transfer_to_agent(
        call_id=call.id, target_agent_id=target.id, idempotency_key="agent-1"
    )
    assert result.status == replay.status == "completed"
    assert result.id == replay.id
    assert active.active_agent_id == target.id
    async with database.session() as session:
        stored = await CallRepository(session).get_by_id(call.id)
    assert stored is not None and stored.active_agent_id == target.id
    with pytest.raises(TransferConflictError, match="loop"):
        await service.transfer_to_agent(
            call_id=call.id, target_agent_id=source.id, idempotency_key="agent-2"
        )


@pytest.mark.asyncio
async def test_human_transfer_closes_ai_only_after_provider_acceptance(
    database: Database,
) -> None:
    source = await create_agent(database, "Human Source")
    registry = ActiveCallRegistry()
    call, active = await active_call(database, registry, source.id)
    gateway = Gateway()
    service = TransferService(
        database=database,
        registry=registry,
        runtime_factory=RuntimeFactory(),
        telephony=gateway,
    )
    result = await service.transfer_to_human(
        call_id=call.id, to_number="+15555550402", idempotency_key="human-1"
    )
    replay = await service.transfer_to_human(
        call_id=call.id, to_number="+15555550402", idempotency_key="human-1"
    )
    assert result.status == "accepted"
    assert replay.id == result.id
    assert len(gateway.transfers) == 1
    assert active.closed is True


@pytest.mark.asyncio
async def test_human_transfer_provider_failure_keeps_ai_session(
    database: Database,
) -> None:
    source = await create_agent(database, "Failure Source")
    registry = ActiveCallRegistry()
    call, active = await active_call(database, registry, source.id)
    service = TransferService(
        database=database,
        registry=registry,
        runtime_factory=RuntimeFactory(),
        telephony=Gateway("twilio_unavailable"),
    )
    with pytest.raises(TransferProviderError, match="twilio_unavailable"):
        await service.transfer_to_human(
            call_id=call.id, to_number="+15555550403", idempotency_key="human-fail"
        )
    assert active.closed is False
    async with database.session() as session:
        transfer = (await session.execute(select(CallTransfer))).scalar_one()
    assert transfer.status == "failed"
    assert transfer.failure_code == "twilio_unavailable"
