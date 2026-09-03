"""Regression coverage for the committed two-creative demo bundle."""

import asyncio
import shutil

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from conftest import TEST_API_KEY, make_evaluation, upload_payload

DEMO_TASKS_PATH = "/api/v1/demo/tasks"


class PassingDemoService:
    """Deterministic service used to exercise demo files without network calls."""

    async def generate_variant(
        self,
        original_path,
        destination_path,
        recommendations,
        brand_guidelines,
        repair_feedback=None,
    ):
        await asyncio.to_thread(shutil.copyfile, original_path, destination_path)

    async def evaluate_variant(
        self,
        original_path,
        variant_path,
        recommendations,
        brand_guidelines,
    ):
        return make_evaluation(recommendations, brand_guidelines, True)


def make_demo_config(tmp_path) -> AppConfig:
    """Return deterministic settings for demo endpoint tests."""

    return AppConfig(
        openai_api_key=TEST_API_KEY,
        image_model="test-image-model",
        evaluation_model="test-evaluation-model",
        log_level="WARNING",
        runtime_root=tmp_path,
        max_image_bytes=10 * 1024 * 1024,
        max_iterations=2,
        provider_timeout_seconds=5,
    )


def test_demo_bundle_completes_without_uploaded_files(tmp_path):
    """Exercise the committed bundle through its default-backed API."""

    with TestClient(
        create_app(service=PassingDemoService(), config=make_demo_config(tmp_path))
    ) as client:
        response = client.post(DEMO_TASKS_PATH)

        assert response.status_code == 202
        assert response.json()["status_url"].startswith(f"{DEMO_TASKS_PATH}/")
        task = client.get(response.json()["status_url"]).json()
        assert task["status"] == "completed"
        assert [result["source_filename"] for result in task["results"]] == [
            "creative_1.png",
            "creative_2.png",
        ]
        assert all(
            result["variant_url"].startswith(f"{DEMO_TASKS_PATH}/")
            for result in task["results"]
        )
        assert all(
            client.get(result["variant_url"]).status_code == 200
            for result in task["results"]
        )


def test_demo_fields_can_replace_the_bundled_defaults(
    tmp_path,
    png_bytes,
    recommendations,
    brand_guidelines,
):
    """Use explicit multipart values when callers choose demo overrides."""

    images, recommendations_file, guidelines_file = upload_payload(
        png_bytes,
        recommendations,
        brand_guidelines,
        filenames=("custom.png",),
    )
    with TestClient(
        create_app(service=PassingDemoService(), config=make_demo_config(tmp_path))
    ) as client:
        response = client.post(
            DEMO_TASKS_PATH,
            files=[*images, recommendations_file, guidelines_file],
        )

        assert response.status_code == 202
        task = client.get(response.json()["status_url"]).json()
        assert task["status"] == "completed"
        assert [result["source_filename"] for result in task["results"]] == [
            "custom.png"
        ]


def test_demo_openapi_documents_optional_file_overrides(tmp_path):
    """Keep the editable Swagger demo form visible in the public schema."""

    client = TestClient(create_app(config=make_demo_config(tmp_path)))
    schema = client.get("/openapi.json").json()
    operation = schema["paths"][DEMO_TASKS_PATH]["post"]
    body_reference = operation["requestBody"]["content"]["multipart/form-data"][
        "schema"
    ]["$ref"]
    body_name = body_reference.rsplit("/", maxsplit=1)[-1]
    body_schema = schema["components"]["schemas"][body_name]
    properties = body_schema["properties"]

    assert "required" not in body_schema
    assert properties["images"]["items"]["format"] == "binary"
    assert properties["recommendations"]["format"] == "binary"
    assert properties["brand_guidelines"]["format"] == "binary"
    assert f"{DEMO_TASKS_PATH}/{{task_id}}" in schema["paths"]
    assert f"{DEMO_TASKS_PATH}/{{task_id}}/variants/{{image_id}}" in schema["paths"]
