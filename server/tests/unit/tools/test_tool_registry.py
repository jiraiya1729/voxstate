import pytest
from app.tools.registry import (
    DuplicateToolError,
    ToolDefinition,
    ToolDependencyUnavailableError,
    ToolRegistry,
    UnknownToolError,
    build_default_tool_registry,
)


def noop_tool(**kwargs: object) -> object:
    return {"received": kwargs}


def test_default_registry_exposes_backend_owned_tools() -> None:
    registry = build_default_tool_registry(
        dependencies={
            "customer_repository": object(),
            "payment_repository": object(),
            "ticket_service": object(),
        }
    )

    definitions = registry.list_definitions()

    assert [definition.name for definition in definitions] == [
        "check_payment",
        "create_ticket",
        "get_customer",
    ]
    assert {
        definition.name: definition.required_dependencies for definition in definitions
    } == {
        "check_payment": frozenset({"payment_repository"}),
        "create_ticket": frozenset({"ticket_service"}),
        "get_customer": frozenset({"customer_repository"}),
    }


def test_duplicate_tool_names_are_rejected() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="get_customer",
            description="Fetch a customer record.",
            handler=noop_tool,
        )
    )

    with pytest.raises(DuplicateToolError, match="get_customer"):
        registry.register(
            ToolDefinition(
                name="get_customer",
                description="Conflicting implementation.",
                handler=noop_tool,
            )
        )


def test_unknown_tool_lookup_fails() -> None:
    registry = ToolRegistry()

    with pytest.raises(UnknownToolError, match="unknown_tool"):
        registry.get("unknown_tool")


def test_unavailable_dependencies_prevent_tool_resolution() -> None:
    registry = build_default_tool_registry(dependencies={})

    with pytest.raises(ToolDependencyUnavailableError, match="customer_repository"):
        registry.resolve("get_customer")


def test_available_tool_resolution_returns_bound_handler_and_dependencies() -> None:
    dependency = object()
    registry = ToolRegistry(dependencies={"customer_repository": dependency})
    registry.register(
        ToolDefinition(
            name="get_customer",
            description="Fetch a customer record.",
            handler=noop_tool,
            required_dependencies=frozenset({"customer_repository"}),
        )
    )

    resolved = registry.resolve("get_customer")

    assert resolved.definition.name == "get_customer"
    assert resolved.dependencies == {"customer_repository": dependency}
    assert resolved.handler(customer_id="cus_123") == {
        "received": {"customer_id": "cus_123"}
    }
