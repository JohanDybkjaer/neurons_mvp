"""Concurrent task orchestration with one bounded repair per creative."""

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from app.ai_services import OpenAIService
from app.schema_models import (
    BrandGuidelines,
    Evaluation,
    ImageResult,
    Recommendation,
    TaskState,
    TaskStatus,
)

ReturnType = TypeVar("ReturnType")
LOGGER = logging.getLogger(__name__)


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


async def _run_step(
    awaitable: Awaitable[ReturnType],
    timeout_seconds: float,
    task_id: str,
    image_id: str,
    step: str,
    attempt: int,
) -> ReturnType:
    """Run and safely log one bounded workflow operation."""

    started_at = time.perf_counter()
    LOGGER.info(
        (
            "task_id=%s image_id=%s step=%s attempt=%d "
            "outcome=started duration_ms=0.0"
        ),
        task_id,
        image_id,
        step,
        attempt,
    )
    try:
        result = await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except Exception as error:
        LOGGER.warning(
            (
                "task_id=%s image_id=%s step=%s attempt=%d "
                "outcome=failed error_type=%s duration_ms=%.1f"
            ),
            task_id,
            image_id,
            step,
            attempt,
            type(error).__name__,
            (time.perf_counter() - started_at) * 1000,
        )
        raise

    LOGGER.info(
        (
            "task_id=%s image_id=%s step=%s attempt=%d "
            "outcome=success duration_ms=%.1f"
        ),
        task_id,
        image_id,
        step,
        attempt,
        (time.perf_counter() - started_at) * 1000,
    )
    return result


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


async def _request_evaluation(
    item: ImageWorkItem,
    service: OpenAIService,
) -> Evaluation:
    """Request and validate the evaluator's schema and semantic coverage."""

    response = await service.evaluate_variant(
        item.original_path,
        item.variant_path,
        item.recommendations,
        item.brand_guidelines,
    )
    evaluation = Evaluation.model_validate(response)
    _validate_evaluation(evaluation, item)
    return evaluation


async def _process_image(
    task_id: str,
    item: ImageWorkItem,
    service: OpenAIService,
    semaphore: asyncio.Semaphore,
    timeout_seconds: float,
) -> ImageResult:
    """Run generation, evaluation, and at most one repair sequentially."""

    started_at = time.perf_counter()
    attempts = 1
    try:
        async with semaphore:
            await _run_step(
                service.generate_variant(
                    item.original_path,
                    item.variant_path,
                    item.recommendations,
                    item.brand_guidelines,
                ),
                timeout_seconds,
                task_id,
                item.image_id,
                "generation",
                1,
            )
            evaluation = await _run_step(
                _request_evaluation(item, service),
                timeout_seconds,
                task_id,
                item.image_id,
                "evaluation",
                1,
            )
            if not evaluation.overall_pass:
                attempts = 2
                # Repair from the original creative to avoid cumulative image drift.
                await _run_step(
                    service.generate_variant(
                        item.original_path,
                        item.variant_path,
                        item.recommendations,
                        item.brand_guidelines,
                        repair_feedback=evaluation,
                    ),
                    timeout_seconds,
                    task_id,
                    item.image_id,
                    "generation",
                    2,
                )
                evaluation = await _run_step(
                    _request_evaluation(item, service),
                    timeout_seconds,
                    task_id,
                    item.image_id,
                    "evaluation",
                    2,
                )

        result = ImageResult(
            image_id=item.image_id,
            source_filename=item.source_filename,
            variant_url=item.variant_url,
            attempts=attempts,
            evaluation=evaluation,
        )
    except Exception as error:
        LOGGER.warning(
            (
                "task_id=%s image_id=%s step=pipeline attempt=%d "
                "outcome=failed error_type=%s duration_ms=%.1f"
            ),
            task_id,
            item.image_id,
            attempts,
            type(error).__name__,
            (time.perf_counter() - started_at) * 1000,
        )
        raise

    LOGGER.info(
        (
            "task_id=%s image_id=%s step=pipeline attempt=%d "
            "outcome=success overall_pass=%s duration_ms=%.1f"
        ),
        task_id,
        item.image_id,
        attempts,
        str(evaluation.overall_pass).lower(),
        (time.perf_counter() - started_at) * 1000,
    )
    return result


async def run_task(
    task: TaskState,
    work_items: list[ImageWorkItem],
    service: OpenAIService,
    timeout_seconds: float,
) -> None:
    """Run up to two image pipelines and mutate the task to a terminal state."""

    started_at = time.perf_counter()
    image_count = len(work_items)
    task.status = TaskStatus.running
    LOGGER.info(
        (
            "task_id=%s image_id=all step=task attempt=1 "
            "outcome=started image_count=%d duration_ms=0.0"
        ),
        task.task_id,
        image_count,
    )
    try:
        semaphore = asyncio.Semaphore(2)
        task.results = list(
            await asyncio.gather(
                *(
                    _process_image(
                        task.task_id,
                        item,
                        service,
                        semaphore,
                        timeout_seconds,
                    )
                    for item in work_items
                )
            )
        )
    except Exception as error:
        # Provider details are intentionally collapsed into a safe public error.
        task.results = []
        task.status = TaskStatus.failed
        task.error = "Task processing failed."
        LOGGER.warning(
            (
                "task_id=%s image_id=all step=task attempt=1 outcome=failed "
                "image_count=%d error_type=%s duration_ms=%.1f"
            ),
            task.task_id,
            image_count,
            type(error).__name__,
            (time.perf_counter() - started_at) * 1000,
        )
        return

    task.status = TaskStatus.completed
    LOGGER.info(
        (
            "task_id=%s image_id=all step=task attempt=1 outcome=success "
            "image_count=%d duration_ms=%.1f"
        ),
        task.task_id,
        image_count,
        (time.perf_counter() - started_at) * 1000,
    )
