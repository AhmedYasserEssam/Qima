from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
ProfileId = Annotated[str, StringConstraints(pattern=r"^profile_[a-zA-Z0-9_\-]{6,}$")]


class Sex(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class ActivityLevel(str, Enum):
    SEDENTARY = "sedentary"
    LIGHTLY_ACTIVE = "lightly_active"
    MODERATELY_ACTIVE = "moderately_active"
    VERY_ACTIVE = "very_active"
    ATHLETE = "athlete"


class Goal(str, Enum):
    LOSE_WEIGHT = "lose_weight"
    GAIN_MUSCLE = "gain_muscle"
    MAINTAIN_WEIGHT = "maintain_weight"
    IMPROVE_GENERAL_HEALTH = "improve_general_health"


class Unit(str, Enum):
    G = "g"
    KG = "kg"
    ML = "ml"
    L = "l"
    PIECE = "piece"
    TBSP = "tbsp"
    TSP = "tsp"
    CUP = "cup"
    PACK = "pack"
    CAN = "can"
    BUNCH = "bunch"
    CLOVE = "clove"
    HEAD = "head"


class Allergen(str, Enum):
    MILK = "milk"
    EGG = "egg"
    FISH = "fish"
    SHELLFISH = "shellfish"
    TREE_NUTS = "tree_nuts"
    PEANUTS = "peanuts"
    WHEAT = "wheat"
    SOY = "soy"
    SESAME = "sesame"
    OTHER = "other"


class DietaryExclusion(str, Enum):
    PORK = "pork"
    ALCOHOL = "alcohol"
    MEAT = "meat"
    POULTRY = "poultry"
    FISH = "fish"
    SHELLFISH = "shellfish"
    DAIRY = "dairy"
    EGGS = "eggs"
    GLUTEN = "gluten"
    SOY = "soy"
    NUTS = "nuts"
    ADDED_SUGAR = "added_sugar"
    HIGH_SODIUM = "high_sodium"
    OTHER = "other"


class DietaryFilter(str, Enum):
    HALAL = "halal"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    HIGH_PROTEIN = "high_protein"
    HIGH_FIBER = "high_fiber"
    LOW_SUGAR = "low_sugar"
    LOW_SODIUM = "low_sodium"
    BUDGET_FRIENDLY = "budget_friendly"
    EGYPTIAN_FOODS = "egyptian_foods"
    QUICK_MEALS = "quick_meals"


class ExclusionFlag(str, Enum):
    PREGNANCY = "pregnancy"
    ADOLESCENT = "adolescent"
    UNDERWEIGHT = "underweight"
    EATING_DISORDER_RISK = "eating_disorder_risk"
    KIDNEY_DISEASE = "kidney_disease"
    DIABETES = "diabetes"
    OTHER_CLINICAL_CONDITION = "other_clinical_condition"


class TimeHorizon(str, Enum):
    SINGLE_DAY = "single_day"
    SINGLE_MEAL = "single_meal"


class SupportStatusValue(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"


class TargetBasis(str, Enum):
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class MealType(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    UNSPECIFIED = "unspecified"


class Currency(str, Enum):
    EGP = "EGP"


class EstimateQuality(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class MealSourceType(str, Enum):
    RECIPE_CORPUS = "recipe_corpus"
    NUTRITION_DATASET = "nutrition_dataset"
    MIXED_SOURCES = "mixed_sources"


class SourceProvider(str, Enum):
    QIMA_BACKEND = "qima_backend"


class SourceType(str, Enum):
    MEAL_PLAN_RANKER = "meal_plan_ranker"


class DataCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class SafetyFlag(str, Enum):
    NON_DIAGNOSTIC = "non_diagnostic"
    NO_TREATMENT_ADVICE = "no_treatment_advice"
    NO_SUPPLEMENT_PRESCRIPTION = "no_supplement_prescription"
    GENERAL_INFORMATION_ONLY = "general_information_only"
    PROFILE_EXCLUSION_TRIGGERED = "profile_exclusion_triggered"
    INCOMPLETE_PROFILE = "incomplete_profile"
    ESTIMATED_TARGETS_ONLY = "estimated_targets_only"
    ESTIMATED_COST_ONLY = "estimated_cost_only"


class Profile(StrictBaseModel):
    age_years: int = Field(ge=18)
    sex: Sex
    height_cm: float = Field(gt=0)
    weight_kg: float = Field(gt=0)
    activity_level: ActivityLevel
    goal: Goal
    allergens: list[Allergen] = Field(default_factory=list)
    dietary_exclusions: list[DietaryExclusion] = Field(default_factory=list)
    exclusion_flags: list[ExclusionFlag] = Field(default_factory=list)


class PantryItem(StrictBaseModel):
    name: NonEmptyString
    quantity: float | None = Field(default=None, ge=0)
    unit: Unit | None = None


class BudgetConstraint(StrictBaseModel):
    max_total_cost: float | None = Field(default=None, ge=0)
    currency: Currency
    geography: str | None = None


class PlanPreferences(StrictBaseModel):
    meal_count: int | None = Field(default=None, ge=1, le=6)
    include_snacks: bool | None = None
    time_horizon: TimeHorizon | None = None


class PlansGenerateRequest(StrictBaseModel):
    profile_id: ProfileId | None = None
    profile: Profile | None = None
    pantry: list[PantryItem] | None = None
    budget: BudgetConstraint | None = None
    dietary_filters: list[DietaryFilter] = Field(default_factory=list)
    plan_preferences: PlanPreferences | None = None

    @model_validator(mode="after")
    def require_exactly_one_profile_source(self) -> "PlansGenerateRequest":
        has_profile_id = self.profile_id is not None
        has_profile = self.profile is not None

        if has_profile_id == has_profile:
            raise ValueError("Exactly one of profile_id or profile must be provided")

        return self


class SupportStatus(StrictBaseModel):
    status: SupportStatusValue
    reason: NonEmptyString


class NutritionTargets(StrictBaseModel):
    calories_kcal: float | None = Field(ge=0)
    protein_g: float | None = Field(ge=0)
    carbohydrates_g: float | None = Field(ge=0)
    fat_g: float | None = Field(ge=0)
    target_basis: TargetBasis


class EstimatedNutrition(StrictBaseModel):
    calories_kcal: float | None = Field(ge=0)
    protein_g: float | None = Field(ge=0)
    carbohydrates_g: float | None = Field(ge=0)
    fat_g: float | None = Field(ge=0)


class EstimatedCost(StrictBaseModel):
    total_cost: float | None = Field(ge=0)
    currency: Currency
    estimate_quality: EstimateQuality


class MealScore(StrictBaseModel):
    overall: float = Field(ge=0, le=1)
    ingredient_match: float = Field(ge=0, le=1)
    target_fit: float = Field(ge=0, le=1)
    cost_fit: float = Field(ge=0, le=1)
    safety_score: float = Field(
        ge=0,
        le=1,
        description="Safety/compliance score where higher is better.",
    )


class MealSource(StrictBaseModel):
    source_type: MealSourceType
    recipe_id: str | None = None


class MealCandidate(StrictBaseModel):
    meal_id: NonEmptyString
    title: NonEmptyString
    meal_type: MealType
    matched_ingredients: list[NonEmptyString]
    missing_ingredients: list[NonEmptyString]
    estimated_nutrition: EstimatedNutrition
    estimated_cost: EstimatedCost
    score: MealScore
    warnings: list[NonEmptyString]
    source: MealSource


class Source(StrictBaseModel):
    provider: SourceProvider
    source_type: SourceType
    fetched_at: datetime


class DataQuality(StrictBaseModel):
    completeness: DataCompleteness


class PlansGenerateSuccess(StrictBaseModel):
    plan_id: NonEmptyString
    support_status: SupportStatus
    nutrition_targets: NutritionTargets
    meals: list[MealCandidate]
    rationale: NonEmptyString
    safety_flags: list[SafetyFlag]
    source: Source
    data_quality: DataQuality
    warnings: list[NonEmptyString] | None = None