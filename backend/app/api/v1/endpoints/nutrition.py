from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.v1.error_responses import build_error_response
from app.schemas.v1.error import ErrorCode, ErrorResponse
from app.schemas.v1.nutrition import (
    NutritionEstimateRequest,
    NutritionEstimateSuccess,
)
from app.services.exceptions import NotFoundError, UpstreamUnavailableError
from app.services.nutrition_service import estimate_nutrition as estimate_nutrition_with_data

router = APIRouter()


@router.post(
    "/estimate",
    response_model=NutritionEstimateSuccess,
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def estimate_nutrition(
    payload: NutritionEstimateRequest,
) -> NutritionEstimateSuccess | JSONResponse:
    try:
        return estimate_nutrition_with_data(payload)
    except NotFoundError:
        return build_error_response(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="No matching dish or ingredient data found for the supplied estimate input.",
            retryable=False,
            details={},
        )
    except UpstreamUnavailableError:
        return build_error_response(
            status_code=503,
            code=ErrorCode.UPSTREAM_UNAVAILABLE,
            message="Nutrition estimation source is currently unavailable.",
            retryable=True,
            details={},
        )
