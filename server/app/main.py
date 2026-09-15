"""FastAPI composition root for Voxstate.

This file creates the app, attaches all API route modules, and closes shared resources
when the process shuts down.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import close_application_dependencies
from app.api.routes.agents import router as agents_router
from app.api.routes.calls import router as calls_router
from app.api.routes.health import router as health_router
from app.api.routes.transfers import router as transfers_router
from app.api.routes.twilio_media import router as twilio_media_router
from app.api.routes.twilio_webhooks import router as twilio_webhooks_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Close cached provider, database, and active-call resources on app shutdown."""
    yield
    await close_application_dependencies()


def create_app() -> FastAPI:
    """Build the FastAPI application and attach all route modules."""
    app = FastAPI(title="voxstate", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(calls_router)
    app.include_router(agents_router)
    app.include_router(twilio_webhooks_router)
    app.include_router(twilio_media_router)
    app.include_router(transfers_router)
    return app


app = create_app()
