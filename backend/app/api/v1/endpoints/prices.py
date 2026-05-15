from fastapi import APIRouter, HTTPException, status

from app.schemas.v1.prices import PricesEstimateRequest, PricesEstimateResponse
from app.services.price_service import (
    PriceDataUnavailableError,
    RecipeNotFoundError,
    estimate_price_request,
)

router = APIRouter()


@router.post("/estimate", response_model=PricesEstimateResponse)
async def estimate_prices(payload: PricesEstimateRequest) -> PricesEstimateResponse:
    try:
        return estimate_price_request(payload)
    except RecipeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PriceDataUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
