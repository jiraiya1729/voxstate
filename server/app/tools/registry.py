"""Deterministic registry for backend-owned voice tools."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.tools.schemas import (
    CheckPaymentInput,
    CreateTicketInput,
    GetCustomerInput,
    ToolInput,
)

ToolHandler = Callable[..., object]
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class DuplicateToolError(Exception):
    """Raised when two tools use the same public name."""


class UnknownToolError(Exception):
    """Raised when a requested tool name is not registered."""


class ToolDependencyUnavailableError(Exception):
    """Raised when a registered tool cannot be used in this runtime."""


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Public metadata and backend handler for one deterministic tool."""

    name: str
    description: str
    handler: ToolHandler
    input_model: type[ToolInput] = ToolInput
    required_dependencies: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        name = self.name.strip()
        description = self.description.strip()
        if not _TOOL_NAME_PATTERN.fullmatch(name):
            raise ValueError("tool name must be lowercase snake_case")
        if not description:
            raise ValueError("tool description is required")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)


@dataclass(frozen=True, slots=True)
class ResolvedTool:
    """A registered tool bound to the dependencies required to run it."""

    definition: ToolDefinition
    handler: ToolHandler
    dependencies: dict[str, object]


class ToolRegistry:
    """In-memory catalog for tools available to the voice runtime."""

    def __init__(self, dependencies: Mapping[str, object] | None = None) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._dependencies = dict(dependencies or {})

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise DuplicateToolError(f"tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise UnknownToolError(f"unknown tool: {name}") from exc

    def list_definitions(self) -> list[ToolDefinition]:
        return [self._definitions[name] for name in sorted(self._definitions)]

    def resolve(self, name: str) -> ResolvedTool:
        definition = self.get(name)
        missing = sorted(
            dependency
            for dependency in definition.required_dependencies
            if dependency not in self._dependencies
        )
        if missing:
            raise ToolDependencyUnavailableError(
                f"tool '{name}' missing dependencies: {', '.join(missing)}"
            )

        return ResolvedTool(
            definition=definition,
            handler=definition.handler,
            dependencies={
                dependency: self._dependencies[dependency]
                for dependency in definition.required_dependencies
            },
        )


def _unimplemented_tool(*_: Any, **__: Any) -> object:
    raise NotImplementedError("tool handler is connected in the application layer")


def build_default_tool_registry(
    dependencies: Mapping[str, object] | None = None,
) -> ToolRegistry:
    """Register the first backend-owned tools exposed to the model layer."""

    registry = ToolRegistry(dependencies=dependencies)
    registry.register(
        ToolDefinition(
            name="get_customer",
            description="Fetch the customer record for the current call.",
            handler=_unimplemented_tool,
            input_model=GetCustomerInput,
            required_dependencies=frozenset({"customer_repository"}),
        )
    )
    registry.register(
        ToolDefinition(
            name="check_payment",
            description="Check payment status for the customer or account.",
            handler=_unimplemented_tool,
            input_model=CheckPaymentInput,
            required_dependencies=frozenset({"payment_repository"}),
        )
    )
    registry.register(
        ToolDefinition(
            name="create_ticket",
            description="Create a support ticket from the conversation context.",
            handler=_unimplemented_tool,
            input_model=CreateTicketInput,
            required_dependencies=frozenset({"ticket_service"}),
        )
    )
    return registry
