"""Log safe HTTP validation failures while preserving FastAPI responses."""

import logging

from fastapi import HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler as default_http_exception_handler,
)
from fastapi.exception_handlers import (
    request_validation_exception_handler as default_request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from app.schema_models import CodedErrorResponse

LOGGER = logging.getLogger(__name__)
FILENAME_SET_MISMATCH_CODE = "image_json_filename_set_mismatch"
UPLOAD_FIELD_NAMES = frozenset({"images", "recommendations", "brand_guidelines"})
VALIDATION_REJECTION_REASONS = {
    "Invalid recommendations JSON.": "invalid_recommendations_json",
    "Invalid brand guidelines JSON.": "invalid_brand_guidelines_json",
    "Duplicate filename in recommendations JSON.": "duplicate_recommendation_filename",
    "Duplicate filename in brand guidelines JSON.": "duplicate_brand_guideline_filename",
    "Image filenames must be unique.": "duplicate_image_filename",
    "JSON filenames must match the uploaded images.": FILENAME_SET_MISMATCH_CODE,
    "Upload between one and ten images.": "image_count_out_of_range",
    "Image exceeds the upload size limit.": "image_too_large",
    "Images must be valid PNG or JPEG files.": "invalid_image",
}


def _route_template(request: Request) -> str:
    """Return the matched route template without logging user-supplied paths."""

    route_path = getattr(request.scope.get("route"), "path", None)
    return route_path if isinstance(route_path, str) else "unmatched"


def _validation_summary(error: RequestValidationError) -> tuple[str, str]:
    """Summarize safe validation metadata without retaining submitted values."""

    error_types: set[str] = set()
    field_names: set[str] = set()
    for issue in error.errors():
        error_type = issue.get("type")
        if isinstance(error_type, str):
            error_types.add(error_type)
        location = issue.get("loc")
        if isinstance(location, tuple) and len(location) > 1:
            field_name = location[1]
            if isinstance(field_name, str) and field_name in UPLOAD_FIELD_NAMES:
                field_names.add(field_name)
    return (
        ",".join(sorted(error_types)) or "unknown",
        ",".join(sorted(field_names)) or "none",
    )


def _validation_rejection_reason(error: HTTPException) -> str:
    """Map only known safe validation details to a stable log reason code."""

    if isinstance(error.detail, str):
        return VALIDATION_REJECTION_REASONS.get(
            error.detail, "unknown_validation_rejection"
        )
    return "unknown_validation_rejection"


async def handle_request_validation_error(
    request: Request,
    error: Exception,
) -> Response:
    """Log safe metadata for validation that happens before an endpoint runs."""

    if not isinstance(error, RequestValidationError):
        raise error
    error_types, field_names = _validation_summary(error)
    LOGGER.info(
        (
            "event=request_rejected route=%s method=%s status_code=422 "
            "category=request_validation error_count=%d error_types=%s fields=%s"
        ),
        _route_template(request),
        request.method,
        len(error.errors()),
        error_types,
        field_names,
    )
    return await default_request_validation_exception_handler(request, error)


async def handle_http_exception(request: Request, error: Exception) -> Response:
    """Log safe metadata for application-raised validation rejections."""

    if not isinstance(error, HTTPException):
        raise error
    if error.status_code == 422:
        reason = _validation_rejection_reason(error)
        LOGGER.info(
            (
                "event=request_rejected route=%s method=%s status_code=422 "
                "category=application_validation error_count=0 reason=%s"
            ),
            _route_template(request),
            request.method,
            reason,
        )
        if reason == FILENAME_SET_MISMATCH_CODE and isinstance(error.detail, str):
            response = CodedErrorResponse(detail=error.detail, code=reason)
            return JSONResponse(
                status_code=error.status_code,
                content=response.model_dump(),
                headers=error.headers,
            )
    return await default_http_exception_handler(request, error)
