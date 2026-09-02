import asyncio
import logging
import shutil

import pytest

from app.schema_models import TaskState, TaskStatus
from app.workflows import ImageWorkItem, run_task
from conftest import make_evaluation, write_original


@pytest.fixture
def workflow_log_records():
    records = []

    class RecordHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("app.workflows.visual_recommendations")
    previous_level = logger.level
    previous_propagate = logger.propagate
    handler = RecordHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def make_work_item(
    tmp_path,
    image_id,
    png_bytes,
    recommendations,
    brand_guidelines,
):
    original_path = tmp_path / "inputs" / f"{image_id}.png"
    variant_path = tmp_path / "variants" / f"{image_id}.png"
    write_original(original_path, png_bytes)
    variant_path.parent.mkdir(parents=True, exist_ok=True)
    return ImageWorkItem(
        image_id=image_id,
        source_filename=f"{image_id}.png",
        original_path=original_path,
        variant_path=variant_path,
        variant_url=f"/api/v1/tasks/task-id/variants/{image_id}",
        recommendations=recommendations,
        brand_guidelines=brand_guidelines,
    )


class ConcurrentService:
    def __init__(self):
        self.active_generations = 0
        self.maximum_active_generations = 0
        self.both_started = asyncio.Event()
        self.evaluation_calls = []

    async def generate_variant(
        self,
        original_path,
        destination_path,
        recommendations,
        brand_guidelines,
        repair_feedback=None,
    ):
        self.active_generations += 1
        self.maximum_active_generations = max(
            self.maximum_active_generations, self.active_generations
        )
        if self.active_generations == 2:
            self.both_started.set()
        await asyncio.wait_for(self.both_started.wait(), timeout=1)
        shutil.copyfile(original_path, destination_path)
        self.active_generations -= 1

    async def evaluate_variant(
        self,
        original_path,
        variant_path,
        recommendations,
        brand_guidelines,
    ):
        self.evaluation_calls.append([item.id for item in recommendations])
        return make_evaluation(recommendations, brand_guidelines, True)


def test_two_pipelines_overlap_and_each_evaluation_is_combined(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    items = [
        make_work_item(
            tmp_path, f"image_{index}", png_bytes, recommendations, brand_guidelines
        )
        for index in (1, 2)
    ]
    service = ConcurrentService()
    task = TaskState(task_id="task-id", status=TaskStatus.pending)

    asyncio.run(run_task(task, items, service, timeout_seconds=120))

    assert task.status == TaskStatus.completed
    assert service.maximum_active_generations == 2
    assert service.evaluation_calls == [
        ["rec_1", "rec_2", "rec_3"],
        ["rec_1", "rec_2", "rec_3"],
    ]


class RepairService:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.generation_calls = []
        self.evaluation_calls = 0

    async def generate_variant(
        self,
        original_path,
        destination_path,
        recommendations,
        brand_guidelines,
        repair_feedback=None,
    ):
        self.generation_calls.append((original_path, repair_feedback))
        shutil.copyfile(original_path, destination_path)

    async def evaluate_variant(
        self,
        original_path,
        variant_path,
        recommendations,
        brand_guidelines,
    ):
        self.evaluation_calls += 1
        return make_evaluation(
            recommendations, brand_guidelines, self.outcomes.pop(0)
        )


def test_failed_first_evaluation_causes_one_repair_from_original(
    tmp_path,
    png_bytes,
    recommendations,
    brand_guidelines,
    workflow_log_records,
):
    item = make_work_item(
        tmp_path, "image_1", png_bytes, recommendations, brand_guidelines
    )
    service = RepairService([False, True])
    task = TaskState(task_id="task-id", status=TaskStatus.pending)

    asyncio.run(run_task(task, [item], service, timeout_seconds=120))

    assert task.status == TaskStatus.completed
    assert task.results[0].attempts == 2
    assert task.results[0].evaluation.overall_pass is True
    assert service.evaluation_calls == 2
    assert len(service.generation_calls) == 2
    assert all(call[0] == item.original_path for call in service.generation_calls)
    assert service.generation_calls[0][1] is None
    assert service.generation_calls[1][1].overall_pass is False
    messages = [record.getMessage() for record in workflow_log_records]
    successful_steps = [
        message
        for message in messages
        if "outcome=success" in message
        and ("step=generation" in message or "step=evaluation" in message)
    ]
    assert len(successful_steps) == 4
    assert all("task_id=task-id" in message for message in messages)
    assert all(
        "image_id=image_1" in message or "image_id=all" in message
        for message in messages
    )
    assert "step=generation attempt=1" in successful_steps[0]
    assert "step=evaluation attempt=1" in successful_steps[1]
    assert "step=generation attempt=2" in successful_steps[2]
    assert "step=evaluation attempt=2" in successful_steps[3]
    assert any(
        "step=pipeline attempt=2 outcome=success overall_pass=true" in message
        for message in messages
    )
    assert any(
        "image_id=all step=task attempt=1 outcome=success image_count=1" in message
        for message in messages
    )


def test_failed_second_evaluation_is_final_and_task_is_completed(
    tmp_path,
    png_bytes,
    recommendations,
    brand_guidelines,
    workflow_log_records,
):
    item = make_work_item(
        tmp_path, "image_1", png_bytes, recommendations, brand_guidelines
    )
    service = RepairService([False, False])
    task = TaskState(task_id="task-id", status=TaskStatus.pending)

    asyncio.run(run_task(task, [item], service, timeout_seconds=120))

    assert task.status == TaskStatus.completed
    assert task.error is None
    assert task.results[0].attempts == 2
    assert task.results[0].evaluation.overall_pass is False
    assert len(service.generation_calls) == 2
    assert service.evaluation_calls == 2
    messages = [record.getMessage() for record in workflow_log_records]
    assert any(
        "step=pipeline attempt=2 outcome=success overall_pass=false" in message
        for message in messages
    )
    assert any("step=task attempt=1 outcome=success" in message for message in messages)


class MalformedEvaluationService(RepairService):
    async def evaluate_variant(
        self,
        original_path,
        variant_path,
        recommendations,
        brand_guidelines,
    ):
        return {"unvalidated": "provider-secret-payload"}


def test_unvalidated_evaluator_output_cannot_control_workflow(
    tmp_path,
    png_bytes,
    recommendations,
    brand_guidelines,
    workflow_log_records,
):
    item = make_work_item(
        tmp_path, "image_1", png_bytes, recommendations, brand_guidelines
    )
    task = TaskState(task_id="task-id", status=TaskStatus.pending)

    asyncio.run(
        run_task(
            task,
            [item],
            MalformedEvaluationService([]),
            timeout_seconds=120,
        )
    )

    assert task.status == TaskStatus.failed
    assert task.error == "Task processing failed."
    assert task.results == []
    messages = [record.getMessage() for record in workflow_log_records]
    assert any(
        "step=generation attempt=1 outcome=success" in message
        for message in messages
    )
    assert any(
        "step=evaluation attempt=1 outcome=failed error_type=ValidationError"
        in message
        for message in messages
    )
    assert any(
        "step=pipeline attempt=1 outcome=failed error_type=ValidationError"
        in message
        for message in messages
    )
    assert any(
        "step=task attempt=1 outcome=failed image_count=1 "
        "error_type=ValidationError" in message
        for message in messages
    )
    assert "provider-secret-payload" not in " ".join(messages)
