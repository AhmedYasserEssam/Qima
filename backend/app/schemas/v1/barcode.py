from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


BarcodeString = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]{8,14}$"),
]


class NutritionBasis(str, Enum):
    PER_100G = "per_100g"
    PER_100ML = "per_100ml"
    PER_SERVING = "per_serving"


class AllergenSeverity(str, Enum):
    CONTAINS = "contains"
    MAY_CONTAIN = "may_contain"
    UNKNOWN = "unknown"


class SourceProvider(str, Enum):
    OPEN_FOOD_FACTS = "open_food_facts"
    CARREFOUR_EGYPT = "carrefour_egypt"


class DataCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class BarcodeLookupRequest(StrictBaseModel):
    barcode: BarcodeString = Field(
        description="Scanned barcode as digits only, 8 to 14 digits."
    )


class NutritionValues(StrictBaseModel):
    energy_kcal: float | None
    protein_g: float | None
    carbohydrates_g: float | None
    fat_g: float | None
    sugars_g: float | None = None
    fiber_g: float | None = None
    sodium_mg: float | None = None
    salt_g: float | None = None


class NutritionFact(StrictBaseModel):
    key: Annotated[str, StringConstraints(min_length=1)]
    label: Annotated[str, StringConstraints(min_length=1)]
    value: float
    unit: Annotated[str, StringConstraints(min_length=1)]
    display_value: Annotated[str, StringConstraints(min_length=1)]


class Nutrition(StrictBaseModel):
    basis: NutritionBasis
    serving_size: str | None
    values: NutritionValues
    basis_label: str | None = None
    serving_label: str | None = None
    facts: list[NutritionFact] = Field(default_factory=list)


class Ingredient(StrictBaseModel):
    text: Annotated[str, StringConstraints(min_length=1)]
    normalized_text: Annotated[str, StringConstraints(min_length=1)]
    is_allergen: bool


class Allergen(StrictBaseModel):
    name: Annotated[str, StringConstraints(min_length=1)]
    severity: AllergenSeverity
    source_text: Annotated[str, StringConstraints(min_length=1)]


class Source(StrictBaseModel):
    provider: SourceProvider
    provider_product_id: Annotated[str, StringConstraints(min_length=1)]
    fetched_at: datetime


class DataQuality(StrictBaseModel):
    completeness: DataCompleteness


class BarcodeLookupSuccess(StrictBaseModel):
    product_id: Annotated[str, StringConstraints(min_length=1)]
    name: Annotated[str, StringConstraints(min_length=1)]
    brand: str | None = None
    nutrition: Nutrition
    ingredients: list[Ingredient]
    allergens: list[Allergen]
    source: Source
    data_quality: DataQuality
