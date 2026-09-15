from uuid import uuid4

import pytest

from app.agents.errors import (
    AgentNotFoundError,
    RoutingAmbiguityError,
    RoutingNoMatchError,
)
from app.agents.routing import RoutingContext, RoutingService
from app.agents.schemas import (
    AgentCreate,
    AgentUpdate,
    PhoneRouteCreate,
    RoutingRuleCreate,
)
from app.agents.service import AgentService
from app.db.database import Database


def agent_data(name: str) -> AgentCreate:
    return AgentCreate(
        name=name,
        system_prompt=f"You are {name}.",
        language="en",
        bedrock_model_id=f"model.{name.lower()}",
        cartesia_voice_id=f"voice-{name.lower()}",
    )


@pytest.mark.asyncio
async def test_agent_crud_and_soft_delete(database: Database) -> None:
    service = AgentService(database)
    created = await service.create(agent_data("Support"))
    updated = await service.update(
        created.id, AgentUpdate(name="Priority Support", enabled=False)
    )
    assert updated.name == "Priority Support"
    assert updated.enabled is False
    assert [agent.id for agent in await service.list()] == [created.id]
    with pytest.raises(AgentNotFoundError):
        await service.get(created.id, selectable=True)
    await service.delete(created.id)
    with pytest.raises(AgentNotFoundError):
        await service.get(created.id)


@pytest.mark.asyncio
async def test_exact_route_beats_rule_and_fallback(database: Database) -> None:
    agents = AgentService(database)
    routing = RoutingService(database)
    exact = await agents.create(agent_data("Exact"))
    rule = await agents.create(agent_data("Rule"))
    fallback = await agents.create(agent_data("Fallback"))
    await routing.create_phone_route(
        PhoneRouteCreate(phone_number="+15555550100", agent_id=exact.id)
    )
    await routing.create_phone_route(PhoneRouteCreate(agent_id=fallback.id))
    await routing.create_rule(
        RoutingRuleCreate(language="en", priority=100, agent_id=rule.id)
    )
    decision = await routing.resolve(
        RoutingContext(called_number="+15555550100", language="en")
    )
    assert decision.agent.id == exact.id
    assert decision.reason == "exact_phone_number"


@pytest.mark.asyncio
async def test_rule_priority_specificity_ambiguity_and_fallback(
    database: Database,
) -> None:
    agents = AgentService(database)
    routing = RoutingService(database)
    first = await agents.create(agent_data("First"))
    second = await agents.create(agent_data("Second"))
    fallback = await agents.create(agent_data("Fallback Agent"))
    await routing.create_phone_route(PhoneRouteCreate(agent_id=fallback.id))
    await routing.create_rule(
        RoutingRuleCreate(language="en", priority=1, agent_id=first.id)
    )
    await routing.create_rule(
        RoutingRuleCreate(
            language="en", category="billing", priority=1, agent_id=second.id
        )
    )
    decision = await routing.resolve(
        RoutingContext(called_number="+15555550199", language="en", category="billing")
    )
    assert decision.agent.id == second.id
    await routing.create_rule(
        RoutingRuleCreate(
            language="en", category="billing", priority=1, agent_id=first.id
        )
    )
    with pytest.raises(RoutingAmbiguityError):
        await routing.resolve(
            RoutingContext(
                called_number="+15555550199", language="en", category="billing"
            )
        )
    fallback_decision = await routing.resolve(
        RoutingContext(called_number="+15555550198")
    )
    assert fallback_decision.agent.id == fallback.id


@pytest.mark.asyncio
async def test_no_match_and_unavailable_route_target(database: Database) -> None:
    routing = RoutingService(database)
    with pytest.raises(RoutingNoMatchError):
        await routing.resolve(RoutingContext(called_number="+15555550197"))
    with pytest.raises(AgentNotFoundError):
        await routing.create_phone_route(
            PhoneRouteCreate(phone_number="+15555550197", agent_id=uuid4())
        )
