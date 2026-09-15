from collections.abc import Awaitable, Callable, Sequence
from uuid import uuid4

import pytest

from app.voice.conversation.response import ConversationSession, Message, MessageRole
from app.voice.conversation.transcription import TranscriptEvent, TranscriptKind
from app.voice.runtime import AgentRuntime
from app.voice.sessions.service import ActiveCallSession, InvalidMediaStartError


class Transcriber:
    async def send_audio(self, audio: bytes) -> None:
        pass

    async def close(self) -> bool:
        return True


class Model:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    async def generate(self, *, system_prompt: str, messages: Sequence[Message]) -> str:
        self.prompts.append(system_prompt)
        return self.response


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


async def discard(audio: bytes) -> None:
    pass


@pytest.mark.asyncio
async def test_agent_transfer_keeps_history_and_rejects_loops() -> None:
    call_id, first_id, second_id = uuid4(), uuid4(), uuid4()
    first_model = Model("first answer")
    conversation = ConversationSession(
        call_id=call_id,
        language_model=first_model,
        response_observer=Observer(),
        system_prompt="first prompt",
    )
    await conversation.on_transcript(
        TranscriptEvent(text="hello", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()
    active = ActiveCallSession(
        call_id=call_id,
        provider_call_id="CA1",
        stream_sid="MZ1",
        transcriber=Transcriber(),
        conversation=conversation,
        active_agent_id=first_id,
        visited_agent_ids={first_id},
        audio_sink=discard,
    )
    second_model = Model("second answer")
    await active.transfer_to(
        second_id,
        AgentRuntime("second prompt", second_model, Synthesizer()),
    )
    await conversation.on_transcript(
        TranscriptEvent(text="continue", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()
    assert conversation.history[:2] == (
        Message(MessageRole.USER, "hello"),
        Message(MessageRole.ASSISTANT, "first answer"),
    )
    assert second_model.prompts == ["second prompt"]
    with pytest.raises(InvalidMediaStartError, match="loop"):
        await active.transfer_to(
            first_id, AgentRuntime("first", first_model, Synthesizer())
        )
