import asyncio
from uuid import UUID

import pytest

from app.events.envelope import EventCreate
from app.tools.executor import ToolExecutor, ToolInputValidationError
from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.results import ToolResultStatus
from app.tools.schemas import GetCustomerInput


def build_registry(handler: object) -> ToolRegistry:
    registry = ToolRegistry(dependencies={"customer_repository": object()})
    registry.register(
        ToolDefinition(
            name="get_customer",
            description="Fetch a customer record.",
            handler=handler,
            input_model=GetCustomerInput,
            required_dependencies=frozenset({"customer_repository"}),
        )
    )
    return registry


class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[EventCreate] = []

    async def append(self, event: EventCreate) -> object:
        self.events.append(event)
        return object()


@pytest.mark.asyncio
async def test_executor_validates_arguments_and_returns_success_data() -> None:
    def handler(
        input_payload: GetCustomerInput, **dependencies: object
    ) -> dict[str, object]:
        assert input_payload.customer_id == "cus_123"
        assert dependencies["customer_repository"] is not None
        return {"name": "Synthetic Customer"}

    result = await ToolExecutor(build_registry(handler)).execute(
        "get_customer",
        {"customer_id": "cus_123"},
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert result.data == {"name": "Synthetic Customer"}


@pytest.mark.asyncio
async def test_executor_rejects_invalid_model_arguments() -> None:
    def handler(
        input_payload: GetCustomerInput, **dependencies: object
    ) -> dict[str, object]:
        raise AssertionError("handler should not run")

    with pytest.raises(ToolInputValidationError):
        await ToolExecutor(build_registry(handler)).execute("get_customer", {})


@pytest.mark.asyncio
async def test_executor_maps_unexpected_exceptions_to_permanent_error() -> None:
    def handler(input_payload: GetCustomerInput, **dependencies: object) -> object:
        raise RuntimeError("repository failed")

    result = await ToolExecutor(build_registry(handler)).execute(
        "get_customer",
        {"customer_id": "cus_123"},
    )

    assert result.status is ToolResultStatus.PERMANENT_ERROR
    assert result.error_code == "RuntimeError"


@pytest.mark.asyncio
async def test_executor_maps_timeout_to_timeout_result() -> None:
    async def handler(
        input_payload: GetCustomerInput, **dependencies: object
    ) -> object:
        await asyncio.sleep(0.05)
        return {"too": "late"}

    result = await ToolExecutor(build_registry(handler), timeout_seconds=0.001).execute(
        "get_customer",
        {"customer_id": "cus_123"},
    )

    assert result.status is ToolResultStatus.TIMEOUT
    assert result.error_code == "timeout"


@pytest.mark.asyncio
async def test_executor_emits_tool_started_and_completed_events() -> None:
    def handler(
        input_payload: GetCustomerInput, **dependencies: object
    ) -> dict[str, object]:
        del input_payload, dependencies
        return {"name": "Synthetic Customer"}

    sink = RecordingEventSink()
    result = await ToolExecutor(build_registry(handler), event_sink=sink).execute(
        "get_customer",
        {"customer_id": "cus_123"},
        call_id=UUID("00000000-0000-0000-0000-000000000123"),
        turn_id=7,
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert [event.event_type for event in sink.events] == [
        "tool.started",
        "tool.completed",
    ]
    assert [event.correlation_id for event in sink.events] == ["turn:7", "turn:7"]
