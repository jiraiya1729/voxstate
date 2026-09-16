"""Pure workflow-run state transition rules."""

from enum import StrEnum


class WorkflowRunStatus(StrEnum):
    """Persisted lifecycle status for one durable workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_WORKFLOW_STATUSES = {
    WorkflowRunStatus.COMPLETED,
    WorkflowRunStatus.FAILED,
    WorkflowRunStatus.CANCELLED,
}

LEGAL_WORKFLOW_TRANSITIONS = {
    WorkflowRunStatus.PENDING: {
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.CANCELLED,
        WorkflowRunStatus.FAILED,
    },
    WorkflowRunStatus.RUNNING: {
        WorkflowRunStatus.WAITING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
    },
    WorkflowRunStatus.WAITING: {
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
    },
    WorkflowRunStatus.COMPLETED: set(),
    WorkflowRunStatus.FAILED: set(),
    WorkflowRunStatus.CANCELLED: set(),
}


class InvalidWorkflowTransition(ValueError):
    """Raised when a workflow run is moved through an illegal lifecycle edge."""


def resolve_workflow_transition(
    current_status: str | WorkflowRunStatus,
    target_status: str | WorkflowRunStatus,
) -> WorkflowRunStatus | None:
    """Return the target status, or None when the transition is idempotent."""
    current = WorkflowRunStatus(current_status)
    target = WorkflowRunStatus(target_status)

    if current == target:
        return None

    if target not in LEGAL_WORKFLOW_TRANSITIONS[current]:
        raise InvalidWorkflowTransition(
            f"cannot move workflow from {current} to {target}"
        )

    return target
