import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.voice.errors import VoiceRuntimeError
from app.voice.transcription import TranscriptEvent, TranscriptKind

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are Voxstate, a concise voice assistant. "
    "Respond naturally for a phone conversation. "
    "Keep answers brief and do not use Markdown."
)


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    text: str


class ModelError(VoiceRuntimeError):
    pass


class EmptyModelInputError(ModelError):
    pass


class ModelTimeoutError(ModelError):
    pass


class ModelProviderError(ModelError):
    pass


class ModelResponseError(ModelError):
    pass


class LanguageModel(Protocol):
    async def generate(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
    ) -> str: ...


class AssistantResponseObserver(Protocol):
    async def on_response(self, call_id: UUID, text: str) -> None: ...


class LoggingAssistantResponseObserver:
    async def on_response(self, call_id: UUID, text: str) -> None:
        logger.info(
            "assistant response",
            extra={"call_id": str(call_id), "response": text},
        )


class ConversationSession:
    def __init__(
        self,
        *,
        call_id: UUID,
        language_model: LanguageModel,
        response_observer: AssistantResponseObserver,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.call_id = call_id
        self.language_model = language_model
        self.response_observer = response_observer
        self.system_prompt = system_prompt
        self._history: list[Message] = []
        self._turn_lock = asyncio.Lock()

    @property
    def history(self) -> tuple[Message, ...]:
        return tuple(self._history)

    async def on_transcript(self, event: TranscriptEvent) -> None:
        if event.kind is not TranscriptKind.FINAL:
            return

        user_text = event.text.strip()
        if not user_text:
            return

        async with self._turn_lock:
            candidate_history = (
                *self._history,
                Message(role=MessageRole.USER, text=user_text),
            )
            assistant_text = await self.language_model.generate(
                system_prompt=self.system_prompt,
                messages=candidate_history,
            )
            assistant_text = assistant_text.strip()
            if not assistant_text:
                raise ModelResponseError("language model returned empty text")

            completed_history = (
                *candidate_history,
                Message(role=MessageRole.ASSISTANT, text=assistant_text),
            )
            self._history = list(completed_history)
            await self.response_observer.on_response(
                self.call_id,
                assistant_text,
            )
