"""Public exports for unversioned operational routes."""

from app.api.routes import router as health_router

__all__ = ["health_router"]
