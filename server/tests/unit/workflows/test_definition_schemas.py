from uuid import UUID

import pytest
from pydantic import ValidationError

from app.workflows.definition import WorkflowDefinition

AGENT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def test_minimal_call_then_complete_workflow_definition() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "name": "single-call-collection",
            "initial_step_id": "call_customer",
            "steps": [
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(AGENT_ID),
                    "to_number": "+15555550100",
                    "next_step_id": "complete",
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        }
    )

    assert definition.name == "single-call-collection"
    assert definition.initial_step_id == "call_customer"
    assert definition.steps_by_id["call_customer"].kind == "call"
    assert definition.steps_by_id["complete"].kind == "complete"


def test_workflow_definition_accepts_wait_and_retry_policy() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "name": "wait-retry-workflow",
            "initial_step_id": "wait_before_call",
            "steps": [
                {
                    "id": "wait_before_call",
                    "kind": "wait",
                    "delay_seconds": 300,
                    "next_step_id": "call_customer",
                },
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(AGENT_ID),
                    "to_number": "+15555550100",
                    "next_step_id": "complete",
                    "retry_policy": {
                        "max_attempts": 3,
                        "delay_seconds": 60,
                        "backoff": "exponential",
                        "retry_on": ["busy", "no-answer"],
                    },
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        }
    )

    wait_step = definition.steps_by_id["wait_before_call"]
    call_step = definition.steps_by_id["call_customer"]

    assert wait_step.kind == "wait"
    assert call_step.kind == "call"
    assert call_step.retry_policy.max_attempts == 3
    assert call_step.retry_policy.backoff == "exponential"


def test_workflow_definition_accepts_wait_for_event_with_timeout() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "name": "event-wait-workflow",
            "initial_step_id": "wait_for_payment",
            "steps": [
                {
                    "id": "wait_for_payment",
                    "kind": "wait_for_event",
                    "event_type": "payment.received",
                    "correlation_key": "case-123",
                    "on_event_step_id": "complete",
                    "timeout_seconds": 3600,
                    "on_timeout_step_id": "timeout_complete",
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
                {
                    "id": "timeout_complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        }
    )

    event_step = definition.steps_by_id["wait_for_payment"]

    assert event_step.kind == "wait_for_event"
    assert event_step.event_type == "payment.received"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "name": "duplicate-step-ids",
            "initial_step_id": "call_customer",
            "steps": [
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(AGENT_ID),
                    "to_number": "+15555550100",
                    "next_step_id": "complete",
                },
                {
                    "id": "call_customer",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        },
        {
            "name": "missing-initial-step",
            "initial_step_id": "unknown",
            "steps": [
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                }
            ],
        },
        {
            "name": "missing-next-step",
            "initial_step_id": "call_customer",
            "steps": [
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(AGENT_ID),
                    "to_number": "+15555550100",
                    "next_step_id": "unknown",
                }
            ],
        },
        {
            "name": "missing-wait-next-step",
            "initial_step_id": "wait",
            "steps": [
                {
                    "id": "wait",
                    "kind": "wait",
                    "delay_seconds": 60,
                    "next_step_id": "unknown",
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        },
        {
            "name": "invalid-retry-policy",
            "initial_step_id": "call_customer",
            "steps": [
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(AGENT_ID),
                    "to_number": "+15555550100",
                    "next_step_id": "complete",
                    "retry_policy": {"max_attempts": 0},
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        },
        {
            "name": "incomplete-event-timeout",
            "initial_step_id": "wait_for_payment",
            "steps": [
                {
                    "id": "wait_for_payment",
                    "kind": "wait_for_event",
                    "event_type": "payment.received",
                    "correlation_key": "case-123",
                    "on_event_step_id": "complete",
                    "timeout_seconds": 3600,
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        },
        {
            "name": "missing-event-branch",
            "initial_step_id": "wait_for_payment",
            "steps": [
                {
                    "id": "wait_for_payment",
                    "kind": "wait_for_event",
                    "event_type": "payment.received",
                    "correlation_key": "case-123",
                    "on_event_step_id": "unknown",
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        },
    ],
)
def test_workflow_definition_rejects_invalid_graph(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(payload)


def test_call_activity_requires_agent_destination_and_next_step() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(
            {
                "name": "missing-call-fields",
                "initial_step_id": "call_customer",
                "steps": [
                    {
                        "id": "call_customer",
                        "kind": "call",
                        "agent_id": str(AGENT_ID),
                    },
                    {
                        "id": "complete",
                        "kind": "complete",
                        "result": "succeeded",
                    },
                ],
            }
        )


def test_workflow_definition_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(
            {
                "name": "extra-field",
                "initial_step_id": "complete",
                "unexpected": True,
                "steps": [
                    {
                        "id": "complete",
                        "kind": "complete",
                        "result": "succeeded",
                    }
                ],
            }
        )
