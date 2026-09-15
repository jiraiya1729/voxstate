"""Realtime conversation session logic.

This file turns final transcripts into LLM responses, history, interruption, and timing.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Protocol
from uuid import UUID

from app.voice.conversation.transcription import TranscriptEvent, TranscriptKind
from app.voice.conversation.turns import (
    MonotonicClock,
    SystemMonotonicClock,
    TurnMarker,
    TurnState,
    TurnStateMachine,
    TurnTiming,
    TurnTimingSnapshot,
)
from app.voice.errors import VoiceRuntimeError

logger = logging.getLogger("uvicorn.error")

DEFAULT_SYSTEM_PROMPT = (
    "You are Voxstate, a concise voice assistant. "
    "Respond naturally for a phone conversation. "
    "Keep answers brief and do not use Markdown."
)


class MessageRole(StrEnum):
    """Roles used in the provider-neutral conversation history."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    """One user or assistant message sent to the language model."""

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
    """Provider-neutral LLM interface used by ConversationSession."""

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
    ) -> str: ...


class AssistantResponseObserver(Protocol):
    """Observer that handles assistant text, usually by synthesizing speech."""

    async def on_response(
        self,
        call_id: UUID,
        text: str,
        *,
        generation: int,
        is_current: Callable[[], bool],
        timing: TurnTiming,
    ) -> str | None: ...

    async def interrupt(self, call_id: UUID) -> bool: ...


class LoggingAssistantResponseObserver:
    """Test/debug observer that logs assistant text without producing audio."""

    async def on_response(
        self,
        call_id: UUID,
        text: str,
        *,
        generation: int,
        is_current: Callable[[], bool],
        timing: TurnTiming,
    ) -> str | None:
        del generation, is_current, timing
        logger.info(
            "assistant response",
            extra={"call_id": str(call_id), "response": text},
        )
        return None

    async def interrupt(self, call_id: UUID) -> bool:
        del call_id
        return False


class ConversationSession:
    """Owns live turn state, transcript handling, LLM calls, TTS, and interruption."""

    def __init__(
        self,
        *,
        call_id: UUID,
        language_model: LanguageModel,
        response_observer: AssistantResponseObserver,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        clock: MonotonicClock | None = None,
    ) -> None:
        self.call_id = call_id
        self.language_model = language_model
        self.response_observer = response_observer
        self.system_prompt = system_prompt
        self._history: list[Message] = []
        self._turn_lock = asyncio.Lock()
        self._state = TurnStateMachine()
        self._speech_active = False
        self._eager_transcript: str | None = None
        self._generation = 0
        self._response_task: asyncio.Task[None] | None = None
        self._playback_mark: str | None = None
        self._failure: BaseException | None = None
        self._clock = clock or SystemMonotonicClock()
        self._pending_speech_end_at: float | None = None
        self._turn_counter = 0
        self._turn_timings: list[TurnTiming] = []
        self._current_timing: TurnTiming | None = None

    @property
    def history(self) -> tuple[Message, ...]:
        return tuple(self._history)

    @property
    def state(self) -> TurnState:
        return self._state.state

    @property
    def state_history(self) -> tuple[TurnState, ...]:
        return self._state.history

    @property
    def turn_timings(self) -> tuple[TurnTimingSnapshot, ...]:
        return tuple(timing.snapshot() for timing in self._turn_timings)

    async def close(self) -> bool:
        if self._state.state is TurnState.CLOSED:
            return False

        self._generation += 1
        response_task = self._response_task
        if response_task is not None and not response_task.done():
            response_task.cancel()
        if self._state.state is TurnState.SPEAKING:
            await self.response_observer.interrupt(self.call_id)
        if response_task is not None:
            await asyncio.gather(response_task, return_exceptions=True)
        self._playback_mark = None
        self._state.close()
        return True

    async def reconfigure(
        self,
        *,
        language_model: LanguageModel,
        response_observer: AssistantResponseObserver,
        system_prompt: str,
    ) -> None:
        if not system_prompt.strip():
            raise EmptyModelInputError("system prompt must not be empty")
        async with self._turn_lock:
            if self._state.state is TurnState.CLOSED:
                raise ModelError("cannot reconfigure a closed conversation")
            if self._state.state in {TurnState.THINKING, TurnState.SPEAKING}:
                await self._interrupt_active_turn()
            self.language_model = language_model
            self.response_observer = response_observer
            self.system_prompt = system_prompt

    def raise_if_failed(self) -> None:
        if self._failure is not None:
            raise self._failure

    async def wait_until_idle(self) -> None:
        response_task = self._response_task
        if response_task is not None:
            await response_task
        self.raise_if_failed()

    async def on_playback_complete(self, mark_name: str) -> bool:
        if mark_name != self._playback_mark:
            return False
        self._playback_mark = None
        if self._current_timing is not None:
            self._current_timing.record(TurnMarker.COMPLETED)
            self._log_timing(self._current_timing.snapshot())
        if self._state.state is TurnState.SPEAKING:
            self._state.transition(TurnState.LISTENING)
        return True

    async def on_transcript(self, event: TranscriptEvent) -> None:
        if event.kind is TranscriptKind.SPEECH_STARTED:
            self._speech_active = True
            self._eager_transcript = None
            self._pending_speech_end_at = None
            if self._state.state in {TurnState.THINKING, TurnState.SPEAKING}:
                await self._interrupt_active_turn()
            return

        if event.kind is TranscriptKind.EAGER_END:
            self._eager_transcript = event.text
            self._pending_speech_end_at = self._clock.now()
            return

        if event.kind is TranscriptKind.RESUMED:
            self._speech_active = True
            self._eager_transcript = None
            self._pending_speech_end_at = None
            return

        if event.kind is not TranscriptKind.FINAL:
            return

        self._speech_active = False
        self._eager_transcript = None
        speech_end_at = self._pending_speech_end_at
        self._pending_speech_end_at = None
        user_text = event.text.strip()
        if not user_text:
            return

        logger.info(
            "voice.stt.final call_id=%s chars=%d",
            self.call_id,
            len(user_text),
        )
        logger.debug(
            "voice.stt.text call_id=%s text=%r",
            self.call_id,
            user_text,
        )

        async with self._turn_lock:
            if self._state.state is TurnState.CLOSED:
                return
            if self._state.state in {TurnState.THINKING, TurnState.SPEAKING}:
                await self._interrupt_active_turn()

            self._generation += 1
            generation = self._generation
            self._failure = None
            self._turn_counter += 1
            timing = TurnTiming(turn_id=self._turn_counter, clock=self._clock)
            timing.record(
                TurnMarker.SPEECH_END,
                at=speech_end_at if speech_end_at is not None else self._clock.now(),
            )
            timing.record(TurnMarker.STT_FINAL)
            self._turn_timings.append(timing)
            self._current_timing = timing
            self._state.transition(TurnState.THINKING)
            response_task = asyncio.create_task(
                self._run_turn(
                    user_text=user_text,
                    generation=generation,
                    timing=timing,
                )
            )
            response_task.add_done_callback(self._capture_task_failure)
            self._response_task = response_task

    async def _run_turn(
        self,
        *,
        user_text: str,
        generation: int,
        timing: TurnTiming,
    ) -> None:
        candidate_history = (
            *self._history,
            Message(role=MessageRole.USER, text=user_text),
        )
        logger.info(
            "voice.llm.request call_id=%s turns=%d",
            self.call_id,
            len(candidate_history),
        )
        started_at = perf_counter()
        timing.record(TurnMarker.LLM_START)
        try:
            assistant_text = await self.language_model.generate(
                system_prompt=self.system_prompt,
                messages=candidate_history,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "voice.llm.error call_id=%s elapsed_ms=%.1f",
                self.call_id,
                (perf_counter() - started_at) * 1000,
            )
            if self._is_current(generation):
                self._state.transition(TurnState.LISTENING)
            raise

        if not self._is_current(generation):
            return
        timing.record(TurnMarker.LLM_RESPONSE)
        assistant_text = assistant_text.strip()
        if not assistant_text:
            self._state.transition(TurnState.LISTENING)
            raise ModelResponseError("language model returned empty text")

        logger.info(
            "voice.llm.response call_id=%s elapsed_ms=%.1f chars=%d",
            self.call_id,
            (perf_counter() - started_at) * 1000,
            len(assistant_text),
        )
        logger.debug(
            "voice.llm.text call_id=%s text=%r",
            self.call_id,
            assistant_text,
        )

        completed_history = (
            *candidate_history,
            Message(role=MessageRole.ASSISTANT, text=assistant_text),
        )
        self._history = list(completed_history)
        self._state.transition(TurnState.SPEAKING)
        try:
            mark_name = await self.response_observer.on_response(
                self.call_id,
                assistant_text,
                generation=generation,
                is_current=lambda: self._is_current(generation),
                timing=timing,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._is_current(generation):
                self._state.transition(TurnState.LISTENING)
            raise

        if not self._is_current(generation):
            return
        if mark_name is None:
            timing.record(TurnMarker.COMPLETED)
            self._log_timing(timing.snapshot())
            self._state.transition(TurnState.LISTENING)
        else:
            self._playback_mark = mark_name

    async def _interrupt_active_turn(self) -> None:
        interrupted_generation = self._generation
        previous_state = self._state.state
        self._generation += 1
        self._playback_mark = None
        if self._current_timing is not None:
            self._current_timing.record(TurnMarker.INTERRUPTED)
            self._log_timing(self._current_timing.snapshot())
        self._state.transition(TurnState.INTERRUPTED)

        response_task = self._response_task
        if response_task is not None and not response_task.done():
            response_task.cancel()
        if previous_state is TurnState.SPEAKING:
            await self.response_observer.interrupt(self.call_id)
        if response_task is not None:
            await asyncio.gather(response_task, return_exceptions=True)

        if self._state.state is TurnState.INTERRUPTED:
            self._state.transition(TurnState.LISTENING)
        logger.info(
            "voice.turn.interrupted call_id=%s generation=%d",
            self.call_id,
            interrupted_generation,
        )

    def _is_current(self, generation: int) -> bool:
        return (
            generation == self._generation and self._state.state is not TurnState.CLOSED
        )

    def _capture_task_failure(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        failure = task.exception()
        if failure is not None:
            self._failure = failure

    def _log_timing(self, timing: TurnTimingSnapshot) -> None:
        logger.info(
            "voice.turn.timing call_id=%s turn_id=%d stt_ms=%s llm_ms=%s "
            "tts_first_byte_ms=%s response_ms=%s",
            self.call_id,
            timing.turn_id,
            self._format_metric(timing.stt_latency_ms),
            self._format_metric(timing.llm_latency_ms),
            self._format_metric(timing.tts_first_byte_ms),
            self._format_metric(timing.response_latency_ms),
        )

    @staticmethod
    def _format_metric(value: float | None) -> str:
        return "missing" if value is None else f"{value:.1f}"
