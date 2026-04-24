from fastapi import APIRouter, HTTPException, status

from app.schemas.nutrition import NutritionEstimateRequest, NutritionEstimateSuccess
from app.services.exceptions import NotFoundError, UpstreamUnavailableError
from app.services.nutrition_service import NutritionService


router = APIRouter(prefix="/nutrition", tags=["nutrition"])


@router.post(
    "/estimate",
    response_model=NutritionEstimateSuccess,
    status_code=status.HTTP_200_OK,
    summary="Estimate nutrition for a recognized dish or ingredient set",
)
async def estimate_nutrition(
    payload: NutritionEstimateRequest,
) -> NutritionEstimateSuccess:
    """
    POST /v1/nutrition/estimate

    Estimates nutrients from either a recognized dish or an ingredient set,
    using the backend nutrition source hierarchy.
    """
    try:
        return await NutritionService.estimate(payload)

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected nutrition estimation failure.",
        ) from exc