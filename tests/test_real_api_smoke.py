import asyncio
import os

import pytest
from openai import AsyncOpenAI
from PIL import Image, ImageDraw

from app.config import load_config
from app.ai_services import OpenAIService
from app.schema_models import BrandGuidelines, Recommendation


def real_api_enabled() -> bool:
    """Return whether explicit opt-in and a usable key enable paid provider calls."""

    if os.environ.get("RUN_OPENAI_SMOKE_TEST") != "1":
        return False
    try:
        return bool(load_config().openai_api_key.get_secret_value())
    except RuntimeError:
        return False


RUN_REAL_API = real_api_enabled()


@pytest.mark.real_api
@pytest.mark.skipif(
    not RUN_REAL_API,
    reason=(
        "Set RUN_OPENAI_SMOKE_TEST=1, OPENAI_API_KEY, and APP_CONFIG_FILE "
        "to enable."
    ),
)
def test_real_api_single_creative_smoke(tmp_path):
    """Exercise one paid edit and evaluation without visual image inspection."""

    original_path = tmp_path / "original.png"
    variant_path = tmp_path / "variant.png"
    image = Image.new("RGB", (256, 256), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((16, 16, 240, 240), outline="navy", width=12)
    drawing.text((60, 112), "SUMMER", fill="navy")
    image.save(original_path)
    recommendations = [
        Recommendation(
            id="rec_1",
            title="Add a focal accent",
            description="Add a small red circle below the headline.",
            type="composition",
        )
    ]
    brand_guidelines = BrandGuidelines(
        protected_regions=["Keep the navy border intact"],
        typography="Keep the SUMMER headline unchanged and readable",
        aspect_ratio="Keep the square aspect ratio",
        brand_elements="Retain the navy and white visual identity",
    )
    config = load_config()

    async def run_smoke_test():
        client = AsyncOpenAI(
            api_key=config.openai_api_key.get_secret_value(),
            timeout=config.provider_timeout_seconds,
            max_retries=0,
        )
        service = OpenAIService(
            client,
            config.image_model,
            config.evaluation_model,
        )
        try:
            await service.generate_variant(
                original_path,
                variant_path,
                recommendations,
                brand_guidelines,
            )
            return await service.evaluate_variant(
                original_path,
                variant_path,
                recommendations,
                brand_guidelines,
            )
        finally:
            await client.close()

    evaluation = asyncio.run(run_smoke_test())

    assert variant_path.is_file()
    assert [check.id for check in evaluation.recommendations] == ["rec_1"]
    assert [check.criterion for check in evaluation.brand_checks] == (
        brand_guidelines.criteria()
    )
