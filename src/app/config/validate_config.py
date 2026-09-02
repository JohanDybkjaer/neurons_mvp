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


class _ConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _ProviderConfig(_ConfigModel):
    image_editor_model: NonEmptyString
    evaluator_model: NonEmptyString
    timeout_seconds: PositiveFloat


class _LimitsConfig(_ConfigModel):
    max_image_size_mb: PositiveInt


class _LoggingConfig(_ConfigModel):
    level: NonEmptyString


class _StorageConfig(_ConfigModel):
    artifact_root: Path


class _ConfigDocument(_ConfigModel):
    providers: _ProviderConfig
    limits: _LimitsConfig
    logging: _LoggingConfig
    storage: _StorageConfig


class AppConfig(_ConfigModel):
    """Immutable settings resolved from configuration and secret sources."""

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


def validate_config(
    config_values: Mapping[str, object],
    api_key: object,
) -> AppConfig:
    """Validate a complete non-secret document plus its separately loaded key."""

    try:
        document = _ConfigDocument.model_validate(config_values)
        return AppConfig(
            openai_api_key=api_key,
            image_model=document.providers.image_editor_model,
            evaluation_model=document.providers.evaluator_model,
            log_level=document.logging.level,
            runtime_root=document.storage.artifact_root,
            max_image_bytes=document.limits.max_image_size_mb * 1024 * 1024,
            provider_timeout_seconds=document.providers.timeout_seconds,
        )
    except ValidationError:
        raise RuntimeError("Invalid application configuration.") from None
