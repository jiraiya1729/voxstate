"""Validated workflow definition contracts for durable orchestration."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.types import E164number

WorkflowText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
StepId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
    ),
]


class CallActivityDefinition(BaseModel):
    """A workflow activity that starts one outbound voice call."""

    model_config = ConfigDict(extra="forbid")

    id: StepId
    kind: Literal["call"]
    agent_id: UUID
    to_number: E164number
    next_step_id: StepId


class CompleteStepDefinition(BaseModel):
    """A terminal workflow step that completes the run successfully."""

    model_config = ConfigDict(extra="forbid")

    id: StepId
    kind: Literal["complete"]
    result: Literal["succeeded"] = "succeeded"


WorkflowStep = Annotated[
    CallActivityDefinition | CompleteStepDefinition,
    Field(discriminator="kind"),
]


class WorkflowDefinition(BaseModel):
    """Smallest workflow definition that can run one call activity and complete."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[WorkflowText, Field(max_length=120)]
    initial_step_id: StepId
    steps: list[WorkflowStep] = Field(min_length=1)

    @property
    def steps_by_id(self) -> dict[str, WorkflowStep]:
        """Return workflow steps keyed by their stable definition IDs."""
        return {step.id: step for step in self.steps}

    @model_validator(mode="after")
    def validate_graph(self) -> "WorkflowDefinition":
        step_ids: set[str] = set()
        duplicate_ids: set[str] = set()

        for step in self.steps:
            if step.id in step_ids:
                duplicate_ids.add(step.id)
            step_ids.add(step.id)

        if duplicate_ids:
            duplicates = ", ".join(sorted(duplicate_ids))
            raise ValueError(f"duplicate workflow step id: {duplicates}")

        if self.initial_step_id not in step_ids:
            raise ValueError("initial_step_id must reference an existing step")

        has_call = any(step.kind == "call" for step in self.steps)
        has_complete = any(step.kind == "complete" for step in self.steps)

        if not has_call:
            raise ValueError("workflow definition requires at least one call step")
        if not has_complete:
            raise ValueError("workflow definition requires a complete step")

        for step in self.steps:
            if step.kind == "call" and step.next_step_id not in step_ids:
                raise ValueError("call next_step_id must reference an existing step")

        return self
