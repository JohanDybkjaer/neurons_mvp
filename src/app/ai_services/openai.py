"""Adapt application models to OpenAI image and Responses API requests.

Prompt construction, provider payloads, and provider-response decoding stay in
this module so the workflow remains independent of the OpenAI SDK.
"""

import asyncio
import base64
import binascii
import io
import json
import logging
from pathlib import Path
from typing import Literal

from openai import APIStatusError, AsyncOpenAI
from PIL import Image, UnidentifiedImageError

from app.schema_models import BrandGuidelines, Evaluation, Recommendation

LOGGER = logging.getLogger(__name__)


def _editing_prompt(
    recommendations: list[Recommendation],
    brand_guidelines: BrandGuidelines,
    repair_feedback: Evaluation | None,
) -> str:
    """Build an edit prompt with original constraints and optional repair feedback."""

    sections = [
        "Edit the supplied original marketing creative in one pass.",
        (
            "Apply every requested recommendation while preserving every brand "
            "guideline. Brand guidelines are authoritative and override any "
            "conflicting recommendation. Preserve all other visual content."
        ),
        "Brand guidelines (authoritative):\n"
        + json.dumps(brand_guidelines.model_dump(), indent=2),
        "Recommendations:\n"
        + json.dumps(
            [recommendation.model_dump() for recommendation in recommendations],
            indent=2,
        ),
    ]
    if repair_feedback is not None:
        failed_recommendations = [
            check.model_dump()
            for check in repair_feedback.recommendations
            if not check.applied
        ]
        failed_brand_checks = [
            check.model_dump()
            for check in repair_feedback.brand_checks
            if not check.compliant
        ]
        sections.extend(
            [
                (
                    "This is a repair iteration. Start again from the supplied "
                    "original creative, not from a previous variant."
                ),
                "Validated failed recommendation checks:\n"
                + json.dumps(failed_recommendations, indent=2),
                "Validated failed brand checks:\n"
                + json.dumps(failed_brand_checks, indent=2),
                (
                    "Correct these failures while still applying all original "
                    "recommendations and treating every brand guideline as mandatory."
                ),
            ]
        )
    return "\n\n".join(sections)


def _evaluation_prompt(
    recommendations: list[Recommendation],
    brand_guidelines: BrandGuidelines,
) -> str:
    """Build an evaluator prompt requiring every requested check."""

    return "\n\n".join(
        [
            (
                "Compare the labeled original and variant images. Judge each "
                "recommendation and each brand criterion using only visible evidence."
            ),
            "Recommendations to check:\n"
            + json.dumps(
                [recommendation.model_dump() for recommendation in recommendations],
                indent=2,
            ),
            "Brand criteria to check:\n"
            + json.dumps(brand_guidelines.criteria(), indent=2),
            (
                "Return exactly one recommendation check for every supplied ID and "
                "one brand check whose criterion exactly matches every supplied brand "
                "criterion. Set overall_pass to true only when every recommendation "
                "is applied and every brand criterion is compliant."
            ),
        ]
    )


def _media_type(path: Path) -> str:
    """Return the media type for a validated PNG or JPEG task artifact."""

    return "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"


def _data_url(image_bytes: bytes, path: Path) -> str:
    """Encode one local image for a Responses vision input into base 64."""

    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{_media_type(path)};base64,{encoded}"


def _validate_generated_image(image_bytes: bytes, expected_format: str) -> None:
    """Reject provider bytes that are not the requested decoded image format."""

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.format != expected_format:
                raise ValueError("Unexpected image format")
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("Image provider returned invalid image data") from error


def _log_provider_error(operation: str, error: APIStatusError) -> None:
    """Log safe provider diagnostics without recording response content."""

    LOGGER.warning(
        ("provider_operation=%s status_code=%d provider_code=%s request_id=%s"),
        operation,
        error.status_code,
        error.code or "none",
        error.request_id or "none",
    )


