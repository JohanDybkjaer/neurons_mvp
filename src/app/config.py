from pathlib import Path

from pydantic import BaseModel, ConfigDict, PositiveFloat, PositiveInt


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    runtime_root: Path = Path("runtime/tasks")
    max_image_bytes: PositiveInt = 10 * 1024 * 1024
    provider_timeout_seconds: PositiveFloat = 120


DEFAULT_CONFIG = AppConfig()

