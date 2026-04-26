from datetime import UTC, datetime

from fastapi import APIRouter

from app.schemas.v1.prices import (
    PricesEstimateRequest,
    PricesEstimateResponse,
)
from app.schemas.v1.shared_price_context import (
    Coverage,
    EstimatedCost,
    EstimateQuality,
    ItemCost,
    MatchQuality,
    PriceBasis,
    PriceSource,
)

router = APIRouter()


@router.post("/estimate", response_model=PricesEstimateResponse)
async def estimate_prices(payload: PricesEstimateRequest) -> PricesEstimateResponse:
    source = PriceSource(
        source_id="egyptian_ingredient_price_kb",
        source_name="Egyptian ingredient price knowledge base",
        geography=payload.budget.geography,
        observed_at=datetime.now(UTC).date(),
        last_updated_at=datetime.now(UTC),
        price_basis=payload.price_basis,
    )

    item_costs: list[ItemCost] = []

    if payload.ingredients:
        first_item = payload.ingredients[0]

        item_costs.append(
            ItemCost(
                requested_item_id=first_item.id,
                ingredient_name=first_item.name,
                normalized_name="white rice"
                if first_item.name.lower() == "rice"
                else first_item.name.lower(),
                requested_quantity=first_item.quantity,
                requested_unit=first_item.unit,
                usage_cost=17.5,
                purchase_cost=35,
                purchase_quantity=1,
                purchase_unit="kg",
                estimated_cost=17.5,
                currency=payload.currency,
                match_quality=MatchQuality.NORMALIZED,
                assumptions=["Mock conversion and price match for integration testing."],
                warnings=[],
                source=source,
            )
        )

    estimated_cost = EstimatedCost(
        total_cost=17.5 if item_costs else None,
        total_purchase_cost=35 if item_costs else None,
        per_serving_cost=(
            round(17.5 / payload.servings, 2)
            if item_costs and payload.servings
            else None
        ),
        currency=payload.currency,
        coverage=Coverage.PARTIAL if item_costs else Coverage.UNAVAILABLE,
        confidence=0.72 if item_costs else 0,
        quality=EstimateQuality(
            priced_item_count=len(item_costs),
            unpriced_item_count=0 if item_costs else 1,
            staleness_warning=False,
        ),
        item_costs=item_costs,
        assumptions=["Stub response. Prices are estimates only, not live market prices."],
        warnings=[] if item_costs else ["No mock item costs were generated."],
        source=source,
    )

    return PricesEstimateResponse(
        estimate_id="price_est_stub_001",
        price_basis=payload.price_basis,
        recipe_id=payload.recipe_id,
        estimated_cost=estimated_cost,
        warnings=["Stub response. Replace with price_estimator_service later."],
        latency_ms=88,
    )