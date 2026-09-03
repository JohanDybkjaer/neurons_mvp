"""Schemas for validated visual-evaluation output."""

from pydantic import BaseModel, ConfigDict, Field


class RecommendationCheck(BaseModel):
    """Evaluator decision for one supplied recommendation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description="Exact identifier from the input recommendation.",
        examples=["rec_1"],
    )
    applied: bool = Field(
        description="Whether the requested change is visibly present."
    )
    reason: str = Field(
        description="Concise visible-evidence explanation for the decision.",
        examples=["Accent is absent."],
    )


class BrandCheck(BaseModel):
    """Evaluator decision for one explicit brand criterion."""

    model_config = ConfigDict(extra="forbid")

    criterion: str = Field(
        description="Exact protected-region or brand-rule text from the request.",
        examples=["Keep the logo"],
    )
    compliant: bool = Field(
        description="Whether the generated variant obeys the criterion."
    )
    reason: str = Field(
        description="Concise visible-evidence explanation for the decision.",
        examples=["The logo remains visible in its original position."],
    )


class Evaluation(BaseModel):
    """Complete validated evaluator response for one generated variant."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "recommendations": [
                        {
                            "id": "rec_1",
                            "applied": True,
                            "reason": "Focal accent is visible.",
                        }
                    ],
                    "brand_checks": [
                        {
                            "criterion": "Keep the logo",
                            "compliant": True,
                            "reason": "Logo remains visible.",
                        }
                    ],
                    "overall_pass": True,
                }
            ]
        },
    )

    recommendations: list[RecommendationCheck] = Field(
        description="One decision for every input recommendation ID."
    )
    brand_checks: list[BrandCheck] = Field(
        description="One decision for every flattened brand criterion."
    )
    overall_pass: bool = Field(
        description="True only when every recommendation and brand check passes."
    )
