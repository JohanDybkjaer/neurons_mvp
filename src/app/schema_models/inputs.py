"""Schemas for recommendation and brand-guideline inputs."""

from pydantic import BaseModel, ConfigDict, RootModel


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
        """Flatten every explicit guideline into evaluator check criteria.

        Example:
            A guideline with ``protected_regions=["Keep logo"]`` and three
            textual rules returns ``["Keep logo", typography, aspect_ratio,
            brand_elements]`` in stable order.
        """

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
