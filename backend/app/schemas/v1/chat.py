from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.v1.shared_price_context import (
    BudgetPreference,
    Coverage,
    EstimatedCost,
    PriceSource,
    RequestedIngredient,
)


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatSourceType(str, Enum):
    OPEN_FOOD_FACTS = "open_food_facts"
    NUTRITION_DATASET = "nutrition_dataset"
    EGYPTIAN_FOOD_DATASET = "egyptian_food_dataset"
    FOODDATA_CENTRAL = "fooddata_central"
    RECIPE_CORPUS = "recipe_corpus"
    COMPARISON_RESULT = "comparison_result"
    SESSION_CONTEXT = "session_context"
    PRICE_CONTEXT = "price_context"
    PRICE_DATASET = "price_dataset"
    OTHER = "other"


class ActiveContextType(str, Enum):
    RECIPE_SUGGESTIONS = "recipe_suggestions"
    RECIPE_DISCUSSION = "recipe_discussion"
    MEAL_PLAN = "meal_plan"
    SCAN_RESULT = "scan_result"
    GENERAL = "general"


class ProfileOverrides(StrictBaseModel):
    dietary_preferences: list[str] | None = Field(
        default=None,
        description="Temporary diet-specific preferences or constraints.",
    )
    user_preferences: list[str] | None = Field(
        default=None,
        description="Temporary per-request preferences such as vegan, budget_friendly, high_protein, quick_meal, or cooking for someone else.",
    )
    allergens: list[str] | None = Field(
        default=None,
        description="Temporary allergen constraints for this request.",
    )


class ContextRecipe(StrictBaseModel):
    recipe_id: Annotated[str, StringConstraints(min_length=1)]
    title: Annotated[str, StringConstraints(min_length=1)]

    matched_ingredients: list[str] = Field(default_factory=list)
    missing_ingredients: list[str] = Field(default_factory=list)
    applied_filters: list[str] = Field(default_factory=list)

    estimated_cost: EstimatedCost | None = None
    price_rank: int | None = Field(default=None, ge=1)
    price_explanation: str | None = None


class FoodContext(StrictBaseModel):
    selected_recipe_id: Annotated[str, StringConstraints(min_length=1)] | None = None
    recipes: list[ContextRecipe] = Field(default_factory=list)
    pantry: list[RequestedIngredient] = Field(default_factory=list)
    recognized_ingredients: list[str | RequestedIngredient] = Field(default_factory=list)
    estimated_costs: list[EstimatedCost] = Field(default_factory=list)
    budget: BudgetPreference | None = None


class ChatQueryRequest(StrictBaseModel):
    context_id: Annotated[str, StringConstraints(min_length=1)] = Field(
        description="Opaque backend context or session identifier."
    )
    question: Annotated[str, StringConstraints(min_length=1, max_length=2000)] = Field(
        description="User question in natural language."
    )

    active_context_type: ActiveContextType | None = Field(
        default=None,
        description="Optional structured hint describing the active context the user is asking about.",
    )
    food_context: FoodContext | None = Field(
        default=None,
        description="Structured food, recipe, pantry, budget, and price context available to ground chat responses.",
    )

    conversation_turn_id: str | None = Field(
        default=None,
        description="Optional client-generated id for tracing and idempotency.",
    )
    locale: str | None = Field(
        default=None,
        description="Optional BCP-47 locale such as en or ar-EG.",
    )
    profile_overrides: ProfileOverrides | None = Field(
        default=None,
        description="Temporary per-request profile overrides.",
    )
    client_timestamp: datetime | None = None


class SourceReference(StrictBaseModel):
    source_id: str
    source_type: ChatSourceType
    label: str
    excerpt: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class PriceReference(StrictBaseModel):
    reference_type: Literal[
        "estimated_cost",
        "item_cost",
        "budget",
        "price_source",
        "assumption",
        "warning",
    ]
    recipe_id: str | None = None
    ingredient_name: str | None = None
    label: Annotated[str, StringConstraints(min_length=1)]
    value: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    coverage: Coverage | None = None
    source: PriceSource | None = None


class CostSavingAction(StrictBaseModel):
    action_type: Literal[
        "choose_lower_cost_recipe",
        "use_pantry_item",
        "replace_ingredient",
        "remove_optional_ingredient",
        "reduce_quantity",
        "request_price_refresh",
    ]
    description: Annotated[str, StringConstraints(min_length=1)]

    recipe_id: str | None = None
    from_ingredient: str | None = None
    to_ingredient: str | None = None

    estimated_savings: float | None = Field(default=None, ge=0)
    estimated_purchase_savings: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    savings_estimable: bool | None = None

    warnings: list[str] = Field(default_factory=list)


class SafetyFlags(StrictBaseModel):
    grounded: bool = Field(
        description="True only when the answer is supported by at least one backend-approved source reference."
    )
    medical_advice_blocked: bool
    allergen_caution: bool
    low_confidence: bool
    price_context_missing: bool | None = Field(
        default=None,
        description="True when the user asks a price-sensitive question but usable structured price context is unavailable.",
    )
    notes: list[str] | None = Field(
        default=None,
        description="Human-readable notes explaining safety limits, missing context, low confidence, or unavailable price grounding.",
    )


class ChatQueryResponse(StrictBaseModel):
    answer: Annotated[str, StringConstraints(min_length=1)]
    source_references: list[SourceReference] = Field(default_factory=list)

    price_references: list[PriceReference] = Field(default_factory=list)
    recommended_recipe_ids: list[str] = Field(default_factory=list)
    cost_saving_actions: list[CostSavingAction] = Field(default_factory=list)

    safety_flags: SafetyFlags
    latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def grounded_answers_must_have_sources(self) -> "ChatQueryResponse":
        if self.safety_flags.grounded and len(self.source_references) < 1:
            raise ValueError(
                "source_references must contain at least one item when safety_flags.grounded is true"
            )
        return self