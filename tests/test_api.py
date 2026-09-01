import json
import shutil

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppConfig
from app.main import create_app
from app.models import TaskStatus
from conftest import make_evaluation, upload_payload

TASKS_PATH = "/api/v1/tasks"


class RecordingService:
    def __init__(self, outcomes: dict[str, list[bool]] | None = None):
        self.outcomes = outcomes or {}
        self.generation_calls = []
        self.evaluation_calls = []

    async def generate_variant(
        self,
        original_path,
        destination_path,
        recommendations,
        brand_guidelines,
        repair_feedback=None,
    ):
        self.generation_calls.append(
            (original_path.stem, original_path, repair_feedback)
        )
        shutil.copyfile(original_path, destination_path)

    async def evaluate_variant(
        self,
        original_path,
        variant_path,
        recommendations,
        brand_guidelines,
    ):
        self.evaluation_calls.append(
            (
                original_path.stem,
                [recommendation.id for recommendation in recommendations],
                brand_guidelines.criteria(),
            )
        )
        outcomes = self.outcomes.setdefault(original_path.stem, [True])
        passes = outcomes.pop(0)
        return make_evaluation(recommendations, brand_guidelines, passes)


def test_health_and_openapi_expose_contract(tmp_path):
    client = TestClient(create_app(config=AppConfig(runtime_root=tmp_path)))

    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert {
        TASKS_PATH,
        f"{TASKS_PATH}/{{task_id}}",
        f"{TASKS_PATH}/{{task_id}}/variants/{{image_id}}",
        "/health",
    } <= set(schema["paths"])
    request_content = schema["paths"][TASKS_PATH]["post"]["requestBody"][
        "content"
    ]
    assert "multipart/form-data" in request_content
    assert schema["paths"][TASKS_PATH]["post"]["responses"]["202"]


def test_two_image_task_completes_with_retrievable_variants(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    service = RecordingService()
    client = TestClient(
        create_app(service=service, config=AppConfig(runtime_root=tmp_path))
    )
    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes, recommendations, brand_guidelines
    )

    response = client.post(
        TASKS_PATH, files=[*images, recommendations_file, guidelines_file]
    )

    assert response.status_code == 202
    created = response.json()
    assert created["status"] == "pending"
    task_response = client.get(created["status_url"])
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["status"] == "completed"
    assert len(task["results"]) == 2
    assert all(result["attempts"] == 1 for result in task["results"])
    assert all(result["evaluation"]["overall_pass"] for result in task["results"])
    assert all(
        len(result["evaluation"]["recommendations"]) == 3
        for result in task["results"]
    )
    assert all(
        len(result["evaluation"]["brand_checks"]) == 5
        for result in task["results"]
    )
    for result in task["results"]:
        variant = client.get(result["variant_url"])
        assert variant.status_code == 200
        assert variant.content == png_bytes

    assert len(service.evaluation_calls) == 2
    assert all(call[1] == ["rec_1", "rec_2", "rec_3"] for call in service.evaluation_calls)


def test_invalid_json_is_rejected(tmp_path, png_bytes):
    client = TestClient(create_app(config=AppConfig(runtime_root=tmp_path)))
    response = client.post(
        TASKS_PATH,
        files=[
            ("images", ("creative.png", png_bytes, "image/png")),
            ("recommendations", ("recommendations.json", "not-json", "application/json")),
            ("brand_guidelines", ("guidelines.json", "{}", "application/json")),
        ],
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid recommendations JSON."}


def test_invalid_image_is_rejected(
    tmp_path, recommendations, brand_guidelines
):
    images, recommendations_file, guidelines_file = upload_payload(
        b"not-an-image", recommendations, brand_guidelines, ("creative.png",)
    )
    client = TestClient(create_app(config=AppConfig(runtime_root=tmp_path)))

    response = client.post(
        TASKS_PATH, files=[*images, recommendations_file, guidelines_file]
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Images must be valid PNG or JPEG files."}


def test_oversized_image_is_rejected(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes, recommendations, brand_guidelines, ("creative.png",)
    )
    client = TestClient(
        create_app(
            config=AppConfig(
                runtime_root=tmp_path,
                max_image_bytes=len(png_bytes) - 1,
            )
        )
    )

    response = client.post(
        TASKS_PATH, files=[*images, recommendations_file, guidelines_file]
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Image exceeds the upload size limit."}


def test_mismatched_filenames_are_rejected(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes, recommendations, brand_guidelines, ("different.png",)
    )
    images = [("images", ("creative.png", png_bytes, "image/png"))]
    client = TestClient(create_app(config=AppConfig(runtime_root=tmp_path)))

    response = client.post(
        TASKS_PATH, files=[*images, recommendations_file, guidelines_file]
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "JSON filenames must match the uploaded images."
    }


def test_more_than_two_images_are_rejected(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    filenames = ("one.png", "two.png", "three.png")
    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes, recommendations, brand_guidelines, filenames
    )
    client = TestClient(create_app(config=AppConfig(runtime_root=tmp_path)))

    response = client.post(
        TASKS_PATH, files=[*images, recommendations_file, guidelines_file]
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Upload one or two images."}


class FailingService(RecordingService):
    async def generate_variant(self, *args, **kwargs):
        raise RuntimeError("provider-secret-payload")


def test_provider_failure_marks_task_failed_safely(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    client = TestClient(
        create_app(
            service=FailingService(), config=AppConfig(runtime_root=tmp_path)
        )
    )
    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes, recommendations, brand_guidelines, ("creative.png",)
    )

    created = client.post(
        TASKS_PATH, files=[*images, recommendations_file, guidelines_file]
    ).json()
    task = client.get(created["status_url"]).json()

    assert task["status"] == TaskStatus.failed
    assert task["results"] == []
    assert task["error"] == "Task processing failed."
    assert "secret" not in json.dumps(task)


def test_unknown_task_and_variant_return_safe_not_found(tmp_path):
    client = TestClient(create_app(config=AppConfig(runtime_root=tmp_path)))

    assert client.get(f"{TASKS_PATH}/not-a-task").status_code == 404
    assert client.get(f"{TASKS_PATH}/not-a-task/variants/image_1").status_code == 404


def test_configuration_rejects_non_positive_limits():
    with pytest.raises(ValidationError):
        AppConfig(max_image_bytes=0)

    with pytest.raises(ValidationError):
        AppConfig(provider_timeout_seconds=0)
