"""Execution boundary for validated backend tool calls."""

import asyncio
from inspect import isawaitable
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.events.envelope import EventCreate
from app.events.sink import EventSink
from app.tools.registry import ToolRegistry
from app.tools.results import ToolResult
from app.tools.schemas import ToolInput


class ToolInputValidationError(Exception):
    """Raised when model-generated arguments fail a tool schema."""

    def __init__(self, tool_name: str, validation_error: ValidationError) -> None:
        self.tool_name = tool_name
        self.validation_error = validation_error
        super().__init__(f"invalid arguments for tool: {tool_name}")


class ToolExecutor:
    """Validates inputs, invokes a registered handler, and normalizes failures."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        timeout_seconds: float = 10.0,
        event_sink: EventSink | None = None,
    ) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds
        self._event_sink = event_sink

    async def execute(
        self,
        tool_name: str,
        arguments: object,
        *,
        call_id: UUID | None = None,
        turn_id: int | None = None,
    ) -> ToolResult:
        resolved = self._registry.resolve(tool_name)
        input_payload = self._validate_input(
            tool_name=tool_name,
            input_model=resolved.definition.input_model,
            arguments=arguments,
        )
        await self._append_event(
            EventCreate(
                event_type="tool.started",
                call_id=call_id,
                correlation_id=f"turn:{turn_id}" if turn_id is not None else None,
                payload={"tool_name": tool_name},
            )
        )

        try:
            raw_result = await asyncio.wait_for(
                self._call_handler(
                    resolved.handler,
                    input_payload,
                    resolved.dependencies,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            result = ToolResult.timeout()
            await self._append_tool_result(tool_name, result, call_id, turn_id)
            return result
        except Exception as exc:
            result = ToolResult.permanent_error(
                error_code=exc.__class__.__name__,
                message=str(exc) or "tool execution failed",
            )
            await self._append_tool_result(tool_name, result, call_id, turn_id)
            return result

        if isinstance(raw_result, ToolResult):
            result = raw_result
        elif isinstance(raw_result, dict):
            result = ToolResult.success(raw_result)
        else:
            result = ToolResult.permanent_error(
                error_code="invalid_tool_result",
                message="tool handler returned an unsupported result",
            )
        await self._append_tool_result(tool_name, result, call_id, turn_id)
        return result

    @staticmethod
    def _validate_input(
        *,
        tool_name: str,
        input_model: type[ToolInput],
        arguments: object,
    ) -> ToolInput:
        try:
            return input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolInputValidationError(tool_name, exc) from exc

    @staticmethod
    async def _call_handler(
        handler: Any,
        input_payload: ToolInput,
        dependencies: dict[str, object],
    ) -> object:
        result = handler(input_payload, **dependencies)
        if isawaitable(result):
            return await result
        return result

    async def _append_tool_result(
        self,
        tool_name: str,
        result: ToolResult,
        call_id: UUID | None,
        turn_id: int | None,
    ) -> None:
        event_type = "tool.completed" if result.status == "success" else "tool.failed"
        await self._append_event(
            EventCreate(
                event_type=event_type,
                call_id=call_id,
                correlation_id=f"turn:{turn_id}" if turn_id is not None else None,
                payload={
                    "tool_name": tool_name,
                    "status": result.status.value,
                    "error_code": result.error_code,
                    "retry_after_seconds": result.retry_after_seconds,
                },
            )
        )

    async def _append_event(self, event: EventCreate) -> None:
        if self._event_sink is None:
            return
        await self._event_sink.append(event)
