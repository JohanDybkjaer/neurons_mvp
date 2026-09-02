import pytest
from pydantic import ValidationError

from app.config import AppConfig, load_config
from conftest import TEST_API_KEY


def test_load_config_maps_only_supported_environment_values():
    config = load_config(
        {
            "OPENAI_API_KEY": TEST_API_KEY,
            "IMAGE_MODEL": "custom-image-model",
            "EVALUATION_MODEL": "custom-evaluation-model",
            "RUNTIME_ROOT": "/must/not/be/read",
        }
    )

    assert config.openai_api_key.get_secret_value() == TEST_API_KEY
    assert config.image_model == "custom-image-model"
    assert config.evaluation_model == "custom-evaluation-model"
    assert str(config.runtime_root) == "runtime/tasks"


def test_load_config_uses_model_defaults():
    config = load_config({"OPENAI_API_KEY": TEST_API_KEY})

    assert config.image_model == "gpt-image-2"
    assert config.evaluation_model == "gpt-5.6"


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"OPENAI_API_KEY": ""},
        {"OPENAI_API_KEY": TEST_API_KEY, "IMAGE_MODEL": " "},
        {"OPENAI_API_KEY": TEST_API_KEY, "EVALUATION_MODEL": " "},
    ],
)
def test_load_config_rejects_missing_or_invalid_values_safely(environment):
    with pytest.raises(RuntimeError) as captured:
        load_config(environment)

    assert str(captured.value) == "Invalid application configuration."
    assert TEST_API_KEY not in str(captured.value)


def test_direct_configuration_is_immutable_and_keeps_key_secret():
    config = AppConfig(openai_api_key=TEST_API_KEY)

    assert TEST_API_KEY not in repr(config)
    with pytest.raises(ValidationError):
        config.image_model = "replacement"
