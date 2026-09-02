"""Version 1 demo task routes with bundled inputs callers may override."""

import asyncio
import io
from pathlib import Path
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

DEMO_API_PREFIX = "/api/v1/demo"
DEMO_DIRECTORY = Path(__file__).resolve().parents[5] / "examples" / "demo"
DEMO_IMAGE_FILENAMES = ("creative_1.png", "creative_2.png")

router = APIRouter(prefix=DEMO_API_PREFIX, tags=["demo"])


async def _load_demo_upload(filename: str) -> UploadFile:
    """Create an upload object from a committed demo file on demand."""

    content = await asyncio.to_thread((DEMO_DIRECTORY / filename).read_bytes)
    return UploadFile(file=io.BytesIO(content), filename=filename)


@router.post(
    "/tasks",
    response_model=TaskCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_demo_task(
    request: Request,
    background_tasks: BackgroundTasks,
    images: Annotated[
        list[UploadFile] | None,
        File(
            description=(
                "Optional PNG/JPEG creatives; defaults to both bundled demo images"
            ),
            json_schema_extra={"items": BINARY_FILE_SCHEMA},
        ),
    ] = None,
    recommendations: Annotated[
        UploadFile | None,
        File(
            description=(
                "Optional recommendations JSON; defaults to the bundled demo file"
            ),
            json_schema_extra=BINARY_FILE_SCHEMA,
        ),
    ] = None,
    brand_guidelines: Annotated[
        UploadFile | None,
        File(
            description=(
                "Optional brand-guidelines JSON; defaults to the bundled demo file"
            ),
            json_schema_extra=BINARY_FILE_SCHEMA,
        ),
    ] = None,
) -> TaskCreated:
    """Run the demo bundle, optionally replacing any multipart input field.

    Execute the request with no files to use both bundled creatives and their
    matching JSON documents. Selecting a field in Swagger replaces that field's
    default while preserving the normal validation rules.
    """

    owned_uploads: list[UploadFile] = []
    try:
        active_images = images
        if active_images is None:
            active_images = [
                await _load_demo_upload(filename) for filename in DEMO_IMAGE_FILENAMES
            ]
            owned_uploads.extend(active_images)

        active_recommendations = recommendations
        if active_recommendations is None:
            active_recommendations = await _load_demo_upload("recommendations.json")
            owned_uploads.append(active_recommendations)

        active_guidelines = brand_guidelines
        if active_guidelines is None:
            active_guidelines = await _load_demo_upload("brand_guidelines.json")
            owned_uploads.append(active_guidelines)

        return await submit_task(
            request,
            background_tasks,
            active_images,
            active_recommendations,
            active_guidelines,
            DEMO_API_PREFIX,
        )
    finally:
        for upload in owned_uploads:
            await upload.close()


@router.get("/tasks/{task_id}", response_model=TaskState)
async def get_demo_task(request: Request, task_id: str) -> TaskState:
    """Return the current state of a demo task."""

    return read_task(request, task_id)


@router.get("/tasks/{task_id}/variants/{image_id}")
async def get_demo_variant(
    request: Request,
    task_id: str,
    image_id: str,
) -> FileResponse:
    """Return a completed variant created through the demo API."""

    return serve_variant(request, task_id, image_id)
