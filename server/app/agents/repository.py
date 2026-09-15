"""Database repositories for agents, phone-number routes, and routing rules."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, PhoneNumberRoute, RoutingRule
from app.agents.schemas import (
    AgentCreate,
    AgentUpdate,
    PhoneRouteCreate,
    RoutingRuleCreate,
)


class AgentRepository:
    """SQLAlchemy queries for persisted agents and soft-delete behavior."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: AgentCreate) -> Agent:
        """Insert an agent row from validated API data."""
        agent = Agent(**data.model_dump())
        self.session.add(agent)
        await self.session.flush()
        await self.session.refresh(agent)
        return agent

    async def list(self) -> list[Agent]:
        """Return non-deleted agents in stable display order."""
        result = await self.session.execute(
            select(Agent)
            .where(Agent.deleted_at.is_(None))
            .order_by(Agent.name, Agent.id)
        )
        return list(result.scalars())

    async def get(self, agent_id: UUID, *, selectable: bool = False) -> Agent | None:
        """Load an agent, optionally requiring it to be enabled for call selection."""
        statement = select(Agent).where(
            Agent.id == agent_id, Agent.deleted_at.is_(None)
        )
        if selectable:
            statement = statement.where(Agent.enabled.is_(True))
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def update(self, agent: Agent, data: AgentUpdate) -> Agent:
        """Apply partial validated updates to an existing agent row."""
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(agent, key, value)
        await self.session.flush()
        await self.session.refresh(agent)
        return agent

    async def soft_delete(self, agent: Agent) -> None:
        """Hide an agent from selection while preserving historical call references."""
        agent.enabled = False
        agent.deleted_at = datetime.now(UTC)
        await self.session.flush()


class RoutingRepository:
    """SQLAlchemy queries for exact phone routes and ranked routing rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_phone_route(self, data: PhoneRouteCreate) -> PhoneNumberRoute:
        """Insert an exact or fallback phone route."""
        route = PhoneNumberRoute(**data.model_dump())
        self.session.add(route)
        await self.session.flush()
        await self.session.refresh(route)
        return route

    async def list_phone_routes(self) -> list[PhoneNumberRoute]:
        """Return configured phone routes with fallback routes last."""
        return list(
            (
                await self.session.execute(
                    select(PhoneNumberRoute).order_by(
                        PhoneNumberRoute.phone_number.nulls_last(), PhoneNumberRoute.id
                    )
                )
            ).scalars()
        )

    async def create_rule(self, data: RoutingRuleCreate) -> RoutingRule:
        """Insert a deterministic routing rule after schema validation."""
        rule = RoutingRule(**data.model_dump())
        self.session.add(rule)
        await self.session.flush()
        await self.session.refresh(rule)
        return rule

    async def list_rules(self) -> list[RoutingRule]:
        """Return routing rules in stable insertion order."""
        return list(
            (
                await self.session.execute(select(RoutingRule).order_by(RoutingRule.id))
            ).scalars()
        )

    async def candidates(self) -> tuple[list[PhoneNumberRoute], list[RoutingRule]]:
        """Return enabled routes and rules for in-memory routing resolution."""
        routes = list(
            (
                await self.session.execute(
                    select(PhoneNumberRoute).where(PhoneNumberRoute.enabled.is_(True))
                )
            ).scalars()
        )
        rules = list(
            (
                await self.session.execute(
                    select(RoutingRule).where(RoutingRule.enabled.is_(True))
                )
            ).scalars()
        )
        return routes, rules
