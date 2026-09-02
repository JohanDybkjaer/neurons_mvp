"""Typed and validated application settings."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    StringConstraints,
    ValidationError,
    field_validator,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AppConfig(BaseModel):
    """Immutable provider, runtime-limit, and filesystem settings."""

    model_config = ConfigDict(frozen=True)

    openai_api_key: SecretStr
    image_model: NonEmptyString = "gpt-image-2"
    evaluation_model: NonEmptyString = "gpt-5.6"
    runtime_root: Path = Path("runtime/tasks")
    max_image_bytes: PositiveInt = 10 * 1024 * 1024
    provider_timeout_seconds: PositiveFloat = 120

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value: object) -> str:
        """Reject blank credentials without including them in an error."""

        raw_value = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError("API key is required")
        return raw_value.strip()


def load_config(environment: Mapping[str, str] | None = None) -> AppConfig:
    """Load supported environment values and collapse failures to a safe error."""

    source = os.environ if environment is None else environment
    try:
        return AppConfig.model_validate(
            {
                "openai_api_key": source.get("OPENAI_API_KEY"),
                "image_model": source.get("IMAGE_MODEL", "gpt-image-2"),
                "evaluation_model": source.get("EVALUATION_MODEL", "gpt-5.6"),
            }
        )
    except ValidationError:
        raise RuntimeError("Invalid application configuration.") from None
