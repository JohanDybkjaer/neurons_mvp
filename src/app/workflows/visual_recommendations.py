"""Coordinate independent image pipelines and their bounded iteration cycle.

Provider payload construction stays in ``ai_services``. This module controls
only validated workflow state: generate, evaluate, repair within a cost bound,
and store a terminal result.
"""

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
    MAX_ITERATIONS,
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
    """Run one timed operation and log its safe outcome before re-raising errors."""

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
    """Reject evaluator checks that do not exactly cover the original request."""

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
    """Request one evaluation and validate its schema and requested coverage."""

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
    max_iterations: int,
) -> ImageResult:
    """Run bounded generation and evaluation iterations sequentially.

    The initial generation and evaluation count as iteration 1. Every iteration
    starts from the original creative; a failed, validated evaluation supplies
    the feedback for the next iteration. This prevents cumulative image drift.

    The semaphore covers the complete pipeline rather than individual calls,
    ensuring no more than two creatives are in provider-backed processing at
    once while preserving step order within each creative.

    """

    started_at = time.perf_counter()
    attempts = 0
    try:
        async with semaphore:
            repair_feedback: Evaluation | None = None
            evaluation: Evaluation | None = None
            for attempts in range(1, max_iterations + 1):
                # Every iteration starts from the original creative to avoid
                # cumulative drift from an earlier generated variant.
                await _run_step(
                    service.generate_variant(
                        item.original_path,
                        item.variant_path,
                        item.recommendations,
                        item.brand_guidelines,
                        repair_feedback=repair_feedback,
                    ),
                    timeout_seconds,
                    task_id,
                    item.image_id,
                    "generation",
                    attempts,
                )
                evaluation = await _run_step(
                    _request_evaluation(item, service),
                    timeout_seconds,
                    task_id,
                    item.image_id,
                    "evaluation",
                    attempts,
                )
                if evaluation.overall_pass:
                    break
                repair_feedback = evaluation

        if evaluation is None:
            raise RuntimeError("Image processing reached no evaluation")

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
    max_iterations: int,
) -> None:
    """Run image pipelines and mutate the supplied task to a terminal state.

    A completed workflow may still contain a failed visual evaluation;
    ``failed`` is reserved for technical execution errors.

    Args:
        task: Process-local state updated in place for API polling.
        work_items: One to ten validated creatives prepared by the API layer.
        service: AI editing and evaluation operations.
        timeout_seconds: Hard timeout independently applied to every operation.
        max_iterations: Configured per-image generation and evaluation bound,
            including the initial iteration. Direct callers are capped at the
            shared hard maximum.

    """

    if (
        isinstance(max_iterations, bool)
        or not isinstance(max_iterations, int)
        or max_iterations < 1
    ):
        raise ValueError("max_iterations must be a positive integer")
    bounded_iterations = min(max_iterations, MAX_ITERATIONS)
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
        # The API accepts up to ten items. Keeping the semaphore here also
        # protects direct workflow callers from exceeding two active pipelines.
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
                        bounded_iterations,
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
