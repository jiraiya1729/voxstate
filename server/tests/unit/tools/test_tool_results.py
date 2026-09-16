import pytest
from pydantic import ValidationError

from app.tools.results import ToolResult, ToolResultStatus


def test_success_result_carries_data_only() -> None:
    result = ToolResult.success({"paid": True})

    assert result.status is ToolResultStatus.SUCCESS
    assert result.data == {"paid": True}
    assert result.error_code is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "success",
            "data": {"ok": True},
            "error_code": "bad",
            "message": "should not be here",
        },
        {"status": "permanent_error", "error_code": "bad"},
        {
            "status": "timeout",
            "error_code": "timeout",
            "message": "late",
            "retry_after_seconds": 1,
        },
        {
            "status": "retryable_error",
            "data": {"partial": True},
            "error_code": "busy",
            "message": "try again",
        },
    ],
)
def test_result_payload_rejects_ambiguous_status_data(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


def test_retryable_error_can_include_retry_metadata() -> None:
    result = ToolResult.retryable_error(
        error_code="provider_busy",
        message="Provider is temporarily unavailable.",
        retry_after_seconds=3.0,
    )

    assert result.status is ToolResultStatus.RETRYABLE_ERROR
    assert result.retry_after_seconds == 3.0
