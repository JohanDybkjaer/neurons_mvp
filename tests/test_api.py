import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import TEST_API_KEY, make_evaluation, upload_payload
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppConfig, load_config
from app.main import create_app
from app.schema_models import TaskState, TaskStatus

TASKS_PATH = "/api/v1/tasks"


def make_test_config(tmp_path, **overrides):
    values = {
        "image_model": "test-image-model",
        "evaluation_model": "test-evaluation-model",
        "log_level": "INFO",
        "runtime_root": tmp_path,
        "max_image_bytes": 10 * 1024 * 1024,
        "max_iterations": 2,
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
    request_content = schema["paths"][TASKS_PATH]["post"]["requestBody"]["content"]
    assert "multipart/form-data" in request_content
    body_reference = request_content["multipart/form-data"]["schema"]["$ref"]
    body_name = body_reference.rsplit("/", maxsplit=1)[-1]
    upload_properties = schema["components"]["schemas"][body_name]["properties"]
    assert upload_properties["images"]["items"]["format"] == "binary"
    assert upload_properties["recommendations"]["format"] == "binary"
    assert upload_properties["brand_guidelines"]["format"] == "binary"
    create_operation = schema["paths"][TASKS_PATH]["post"]
    assert create_operation["summary"] == "Start visual recommendation processing"
    assert create_operation["responses"]["202"]["description"] == (
        "Accepted task with a polling URL"
    )
    task_created_schema = schema["components"]["schemas"]["TaskCreated"]
    assert task_created_schema["properties"]["status_url"]["description"] == (
        "Polling endpoint for lifecycle state and final results."
    )
    evaluation_schema = schema["components"]["schemas"]["Evaluation"]
    assert evaluation_schema["properties"]["overall_pass"]["description"] == (
        "True only when every recommendation and brand check passes."
    )
    assert evaluation_schema["examples"][0]["overall_pass"] is True


def test_application_creates_runtime_log_file(tmp_path):
    config = make_test_config(tmp_path)
    log_file = tmp_path.parent / "logs" / "app.log"

    with TestClient(create_app(config=config)):
        pass

    assert log_file.is_file()
    log_lines = log_file.read_text().splitlines()
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO app.main application started",
        log_lines[0],
    )
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO app.main application stopped",
        log_lines[-1],
    )


def test_application_startup_keeps_artifacts_and_clears_runtime_state(tmp_path):
    config = make_test_config(tmp_path)
    stale_task_file = tmp_path / "stale-task" / "inputs" / "original.png"
    stale_task_file.parent.mkdir(parents=True)
    stale_task_file.write_bytes(b"stale task artifact")
    stale_log_file = tmp_path.parent / "logs" / "previous.log"
    stale_log_file.parent.mkdir(exist_ok=True)
    stale_log_file.write_text("stale log entry")
    application = create_app(config=config)
    application.state.tasks["stale-task"] = TaskState(
        task_id="stale-task", status=TaskStatus.completed
    )
    application.state.variant_paths["stale-task"] = {"image_1": stale_task_file}

    with TestClient(application):
        assert application.state.tasks == {}
        assert application.state.variant_paths == {}
        assert stale_task_file.read_bytes() == b"stale task artifact"
        assert not stale_log_file.exists()

    log_output = (tmp_path.parent / "logs" / "app.log").read_text()
    assert "stale log entry" not in log_output


def test_validation_rejections_are_logged_without_uploaded_content(tmp_path, png_bytes):
    config = make_test_config(tmp_path)
    log_file = tmp_path.parent / "logs" / "app.log"

    with TestClient(create_app(config=config)) as client:
        missing_uploads = client.post(TASKS_PATH)
        invalid_json = client.post(
            TASKS_PATH,
            files=[
                ("images", ("creative.png", png_bytes, "image/png")),
                (
                    "recommendations",
                    ("recommendations.json", "not-json", "application/json"),
                ),
                ("brand_guidelines", ("guidelines.json", "{}", "application/json")),
            ],
        )

    assert missing_uploads.status_code == 422
    assert invalid_json.status_code == 422
    log_output = log_file.read_text()
    assert (
        "event=request_rejected route=/api/v1/tasks method=POST status_code=422 "
        "category=request_validation error_count=3 error_types=missing "
        "fields=brand_guidelines,images,recommendations"
    ) in log_output
    assert (
        "event=request_rejected route=/api/v1/tasks method=POST status_code=422 "
        "category=application_validation error_count=0 "
        "reason=invalid_recommendations_json"
    ) in log_output
    assert "creative.png" not in log_output


def test_ten_image_task_completes_with_retrievable_variants(
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
        png_bytes,
        recommendations,
        brand_guidelines,
        tuple(f"creative_{index}.png" for index in range(1, 11)),
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
    assert len(task["results"]) == 10
    assert all(result["attempts"] == 1 for result in task["results"])
    assert all(result["evaluation"]["overall_pass"] for result in task["results"])
    assert all(
        len(result["evaluation"]["recommendations"]) == 3 for result in task["results"]
    )
    assert all(
        len(result["evaluation"]["brand_checks"]) == 5 for result in task["results"]
    )
    input_directory = tmp_path / created["task_id"] / "inputs"
    assert json.loads(
        (input_directory / "recommendations.json").read_text()
    ) == json.loads(recommendations_file[1][1])
    assert json.loads(
        (input_directory / "brand_guidelines.json").read_text()
    ) == json.loads(guidelines_file[1][1])
    for result in task["results"]:
        variant = client.get(result["variant_url"])
        assert variant.status_code == 200
        assert variant.content == png_bytes

    assert len(service.evaluation_calls) == 10
    assert all(
        call[1] == ["rec_1", "rec_2", "rec_3"] for call in service.evaluation_calls
    )


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
            (
                "recommendations",
                ("recommendations.json", "not-json", "application/json"),
            ),
            ("brand_guidelines", ("guidelines.json", "{}", "application/json")),
        ],
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid recommendations JSON."}


def test_invalid_image_is_rejected(tmp_path, recommendations, brand_guidelines):
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
    config = make_test_config(tmp_path)
    log_file = tmp_path.parent / "logs" / "app.log"

    with TestClient(create_app(config=config)) as client:
        response = client.post(
            TASKS_PATH, files=[*images, recommendations_file, guidelines_file]
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "JSON filenames must match the uploaded images.",
        "code": "image_json_filename_set_mismatch",
    }
    assert "reason=image_json_filename_set_mismatch" in log_file.read_text()


def test_more_than_ten_images_are_rejected(
    tmp_path, png_bytes, recommendations, brand_guidelines
):
    filenames = tuple(f"creative_{index}.png" for index in range(1, 12))
    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes, recommendations, brand_guidelines, filenames
    )
    client = TestClient(create_app(config=make_test_config(tmp_path)))

    response = client.post(
        TASKS_PATH, files=[*images, recommendations_file, guidelines_file]
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Upload between one and ten images."}


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

    with pytest.raises(ValidationError):
        make_test_config(tmp_path, max_iterations=0)


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
