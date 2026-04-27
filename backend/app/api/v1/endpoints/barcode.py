from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.v1.barcode import (
    BarcodeLookupRequest,
    BarcodeLookupSuccess,
)
from app.schemas.v1.error import ErrorBody, ErrorCode, ErrorResponse
from app.services.barcode_service import lookup_barcode
from app.services.exceptions import NotFoundError, UpstreamUnavailableError

router = APIRouter()


@router.post(
    "/lookup",
    response_model=BarcodeLookupSuccess,
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def lookup_barcode_endpoint(
    payload: BarcodeLookupRequest,
) -> BarcodeLookupSuccess | JSONResponse:
    try:
        return await lookup_barcode(payload.barcode)
    except NotFoundError:
        return _error_response(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="No product found for the supplied barcode.",
            retryable=False,
            details={"barcode": payload.barcode},
        )
    except UpstreamUnavailableError:
        return _error_response(
            status_code=503,
            code=ErrorCode.UPSTREAM_UNAVAILABLE,
            message="Barcode provider is currently unavailable.",
            retryable=True,
            details=None,
        )


def _error_response(
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    retryable: bool,
    details: dict | None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            request_id=f"req_{uuid4().hex[:12]}",
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )
