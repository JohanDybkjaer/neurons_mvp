import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.ai_services import OpenAIService
from conftest import make_evaluation, write_original


def make_client(image_response=None, evaluation_response=None):
    images = SimpleNamespace(edit=AsyncMock(return_value=image_response))
    responses = SimpleNamespace(parse=AsyncMock(return_value=evaluation_response))
    return SimpleNamespace(images=images, responses=responses)


def test_generate_variant_calls_image_edit_and_writes_result(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    original_path = tmp_path / "original.png"
    destination_path = tmp_path / "variant.png"
    write_original(original_path, png_bytes)
    image_response = SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(png_bytes).decode())]
    )
    client = make_client(image_response=image_response)
    service = OpenAIService(client, "image-model", "evaluation-model")

    asyncio.run(
        service.generate_variant(
            original_path,
            destination_path,
            recommendations,
            brand_guidelines,
        )
    )

    assert destination_path.read_bytes() == png_bytes
    call = client.images.edit.await_args.kwargs
    assert call["model"] == "image-model"
    assert call["image"][0] == "original.png"
    assert call["image"][1] == png_bytes
    assert call["output_format"] == "png"
    assert "Brand guidelines (authoritative)" in call["prompt"]
    assert all(item.id in call["prompt"] for item in recommendations)
    assert all(
        criterion in call["prompt"] for criterion in brand_guidelines.criteria()
    )


def test_generate_variant_repair_prompt_uses_only_validated_failed_checks(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    original_path = tmp_path / "original.png"
    destination_path = tmp_path / "variant.png"
    write_original(original_path, png_bytes)
    image_response = SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(png_bytes).decode())]
    )
    client = make_client(image_response=image_response)
    service = OpenAIService(client, "image-model", "evaluation-model")
    feedback = make_evaluation(recommendations, brand_guidelines, False)

    asyncio.run(
        service.generate_variant(
            original_path,
            destination_path,
            recommendations,
            brand_guidelines,
            repair_feedback=feedback,
        )
    )

    prompt = client.images.edit.await_args.kwargs["prompt"]
    assert "repair attempt" in prompt
    assert "Start again from the supplied original creative" in prompt
    assert feedback.recommendations[0].reason in prompt
    assert feedback.brand_checks[0].reason in prompt


def test_evaluate_variant_sends_both_images_and_all_criteria_once(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    original_path = tmp_path / "original.png"
    variant_path = tmp_path / "variant.png"
    write_original(original_path, png_bytes)
    write_original(variant_path, png_bytes)
    evaluation = make_evaluation(recommendations, brand_guidelines, True)
    client = make_client(
        evaluation_response=SimpleNamespace(output_parsed=evaluation)
    )
    service = OpenAIService(client, "image-model", "evaluation-model")

    result = asyncio.run(
        service.evaluate_variant(
            original_path,
            variant_path,
            recommendations,
            brand_guidelines,
        )
    )

    assert result == evaluation
    client.responses.parse.assert_awaited_once()
    call = client.responses.parse.await_args.kwargs
    assert call["model"] == "evaluation-model"
    assert call["text_format"] is type(evaluation)
    content = call["input"][0]["content"]
    image_parts = [part for part in content if part["type"] == "input_image"]
    assert len(image_parts) == 2
    assert all(
        part["image_url"].startswith("data:image/png;base64,")
        for part in image_parts
    )
    prompt = "\n".join(
        part["text"] for part in content if part["type"] == "input_text"
    )
    assert all(item.id in prompt for item in recommendations)
    assert all(criterion in prompt for criterion in brand_guidelines.criteria())


def test_malformed_evaluator_output_is_rejected(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    original_path = tmp_path / "original.png"
    variant_path = tmp_path / "variant.png"
    write_original(original_path, png_bytes)
    write_original(variant_path, png_bytes)
    client = make_client(
        evaluation_response=SimpleNamespace(output_parsed={"model": "prose"})
    )
    service = OpenAIService(client, "image-model", "evaluation-model")

    with pytest.raises(ValidationError):
        asyncio.run(
            service.evaluate_variant(
                original_path,
                variant_path,
                recommendations,
                brand_guidelines,
            )
        )


def test_provider_exception_propagates(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    original_path = tmp_path / "original.png"
    write_original(original_path, png_bytes)
    client = make_client()
    client.images.edit.side_effect = RuntimeError("provider failure")
    service = OpenAIService(client, "image-model", "evaluation-model")

    with pytest.raises(RuntimeError, match="provider failure"):
        asyncio.run(
            service.generate_variant(
                original_path,
                tmp_path / "variant.png",
                recommendations,
                brand_guidelines,
            )
        )
