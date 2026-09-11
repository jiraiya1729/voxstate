from collections.abc import Sequence
from unittest.mock import Mock
from uuid import UUID

import pytest

import app.voice.response as response_module
from app.voice.response import (
    ConversationSession,
    Message,
    MessageRole,
    ModelProviderError,
)
from app.voice.transcription import TranscriptEvent, TranscriptKind

CALL_ID = UUID("00000000-0000-0000-0000-000000000001")


class RecordingLanguageModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, tuple[Message, ...]]] = []

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
    ) -> str:
        self.requests.append((system_prompt, tuple(messages)))
        return self.responses.pop(0)


class RecordingResponseObserver:
    def __init__(self) -> None:
        self.responses: list[tuple[UUID, str]] = []

    async def on_response(self, call_id: UUID, text: str) -> None:
        self.responses.append((call_id, text))


@pytest.mark.asyncio
async def test_partial_and_empty_final_transcripts_do_not_call_model() -> None:
    model = RecordingLanguageModel(["unused"])
    observer = RecordingResponseObserver()
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=model,
        response_observer=observer,
    )

    await conversation.on_transcript(
        TranscriptEvent(text="hel", kind=TranscriptKind.PARTIAL)
    )
    await conversation.on_transcript(
        TranscriptEvent(text="   ", kind=TranscriptKind.FINAL)
    )

    assert model.requests == []
    assert conversation.history == ()
    assert observer.responses == []


@pytest.mark.asyncio
async def test_final_turns_build_ordered_conversation_history() -> None:
    model = RecordingLanguageModel(["Hello!", "Certainly."])
    observer = RecordingResponseObserver()
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=model,
        response_observer=observer,
    )

    await conversation.on_transcript(
        TranscriptEvent(text="  Hi  ", kind=TranscriptKind.FINAL)
    )
    await conversation.on_transcript(
        TranscriptEvent(text="Can you help?", kind=TranscriptKind.FINAL)
    )

    assert model.requests[0][1] == (Message(role=MessageRole.USER, text="Hi"),)
    assert model.requests[1][1] == (
        Message(role=MessageRole.USER, text="Hi"),
        Message(role=MessageRole.ASSISTANT, text="Hello!"),
        Message(role=MessageRole.USER, text="Can you help?"),
    )
    assert conversation.history == (
        Message(role=MessageRole.USER, text="Hi"),
        Message(role=MessageRole.ASSISTANT, text="Hello!"),
        Message(role=MessageRole.USER, text="Can you help?"),
        Message(role=MessageRole.ASSISTANT, text="Certainly."),
    )
    assert observer.responses == [
        (CALL_ID, "Hello!"),
        (CALL_ID, "Certainly."),
    ]


@pytest.mark.asyncio
async def test_final_turn_logs_stt_and_llm_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Mock()
    monkeypatch.setattr(response_module, "logger", logger)
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=RecordingLanguageModel(["Hello!"]),
        response_observer=RecordingResponseObserver(),
    )

    await conversation.on_transcript(
        TranscriptEvent(text=" Hi there ", kind=TranscriptKind.FINAL)
    )

    messages = [call.args[0] for call in logger.info.call_args_list]
    debug_messages = [call.args[0] for call in logger.debug.call_args_list]
    assert "voice.stt.final call_id=%s chars=%d" in messages
    assert "voice.stt.text call_id=%s text=%r" in debug_messages
    assert "voice.llm.request call_id=%s turns=%d" in messages
    assert "voice.llm.response call_id=%s elapsed_ms=%.1f chars=%d" in messages
    assert "voice.llm.text call_id=%s text=%r" in debug_messages


@pytest.mark.asyncio
async def test_failed_model_turn_is_not_committed_to_history() -> None:
    class FailingLanguageModel:
        async def generate(
            self,
            *,
            system_prompt: str,
            messages: Sequence[Message],
        ) -> str:
            raise ModelProviderError("failed")

    observer = RecordingResponseObserver()
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=FailingLanguageModel(),
        response_observer=observer,
    )

    with pytest.raises(ModelProviderError):
        await conversation.on_transcript(
            TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
        )

    assert conversation.history == ()
    assert observer.responses == []


@pytest.mark.asyncio
async def test_model_failure_is_logged_and_propagated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingLanguageModel:
        async def generate(
            self,
            *,
            system_prompt: str,
            messages: Sequence[Message],
        ) -> str:
            raise ModelProviderError("failed")

    logger = Mock()
    monkeypatch.setattr(response_module, "logger", logger)
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=FailingLanguageModel(),
        response_observer=RecordingResponseObserver(),
    )

    with pytest.raises(ModelProviderError):
        await conversation.on_transcript(
            TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
        )

    assert logger.exception.call_args.args[0] == (
        "voice.llm.error call_id=%s elapsed_ms=%.1f"
    )
