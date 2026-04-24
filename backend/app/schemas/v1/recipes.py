from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecipeSuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pantry_items: list[str] | None = None
    recognized_ingredients: list[str] | None = None
    dietary_filters: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)
    max_results: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def validate_recipe_input(self) -> "RecipeSuggestRequest":
        if not self.pantry_items and not self.recognized_ingredients:
            raise ValueError(
                "pantry_items or recognized_ingredients is required"
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
    exclusions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
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

    title: str = Field(..., min_length=1)
    matched_ingredients: list[str] = Field(default_factory=list)
    missing_ingredients: list[str] = Field(default_factory=list)


class RecipeDiscussRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str | None = Field(default=None, min_length=1)
    candidate_context: CandidateContext | None = None
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
    safety_flags: SafetyFlags
    warnings: list[str] = Field(default_factory=list)
    latency_ms: int = Field(..., ge=0)