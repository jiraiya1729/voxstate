import pytest

from app.workflows.state import (
    InvalidWorkflowTransition,
    WorkflowRunStatus,
    resolve_workflow_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("pending", "running"),
        ("pending", "paused"),
        ("pending", "cancelled"),
        ("pending", "failed"),
        ("running", "waiting"),
        ("running", "paused"),
        ("running", "completed"),
        ("running", "failed"),
        ("running", "cancelled"),
        ("waiting", "running"),
        ("waiting", "paused"),
        ("waiting", "completed"),
        ("waiting", "failed"),
        ("waiting", "cancelled"),
        ("paused", "running"),
        ("paused", "cancelled"),
    ],
)
def test_workflow_run_allows_legal_transitions(current: str, target: str) -> None:
    assert resolve_workflow_transition(current, target) == WorkflowRunStatus(target)


@pytest.mark.parametrize(
    "status",
    [
        WorkflowRunStatus.PENDING,
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.WAITING,
        WorkflowRunStatus.PAUSED,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
    ],
)
def test_workflow_run_idempotent_transition_returns_none(
    status: WorkflowRunStatus,
) -> None:
    assert resolve_workflow_transition(status, status) is None


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("pending", "completed"),
        ("waiting", "pending"),
        ("paused", "completed"),
        ("paused", "failed"),
        ("completed", "running"),
        ("completed", "failed"),
        ("failed", "running"),
        ("cancelled", "running"),
    ],
)
def test_workflow_run_rejects_illegal_transitions(current: str, target: str) -> None:
    with pytest.raises(InvalidWorkflowTransition):
        resolve_workflow_transition(current, target)
