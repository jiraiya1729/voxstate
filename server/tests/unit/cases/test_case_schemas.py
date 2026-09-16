from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.cases.schemas import CaseCreate, CaseStateUpdate, CaseStatus


def test_case_create_normalizes_customer_reference() -> None:
    payload = CaseCreate.model_validate(
        {
            "customer_reference_id": "  customer-123  ",
            "business_state": "pre_call",
            "customer_state": {"balance_due": 42},
        }
    )

    assert payload.customer_reference_id == "customer-123"
    assert payload.business_state == "pre_call"
    assert payload.customer_state == {"balance_due": 42}


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"customer_reference_id": ""},
        {"customer_reference_id": "customer-123", "business_state": ""},
    ],
)
def test_case_create_rejects_invalid_payloads(arguments: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CaseCreate.model_validate(arguments)


def test_case_state_update_accepts_outcome_and_callback_state() -> None:
    callback_at = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)

    payload = CaseStateUpdate.model_validate(
        {
            "status": "waiting",
            "business_state": "callback_scheduled",
            "attempt_count": 1,
            "last_outcome": {
                "kind": "callback_requested",
                "callback_at": callback_at,
            },
            "customer_state": {"timezone": "UTC"},
        }
    )

    assert payload.status is CaseStatus.WAITING
    assert payload.callback_at == callback_at


def test_case_state_update_rejects_extra_and_invalid_values() -> None:
    with pytest.raises(ValidationError):
        CaseStateUpdate.model_validate({"attempt_count": -1})

    with pytest.raises(ValidationError):
        CaseStateUpdate.model_validate({"unexpected": True})
