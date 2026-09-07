"""Schemas for debug-only text correspondence with OpenAI."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schema_models.tasks import TaskStatus


class OpenAITextMessage(BaseModel):
    """One textual message sent to or received from OpenAI."""

    role: Literal["system", "user", "assistant"] = Field(
        description="OpenAI message role associated with this text."
    )
    text: str = Field(
        description="Exact text content; image bytes and data URLs are excluded."
    )


class OpenAICorrespondence(BaseModel):
    """One generation or evaluation exchange for an image-processing step."""

    step: int = Field(
        ge=1,
        description="One-based generation/evaluation iteration for this image.",
        examples=[1],
    )
    operation: Literal["generation", "evaluation"] = Field(
        description="The provider operation performed during this step."
    )
    model: str = Field(description="OpenAI model selected for this operation.")
    request_messages: list[OpenAITextMessage] = Field(
        description="All textual request messages in provider order."
    )
    response_messages: list[OpenAITextMessage] = Field(
        default_factory=list,
        description="All textual response messages in provider order.",
    )


class ImageDemoDebug(BaseModel):
    """Text-only OpenAI correspondence for one source image."""

    image_id: str = Field(description="Server-generated image identifier.")
    source_filename: str = Field(description="Original uploaded image filename.")
    correspondence: list[OpenAICorrespondence] = Field(
        default_factory=list,
        description="Provider exchanges in execution order.",
    )


class TaskDemoDebug(BaseModel):
    """Debug-only correspondence for every image in a task."""

    task_id: str = Field(description="Server-generated task identifier.")
    status: TaskStatus = Field(description="Task state when this response was read.")
    images: list[ImageDemoDebug] = Field(
        description="Text-only OpenAI correspondence grouped by image."
    )
