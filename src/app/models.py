from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    type: str


class BrandGuidelines(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protected_regions: list[str]
    typography: str
    aspect_ratio: str
    brand_elements: str

    def criteria(self) -> list[str]:
        return [
            *self.protected_regions,
            self.typography,
            self.aspect_ratio,
            self.brand_elements,
        ]


class RecommendationFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    recommendations: list[Recommendation]


class BrandGuidelineFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    brand_guidelines: BrandGuidelines


class RecommendationsDocument(RootModel[dict[str, RecommendationFile]]):
    pass


class BrandGuidelinesDocument(RootModel[dict[str, BrandGuidelineFile]]):
    pass


class RecommendationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    applied: bool
    reason: str


class BrandCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    compliant: bool
    reason: str


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[RecommendationCheck]
    brand_checks: list[BrandCheck]
    overall_pass: bool


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ImageResult(BaseModel):
    image_id: str
    source_filename: str
    variant_url: str
    attempts: int
    evaluation: Evaluation


class TaskState(BaseModel):
    task_id: str
    status: TaskStatus
    results: list[ImageResult] = Field(default_factory=list)
    error: str | None = None


class TaskCreated(BaseModel):
    task_id: str
    status: TaskStatus
    status_url: str


class HealthResponse(BaseModel):
    status: str
