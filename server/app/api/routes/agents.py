"""Agent and routing configuration API routes.

This file exposes CRUD endpoints for voice agents, phone routes, and routing rules.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.agents.errors import AgentConflictError, AgentNotFoundError
from app.agents.routing import RoutingService
from app.agents.schemas import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    PhoneRouteCreate,
    PhoneRouteResponse,
    RoutingRuleCreate,
    RoutingRuleResponse,
)
from app.agents.service import (
    AgentService,
)
from app.api.dependencies import get_agent_service, get_routing_service

router = APIRouter(tags=["agents"])


def _agent_error(exc: Exception) -> HTTPException:
    """Map agent-domain errors to HTTP responses for route handlers."""
    if isinstance(exc, AgentNotFoundError):
        return HTTPException(status_code=404, detail="Agent not found")
    return HTTPException(status_code=409, detail=str(exc))


@router.post("/agents", response_model=AgentResponse, status_code=201)
async def create_agent(
    data: AgentCreate, service: Annotated[AgentService, Depends(get_agent_service)]
) -> AgentResponse:
    """Create a voice agent configuration."""
    try:
        return AgentResponse.model_validate(await service.create(data))
    except AgentConflictError as exc:
        raise _agent_error(exc) from exc


@router.get("/agents", response_model=list[AgentResponse])
async def list_agents(
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> list[AgentResponse]:
    """Return all non-deleted voice agents."""
    return [AgentResponse.model_validate(agent) for agent in await service.list()]


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID, service: Annotated[AgentService, Depends(get_agent_service)]
) -> AgentResponse:
    """Return one voice agent by ID."""
    try:
        return AgentResponse.model_validate(await service.get(agent_id))
    except AgentNotFoundError as exc:
        raise _agent_error(exc) from exc


@router.patch("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentResponse:
    """Apply partial updates to one voice agent."""
    try:
        return AgentResponse.model_validate(await service.update(agent_id, data))
    except (AgentNotFoundError, AgentConflictError) as exc:
        raise _agent_error(exc) from exc


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: UUID, service: Annotated[AgentService, Depends(get_agent_service)]
) -> Response:
    """Soft-delete an agent so historical calls keep their references."""
    try:
        await service.delete(agent_id)
    except AgentNotFoundError as exc:
        raise _agent_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/phone-routes", response_model=PhoneRouteResponse, status_code=201)
async def create_phone_route(
    data: PhoneRouteCreate,
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> PhoneRouteResponse:
    """Create an exact or fallback destination-number route."""
    try:
        return PhoneRouteResponse.model_validate(await service.create_phone_route(data))
    except (AgentNotFoundError, AgentConflictError) as exc:
        raise _agent_error(exc) from exc


@router.get("/phone-routes", response_model=list[PhoneRouteResponse])
async def list_phone_routes(
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> list[PhoneRouteResponse]:
    """Return configured phone-number routes."""
    return [
        PhoneRouteResponse.model_validate(route)
        for route in await service.list_phone_routes()
    ]


@router.post("/routing-rules", response_model=RoutingRuleResponse, status_code=201)
async def create_routing_rule(
    data: RoutingRuleCreate,
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> RoutingRuleResponse:
    """Create a ranked routing rule for call signals."""
    try:
        return RoutingRuleResponse.model_validate(await service.create_rule(data))
    except AgentNotFoundError as exc:
        raise _agent_error(exc) from exc


@router.get("/routing-rules", response_model=list[RoutingRuleResponse])
async def list_routing_rules(
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> list[RoutingRuleResponse]:
    """Return configured deterministic routing rules."""
    return [
        RoutingRuleResponse.model_validate(rule) for rule in await service.list_rules()
    ]
