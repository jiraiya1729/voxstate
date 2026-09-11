from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.calls import router as calls_router
from app.api.dependencies import close_application_dependencies
from app.api.health import router as health_router
from app.api.twilio_media import router as twilio_media_router
from app.api.twilio_webhooks import router as twilio_webhooks_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_application_dependencies()


def create_app() -> FastAPI:
    app = FastAPI(title="voxstate", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(calls_router)
    app.include_router(twilio_webhooks_router)
    app.include_router(twilio_media_router)
    return app


app = create_app()
