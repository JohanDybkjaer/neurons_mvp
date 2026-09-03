"""Schemas for task lifecycle state and API responses."""

from enum import Enum

from pydantic import BaseModel, Field

from app.schema_models.evaluations import Evaluation

# Shared hard per-image cap enforced by configuration, workflow, and result validation.
MAX_ITERATIONS = 5


class TaskStatus(str, Enum):
    """Lifecycle states exposed by the polling API."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ImageResult(BaseModel):
    """Final variant metadata and evaluation for one creative."""

    image_id: str = Field(
        description="Server-generated artifact identifier.", examples=["image_1"]
    )
    source_filename: str = Field(
        description="Original upload name retained as response metadata.",
        examples=["creative_1.png"],
    )
    variant_url: str = Field(
        description="Endpoint that serves the final generated image.",
        examples=["/api/v1/tasks/<task_id>/variants/image_1"],
    )
    attempts: int = Field(
        ge=1,
        le=MAX_ITERATIONS,
        description="Actual generation-and-evaluation pairs performed.",
        examples=[1],
    )
    evaluation: Evaluation = Field(
        description="Final validated result, whether it passes or fails."
    )


class TaskState(BaseModel):
    """Mutable process-local state returned by the polling endpoint."""

    task_id: str = Field(description="Server-generated task identifier.")
    status: TaskStatus = Field(description="Current task lifecycle state.")
    results: list[ImageResult] = Field(
        default_factory=list,
        description="Final per-image results after all pipelines finish.",
    )
    error: str | None = Field(
        default=None,
        description="Safe technical error message when the task fails.",
    )


class TaskCreated(BaseModel):
    """Acknowledgement returned when background processing is scheduled."""

    task_id: str = Field(description="Server-generated task identifier.")
    status: TaskStatus = Field(
        description="Pending lifecycle state returned by a successful POST."
    )
    status_url: str = Field(
        description="Polling endpoint for lifecycle state and final results.",
        examples=["/api/v1/tasks/<task_id>"],
    )
