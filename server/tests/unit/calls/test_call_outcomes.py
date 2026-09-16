from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.calls.outcomes import CallOutcome, CallOutcomeKind


def test_completed_outcome_accepts_summary_and_confidence() -> None:
    outcome = CallOutcome.model_validate(
        {
            "kind": "completed",
            "summary": "Caller completed the verification.",
            "confidence": 0.8,
        }
    )

    assert outcome.kind is CallOutcomeKind.COMPLETED
    assert outcome.confidence == 0.8


def test_callback_requested_requires_callback_time() -> None:
    callback_at = datetime(2026, 9, 17, 13, 30, tzinfo=UTC)

    outcome = CallOutcome.model_validate(
        {"kind": "callback_requested", "callback_at": callback_at}
    )

    assert outcome.callback_at == callback_at

    with pytest.raises(ValidationError, match="callback_at"):
        CallOutcome.model_validate({"kind": "callback_requested"})


def test_promise_to_pay_requires_promised_payment_date() -> None:
    promised_at = datetime(2026, 9, 20, tzinfo=UTC)

    outcome = CallOutcome.model_validate(
        {"kind": "promise_to_pay", "promised_payment_date": promised_at}
    )

    assert outcome.promised_payment_date == promised_at

    with pytest.raises(ValidationError, match="promised_payment_date"):
        CallOutcome.model_validate({"kind": "promise_to_pay"})


def test_human_required_requires_reason() -> None:
    outcome = CallOutcome.model_validate(
        {"kind": "human_required", "human_reason": "Caller requested a supervisor."}
    )

    assert outcome.human_reason == "Caller requested a supervisor."

    with pytest.raises(ValidationError, match="human_reason"):
        CallOutcome.model_validate({"kind": "human_required"})


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "completed", "callback_at": datetime(2026, 9, 17, tzinfo=UTC)},
        {
            "kind": "not_interested",
            "promised_payment_date": datetime(2026, 9, 20, tzinfo=UTC),
        },
        {"kind": "wrong_number", "human_reason": "Needs a person."},
        {"kind": "unknown", "confidence": 1.5},
    ],
)
def test_outcome_rejects_fields_that_do_not_match_kind(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CallOutcome.model_validate(payload)
