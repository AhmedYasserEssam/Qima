from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonEmptyString = Annotated[str, StringConstraints(min_length=1)]


class NutritionEstimateInputType(str, Enum):
    RECOGNIZED_DISH = "recognized_dish"
    INGREDIENT_SET = "ingredient_set"


class MatchType(str, Enum):
    DISH = "dish"
    INGREDIENT_SET = "ingredient_set"
    FOOD_ITEM = "food_item"


class NutritionDataset(str, Enum):
    NUTRITION_XLSX = "nutrition_xlsx"
    EGYPTIAN_FOOD_CSV = "egyptian_food_csv"
    FDC_FOUNDATION = "fdc_foundation"
    FDC_SR_LEGACY = "fdc_sr_legacy"


class NutritionSourceType(str, Enum):
    NUTRITION_DATASET = "nutrition_dataset"
    EGYPTIAN_FOOD_DATASET = "egyptian_food_dataset"
    FOODDATA_CENTRAL = "fooddata_central"


class DataCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class NutritionEstimateRequest(StrictBaseModel):
    input_type: NutritionEstimateInputType
    recognized_dish: NonEmptyString | None = None
    ingredients: list[NonEmptyString] | None = None
    serving_hint: str | None = None

    @model_validator(mode="after")
    def validate_input_payload(self) -> "NutritionEstimateRequest":
        if self.input_type == NutritionEstimateInputType.RECOGNIZED_DISH:
            if not self.recognized_dish:
                raise ValueError(
                    "recognized_dish is required when input_type is recognized_dish"
                )

        if self.input_type == NutritionEstimateInputType.INGREDIENT_SET:
            if not self.ingredients:
                raise ValueError(
                    "ingredients is required when input_type is ingredient_set"
                )

        return self


class MatchedDish(StrictBaseModel):
    name: NonEmptyString = Field(
        description="Backend-selected normalized food or dish match used for nutrient estimation."
    )
    match_type: MatchType | None = None
    match_id: str | None = None


class ServingAssumptions(StrictBaseModel):
    basis: NonEmptyString = Field(
        description="Serving assumption used for nutrient estimation."
    )
    note: str | None = None


class Nutrients(StrictBaseModel):
    calories_kcal: float | None = Field(ge=0)
    protein_g: float | None = Field(ge=0)
    carbohydrates_g: float | None = Field(ge=0)
    fat_g: float | None = Field(ge=0)
    fiber_g: float | None = Field(default=None, ge=0)
    sugar_g: float | None = Field(default=None, ge=0)
    sodium_mg: float | None = Field(default=None, ge=0)


class Source(StrictBaseModel):
    dataset: NutritionDataset
    source_type: NutritionSourceType

    @model_validator(mode="after")
    def validate_dataset_source_type(self) -> "Source":
        expected_source_type = {
            NutritionDataset.NUTRITION_XLSX: NutritionSourceType.NUTRITION_DATASET,
            NutritionDataset.EGYPTIAN_FOOD_CSV: NutritionSourceType.EGYPTIAN_FOOD_DATASET,
            NutritionDataset.FDC_FOUNDATION: NutritionSourceType.FOODDATA_CENTRAL,
            NutritionDataset.FDC_SR_LEGACY: NutritionSourceType.FOODDATA_CENTRAL,
        }[self.dataset]

        if self.source_type != expected_source_type:
            raise ValueError(
                f"source_type must be {expected_source_type.value} when dataset is {self.dataset.value}"
            )

        return self


class DataQuality(StrictBaseModel):
    completeness: DataCompleteness


class NutritionEstimateSuccess(StrictBaseModel):
    matched_dish: MatchedDish
    serving_assumptions: ServingAssumptions
    nutrients: Nutrients
    confidence: float = Field(ge=0, le=1)
    source: Source
    data_quality: DataQuality
    warnings: list[NonEmptyString] | None = None