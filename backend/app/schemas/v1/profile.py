from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class ActivityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHTLY_ACTIVE = "lightly_active"
    MODERATELY_ACTIVE = "moderately_active"
    VERY_ACTIVE = "very_active"
    ATHLETE = "athlete"


class NutritionGoal(StrEnum):
    LOSE_WEIGHT = "lose_weight"
    MAINTAIN_WEIGHT = "maintain_weight"
    GAIN_WEIGHT = "gain_weight"
    BUILD_MUSCLE = "build_muscle"
    IMPROVE_GENERAL_HEALTH = "improve_general_health"
    EAT_HIGH_PROTEIN = "eat_high_protein"
    EAT_LOW_CALORIE = "eat_low_calorie"
    EAT_BALANCED = "eat_balanced"
    REDUCE_SUGAR = "reduce_sugar"
    REDUCE_SODIUM = "reduce_sodium"
    REDUCE_SATURATED_FAT = "reduce_saturated_fat"
    INCREASE_FIBER = "increase_fiber"
    BUDGET_FRIENDLY = "budget_friendly"


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


class NutritionProfileCreateUpdate(StrictBaseModel):
    age: int = Field(..., ge=1, le=120)
    sex: Sex
    height_cm: float = Field(..., ge=80, le=260)
    weight_kg: float = Field(..., ge=25, le=400)
    activity_level: ActivityLevel
    goal: NutritionGoal
    allergens: list[str] = Field(default_factory=list)
    dietary_restrictions: list[str] = Field(default_factory=list)
    budget_limit_egp: float | None = Field(default=None, gt=0)

    @field_validator("allergens", "dietary_restrictions", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Expected a list of strings")
        return _normalize_string_list([str(v) for v in value])


class NutritionProfileResponse(StrictBaseModel):
    user_id: int
    age: int
    sex: Sex
    height_cm: float
    weight_kg: float
    activity_level: ActivityLevel
    goal: NutritionGoal
    allergens: list[str]
    dietary_restrictions: list[str]
    budget_limit_egp: float | None
    updated_at: datetime
