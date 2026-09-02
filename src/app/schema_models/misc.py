"""Small schemas that do not belong to a larger domain group."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Operational health-check response."""

    status: str


class CodedErrorResponse(BaseModel):
    """Safe client error with a stable machine-readable code."""

    detail: str
    code: str
