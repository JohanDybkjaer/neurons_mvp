import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppConfig, load_config
from app.main import create_app
from app.schema_models import TaskStatus
from conftest import TEST_API_KEY, make_evaluation, upload_payload

TASKS_PATH = "/api/v1/tasks"


def make_test_config(tmp_path, **overrides):
    values = {
        "image_model": "test-image-model",
        "evaluation_model": "test-evaluation-model",
        "log_level": "INFO",
        "runtime_root": tmp_path,
        "max_image_bytes": 10 * 1024 * 1024,
        "provider_timeout_seconds": 120,
        **overrides,
    }
    return AppConfig(
        openai_api_key=TEST_API_KEY,
        **values,
    )


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


def test_health_swagger_and_openapi_expose_contract(tmp_path):
    client = TestClient(create_app(config=make_test_config(tmp_path)))

    assert client.get("/health").json() == {"status": "ok"}
    swagger_response = client.get("/docs")
    assert swagger_response.status_code == 200
    assert "Swagger UI" in swagger_response.text
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
        create_app(
            service=service,
            config=make_test_config(tmp_path),
        )
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


def test_workflow_step_metadata_is_logged_to_stdout(
    capsys,
    tmp_path,
    png_bytes,
    recommendations,
    brand_guidelines,
):
    service = RecordingService()
    application = create_app(
        service=service,
        config=make_test_config(tmp_path),
    )
    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes,
        recommendations,
        brand_guidelines,
        ("creative.png",),
    )

    with TestClient(application) as client:
        created = client.post(
            TASKS_PATH,
            files=[*images, recommendations_file, guidelines_file],
        ).json()

    output = capsys.readouterr().out
    log_prefix = f"task_id={created['task_id']} image_id=image_1"
    assert f"{log_prefix} step=generation attempt=1 outcome=success" in output
    assert f"{log_prefix} step=evaluation attempt=1 outcome=success" in output
    assert (
        f"{log_prefix} step=pipeline attempt=1 outcome=success overall_pass=true"
        in output
    )
    assert (
        f"task_id={created['task_id']} image_id=all step=task attempt=1 "
        "outcome=success image_count=1" in output
    )
    assert "duration_ms=" in output
    assert "creative.png" not in output


def test_configured_warning_level_suppresses_success_logs(
    capsys,
    tmp_path,
    png_bytes,
    recommendations,
    brand_guidelines,
):
    application = create_app(
        service=RecordingService(),
        config=make_test_config(tmp_path, log_level="WARNING"),
    )
    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes,
        recommendations,
        brand_guidelines,
        ("creative.png",),
    )

    with TestClient(application) as client:
        response = client.post(
            TASKS_PATH,
            files=[*images, recommendations_file, guidelines_file],
        )

    assert response.status_code == 202
    assert "app.workflows.visual_recommendations" not in capsys.readouterr().out


def test_invalid_json_is_rejected(tmp_path, png_bytes):
    client = TestClient(create_app(config=make_test_config(tmp_path)))
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
    client = TestClient(create_app(config=make_test_config(tmp_path)))

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
            config=make_test_config(
                tmp_path,
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
    client = TestClient(create_app(config=make_test_config(tmp_path)))

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
    client = TestClient(create_app(config=make_test_config(tmp_path)))

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
            service=FailingService(),
            config=make_test_config(tmp_path),
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
    client = TestClient(create_app(config=make_test_config(tmp_path)))

    assert client.get(f"{TASKS_PATH}/not-a-task").status_code == 404
    assert client.get(f"{TASKS_PATH}/not-a-task/variants/image_1").status_code == 404


def test_configuration_rejects_non_positive_limits(tmp_path):
    with pytest.raises(ValidationError):
        make_test_config(tmp_path, max_image_bytes=0)

    with pytest.raises(ValidationError):
        make_test_config(tmp_path, provider_timeout_seconds=0)


def test_missing_runtime_configuration_fails_startup_safely(monkeypatch, tmp_path):
    secret = "must-not-leak"
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        (Path("config/dev.toml").read_text()).replace(
            'image_editor_model = "gpt-image-2"',
            'image_editor_model = ""',
        )
    )

    def invalid_config():
        return load_config(
            {"OPENAI_API_KEY": secret},
            env_file=None,
            config_file=config_file,
        )

    monkeypatch.setattr("app.main.load_config", invalid_config)

    with pytest.raises(RuntimeError) as captured:
        with TestClient(create_app()):
            pass

    assert str(captured.value) == "Invalid application configuration."
    assert secret not in str(captured.value)


def test_application_closes_its_single_openai_client(monkeypatch, tmp_path):
    provider_client = SimpleNamespace(close=AsyncMock())
    construction_arguments = {}

    def make_client(**kwargs):
        construction_arguments.update(kwargs)
        return provider_client

    monkeypatch.setattr("app.main.AsyncOpenAI", make_client)
    config = make_test_config(
        tmp_path,
        image_model="image-model",
        evaluation_model="evaluation-model",
        provider_timeout_seconds=30,
    )
    application = create_app(config=config)

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        first_service = application.state.service
        assert first_service is not None
        assert application.state.service is first_service

    assert construction_arguments == {
        "api_key": TEST_API_KEY,
        "timeout": 30.0,
        "max_retries": 0,
    }
    provider_client.close.assert_awaited_once()
