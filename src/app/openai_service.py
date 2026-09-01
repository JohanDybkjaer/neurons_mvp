import asyncio
import shutil
from pathlib import Path

from app.models import (
    BrandCheck,
    BrandGuidelines,
    Evaluation,
    Recommendation,
    RecommendationCheck,
)


class OpenAIService:
    """Deterministic Step 1 service, replaced by provider calls in Step 2."""

    async def generate_variant(
        self,
        original_path: Path,
        destination_path: Path,
        recommendations: list[Recommendation],
        brand_guidelines: BrandGuidelines,
        repair_feedback: Evaluation | None = None,
    ) -> None:
        del recommendations, brand_guidelines, repair_feedback
        await asyncio.to_thread(shutil.copyfile, original_path, destination_path)

    async def evaluate_variant(
        self,
        original_path: Path,
        variant_path: Path,
        recommendations: list[Recommendation],
        brand_guidelines: BrandGuidelines,
    ) -> Evaluation:
        del original_path, variant_path
        return Evaluation(
            recommendations=[
                RecommendationCheck(
                    id=recommendation.id,
                    applied=True,
                    reason="Applied by the deterministic Step 1 service.",
                )
                for recommendation in recommendations
            ],
            brand_checks=[
                BrandCheck(
                    criterion=criterion,
                    compliant=True,
                    reason="Preserved by the deterministic Step 1 service.",
                )
                for criterion in brand_guidelines.criteria()
            ],
            overall_pass=True,
        )

