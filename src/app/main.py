"""FastAPI application composition root."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from openai import AsyncOpenAI

from app.api import health_router
from app.api.v1 import router as v1_router
from app.config import AppConfig, load_config
from app.models import TaskState
from app.openai_service import OpenAIService


def create_app(
    service: OpenAIService | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    """Build an isolated application with injectable service and settings."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Create and close the application-owned provider client."""

        active_config = config or load_config()
        owned_client: AsyncOpenAI | None = None
        active_service = service
        if active_service is None:
            owned_client = AsyncOpenAI(
                api_key=active_config.openai_api_key.get_secret_value(),
                timeout=active_config.provider_timeout_seconds,
                max_retries=0,
            )
            active_service = OpenAIService(
                owned_client,
                active_config.image_model,
                active_config.evaluation_model,
            )
        application.state.config = active_config
        application.state.service = active_service
        try:
            yield
        finally:
            if owned_client is not None:
                await owned_client.close()

    application = FastAPI(
        title="Visual Recommendations MVP",
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    application.state.tasks: dict[str, TaskState] = {}
    application.state.variant_paths: dict[str, dict[str, Path]] = {}
    application.state.service = service
    application.state.config = config
    application.include_router(health_router)
    application.include_router(v1_router)
    return application


app = create_app()
