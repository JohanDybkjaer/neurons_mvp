import asyncio
import io
import json
from pathlib import Path
from typing import Annotated, TypeVar
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ValidationError

from app.config import AppConfig, DEFAULT_CONFIG
from app.models import (
    BrandGuidelineFile,
    BrandGuidelinesDocument,
    HealthResponse,
    RecommendationFile,
    RecommendationsDocument,
    TaskCreated,
    TaskState,
    TaskStatus,
)
from app.openai_service import OpenAIService
from app.workflow import ImageWorkItem, run_task

ModelType = TypeVar("ModelType", bound=BaseModel)
FilenameEntry = TypeVar("FilenameEntry", RecommendationFile, BrandGuidelineFile)


def _decode_image(image_bytes: bytes) -> str:
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
    try:
        content = await upload.read()
        return model_type.model_validate(json.loads(content))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid {label} JSON.",
        ) from None


def _index_by_filename(
    entries: list[FilenameEntry],
    label: str,
) -> dict[str, FilenameEntry]:
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


def create_app(
    service: OpenAIService | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    app_config = config or DEFAULT_CONFIG
    application = FastAPI(title="Visual Recommendations MVP")
    application.state.tasks: dict[str, TaskState] = {}
    application.state.variant_paths: dict[str, dict[str, Path]] = {}
    application.state.service = service or OpenAIService()
    application.state.config = app_config

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.post(
        "/tasks",
        response_model=TaskCreated,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_task(
        background_tasks: BackgroundTasks,
        images: Annotated[
            list[UploadFile], File(description="One or two PNG/JPEG creatives")
        ],
        recommendations: Annotated[
            UploadFile, File(description="Recommendations JSON file")
        ],
        brand_guidelines: Annotated[
            UploadFile, File(description="Brand guidelines JSON file")
        ],
    ) -> TaskCreated:
        if not 1 <= len(images) <= 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Upload one or two images.",
            )

        recommendation_document = await _parse_json_upload(
            recommendations, RecommendationsDocument, "recommendations"
        )
        guideline_document = await _parse_json_upload(
            brand_guidelines, BrandGuidelinesDocument, "brand guidelines"
        )
        recommendation_entries = list(recommendation_document.root.values())
        guideline_entries = list(guideline_document.root.values())
        recommendations_by_filename = _index_by_filename(
            recommendation_entries, "recommendations"
        )
        guidelines_by_filename = _index_by_filename(
            guideline_entries, "brand guidelines"
        )

        filenames = [image.filename or "" for image in images]
        _validate_filename_matches(
            filenames, recommendations_by_filename, guidelines_by_filename
        )

        validated_images: list[tuple[str, bytes, str]] = []
        for image in images:
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

        task_id = str(uuid4())
        task_directory = app_config.runtime_root / task_id
        input_directory = task_directory / "inputs"
        variant_directory = task_directory / "variants"
        await asyncio.to_thread(input_directory.mkdir, parents=True)
        await asyncio.to_thread(variant_directory.mkdir, parents=True)

        work_items: list[ImageWorkItem] = []
        variant_paths: dict[str, Path] = {}
        for index, (filename, image_bytes, suffix) in enumerate(
            validated_images, start=1
        ):
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
                    recommendations=recommendation_entry.recommendations,
                    brand_guidelines=guideline_entry.brand_guidelines,
                )
            )
            variant_paths[image_id] = variant_path

        task = TaskState(task_id=task_id, status=TaskStatus.pending)
        application.state.tasks[task_id] = task
        application.state.variant_paths[task_id] = variant_paths
        background_tasks.add_task(
            run_task,
            task,
            work_items,
            application.state.service,
            app_config.provider_timeout_seconds,
        )
        return TaskCreated(
            task_id=task_id,
            status=TaskStatus.pending,
            status_url=f"/tasks/{task_id}",
        )

    @application.get("/tasks/{task_id}", response_model=TaskState)
    async def get_task(task_id: str) -> TaskState:
        task = application.state.tasks.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Task not found."
            )
        return task

    @application.get("/tasks/{task_id}/variants/{image_id}")
    async def get_variant(task_id: str, image_id: str) -> FileResponse:
        task = application.state.tasks.get(task_id)
        variant_path = application.state.variant_paths.get(task_id, {}).get(image_id)
        if (
            task is None
            or task.status != TaskStatus.completed
            or variant_path is None
            or not variant_path.is_file()
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found."
            )
        return FileResponse(variant_path)

    return application


app = create_app()
