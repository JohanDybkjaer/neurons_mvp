"""Concurrent task orchestration with one bounded repair per creative."""

import asyncio
from collections import Counter
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from app.models import (
    BrandGuidelines,
    Evaluation,
    ImageResult,
    Recommendation,
    TaskState,
    TaskStatus,
)
from app.openai_service import OpenAIService

ReturnType = TypeVar("ReturnType")


@dataclass(frozen=True)
class ImageWorkItem:
    """Validated inputs and server-owned artifact locations for one pipeline."""

    image_id: str
    source_filename: str
    original_path: Path
    variant_path: Path
    variant_url: str
    recommendations: list[Recommendation]
    brand_guidelines: BrandGuidelines


async def _call_with_timeout(
    awaitable: Awaitable[ReturnType],
    timeout_seconds: float,
) -> ReturnType:
    """Bound one asynchronous provider operation by the configured timeout."""

    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)


def _validate_evaluation(evaluation: Evaluation, item: ImageWorkItem) -> None:
    """Ensure evaluator checks correspond exactly to the requested criteria."""

    expected_recommendations = [recommendation.id for recommendation in item.recommendations]
    returned_recommendations = [check.id for check in evaluation.recommendations]
    expected_criteria = item.brand_guidelines.criteria()
    returned_criteria = [check.criterion for check in evaluation.brand_checks]
    # Counter comparison accepts any response order while still detecting
    # missing, duplicated, or invented checks.
    if Counter(returned_recommendations) != Counter(expected_recommendations):
        raise ValueError("Evaluation recommendation checks do not match the request")
    if Counter(returned_criteria) != Counter(expected_criteria):
        raise ValueError("Evaluation brand checks do not match the request")


async def _evaluate(
    item: ImageWorkItem,
    service: OpenAIService,
    timeout_seconds: float,
) -> Evaluation:
    """Call the evaluator and validate both its schema and semantic coverage."""

    response = await _call_with_timeout(
        service.evaluate_variant(
            item.original_path,
            item.variant_path,
            item.recommendations,
            item.brand_guidelines,
        ),
        timeout_seconds,
    )
    evaluation = Evaluation.model_validate(response)
    _validate_evaluation(evaluation, item)
    return evaluation


async def _process_image(
    item: ImageWorkItem,
    service: OpenAIService,
    semaphore: asyncio.Semaphore,
    timeout_seconds: float,
) -> ImageResult:
    """Run generation, evaluation, and at most one repair sequentially."""

    async with semaphore:
        await _call_with_timeout(
            service.generate_variant(
                item.original_path,
                item.variant_path,
                item.recommendations,
                item.brand_guidelines,
            ),
            timeout_seconds,
        )
        evaluation = await _evaluate(item, service, timeout_seconds)
        attempts = 1

        if not evaluation.overall_pass:
            attempts = 2
            # Repair from the original creative to avoid cumulative image drift.
            await _call_with_timeout(
                service.generate_variant(
                    item.original_path,
                    item.variant_path,
                    item.recommendations,
                    item.brand_guidelines,
                    repair_feedback=evaluation,
                ),
                timeout_seconds,
            )
            evaluation = await _evaluate(item, service, timeout_seconds)

        return ImageResult(
            image_id=item.image_id,
            source_filename=item.source_filename,
            variant_url=item.variant_url,
            attempts=attempts,
            evaluation=evaluation,
        )


async def run_task(
    task: TaskState,
    work_items: list[ImageWorkItem],
    service: OpenAIService,
    timeout_seconds: float,
) -> None:
    """Run up to two image pipelines and mutate the task to a terminal state."""

    task.status = TaskStatus.running
    try:
        semaphore = asyncio.Semaphore(2)
        task.results = list(
            await asyncio.gather(
                *(
                    _process_image(
                        item,
                        service,
                        semaphore,
                        timeout_seconds,
                    )
                    for item in work_items
                )
            )
        )
    except Exception:
        # Provider details are intentionally collapsed into a safe public error.
        task.results = []
        task.status = TaskStatus.failed
        task.error = "Task processing failed."
        return

    task.status = TaskStatus.completed
