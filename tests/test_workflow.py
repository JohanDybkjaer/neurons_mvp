import asyncio
import shutil

from app.models import TaskState, TaskStatus
from app.workflow import ImageWorkItem, run_task
from conftest import make_evaluation, write_original


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
    tmp_path, png_bytes, recommendations, brand_guidelines
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


def test_failed_second_evaluation_is_final_and_task_is_completed(
    tmp_path, png_bytes, recommendations, brand_guidelines
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


class MalformedEvaluationService(RepairService):
    async def evaluate_variant(
        self,
        original_path,
        variant_path,
        recommendations,
        brand_guidelines,
    ):
        return {"unvalidated": "prose"}


def test_unvalidated_evaluator_output_cannot_control_workflow(
    tmp_path, png_bytes, recommendations, brand_guidelines
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
