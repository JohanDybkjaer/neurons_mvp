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
    summary="Start visual recommendation processing",
    response_description="Accepted task with a polling URL",
)
async def create_task(
    request: Request,
    background_tasks: BackgroundTasks,
    images: Annotated[
        list[UploadFile],
        File(
            description="One to ten PNG/JPEG creatives",
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
    """Start asynchronous processing for matching multipart uploads.

    - Upload one to ten PNG or JPEG creatives.
    - Supply recommendation and brand-guideline JSON entries for every filename.
    - Poll the returned URL for final evaluations and generated-variant URLs.
    """

    return await submit_task(
        request,
        background_tasks,
        images,
        recommendations,
        brand_guidelines,
        API_V1_PREFIX,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskState,
    summary="Poll a visual recommendation task",
    response_description="Current task state and final results when available",
)
async def get_task(request: Request, task_id: str) -> TaskState:
    """Return the current task lifecycle state and final results when complete.

    Completed image results include the actual iteration count, evaluation, and
    generated-variant URL. Unknown task IDs return HTTP 404.
    """

    return read_task(request, task_id)


@router.get(
    "/tasks/{task_id}/variants/{image_id}",
    summary="Retrieve a completed generated variant",
    response_description="Generated PNG or JPEG variant",
)
async def get_variant(
    request: Request,
    task_id: str,
    image_id: str,
) -> FileResponse:
    """Return the stored PNG or JPEG for a completed image result.

    Unfinished, missing, and unknown artifacts return the same HTTP 404 response.
    """

    return serve_variant(request, task_id, image_id)
