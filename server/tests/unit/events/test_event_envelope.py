from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.events.envelope import EventCreate, EventEnvelope


def test_event_create_accepts_normalized_type_and_payload() -> None:
    event = EventCreate.model_validate(
        {
            "event_type": "call.completed",
            "call_id": uuid4(),
            "correlation_id": "CA123",
            "idempotency_key": "provider-event-1",
            "payload": {"status": "completed"},
        }
    )

    assert event.version == 1
    assert event.payload == {"status": "completed"}


@pytest.mark.parametrize(
    "event_type",
    ["completed", "Call.Completed", "call-completed", ""],
)
def test_event_type_must_be_dot_namespaced_snake_case(event_type: str) -> None:
    with pytest.raises(ValidationError):
        EventCreate.model_validate({"event_type": event_type})


def test_persisted_call_event_requires_sequence() -> None:
    with pytest.raises(ValidationError, match="sequence"):
        EventEnvelope.model_validate(
            {
                "id": uuid4(),
                "event_type": "call.completed",
                "call_id": uuid4(),
                "sequence": None,
                "version": 1,
                "payload": {},
                "occurred_at": "2026-09-16T00:00:00Z",
            }
        )
