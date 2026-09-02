"""Selection and loading of non-secret and secret configuration sources."""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values

from app.config.validate_config import AppConfig, validate_config


def load_config(
    environment: Mapping[str, str] | None = None,
    env_file: Path | None = Path(".env"),
    config_file: Path | None = None,
) -> AppConfig:
    """Load one selected TOML document and the API key from secret sources."""

    process_environment = os.environ if environment is None else environment
    try:
        secret_file_values = (
            dotenv_values(env_file, interpolate=False) if env_file is not None else {}
        )
        if not set(secret_file_values).issubset({"OPENAI_API_KEY"}):
            raise ValueError("Secret file contains unsupported settings")

        selected_config_file = config_file
        if selected_config_file is None:
            configured_path = process_environment.get("APP_CONFIG_FILE", "").strip()
            if not configured_path:
                raise ValueError("Configuration file is required")
            selected_config_file = Path(configured_path)

        with selected_config_file.open("rb") as file_handle:
            config_values = tomllib.load(file_handle)

        api_key = process_environment.get(
            "OPENAI_API_KEY", secret_file_values.get("OPENAI_API_KEY")
        )
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        raise RuntimeError("Invalid application configuration.") from None

    return validate_config(config_values, api_key)
