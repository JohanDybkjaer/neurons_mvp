"""Schemas for recommendation and brand-guideline inputs."""

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Recommendation(BaseModel):
    """One traceable visual change requested for a creative."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description="Stable identifier repeated by the evaluator.",
        examples=["rec_1"],
    )
    title: str = Field(
        description="Short, human-readable name of the requested change.",
        examples=["Add a focal accent"],
    )
    description: str = Field(
        description="Specific change the image model should make.",
        examples=["Add a small red circle below the headline."],
    )
    type: str = Field(
        description="Caller-defined category for the recommendation.",
        examples=["composition"],
    )


class BrandGuidelines(BaseModel):
    """Brand constraints that generation and evaluation must respect."""

    model_config = ConfigDict(extra="forbid")

    protected_regions: list[str] = Field(
        description="Constraints that each become an independent evaluator check.",
        examples=[["Keep the logo"]],
    )
    typography: str = Field(
        description="Text styling and readability constraint.",
        examples=["Maintain typography"],
    )
    aspect_ratio: str = Field(
        description="Required output proportion constraint.",
        examples=["Maintain original aspect ratio"],
    )
    brand_elements: str = Field(
        description="Required logo, product, or other brand-element rule.",
        examples=["Keep brand elements visible"],
    )

    def criteria(self) -> list[str]:
        """Return protected regions followed by the three textual constraints."""

        return [
            *self.protected_regions,
            self.typography,
            self.aspect_ratio,
            self.brand_elements,
        ]


class RecommendationFile(BaseModel):
    """Recommendations associated with one uploaded filename."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(
        description="Exact multipart image filename used as the join key.",
        examples=["creative_1.png"],
    )
    recommendations: list[Recommendation] = Field(
        description="All requested changes for this image."
    )


class BrandGuidelineFile(BaseModel):
    """Brand guidelines associated with one uploaded filename."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(
        description="Exact multipart image filename used as the join key.",
        examples=["creative_1.png"],
    )
    brand_guidelines: BrandGuidelines = Field(
        description="Constraints for this image's generated variant."
    )


class RecommendationsDocument(RootModel[dict[str, RecommendationFile]]):
    """Recommendations upload keyed by arbitrary labels and joined by filename."""


class BrandGuidelinesDocument(RootModel[dict[str, BrandGuidelineFile]]):
    """Brand-guidelines upload keyed by arbitrary labels and joined by filename."""
