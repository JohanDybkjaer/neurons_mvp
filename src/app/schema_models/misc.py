"""Small schemas that do not belong to a larger domain group."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Operational health-check response."""

    status: str
