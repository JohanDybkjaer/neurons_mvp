"""Shared HTTP-boundary operations for task creation and retrieval."""

import asyncio
import io
import json
import logging
from pathlib import Path
from typing import TypeVar, cast
from uuid import uuid4

from fastapi import BackgroundTasks, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ValidationError

from app.config import AppConfig
from app.schema_models import (
    BrandGuidelineFile,
    BrandGuidelinesDocument,
    RecommendationFile,
    RecommendationsDocument,
    TaskCreated,
    TaskState,
    TaskStatus,
)
from app.workflows import ImageWorkItem, run_task

ModelType = TypeVar("ModelType", bound=BaseModel)
FilenameEntry = TypeVar("FilenameEntry", RecommendationFile, BrandGuidelineFile)
# Public request boundary. The workflow independently limits active pipelines to two.
MAX_IMAGES = 10

# Swagger UI uses OpenAPI's binary format marker to render operating-system
# file pickers. Pydantic otherwise emits only contentMediaType for UploadFile.
BINARY_FILE_SCHEMA = {"type": "string", "format": "binary"}
LOGGER = logging.getLogger(__name__)


def _decode_image(image_bytes: bytes) -> str:
    """Decode valid PNG/JPEG bytes and return the server-owned file suffix."""

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = image.format
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("Invalid image") from error

    if image_format == "PNG":
        return ".png"
    if image_format == "JPEG":
        return ".jpg"
    raise ValueError("Unsupported image format")


async def _parse_json_upload(
    upload: UploadFile,
    model_type: type[ModelType],
    label: str,
) -> ModelType:
    """Parse one uploaded JSON document or return a safe HTTP 422 response."""

    try:
        content = await upload.read()
        return model_type.model_validate(json.loads(content))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid {label} JSON.",
        ) from None


async def _store_validated_json_inputs(
    input_directory: Path,
    recommendations: RecommendationsDocument,
    brand_guidelines: BrandGuidelinesDocument,
) -> None:
    """Write canonical validated JSON inputs into the server-owned task directory."""

    await asyncio.gather(
        asyncio.to_thread(
            (input_directory / "recommendations.json").write_text,
            recommendations.model_dump_json(indent=2),
            encoding="utf-8",
        ),
        asyncio.to_thread(
            (input_directory / "brand_guidelines.json").write_text,
            brand_guidelines.model_dump_json(indent=2),
            encoding="utf-8",
        ),
    )


def _index_by_filename(
    entries: list[FilenameEntry],
    label: str,
) -> dict[str, FilenameEntry]:
    """Index parsed entries by filename and reject duplicate join keys."""

    indexed = {entry.filename: entry for entry in entries}
    if len(indexed) != len(entries):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Duplicate filename in {label} JSON.",
        )
    return indexed


def _validate_filename_matches(
    filenames: list[str],
    recommendations: dict[str, RecommendationFile],
    guidelines: dict[str, BrandGuidelineFile],
) -> None:
    """Require JSON entries to match uploaded image filenames exactly once."""

    expected = set(filenames)
    if len(expected) != len(filenames):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Image filenames must be unique.",
        )
    if set(recommendations) != expected or set(guidelines) != expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="JSON filenames must match the uploaded images.",
        )


