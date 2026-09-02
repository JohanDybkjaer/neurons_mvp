"""Validated models for HTTP, uploaded JSON, workflow, and AI boundaries."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Recommendation(BaseModel):
    """One requested visual change for a creative."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    type: str


class BrandGuidelines(BaseModel):
    """Brand constraints that generation and evaluation must respect."""

    model_config = ConfigDict(extra="forbid")

    protected_regions: list[str]
    typography: str
    aspect_ratio: str
    brand_elements: str

    def criteria(self) -> list[str]:
        """Flatten every explicit guideline into evaluator check criteria."""

        return [
            *self.protected_regions,
            self.typography,
            self.aspect_ratio,
            self.brand_elements,
        ]


class RecommendationFile(BaseModel):
    """Recommendations associated with one uploaded filename."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    recommendations: list[Recommendation]


class BrandGuidelineFile(BaseModel):
    """Brand guidelines associated with one uploaded filename."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    brand_guidelines: BrandGuidelines


class RecommendationsDocument(RootModel[dict[str, RecommendationFile]]):
    """Top-level recommendations upload keyed by source document labels."""


class BrandGuidelinesDocument(RootModel[dict[str, BrandGuidelineFile]]):
    """Top-level brand-guidelines upload keyed by source document labels."""


class RecommendationCheck(BaseModel):
    """Evaluator decision for one supplied recommendation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    applied: bool
    reason: str


class BrandCheck(BaseModel):
    """Evaluator decision for one explicit brand criterion."""

    model_config = ConfigDict(extra="forbid")

    criterion: str
    compliant: bool
    reason: str


class Evaluation(BaseModel):
    """Complete validated evaluator response for one generated variant."""

    model_config = ConfigDict(extra="forbid")

    recommendations: list[RecommendationCheck]
    brand_checks: list[BrandCheck]
    overall_pass: bool


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
    attempts: int
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


class HealthResponse(BaseModel):
    """Operational health-check response."""

    status: str
