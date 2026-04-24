from datetime import UTC, date, datetime

from fastapi import APIRouter

from app.schemas.v1.prices import (
    DataQuality,
    EstimateQuality,
    ItemCost,
    PricesEstimateRequest,
    PricesEstimateResponse,
    Source,
)

router = APIRouter()


@router.post("/estimate", response_model=PricesEstimateResponse)
async def estimate_prices(payload: PricesEstimateRequest) -> PricesEstimateResponse:
    return PricesEstimateResponse(
        estimate_id="price_est_stub_001",
        estimate_type=payload.estimate_type,
        currency="EGP",
        item_costs=[
            ItemCost(
                requested_name="rice",
                matched_name="white rice",
                quantity=500,
                unit="g",
                normalized_quantity=0.5,
                normalized_unit="kg",
                unit_price=35,
                estimated_cost=17.5,
                match_quality="normalized",
                assumptions=["Converted 500 g to 0.5 kg."],
            )
        ],
        total_cost=17.5,
        estimate_quality=EstimateQuality(confidence=0.72, coverage="partial"),
        source=Source(
            provider="egyptian_ingredient_price_kb",
            source_type="price_dataset",
            price_date=date(2026, 4, 20),
            geography=payload.geography or "Cairo",
            fetched_at=datetime.now(UTC),
        ),
        data_quality=DataQuality(completeness="partial", freshness="fresh"),
        warnings=["Stub response. Prices are estimates only."],
    )