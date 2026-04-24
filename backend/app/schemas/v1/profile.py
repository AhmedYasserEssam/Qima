from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Sex = Literal["male", "female", "other", "prefer_not_to_say"]

ActivityLevel = Literal[
    "sedentary",
    "lightly_active",
    "moderately_active",
    "very_active",
    "athlete",
]

Goal = Literal[
    "lose_weight",
    "gain_muscle",
    "maintain_weight",
    "improve_general_health",
    "budget_friendly_eating",
]

Allergen = Literal[
    "milk",
    "egg",
    "fish",
    "shellfish",
    "tree_nuts",
    "peanuts",
    "wheat",
    "soy",
    "sesame",
    "other",
]

DietaryExclusion = Literal[
    "pork",
    "alcohol",
    "meat",
    "poultry",
    "fish",
    "shellfish",
    "dairy",
    "eggs",
    "gluten",
    "soy",
    "nuts",
    "added_sugar",
    "high_sodium",
    "other",
]

DietaryPreference = Literal[
    "halal",
    "vegetarian",
    "vegan",
    "high_protein",
    "high_fiber",
    "low_sugar",
    "low_sodium",
    "budget_friendly",
    "egyptian_foods",
    "quick_meals",
]

ExclusionFlag = Literal[
    "pregnancy",
    "adolescent",
    "underweight",
    "eating_disorder_risk",
    "kidney_disease",
    "diabetes",
    "other_clinical_condition",
]

ValidationFlag = Literal[
    "missing_age",
    "missing_sex",
    "missing_height",
    "missing_weight",
    "missing_activity_level",
    "missing_goal",
    "partial_profile",
    "invalid_or_unsupported_value",
]

LimitationFlag = Literal[
    "general_information_only",
    "goal_guidance_unavailable",
    "lab_guidance_limited",
    "profile_exclusion_triggered",
    "incomplete_profile",
    "guest_or_session_scoped",
]


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str | None = None
    age_years: int | None = Field(default=None, ge=0)
    sex: Sex | None = None
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    activity_level: ActivityLevel | None = None
    goal: Goal | None = None
    allergens: list[Allergen] = Field(default_factory=list)
    dietary_exclusions: list[DietaryExclusion] = Field(default_factory=list)
    dietary_preferences: list[DietaryPreference] = Field(default_factory=list)
    exclusion_flags: list[ExclusionFlag] = Field(default_factory=list)


class NormalizedProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_years: int | None = Field(default=None, ge=0)
    sex: Sex | None
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    activity_level: ActivityLevel | None
    goal: Goal | None
    allergens: list[Allergen]
    dietary_exclusions: list[DietaryExclusion]
    dietary_preferences: list[DietaryPreference]
    exclusion_flags: list[ExclusionFlag]


class SupportStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["supported", "partially_supported", "unsupported"]
    reason: str = Field(..., min_length=1)


class ProfileUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(..., min_length=1)
    normalized_profile: NormalizedProfile
    validation_flags: list[ValidationFlag] = Field(default_factory=list)
    limitation_flags: list[LimitationFlag] = Field(default_factory=list)
    support_status: SupportStatus
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)