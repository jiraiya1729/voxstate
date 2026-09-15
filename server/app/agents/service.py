"""Application service for voice-agent CRUD operations."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.agents.errors import AgentConflictError, AgentNotFoundError
from app.agents.models import Agent
from app.agents.repository import AgentRepository
from app.agents.schemas import AgentCreate, AgentUpdate
from app.db.database import Database


class AgentService:
    """Agent CRUD service that maps repository errors to domain errors."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, data: AgentCreate) -> Agent:
        """Create a new agent and translate duplicate names into AgentConflictError."""
        try:
            async with self.database.session() as session:
                return await AgentRepository(session).create(data)
        except IntegrityError as exc:
            raise AgentConflictError("agent name already exists") from exc

    async def list(self) -> list[Agent]:
        """Return all non-deleted agents for API display and selection."""
        async with self.database.session() as session:
            return await AgentRepository(session).list()

    async def get(self, agent_id: UUID, *, selectable: bool = False) -> Agent:
        """Load one agent or raise when missing, deleted, or not selectable."""
        async with self.database.session() as session:
            agent = await AgentRepository(session).get(agent_id, selectable=selectable)
        if agent is None:
            raise AgentNotFoundError(str(agent_id))
        return agent

    async def update(self, agent_id: UUID, data: AgentUpdate) -> Agent:
        """Apply partial agent edits while preserving unique-name errors."""
        try:
            async with self.database.session() as session:
                repository = AgentRepository(session)
                agent = await repository.get(agent_id)
                if agent is None:
                    raise AgentNotFoundError(str(agent_id))
                return await repository.update(agent, data)
        except IntegrityError as exc:
            raise AgentConflictError("agent name already exists") from exc

    async def delete(self, agent_id: UUID) -> None:
        """Soft-delete an agent so old calls keep their foreign-key history."""
        async with self.database.session() as session:
            repository = AgentRepository(session)
            agent = await repository.get(agent_id)
            if agent is None:
                raise AgentNotFoundError(str(agent_id))
            await repository.soft_delete(agent)
