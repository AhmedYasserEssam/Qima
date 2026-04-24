from fastapi import APIRouter

from app.schemas.v1.nutrition import (
    DataQuality,
    MatchedDish,
    Nutrients,
    NutritionEstimateRequest,
    NutritionEstimateSuccess,
    ServingAssumptions,
    Source,
)

router = APIRouter()


@router.post("/estimate", response_model=NutritionEstimateSuccess)
async def estimate_nutrition(
    payload: NutritionEstimateRequest,
) -> NutritionEstimateSuccess:
    if payload.recognized_dish:
        matched_name = payload.recognized_dish
        match_type = "dish"
    else:
        matched_name = ", ".join(payload.ingredients or ["mixed ingredients"])
        match_type = "ingredient_set"

    return NutritionEstimateSuccess(
        matched_dish=MatchedDish(
            name=matched_name,
            match_type=match_type,
            match_id="nutrition_stub_001",
        ),
        serving_assumptions=ServingAssumptions(
            basis=payload.serving_hint or "one typical serving",
            note="Mock serving assumption for API integration testing.",
        ),
        nutrients=Nutrients(
            calories_kcal=520,
            protein_g=24,
            carbohydrates_g=68,
            fat_g=16,
            fiber_g=9,
            sugar_g=6,
            sodium_mg=430,
        ),
        confidence=0.7,
        source=Source(dataset="egyptian_food_csv", source_type="egyptian_food_dataset"),
        data_quality=DataQuality(completeness="partial"),
        warnings=["Mock response. Nutrition values are estimates."],
    )
