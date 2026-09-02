"""Compose the FastAPI process, application-owned state, and provider client."""

import asyncio
import logging
import shutil
import sys
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from openai import AsyncOpenAI

from app.ai_services import OpenAIService
from app.api import health_router
from app.api.error_handlers import handle_http_exception, handle_request_validation_error
from app.api.v1 import router as v1_router
from app.api.v1.demo import router as demo_router
from app.config import AppConfig, load_config
from app.schema_models import TaskState

LOGGER = logging.getLogger(__name__)


def _clear_runtime_directories(runtime_root: Path) -> None:
    """Remove application-owned task artifacts and logs from an earlier run."""

    runtime_log_root = runtime_root.parent / "logs"
    for directory in (runtime_root, runtime_log_root):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)


@contextmanager
def _application_logging(log_level: str, runtime_root: Path) -> Iterator[None]:
    """Write application and Uvicorn logs to a runtime log for one lifetime.

    Previous logger state is restored on exit so multiple test applications do
    not leak handlers or log levels into one another.
    """

    application_logger = logging.getLogger("app")
    log_file = runtime_root.parent / "logs" / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    stream_handler = logging.StreamHandler(sys.stdout)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    stream_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    previous_level = application_logger.level
    previous_propagate = application_logger.propagate
    application_logger.addHandler(stream_handler)
    application_logger.addHandler(file_handler)
    application_logger.setLevel(log_level)
    application_logger.propagate = False
    uvicorn_loggers = (
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.access"),
    )
    for logger in uvicorn_loggers:
        logger.addHandler(file_handler)
    try:
        yield
    finally:
        for logger in uvicorn_loggers:
            logger.removeHandler(file_handler)
        application_logger.removeHandler(stream_handler)
        application_logger.removeHandler(file_handler)
        stream_handler.close()
        file_handler.close()
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
        await asyncio.to_thread(_clear_runtime_directories, active_config.runtime_root)
        application.state.tasks.clear()
        application.state.variant_paths.clear()
        with _application_logging(active_config.log_level, active_config.runtime_root):
            LOGGER.info("application started")
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
                LOGGER.info("application stopped")

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
    application.add_exception_handler(
        RequestValidationError, handle_request_validation_error
    )
    application.add_exception_handler(HTTPException, handle_http_exception)
    return application


app = create_app()
