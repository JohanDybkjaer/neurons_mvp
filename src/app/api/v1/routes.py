"""Version 1 routes for normal user-supplied task inputs."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.api.task_operations import (
    BINARY_FILE_SCHEMA,
    read_task,
    serve_variant,
    submit_task,
)
from app.schema_models import TaskCreated, TaskState

API_V1_PREFIX = "/api/v1"

router = APIRouter(prefix=API_V1_PREFIX, tags=["tasks"])


@router.post(
    "/tasks",
    response_model=TaskCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_task(
    request: Request,
    background_tasks: BackgroundTasks,
    images: Annotated[
        list[UploadFile],
        File(
            description="One or two PNG/JPEG creatives",
            json_schema_extra={"items": BINARY_FILE_SCHEMA},
        ),
    ],
    recommendations: Annotated[
        UploadFile,
        File(
            description="Recommendations JSON file",
            json_schema_extra=BINARY_FILE_SCHEMA,
        ),
    ],
    brand_guidelines: Annotated[
        UploadFile,
        File(
            description="Brand guidelines JSON file",
            json_schema_extra=BINARY_FILE_SCHEMA,
        ),
    ],
) -> TaskCreated:
    """Validate required uploads and schedule asynchronous processing."""

    return await submit_task(
        request,
        background_tasks,
        images,
        recommendations,
        brand_guidelines,
        API_V1_PREFIX,
    )


@router.get("/tasks/{task_id}", response_model=TaskState)
async def get_task(request: Request, task_id: str) -> TaskState:
    """Return the current state of a normally submitted task."""

    return read_task(request, task_id)


@router.get("/tasks/{task_id}/variants/{image_id}")
async def get_variant(
    request: Request,
    task_id: str,
    image_id: str,
) -> FileResponse:
    """Return a completed variant for a normally submitted task."""

    return serve_variant(request, task_id, image_id)
