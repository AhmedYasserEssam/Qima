import logging

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.api.v1.error_responses import build_error_response
from app.schemas.v1.error import ErrorCode, ErrorResponse
from app.schemas.v1.vision import VisionIdentifyRequestMetadata, VisionIdentifyResponse
from app.services.exceptions import BadRequestError, UpstreamUnavailableError
from app.services.vision_service import (
    identify_food_image as identify_uploaded_food_image,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/identify",
    response_model=VisionIdentifyResponse,
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def identify_food_image(
    image: UploadFile = File(...),
    locale: str | None = Form(default=None),
) -> VisionIdentifyResponse | JSONResponse:
    metadata = VisionIdentifyRequestMetadata(locale=locale)

    try:
        image_bytes = await image.read()
        return await identify_uploaded_food_image(
            image_bytes=image_bytes,
            filename=image.filename,
            content_type=image.content_type,
            locale=metadata.locale,
        )
    except BadRequestError as exc:
        return build_error_response(
            status_code=400,
            code=ErrorCode.BAD_REQUEST,
            message=str(exc) or "Request must include a valid image file.",
            retryable=False,
            details={},
        )
    except UpstreamUnavailableError as exc:
        reason = str(exc) or "Vision identification service is currently unavailable."
        logger.warning("Vision identification failed: %s", reason)
        return build_error_response(
            status_code=503,
            code=ErrorCode.UPSTREAM_UNAVAILABLE,
            message=reason,
            retryable=True,
            details={"reason": reason},
        )
