"""Select configuration sources and pass their raw values to validation.

This module owns source precedence and filesystem parsing. It deliberately does
not decide whether individual application values are valid; that responsibility
belongs to :mod:`app.config.validate_config`.
"""

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
    """Load one TOML document and resolve its separately supplied API key.

    An explicit ``config_file`` argument takes precedence over
    ``APP_CONFIG_FILE``. A process ``OPENAI_API_KEY`` takes precedence over the
    ignored local ``.env`` file. The local file may contain only that secret.

    Args:
        environment: Process-like values, injectable for deterministic tests.
        env_file: Optional local secret file. ``None`` disables file loading.
        config_file: Explicit TOML path, primarily used by tests and embedding.

    Returns:
        Immutable, validated application configuration.

    Raises:
        RuntimeError: If source selection, parsing, or validation fails.

    Example:
        >>> config = load_config(
        ...     environment={"OPENAI_API_KEY": "local-placeholder"},
        ...     env_file=None,
        ...     config_file=Path("config/dev.toml"),
        ... )
        >>> config.log_level
        'INFO'
    """

    process_environment = os.environ if environment is None else environment
    try:
        # Keeping the local file secret-only prevents ordinary settings from
        # gaining a second, less visible override path.
        secret_file_values = (
            dotenv_values(env_file, interpolate=False) if env_file is not None else {}
        )
        if not set(secret_file_values).issubset({"OPENAI_API_KEY"}):
            raise ValueError("Secret file contains unsupported settings")

        # Callers embedding the app can pass a path directly; normal process
        # startup selects the complete deployment document explicitly.
        selected_config_file = config_file
        if selected_config_file is None:
            configured_path = process_environment.get("APP_CONFIG_FILE", "").strip()
            if not configured_path:
                raise ValueError("Configuration file is required")
            selected_config_file = Path(configured_path)

        with selected_config_file.open("rb") as file_handle:
            config_values = tomllib.load(file_handle)

        # Deployment-provided secrets override the developer-local value.
        api_key = process_environment.get(
            "OPENAI_API_KEY", secret_file_values.get("OPENAI_API_KEY")
        )
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        raise RuntimeError("Invalid application configuration.") from None

    return validate_config(config_values, api_key)
