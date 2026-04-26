from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.v1.shared_price_context import (
    BudgetPreference,
    Coverage,
    EstimatedCost,
    PriceContext,
    PricePreferences,
    PriceSource,
    RequestedIngredient,
)


class RecipeSuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pantry_items: list[str] | None = None
    pantry: list[RequestedIngredient] | None = None
    recognized_ingredients: list[str | RequestedIngredient] | None = None

    user_preferences: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)

    budget: BudgetPreference | None = None
    price_preferences: PricePreferences | None = None

    max_results: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def validate_recipe_input(self) -> "RecipeSuggestRequest":
        if not self.pantry_items and not self.pantry and not self.recognized_ingredients:
            raise ValueError(
                "pantry_items, pantry, or recognized_ingredients is required"
            )
        return self


class GroundingMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieved_from: Literal["recipe_corpus_primary"]
    matched_count: int = Field(..., ge=0)
    missing_count: int = Field(..., ge=0)


class RecipeCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    match_score: float = Field(..., ge=0, le=1)

    matched_ingredients: list[str] = Field(default_factory=list)
    missing_ingredients: list[str] = Field(default_factory=list)
    applied_filters: list[str] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)

    estimated_cost: EstimatedCost | None = None
    price_rank: int | None = Field(default=None, ge=1)
    price_explanation: str | None = None

    grounding_metadata: GroundingMetadata


class RecipeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: Literal["recipe_corpus_primary"]
    retrieval_mode: Literal["retrieval_first"]
    source_type: Literal["recipe_corpus"]


class RecipeSuggestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipes: list[RecipeCandidate] = Field(..., min_length=1)
    source: RecipeSource
    latency_ms: int = Field(..., ge=0)


class CandidateContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str | None = Field(default=None, min_length=1)
    title: str = Field(..., min_length=1)

    matched_ingredients: list[str] = Field(default_factory=list)
    missing_ingredients: list[str] = Field(default_factory=list)
    applied_filters: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    estimated_cost: EstimatedCost | None = None


class ConversationIntent(str):
    EXPLAIN_RECIPE = "explain_recipe"
    REDUCE_COST = "reduce_cost"
    SUBSTITUTE_INGREDIENT = "substitute_ingredient"
    COMPARE_OPTIONS = "compare_options"
    GENERAL = "general"


class RecipeDiscussRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str | None = Field(default=None, min_length=1)
    candidate_context: CandidateContext | None = None

    price_context: PriceContext | None = None
    conversation_intent: Literal[
        "explain_recipe",
        "reduce_cost",
        "substitute_ingredient",
        "compare_options",
        "general",
    ] | None = None

    question: str = Field(..., min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_discussion_context(self) -> "RecipeDiscussRequest":
        has_recipe_id = self.recipe_id is not None
        has_candidate_context = self.candidate_context is not None

        if has_recipe_id == has_candidate_context:
            raise ValueError(
                "exactly one of recipe_id or candidate_context is required"
            )

        return self


class GroundedReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    reference_type: Literal["ingredient", "instruction", "metadata"]
    reference_text: str = Field(..., min_length=1)


class PriceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_type: Literal[
        "estimated_cost",
        "item_cost",
        "budget",
        "price_source",
        "assumption",
        "warning",
    ]
    ingredient_name: str | None = None
    label: str = Field(..., min_length=1)
    value: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    coverage: Coverage | None = None
    source: PriceSource | None = None


class SuggestedSubstitution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_ingredient: str = Field(..., min_length=1)
    to_ingredient: str = Field(..., min_length=1)

    estimated_savings: float | None = Field(default=None, ge=0)
    estimated_purchase_savings: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    savings_estimable: bool | None = None

    tradeoffs: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    price_references: list[PriceReference] = Field(default_factory=list)


class SafetyFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allergen_risk: bool
    undercooked_risk: bool
    cross_contamination_risk: bool
    diet_conflict: bool
    notes: list[str] = Field(default_factory=list)


class RecipeDiscussResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(..., min_length=1)
    grounded_references: list[GroundedReference] = Field(..., min_length=1)

    price_references: list[PriceReference] = Field(default_factory=list)
    suggested_substitutions: list[SuggestedSubstitution] = Field(default_factory=list)
    updated_estimated_cost: EstimatedCost | None = None

    safety_flags: SafetyFlags
    warnings: list[str] = Field(default_factory=list)
    latency_ms: int = Field(..., ge=0)