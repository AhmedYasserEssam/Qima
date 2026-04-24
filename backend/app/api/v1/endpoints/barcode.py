from datetime import UTC, datetime

from fastapi import APIRouter

from app.schemas.v1.barcode import (
    Allergen,
    BarcodeLookupRequest,
    BarcodeLookupSuccess,
    DataQuality,
    Ingredient,
    Nutrition,
    NutritionValues,
    Source,
)

router = APIRouter()


@router.post("/lookup", response_model=BarcodeLookupSuccess)
async def lookup_barcode(payload: BarcodeLookupRequest) -> BarcodeLookupSuccess:
    return BarcodeLookupSuccess(
        product_id=f"off:{payload.barcode}",
        name="Mock Whole Grain Cereal",
        brand="Qima Mock Foods",
        nutrition=Nutrition(
            basis="per_100g",
            serving_size="40 g",
            values=NutritionValues(
                energy_kcal=380,
                protein_g=9,
                carbohydrates_g=72,
                fat_g=5,
                sugars_g=12,
                fiber_g=8,
                sodium_mg=220,
                salt_g=0.55,
            ),
        ),
        ingredients=[
            Ingredient(
                text="Whole grain wheat",
                normalized_text="whole grain wheat",
                is_allergen=True,
            ),
            Ingredient(text="Sugar", normalized_text="sugar", is_allergen=False),
        ],
        allergens=[
            Allergen(name="wheat", severity="contains", source_text="Whole grain wheat")
        ],
        source=Source(
            provider="open_food_facts",
            provider_product_id=payload.barcode,
            fetched_at=datetime.now(UTC),
        ),
        data_quality=DataQuality(completeness="partial"),
    )
