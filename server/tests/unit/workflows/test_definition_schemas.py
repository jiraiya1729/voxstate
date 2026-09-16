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
