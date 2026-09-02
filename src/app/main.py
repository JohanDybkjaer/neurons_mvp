"""FastAPI application composition root."""

import logging
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI
from openai import AsyncOpenAI

from app.api import health_router
from app.api.v1 import router as v1_router
from app.config import AppConfig, load_config
from app.models import TaskState
from app.openai_service import OpenAIService


@contextmanager
def _application_logging() -> Iterator[None]:
    """Emit application logs to stdout for the application's lifetime."""

    application_logger = logging.getLogger("app")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    previous_level = application_logger.level
    previous_propagate = application_logger.propagate
    application_logger.addHandler(handler)
    application_logger.setLevel(logging.INFO)
    application_logger.propagate = False
    try:
        yield
    finally:
        application_logger.removeHandler(handler)
        handler.close()
        application_logger.setLevel(previous_level)
        application_logger.propagate = previous_propagate


def create_app(
    service: OpenAIService | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    """Build an isolated application with injectable service and settings."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Create and close the application-owned provider client."""

        with _application_logging():
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
