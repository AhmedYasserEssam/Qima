from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.responses import JSONResponse

from app.schemas.v1.error import ErrorBody, ErrorCode, ErrorResponse


def build_error_response(
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    retryable: bool,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            request_id=f"req_{uuid4().hex[:12]}",
            details=details or {},
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )
