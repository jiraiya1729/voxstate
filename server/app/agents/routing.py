"""Deterministic agent routing for inbound calls.

This file chooses one enabled agent using exact phone routes, ranked rules, or fallback.
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from app.agents.errors import (
    AgentConflictError,
    AgentNotFoundError,
    RoutingAmbiguityError,
    RoutingNoMatchError,
)
from app.agents.models import Agent, PhoneNumberRoute, RoutingRule
from app.agents.repository import AgentRepository, RoutingRepository
from app.agents.schemas import PhoneRouteCreate, RoutingRuleCreate
from app.db.database import Database


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """Known call signals used to select an agent before the media session starts."""

    called_number: str
    language: str | None = None
    category: str | None = None


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Resolved agent plus the reason the routing policy selected it."""

    agent: Agent
    reason: str


def _rule_matches(rule: RoutingRule, context: RoutingContext) -> bool:
    """Return true when every configured signal on a rule matches the call."""
    return (
        (rule.called_number is None or rule.called_number == context.called_number)
        and (
            rule.language is None
            or rule.language.casefold() == (context.language or "").casefold()
        )
        and (
            rule.category is None
            or rule.category.casefold() == (context.category or "").casefold()
        )
    )


def _specificity(rule: RoutingRule) -> int:
    """Count how many signals a rule defines so more specific rules win ties."""
    return sum(
        value is not None
        for value in (rule.called_number, rule.language, rule.category)
    )


class RoutingService:
    """Deterministically selects agents from exact routes, rules, or fallback routes."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_phone_route(self, data: PhoneRouteCreate) -> PhoneNumberRoute:
        """Create a route only if its target agent is selectable."""
        async with self.database.session() as session:
            if (
                await AgentRepository(session).get(data.agent_id, selectable=True)
                is None
            ):
                raise AgentNotFoundError(str(data.agent_id))
            try:
                return await RoutingRepository(session).create_phone_route(data)
            except IntegrityError as exc:
                raise AgentConflictError("phone route already exists") from exc

    async def list_phone_routes(self) -> list[PhoneNumberRoute]:
        """List configured phone-number routes for API/admin display."""
        async with self.database.session() as session:
            return await RoutingRepository(session).list_phone_routes()

    async def create_rule(self, data: RoutingRuleCreate) -> RoutingRule:
        """Create a routing rule only if its target agent is selectable."""
        async with self.database.session() as session:
            if (
                await AgentRepository(session).get(data.agent_id, selectable=True)
                is None
            ):
                raise AgentNotFoundError(str(data.agent_id))
            return await RoutingRepository(session).create_rule(data)

    async def list_rules(self) -> list[RoutingRule]:
        """List deterministic routing rules for API/admin display."""
        async with self.database.session() as session:
            return await RoutingRepository(session).list_rules()

    async def resolve(self, context: RoutingContext) -> RoutingDecision:
        """Resolve a call to one enabled agent by exact, rule, then fallback order."""
        async with self.database.session() as session:
            routes, rules = await RoutingRepository(session).candidates()
            agents = {
                agent.id: agent
                for agent in await AgentRepository(session).list()
                if agent.enabled
            }

        exact = [
            route
            for route in routes
            if route.phone_number == context.called_number and route.agent_id in agents
        ]
        if exact:
            return RoutingDecision(agents[exact[0].agent_id], "exact_phone_number")

        matching = [
            rule
            for rule in rules
            if rule.agent_id in agents and _rule_matches(rule, context)
        ]
        if matching:
            best_rank = max((rule.priority, _specificity(rule)) for rule in matching)
            best = [
                rule
                for rule in matching
                if (rule.priority, _specificity(rule)) == best_rank
            ]
            agent_ids = {rule.agent_id for rule in best}
            if len(agent_ids) != 1:
                raise RoutingAmbiguityError("top-ranked rules target different agents")
            agent_id = next(iter(agent_ids))
            return RoutingDecision(agents[agent_id], "routing_rule")

        fallback = [
            route
            for route in routes
            if route.phone_number is None and route.agent_id in agents
        ]
        if fallback:
            return RoutingDecision(agents[fallback[0].agent_id], "fallback")
        raise RoutingNoMatchError(context.called_number)
