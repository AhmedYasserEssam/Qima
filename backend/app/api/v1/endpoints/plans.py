from datetime import UTC, datetime

from fastapi import APIRouter

from app.schemas.v1.plans import (
    DataQuality,
    EstimatedNutrition,
    MealCandidate,
    MealScore,
    MealSource,
    NutritionTargets,
    PlansGenerateRequest,
    PlansGenerateSuccess,
    Source,
    SupportStatus,
)
from app.schemas.v1.shared_price_context import (
    Coverage,
    EstimatedCost,
    EstimateQuality,
    PriceBasis,
    PriceSource,
)

router = APIRouter()


@router.post(
    "/generate",
    response_model=PlansGenerateSuccess,
    summary="Generate bounded goal-based meal guidance",
)
async def generate_plan(payload: PlansGenerateRequest) -> PlansGenerateSuccess:
    return _mock_plan_response(
        plan_id="plan_stub_001",
        matched_ingredients=[item.name for item in payload.pantry or []],
    )


@router.get("/{plan_id}", response_model=PlansGenerateSuccess)
async def get_plan(plan_id: str) -> PlansGenerateSuccess:
    return _mock_plan_response(plan_id=plan_id, matched_ingredients=["rice", "lentils"])


def _mock_plan_response(
    plan_id: str,
    matched_ingredients: list[str],
) -> PlansGenerateSuccess:
    return PlansGenerateSuccess(
        plan_id=plan_id,
        support_status=SupportStatus(
            status="supported",
            reason="Mock plan is within the general adult food-guidance boundary.",
        ),
        nutrition_targets=NutritionTargets(
            calories_kcal=2200,
            protein_g=110,
            carbohydrates_g=260,
            fat_g=70,
            target_basis="estimated",
        ),
        meals=[
            MealCandidate(
                meal_id="meal_stub_001",
                title="Lentil Rice Bowl",
                meal_type="lunch",
                matched_ingredients=matched_ingredients or ["rice", "lentils"],
                missing_ingredients=["tomato", "onion"],
                estimated_nutrition=EstimatedNutrition(
                    calories_kcal=610,
                    protein_g=28,
                    carbohydrates_g=92,
                    fat_g=14,
                ),
                estimated_cost=EstimatedCost(
                    total_cost=75,
                    currency="EGP",
                    coverage=Coverage.PARTIAL,
                    confidence=0.72,
                    quality=EstimateQuality(
                        priced_item_count=2,
                        unpriced_item_count=1,
                        staleness_warning=False,
                    ),
                    assumptions=[
                        "Mock cost uses estimated ingredient prices, not live market prices."
                    ],
                    warnings=[
                        "Cost estimate is partial because some ingredient prices are unavailable."
                    ],
                    source=PriceSource(
                        source_id="egyptian_ingredient_price_kb",
                        source_name="Egyptian ingredient price knowledge base",
                        geography="Cairo",
                        observed_at=datetime.now(UTC).date(),
                        last_updated_at=datetime.now(UTC),
                        price_basis=PriceBasis.RECIPE_INGREDIENTS,
                    ),
                ),
                score=MealScore(
                    overall=0.82,
                    ingredient_match=0.78,
                    target_fit=0.8,
                    cost_fit=0.86,
                    safety_score=1,
                ),
                warnings=["Mock meal. Cost and nutrition are estimated."],
                source=MealSource(
                    source_type="recipe_corpus",
                    recipe_id="recipe_stub_001",
                ),
            )
        ],
        rationale=(
            "Mock meals are ranked with pantry fit, estimated nutrition, estimated "
            "cost, and safety boundaries. This is general food guidance only."
        ),
        safety_flags=[
            "non_diagnostic",
            "general_information_only",
            "estimated_targets_only",
            "estimated_cost_only",
        ],
        source=Source(
            provider="qima_backend",
            source_type="meal_plan_ranker",
            fetched_at=datetime.now(UTC),
        ),
        data_quality=DataQuality(completeness="partial"),
        warnings=["Mock response. Not diagnosis, treatment, or clinical diet therapy."],
    )