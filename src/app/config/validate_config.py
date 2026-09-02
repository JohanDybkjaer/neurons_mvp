"""Typed application configuration schema and validation."""

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

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
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class AppConfig(BaseModel):
    """Immutable provider, runtime-limit, and filesystem settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    openai_api_key: SecretStr
    image_model: NonEmptyString
    evaluation_model: NonEmptyString
    log_level: LogLevel
    runtime_root: Path
    max_image_bytes: PositiveInt
    provider_timeout_seconds: PositiveFloat

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value: object) -> str:
        """Reject blank credentials without including them in an error."""

        raw_value = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError("API key is required")
        return raw_value.strip()

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        """Accept conventional case-insensitive logging level names."""

        return value.strip().upper() if isinstance(value, str) else value


CONFIG_KEYS = frozenset(AppConfig.model_fields) - {"openai_api_key"}


def validate_config(
    config_values: Mapping[str, object],
    api_key: object,
) -> AppConfig:
    """Validate a complete non-secret document plus its separately loaded key."""

    try:
        if set(config_values) != CONFIG_KEYS:
            raise ValueError("Configuration document does not match the schema")
        return AppConfig.model_validate(
            {
                **config_values,
                "openai_api_key": api_key,
            }
        )
    except (ValidationError, ValueError):
        raise RuntimeError("Invalid application configuration.") from None
