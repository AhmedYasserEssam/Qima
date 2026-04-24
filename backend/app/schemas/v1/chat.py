from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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
    OTHER = "other"


class ProfileOverrides(StrictBaseModel):
    dietary_preferences: list[str] | None = None
    allergens: list[str] | None = None


class ChatQueryRequest(StrictBaseModel):
    context_id: Annotated[str, StringConstraints(min_length=1)] = Field(
        description="Opaque backend context or session identifier."
    )
    question: Annotated[str, StringConstraints(min_length=1, max_length=2000)] = Field(
        description="User question in natural language."
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


class SafetyFlags(StrictBaseModel):
    grounded: bool = Field(
        description="True only when the answer is supported by at least one backend-approved source reference."
    )
    medical_advice_blocked: bool
    allergen_caution: bool
    low_confidence: bool
    notes: list[str] | None = None


class ChatQueryResponse(StrictBaseModel):
    answer: Annotated[str, StringConstraints(min_length=1)]
    source_references: list[SourceReference] = Field(default_factory=list)
    safety_flags: SafetyFlags
    latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def grounded_answers_must_have_sources(self) -> "ChatQueryResponse":
        if self.safety_flags.grounded and len(self.source_references) < 1:
            raise ValueError(
                "source_references must contain at least one item when safety_flags.grounded is true"
            )
        return self