async def submit_task(
    request: Request,
    background_tasks: BackgroundTasks,
    images: list[UploadFile],
    recommendations: UploadFile,
    brand_guidelines: UploadFile,
    api_prefix: str,
) -> TaskCreated:
    """Validate one to ten matching uploads, persist them, and schedule processing."""

    app_config = cast(AppConfig, request.app.state.config)
    LOGGER.info("event=task_submission_received image_count=%d", len(images))
    if not 1 <= len(images) <= MAX_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Upload between one and ten images.",
        )

    # Parse both documents before writing files so malformed requests leave no
    # partial task directory behind.
    recommendation_document = await _parse_json_upload(
        recommendations, RecommendationsDocument, "recommendations"
    )
    guideline_document = await _parse_json_upload(
        brand_guidelines, BrandGuidelinesDocument, "brand guidelines"
    )
    recommendations_by_filename = _index_by_filename(
        list(recommendation_document.root.values()), "recommendations"
    )
    guidelines_by_filename = _index_by_filename(
        list(guideline_document.root.values()), "brand guidelines"
    )

    # Filenames are join keys between the three multipart inputs. They are
    # validated here, then replaced by server-owned IDs for filesystem access.
    filenames = [image.filename or "" for image in images]
    _validate_filename_matches(
        filenames, recommendations_by_filename, guidelines_by_filename
    )

    validated_images: list[tuple[str, bytes, str]] = []
    for image in images:
        # Reading one extra byte detects an oversized upload without buffering
        # the rest of an untrusted file.
        image_bytes = await image.read(app_config.max_image_bytes + 1)
        if len(image_bytes) > app_config.max_image_bytes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Image exceeds the upload size limit.",
            )
        try:
            suffix = await asyncio.to_thread(_decode_image, image_bytes)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Images must be valid PNG or JPEG files.",
            ) from None
        validated_images.append((image.filename or "", image_bytes, suffix))

    # UUID-backed directories ensure uploaded filenames are metadata only and
    # can never choose a filesystem path.
    task_id = str(uuid4())
    task_directory = app_config.runtime_root / task_id
    input_directory = task_directory / "inputs"
    variant_directory = task_directory / "variants"
    await asyncio.to_thread(input_directory.mkdir, parents=True)
    await asyncio.to_thread(variant_directory.mkdir, parents=True)
    await _store_validated_json_inputs(
        input_directory,
        recommendation_document,
        guideline_document,
    )

    work_items: list[ImageWorkItem] = []
    variant_paths: dict[str, Path] = {}
    for index, (filename, image_bytes, suffix) in enumerate(validated_images, start=1):
        image_id = f"image_{index}"
        original_path = input_directory / f"{image_id}{suffix}"
        variant_path = variant_directory / f"{image_id}{suffix}"
        await asyncio.to_thread(original_path.write_bytes, image_bytes)
        recommendation_entry = recommendations_by_filename[filename]
        guideline_entry = guidelines_by_filename[filename]
        work_items.append(
            ImageWorkItem(
                image_id=image_id,
                source_filename=filename,
                original_path=original_path,
                variant_path=variant_path,
                variant_url=f"{api_prefix}/tasks/{task_id}/variants/{image_id}",
                recommendations=recommendation_entry.recommendations,
                brand_guidelines=guideline_entry.brand_guidelines,
            )
        )
        variant_paths[image_id] = variant_path

    task = TaskState(task_id=task_id, status=TaskStatus.pending)
    request.app.state.tasks[task_id] = task
    request.app.state.variant_paths[task_id] = variant_paths
    background_tasks.add_task(
        run_task,
        task,
        work_items,
        request.app.state.service,
        app_config.provider_timeout_seconds,
        app_config.max_iterations,
    )
    LOGGER.info(
        "task_id=%s image_id=all step=submission outcome=accepted image_count=%d",
        task_id,
        len(work_items),
    )
    return TaskCreated(
        task_id=task_id,
        status=TaskStatus.pending,
        status_url=f"{api_prefix}/tasks/{task_id}",
    )


def read_task(request: Request, task_id: str) -> TaskState:
    """Return a process-local task or a safe not-found response."""

    task = request.app.state.tasks.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found."
        )
    return cast(TaskState, task)


def serve_variant(request: Request, task_id: str, image_id: str) -> FileResponse:
    """Serve a completed artifact through server-owned task and image IDs."""

    task = request.app.state.tasks.get(task_id)
    variant_path = request.app.state.variant_paths.get(task_id, {}).get(image_id)
    if (
        task is None
        or task.status != TaskStatus.completed
        or variant_path is None
        or not variant_path.is_file()
    ):
        # Use the same response for unknown, unfinished, and missing artifacts;
        # no server path or task detail is exposed at this boundary.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found."
        )
    return FileResponse(variant_path)
