from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.error_responses import build_error_response
from app.schemas.v1.error import ErrorCode


def _error_code_from_status(status_code: int) -> ErrorCode:
    if status_code == status.HTTP_400_BAD_REQUEST:
        return ErrorCode.BAD_REQUEST
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return ErrorCode.UNAUTHORIZED
    if status_code == status.HTTP_403_FORBIDDEN:
        return ErrorCode.FORBIDDEN
    if status_code == status.HTTP_404_NOT_FOUND:
        return ErrorCode.NOT_FOUND
    if status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        return ErrorCode.VALIDATION_ERROR
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return ErrorCode.RATE_LIMITED
    if status_code >= 500:
        return ErrorCode.INTERNAL_ERROR
    return ErrorCode.BAD_REQUEST


def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    errors = exc.errors()
    message = "Request validation failed."
    if errors:
        first_error = errors[0]
        first_message = str(first_error.get("msg", "")).strip()
        if first_message:
            message = first_message
    return build_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code=ErrorCode.VALIDATION_ERROR,
        message=message,
        retryable=False,
        details={"errors": errors},
    )


def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    del request
    detail = exc.detail
    message = "Request failed."
    details: dict = {}
    if isinstance(detail, str):
        trimmed = detail.strip()
        if trimmed:
            message = trimmed
    elif isinstance(detail, list):
        details = {"errors": detail}
        if detail:
            first = detail[0]
            if isinstance(first, dict):
                first_message = str(first.get("msg", "")).strip()
                if first_message:
                    message = first_message
    elif isinstance(detail, dict):
        details = detail
    return build_error_response(
        status_code=exc.status_code,
        code=_error_code_from_status(exc.status_code),
        message=message,
        retryable=exc.status_code >= 500 or exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS,
        details=details,
    )
