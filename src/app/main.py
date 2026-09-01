from pathlib import Path

from fastapi import FastAPI

from app.api import health_router
from app.api.v1 import router as v1_router
from app.config import AppConfig, DEFAULT_CONFIG
from app.models import TaskState
from app.openai_service import OpenAIService


def create_app(
    service: OpenAIService | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    application = FastAPI(title="Visual Recommendations MVP", version="1.0.0")
    application.state.tasks: dict[str, TaskState] = {}
    application.state.variant_paths: dict[str, dict[str, Path]] = {}
    application.state.service = service or OpenAIService()
    application.state.config = config or DEFAULT_CONFIG
    application.include_router(health_router)
    application.include_router(v1_router)
    return application


app = create_app()