class OpenAIService:
    """Perform both AI roles through one long-lived asynchronous client.

    The caller owns the client lifecycle. ``create_app`` creates and closes the
    production client, while tests inject a deterministic stand-in.

    Args:
        client: Long-lived asynchronous OpenAI client supplied by the caller.
        image_model: Configured model name for image editing.
        evaluation_model: Configured vision-capable model name for evaluation.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        image_model: str,
        evaluation_model: str,
    ) -> None:
        self._client = client
        self._image_model = image_model
        self._evaluation_model = evaluation_model

    async def generate_variant(
        self,
        original_path: Path,
        destination_path: Path,
        recommendations: list[Recommendation],
        brand_guidelines: BrandGuidelines,
        repair_feedback: Evaluation | None = None,
    ) -> None:
        """Edit the original creative and persist the returned image bytes.

        Args:
            original_path: Server-owned source creative for this iteration.
            destination_path: Server-owned path for the returned variant bytes.
            recommendations: Every original requested change.
            brand_guidelines: Authoritative visual constraints.
            repair_feedback: Latest schema- and coverage-validated failed
                evaluation, when making a repair attempt.

        Returns:
            ``None`` after writing returned image bytes to ``destination_path``.

        Raises:
            ValueError: If the provider omits image data or returns invalid
                base64 content.

        """

        original_bytes = await asyncio.to_thread(original_path.read_bytes)
        output_format: Literal["jpeg", "png"] = (
            "jpeg" if destination_path.suffix.lower() in {".jpg", ".jpeg"} else "png"
        )
        try:
            response = await self._client.images.edit(
                model=self._image_model,
                image=(original_path.name, original_bytes, _media_type(original_path)),
                prompt=_editing_prompt(
                    recommendations,
                    brand_guidelines,
                    repair_feedback,
                ),
                output_format=output_format,
            )
        except APIStatusError as error:
            _log_provider_error("image_edit", error)
            raise
        # Treat provider output as untrusted even after a successful HTTP call.
        if not response.data or not response.data[0].b64_json:
            raise ValueError("Image provider returned no image data")
        try:
            image_bytes = base64.b64decode(
                response.data[0].b64_json,
                validate=True,
            )
        except (binascii.Error, ValueError) as error:
            raise ValueError("Image provider returned invalid image data") from error
        expected_image_format = "JPEG" if output_format == "jpeg" else "PNG"
        await asyncio.to_thread(
            _validate_generated_image,
            image_bytes,
            expected_image_format,
        )
        await asyncio.to_thread(destination_path.write_bytes, image_bytes)

    async def evaluate_variant(
        self,
        original_path: Path,
        variant_path: Path,
        recommendations: list[Recommendation],
        brand_guidelines: BrandGuidelines,
    ) -> Evaluation:
        """Compare both images and return one structured result for all checks.

        Args:
            original_path: Server-owned source creative used for comparison.
            variant_path: Generated variant to evaluate against the source.
            recommendations: Every original requested change.
            brand_guidelines: Authoritative criteria to check.

        Returns:
            Parsed ``Evaluation`` containing decisions for every requested check.

        """

        original_bytes, variant_bytes = await asyncio.gather(
            asyncio.to_thread(original_path.read_bytes),
            asyncio.to_thread(variant_path.read_bytes),
        )
        # One combined request gives every recommendation and brand check the
        # same visual context and avoids inconsistent per-criterion judgments.
        try:
            response = await self._client.responses.parse(
                model=self._evaluation_model,
                instructions=(
                    "You are a strict visual compliance evaluator. Return only the "
                    "requested structured evaluation."
                ),
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": _evaluation_prompt(
                                    recommendations,
                                    brand_guidelines,
                                ),
                            },
                            {"type": "input_text", "text": "Original creative:"},
                            {
                                "type": "input_image",
                                "image_url": _data_url(original_bytes, original_path),
                                "detail": "high",
                            },
                            {"type": "input_text", "text": "Generated variant:"},
                            {
                                "type": "input_image",
                                "image_url": _data_url(variant_bytes, variant_path),
                                "detail": "high",
                            },
                        ],
                    }
                ],
                text_format=Evaluation,
            )
        except APIStatusError as error:
            _log_provider_error("evaluation", error)
            raise
        return Evaluation.model_validate(response.output_parsed)
