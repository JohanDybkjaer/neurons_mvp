"""Schemas for task lifecycle state and API responses."""

from enum import Enum

from pydantic import BaseModel, Field

from app.schema_models.evaluations import Evaluation

MAX_ITERATIONS = 5


class TaskStatus(str, Enum):
    """Lifecycle states exposed by the polling API."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ImageResult(BaseModel):
    """Final variant metadata and evaluation for one creative."""

    image_id: str
    source_filename: str
    variant_url: str
    attempts: int = Field(ge=1, le=MAX_ITERATIONS)
    evaluation: Evaluation


class TaskState(BaseModel):
    """Mutable process-local state returned by the polling endpoint."""

    task_id: str
    status: TaskStatus
    results: list[ImageResult] = Field(default_factory=list)
    error: str | None = None


class TaskCreated(BaseModel):
    """Acknowledgement returned when background processing is scheduled."""

    task_id: str
    status: TaskStatus
    status_url: str
