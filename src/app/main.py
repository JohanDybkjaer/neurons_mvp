"""Compose the FastAPI process, application-owned state, and provider client."""

import logging
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI
from openai import AsyncOpenAI

from app.ai_services import OpenAIService
from app.api import health_router
from app.api.v1 import router as v1_router
from app.api.v1.demo import router as demo_router
from app.config import AppConfig, load_config
from app.schema_models import TaskState


@contextmanager
def _application_logging(log_level: str) -> Iterator[None]:
    """Emit application logs to stdout for one application's lifetime.

    Previous logger state is restored on exit so multiple test applications do
    not leak handlers or log levels into one another.
    """

    application_logger = logging.getLogger("app")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    previous_level = application_logger.level
    previous_propagate = application_logger.propagate
    application_logger.addHandler(handler)
    application_logger.setLevel(log_level)
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
    """Build an isolated application with injectable external dependencies.

    Passing ``service`` and ``config`` keeps tests deterministic. During normal
    startup both are composed from the selected configuration and one
    application-owned OpenAI client.

    Args:
        service: Optional deterministic or externally managed AI service.
        config: Optional validated settings that bypass startup file loading.

    Returns:
        A fully routed FastAPI application with process-local task state.
    """

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Create and close the application-owned provider client."""

        active_config = config or load_config()
        with _application_logging(active_config.log_level):
            owned_client: AsyncOpenAI | None = None
            active_service = service
            # Only clients created here are closed here. Injected services remain
            # owned by the caller that supplied them.
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
    # Task state and artifact indexes intentionally share this process lifetime;
    # running more than one worker would create independent, inconsistent views.
    application.state.tasks: dict[str, TaskState] = {}
    application.state.variant_paths: dict[str, dict[str, Path]] = {}
    application.state.service = service
    application.state.config = config
    application.include_router(health_router)
    application.include_router(v1_router)
    application.include_router(demo_router)
    return application


app = create_app()
