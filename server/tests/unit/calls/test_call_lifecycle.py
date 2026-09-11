import pytest

from app.calls.lifecycle import (
    CallStatus,
    UnsupportedProviderStatus,
    normalize_provider_status,
    resolve_call_transition,
)


@pytest.mark.parametrize("provider_status", ["answered", "in-progress"])
def test_answered_statuses_normalize_to_in_progress(
    provider_status: str,
) -> None:
    assert normalize_provider_status(provider_status) is CallStatus.IN_PROGRESS


def test_duplicate_callback_is_idempotent() -> None:
    assert resolve_call_transition("ringing", "ringing") is None


def test_out_of_order_callback_cannot_regress_state() -> None:
    assert resolve_call_transition("in-progress", "ringing") is None


@pytest.mark.parametrize(
    "terminal_status",
    ["completed", "failed", "busy", "no-answer"],
)
def test_terminal_status_cannot_transition(
    terminal_status: str,
) -> None:
    assert resolve_call_transition(terminal_status, "ringing") is None


def test_unknown_provider_status_is_rejected() -> None:
    with pytest.raises(UnsupportedProviderStatus):
        normalize_provider_status("mystery")
