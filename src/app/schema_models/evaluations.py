"""Schemas for validated visual-evaluation output."""

from pydantic import BaseModel, ConfigDict


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
