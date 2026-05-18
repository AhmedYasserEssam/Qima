from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


MarkerName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]


class Sex(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class ExclusionFlag(str, Enum):
    PREGNANCY = "pregnancy"
    ADOLESCENT = "adolescent"
    UNDERWEIGHT = "underweight"
    EATING_DISORDER_RISK = "eating_disorder_risk"
    KIDNEY_DISEASE = "kidney_disease"
    DIABETES = "diabetes"
    OTHER_CLINICAL_CONDITION = "other_clinical_condition"


class RangeComparison(str, Enum):
    BELOW_RANGE = "below_range"
    WITHIN_RANGE = "within_range"
    ABOVE_RANGE = "above_range"
    UNKNOWN = "unknown"


class NutrientThemeName(str, Enum):
    IRON_RICH_FOODS = "iron_rich_foods"
    VITAMIN_D_FOODS = "vitamin_d_foods"
    B12_FOODS = "b12_foods"
    FOLATE_FOODS = "folate_foods"
    MAGNESIUM_FOODS = "magnesium_foods"
    HYDRATION_AND_ELECTROLYTES = "hydration_and_electrolytes"
    GENERAL_BALANCED_DIET = "general_balanced_diet"


class GuidanceType(str, Enum):
    INCLUDE_FOODS = "include_foods"
    LIMIT_FOODS = "limit_foods"
    GENERAL_NOTE = "general_note"
    CLINICIAN_DISCUSSION = "clinician_discussion"


class SafetyFlag(str, Enum):
    NON_DIAGNOSTIC = "non_diagnostic"
    NO_TREATMENT_ADVICE = "no_treatment_advice"
    NO_SUPPLEMENT_PRESCRIPTION = "no_supplement_prescription"
    UNSUPPORTED_MARKER = "unsupported_marker"
    UNSUPPORTED_UNIT = "unsupported_unit"
    AMBIGUOUS_REFERENCE_RANGE = "ambiguous_reference_range"
    PROFILE_EXCLUSION_TRIGGERED = "profile_exclusion_triggered"
    CLINICIAN_DISCUSSION_RECOMMENDED = "clinician_discussion_recommended"


class SupportStatusValue(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"


class SourceProvider(str, Enum):
    VALIDATED_LAB_MARKER_MAPPING_TABLE = "validated_lab_marker_mapping_table"


class SourceType(str, Enum):
    LAB_MARKER_RULES = "lab_marker_rules"


class ReferenceRange(StrictBaseModel):
    low: float | None
    high: float | None
    unit: NonEmptyString


class ProfileContext(StrictBaseModel):
    age_years: int | None = Field(default=None, ge=18)
    sex: Sex | None = None
    exclusion_flags: list[ExclusionFlag] = Field(default_factory=list)


class LabsInterpretRequest(StrictBaseModel):
    marker_name: MarkerName = Field(
        description="Backend-normalized lab marker key, such as ferritin, vitamin_d, b12, hemoglobin, or magnesium."
    )
    value: float = Field(description="User-provided lab marker value.")
    unit: NonEmptyString = Field(
        description="Unit shown on the user's lab result."
    )
    reference_range: ReferenceRange
    profile_context: ProfileContext | None = None


class MarkerResult(StrictBaseModel):
    name: NonEmptyString
    normalized_name: str | None
    value: float
    unit: NonEmptyString


class NutrientTheme(StrictBaseModel):
    theme: NutrientThemeName
    reason: NonEmptyString


class FoodGuidance(StrictBaseModel):
    guidance_type: GuidanceType
    message: NonEmptyString
    foods: list[NonEmptyString]


class SupportStatus(StrictBaseModel):
    status: SupportStatusValue
    reason: NonEmptyString


class Source(StrictBaseModel):
    provider: SourceProvider
    source_type: SourceType
    fetched_at: datetime


class LabsInterpretSuccess(StrictBaseModel):
    interpretation_id: NonEmptyString
    supported_marker: bool
    marker: MarkerResult
    range_comparison: RangeComparison
    used_user_range: bool
    nutrient_themes: list[NutrientTheme]
    food_guidance: list[FoodGuidance]
    safety_flags: list[SafetyFlag]
    support_status: SupportStatus
    source: Source
    warnings: list[NonEmptyString] | None = None