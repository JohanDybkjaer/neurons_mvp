from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import AppConfig, load_config
from conftest import TEST_API_KEY


def write_config(path: Path, **overrides: object) -> Path:
    """Write a complete non-secret configuration for a loader test."""

    values = {
        "image_model": "custom-image-model",
        "evaluation_model": "custom-evaluation-model",
        "log_level": "INFO",
        "runtime_root": "runtime/tasks",
        "max_image_bytes": 10485760,
        "max_iterations": 2,
        "provider_timeout_seconds": 120,
        **overrides,
    }
    lines = [
        "[providers]",
        f'image_editor_model = {values["image_model"]!r}',
        f'evaluator_model = {values["evaluation_model"]!r}',
        f'timeout_seconds = {values["provider_timeout_seconds"]}',
        "",
        "[limits]",
        f'max_image_size_mb = {values["max_image_bytes"] / 1024 / 1024:g}',
        f'max_iterations = {values["max_iterations"]!r}',
        "",
        "[logging]",
        f'level = {values["log_level"]!r}',
        "",
        "[storage]",
        f'artifact_root = {values["runtime_root"]!r}',
    ]
    path.write_text("\n".join(lines))
    return path


def test_load_config_reads_non_secrets_only_from_toml(tmp_path):
    config_file = write_config(tmp_path / "config.toml", log_level="debug")

    config = load_config(
        {
            "OPENAI_API_KEY": TEST_API_KEY,
            "IMAGE_MODEL": "must-not-be-read",
            "LOG_LEVEL": "ERROR",
            "RUNTIME_ROOT": "/must/not/be/read",
        },
        env_file=None,
        config_file=config_file,
    )

    assert config.openai_api_key.get_secret_value() == TEST_API_KEY
    assert config.image_model == "custom-image-model"
    assert config.evaluation_model == "custom-evaluation-model"
    assert config.log_level == "DEBUG"
    assert str(config.runtime_root) == "runtime/tasks"
    assert config.max_image_bytes == 10 * 1024 * 1024
    assert config.max_iterations == 2


@pytest.mark.parametrize(
    ("config_file", "expected_log_level", "expected_runtime_root"),
    [
        (Path("config/dev.toml"), "DEBUG", "runtime/tasks"),
        (Path("config/test.toml"), "WARNING", "runtime/test-tasks"),
    ],
)
def test_committed_configs_are_valid(
    config_file,
    expected_log_level,
    expected_runtime_root,
):
    config = load_config(
        {"OPENAI_API_KEY": TEST_API_KEY},
        env_file=None,
        config_file=config_file,
    )

    assert config.image_model == "gpt-image-2"
    assert config.evaluation_model == "gpt-5.6-terra"
    assert config.log_level == expected_log_level
    assert str(config.runtime_root) == expected_runtime_root
    assert config.max_iterations == 2


def test_environment_selects_complete_config_file(tmp_path):
    config_file = write_config(tmp_path / "config.toml")

    config = load_config(
        {
            "OPENAI_API_KEY": TEST_API_KEY,
            "APP_CONFIG_FILE": str(config_file),
        },
        env_file=None,
    )

    assert config.log_level == "INFO"
    assert config.image_model == "custom-image-model"


def test_env_file_supplies_secret_and_environment_takes_precedence(tmp_path):
    config_file = write_config(tmp_path / "config.toml")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=file-api-key\n")

    file_config = load_config({}, env_file=env_file, config_file=config_file)
    environment_config = load_config(
        {"OPENAI_API_KEY": TEST_API_KEY},
        env_file=env_file,
        config_file=config_file,
    )

    assert file_config.openai_api_key.get_secret_value() == "file-api-key"
    assert file_config.log_level == "INFO"
    assert environment_config.openai_api_key.get_secret_value() == TEST_API_KEY


def test_env_file_rejects_non_secret_settings(tmp_path):
    config_file = write_config(tmp_path / "config.toml")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=file-api-key\nLOG_LEVEL=DEBUG\n")

    with pytest.raises(RuntimeError, match="Invalid application configuration"):
        load_config({}, env_file=env_file, config_file=config_file)


@pytest.mark.parametrize(
    ("environment", "overrides"),
    [
        ({}, {}),
        ({"OPENAI_API_KEY": ""}, {}),
        ({"OPENAI_API_KEY": TEST_API_KEY}, {"image_model": " "}),
        ({"OPENAI_API_KEY": TEST_API_KEY}, {"evaluation_model": " "}),
        ({"OPENAI_API_KEY": TEST_API_KEY}, {"log_level": "TRACE"}),
        ({"OPENAI_API_KEY": TEST_API_KEY}, {"max_image_bytes": 0}),
        ({"OPENAI_API_KEY": TEST_API_KEY}, {"max_iterations": 0}),
        ({"OPENAI_API_KEY": TEST_API_KEY}, {"max_iterations": 6}),
        ({"OPENAI_API_KEY": TEST_API_KEY}, {"max_iterations": "2"}),
    ],
)
def test_load_config_rejects_missing_or_invalid_values_safely(
    tmp_path,
    environment,
    overrides,
):
    config_file = write_config(tmp_path / "config.toml", **overrides)

    with pytest.raises(RuntimeError) as captured:
        load_config(environment, env_file=None, config_file=config_file)

    assert str(captured.value) == "Invalid application configuration."
    assert TEST_API_KEY not in str(captured.value)


@pytest.mark.parametrize(
    "contents",
    [
        "not valid toml =",
        'image_model = "only-one-setting"',
        Path("config/dev.toml").read_text() + '\nunknown_setting = "typo"\n',
        Path("config/dev.toml").read_text()
        + '\nopenai_api_key = "must-not-be-here"\n',
    ],
)
def test_load_config_rejects_malformed_incomplete_or_extra_toml(tmp_path, contents):
    config_file = tmp_path / "config.toml"
    config_file.write_text(contents)

    with pytest.raises(RuntimeError, match="Invalid application configuration"):
        load_config(
            {"OPENAI_API_KEY": TEST_API_KEY},
            env_file=None,
            config_file=config_file,
        )


def test_load_config_rejects_missing_toml_file(tmp_path):
    with pytest.raises(RuntimeError, match="Invalid application configuration"):
        load_config(
            {"OPENAI_API_KEY": TEST_API_KEY},
            env_file=None,
            config_file=tmp_path / "missing.toml",
        )


def test_load_config_requires_explicit_file_selection():
    with pytest.raises(RuntimeError, match="Invalid application configuration"):
        load_config(
            {"OPENAI_API_KEY": TEST_API_KEY},
            env_file=None,
        )


def test_configuration_is_immutable_and_keeps_key_secret():
    config = load_config(
        {"OPENAI_API_KEY": TEST_API_KEY},
        env_file=None,
        config_file=Path("config/dev.toml"),
    )

    assert TEST_API_KEY not in repr(config)
    with pytest.raises(ValidationError):
        config.image_model = "replacement"
