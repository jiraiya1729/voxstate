"""Realtime turn state machine and latency timing helpers."""

from enum import StrEnum
from time import perf_counter
from typing import Protocol

from app.voice.errors import VoiceRuntimeError


class TurnState(StrEnum):
    """Realtime conversation states for one active call turn."""

    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    CLOSED = "closed"


class IllegalTurnTransition(VoiceRuntimeError):
    pass


class TurnTimingError(VoiceRuntimeError):
    pass


class TurnMarker(StrEnum):
    """Monotonic timing checkpoints used to derive per-turn latency metrics."""

    SPEECH_END = "speech_end"
    STT_FINAL = "stt_final"
    LLM_START = "llm_start"
    LLM_RESPONSE = "llm_response"
    TTS_START = "tts_start"
    TTS_FIRST_BYTE = "tts_first_byte"
    FIRST_PLAYBACK = "first_playback"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"


class MonotonicClock(Protocol):
    """Injectable monotonic clock for deterministic latency tests."""

    def now(self) -> float: ...


class SystemMonotonicClock:
    """Production clock backed by time.perf_counter."""

    def now(self) -> float:
        return perf_counter()


class TurnTiming:
    """Collects ordered latency markers for one user-to-assistant turn."""

    def __init__(self, *, turn_id: int, clock: MonotonicClock) -> None:
        self.turn_id = turn_id
        self._clock = clock
        self._markers: dict[TurnMarker, float] = {}

    def record(self, marker: TurnMarker, *, at: float | None = None) -> bool:
        """Record a marker once and reject timestamps that move backward."""
        if marker in self._markers:
            return False
        timestamp = self._clock.now() if at is None else at
        if self._markers and timestamp < max(self._markers.values()):
            raise TurnTimingError(f"out-of-order marker: {marker}")
        self._markers[marker] = timestamp
        return True

    def snapshot(self) -> "TurnTimingSnapshot":
        """Return an immutable read view for logging and assertions."""
        return TurnTimingSnapshot(
            turn_id=self.turn_id,
            markers=tuple(self._markers.items()),
        )


class TurnTimingSnapshot:
    """Read-only timing view that derives latency durations from recorded markers."""

    def __init__(
        self,
        *,
        turn_id: int,
        markers: tuple[tuple[TurnMarker, float], ...],
    ) -> None:
        self.turn_id = turn_id
        self.markers = markers

    def timestamp(self, marker: TurnMarker) -> float | None:
        return dict(self.markers).get(marker)

    def duration_ms(self, start: TurnMarker, end: TurnMarker) -> float | None:
        start_at = self.timestamp(start)
        end_at = self.timestamp(end)
        if start_at is None or end_at is None:
            return None
        return (end_at - start_at) * 1000

    @property
    def stt_latency_ms(self) -> float | None:
        return self.duration_ms(TurnMarker.SPEECH_END, TurnMarker.STT_FINAL)

    @property
    def llm_latency_ms(self) -> float | None:
        return self.duration_ms(TurnMarker.LLM_START, TurnMarker.LLM_RESPONSE)

    @property
    def tts_first_byte_ms(self) -> float | None:
        return self.duration_ms(TurnMarker.TTS_START, TurnMarker.TTS_FIRST_BYTE)

    @property
    def response_latency_ms(self) -> float | None:
        return self.duration_ms(TurnMarker.SPEECH_END, TurnMarker.FIRST_PLAYBACK)


_ALLOWED_TRANSITIONS: dict[TurnState, frozenset[TurnState]] = {
    TurnState.LISTENING: frozenset({TurnState.THINKING, TurnState.CLOSED}),
    TurnState.THINKING: frozenset(
        {
            TurnState.SPEAKING,
            TurnState.LISTENING,
            TurnState.INTERRUPTED,
            TurnState.CLOSED,
        }
    ),
    TurnState.SPEAKING: frozenset(
        {TurnState.LISTENING, TurnState.INTERRUPTED, TurnState.CLOSED}
    ),
    TurnState.INTERRUPTED: frozenset({TurnState.LISTENING, TurnState.CLOSED}),
    TurnState.CLOSED: frozenset(),
}


class TurnStateMachine:
    """Enforces legal realtime turn transitions and terminal close behavior."""

    def __init__(self, *, initial: TurnState = TurnState.LISTENING) -> None:
        self._state = initial
        self._history = [initial]

    @property
    def state(self) -> TurnState:
        return self._state

    @property
    def history(self) -> tuple[TurnState, ...]:
        return tuple(self._history)

    @staticmethod
    def allowed_targets(state: TurnState) -> frozenset[TurnState]:
        """Expose legal next states for tests and callers that need introspection."""
        return _ALLOWED_TRANSITIONS[state]

    def transition(self, target: TurnState) -> TurnState:
        """Move to a legal target state or raise on invalid state regression."""
        if target not in _ALLOWED_TRANSITIONS[self._state]:
            raise IllegalTurnTransition(f"{self._state} -> {target}")
        self._state = target
        self._history.append(target)
        return target

    def close(self) -> bool:
        """Enter CLOSED once; repeated close calls are harmless no-ops."""
        if self._state is TurnState.CLOSED:
            return False
        self.transition(TurnState.CLOSED)
        return True
