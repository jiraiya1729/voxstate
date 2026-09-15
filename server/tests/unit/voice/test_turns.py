import pytest

from app.voice.conversation.turns import (
    IllegalTurnTransition,
    TurnMarker,
    TurnState,
    TurnStateMachine,
    TurnTiming,
    TurnTimingError,
)


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (TurnState.LISTENING, TurnState.THINKING),
        (TurnState.LISTENING, TurnState.CLOSED),
        (TurnState.THINKING, TurnState.SPEAKING),
        (TurnState.THINKING, TurnState.LISTENING),
        (TurnState.THINKING, TurnState.INTERRUPTED),
        (TurnState.THINKING, TurnState.CLOSED),
        (TurnState.SPEAKING, TurnState.LISTENING),
        (TurnState.SPEAKING, TurnState.INTERRUPTED),
        (TurnState.SPEAKING, TurnState.CLOSED),
        (TurnState.INTERRUPTED, TurnState.LISTENING),
        (TurnState.INTERRUPTED, TurnState.CLOSED),
    ],
)
def test_legal_turn_transitions(start: TurnState, target: TurnState) -> None:
    machine = TurnStateMachine(initial=start)

    assert machine.transition(target) is target
    assert machine.state is target
    assert machine.history == (start, target)


@pytest.mark.parametrize("start", list(TurnState))
def test_close_is_idempotent_from_every_state(start: TurnState) -> None:
    machine = TurnStateMachine(initial=start)

    assert machine.close() is (start is not TurnState.CLOSED)
    assert machine.state is TurnState.CLOSED
    assert machine.close() is False


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (start, target)
        for start in TurnState
        for target in TurnState
        if target not in TurnStateMachine.allowed_targets(start)
        and not (start is TurnState.CLOSED and target is TurnState.CLOSED)
    ],
)
def test_illegal_turn_transitions_are_rejected(
    start: TurnState,
    target: TurnState,
) -> None:
    machine = TurnStateMachine(initial=start)

    with pytest.raises(IllegalTurnTransition, match=f"{start} -> {target}"):
        machine.transition(target)

    assert machine.state is start


def test_closed_state_rejects_all_future_transitions() -> None:
    machine = TurnStateMachine()
    machine.close()

    for target in TurnState:
        with pytest.raises(IllegalTurnTransition):
            machine.transition(target)


def test_turn_timing_derives_latency_from_monotonic_markers() -> None:
    clock = FakeClock(10.0)
    timing = TurnTiming(turn_id=7, clock=clock)
    timing.record(TurnMarker.SPEECH_END)
    clock.advance(0.1)
    timing.record(TurnMarker.STT_FINAL)
    clock.advance(0.05)
    timing.record(TurnMarker.LLM_START)
    clock.advance(0.25)
    timing.record(TurnMarker.LLM_RESPONSE)
    timing.record(TurnMarker.TTS_START)
    clock.advance(0.08)
    timing.record(TurnMarker.TTS_FIRST_BYTE)
    clock.advance(0.02)
    timing.record(TurnMarker.FIRST_PLAYBACK)
    timing.record(TurnMarker.COMPLETED)

    snapshot = timing.snapshot()
    assert snapshot.turn_id == 7
    assert snapshot.stt_latency_ms == pytest.approx(100)
    assert snapshot.llm_latency_ms == pytest.approx(250)
    assert snapshot.tts_first_byte_ms == pytest.approx(80)
    assert snapshot.response_latency_ms == pytest.approx(500)


def test_missing_timing_markers_produce_missing_metrics() -> None:
    timing = TurnTiming(turn_id=1, clock=FakeClock())
    timing.record(TurnMarker.LLM_START)

    snapshot = timing.snapshot()
    assert snapshot.stt_latency_ms is None
    assert snapshot.llm_latency_ms is None
    assert snapshot.tts_first_byte_ms is None
    assert snapshot.response_latency_ms is None


def test_timing_keeps_first_marker_and_rejects_time_reversal() -> None:
    clock = FakeClock(5.0)
    timing = TurnTiming(turn_id=1, clock=clock)
    assert timing.record(TurnMarker.TTS_START) is True
    assert timing.record(TurnMarker.TTS_START, at=9.0) is False

    with pytest.raises(TurnTimingError, match="out-of-order marker"):
        timing.record(TurnMarker.TTS_FIRST_BYTE, at=4.0)

    assert timing.snapshot().timestamp(TurnMarker.TTS_START) == 5.0
