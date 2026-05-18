from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.api.v1.error_responses import build_error_response
from app.schemas.v1.auth import LoginRequest, LoginResponse, SignupRequest, SignupResponse
from app.schemas.v1.error import ErrorCode, ErrorResponse
from app.services.auth_service import auth_service
from app.services.exceptions import (
    AccountAlreadyExistsError,
    AccountNotFoundError,
    InvalidPasswordError,
)

router = APIRouter()


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def signup(payload: SignupRequest) -> SignupResponse | JSONResponse:
    try:
        return auth_service.signup(payload)
    except AccountAlreadyExistsError as exc:
        return build_error_response(
            status_code=status.HTTP_409_CONFLICT,
            code=ErrorCode.ACCOUNT_ALREADY_EXISTS,
            message=str(exc),
            retryable=False,
        )


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    },
)
async def login(payload: LoginRequest) -> LoginResponse | JSONResponse:
    try:
        return auth_service.login(payload)
    except AccountNotFoundError as exc:
        return build_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code=ErrorCode.ACCOUNT_NOT_FOUND,
            message=str(exc),
            retryable=False,
        )
    except InvalidPasswordError as exc:
        return build_error_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=ErrorCode.INVALID_PASSWORD,
            message=str(exc),
            retryable=False,
        )
