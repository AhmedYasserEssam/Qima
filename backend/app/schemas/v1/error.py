from enum import StrEnum
from http import HTTPStatus
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    ACCOUNT_ALREADY_EXISTS = "ACCOUNT_ALREADY_EXISTS"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    INVALID_PASSWORD = "INVALID_PASSWORD"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    SCANNED_PDF_NOT_SUPPORTED = "SCANNED_PDF_NOT_SUPPORTED"
    LAB_REPORT_PARSE_FAILED = "LAB_REPORT_PARSE_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    @property
    def http_status(self) -> int:
        return {
            ErrorCode.BAD_REQUEST: HTTPStatus.BAD_REQUEST,
            ErrorCode.UNAUTHORIZED: HTTPStatus.UNAUTHORIZED,
            ErrorCode.FORBIDDEN: HTTPStatus.FORBIDDEN,
            ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
            ErrorCode.ACCOUNT_ALREADY_EXISTS: HTTPStatus.CONFLICT,
            ErrorCode.ACCOUNT_NOT_FOUND: HTTPStatus.NOT_FOUND,
            ErrorCode.INVALID_PASSWORD: HTTPStatus.UNAUTHORIZED,
            ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
            ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
            ErrorCode.UPSTREAM_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
            ErrorCode.SCANNED_PDF_NOT_SUPPORTED: HTTPStatus.BAD_REQUEST,
            ErrorCode.LAB_REPORT_PARSE_FAILED: HTTPStatus.UNPROCESSABLE_ENTITY,
            ErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
        }[self]


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(..., min_length=1)
    retryable: bool
    request_id: str = Field(..., min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
