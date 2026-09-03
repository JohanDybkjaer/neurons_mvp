import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.schema_models import (
    BrandCheck,
    BrandGuidelines,
    Evaluation,
    Recommendation,
    RecommendationCheck,
)

TEST_API_KEY = "test-api-key"


@pytest.fixture
def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color="navy").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def recommendations() -> list[Recommendation]:
    return [
        Recommendation(
            id=f"rec_{index}",
            title=f"Recommendation {index}",
            description=f"Apply recommendation {index}",
            type="composition",
        )
        for index in range(1, 4)
    ]


@pytest.fixture
def brand_guidelines() -> BrandGuidelines:
    return BrandGuidelines(
        protected_regions=["Keep the logo", "Keep the product"],
        typography="Maintain typography",
        aspect_ratio="Maintain aspect ratio",
        brand_elements="Keep brand elements visible",
    )


def make_evaluation(
    recommendations: list[Recommendation],
    brand_guidelines: BrandGuidelines,
    passes: bool,
) -> Evaluation:
    return Evaluation(
        recommendations=[
            RecommendationCheck(
                id=recommendation.id,
                applied=passes,
                reason="deterministic result",
            )
            for recommendation in recommendations
        ],
        brand_checks=[
            BrandCheck(
                criterion=criterion,
                compliant=passes,
                reason="deterministic result",
            )
            for criterion in brand_guidelines.criteria()
        ],
        overall_pass=passes,
    )


def upload_payload(
    png_bytes: bytes,
    recommendations: list[Recommendation],
    brand_guidelines: BrandGuidelines,
    filenames: tuple[str, ...] = ("creative_1.png", "creative_2.png"),
):
    recommendation_document = {
        f"image{index}": {
            "filename": filename,
            "recommendations": [item.model_dump() for item in recommendations],
        }
        for index, filename in enumerate(filenames, start=1)
    }
    guideline_document = {
        f"image{index}": {
            "filename": filename,
            "brand_guidelines": brand_guidelines.model_dump(),
        }
        for index, filename in enumerate(filenames, start=1)
    }
    image_files = [
        ("images", (filename, png_bytes, "image/png")) for filename in filenames
    ]
    return (
        image_files,
        (
            "recommendations",
            (
                "recommendations.json",
                json.dumps(recommendation_document),
                "application/json",
            ),
        ),
        (
            "brand_guidelines",
            (
                "brand_guidelines.json",
                json.dumps(guideline_document),
                "application/json",
            ),
        ),
    )


def write_original(path: Path, png_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)
