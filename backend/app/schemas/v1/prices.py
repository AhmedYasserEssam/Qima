from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Unit = Literal[
    "g",
    "kg",
    "ml",
    "l",
    "piece",
    "tbsp",
    "tsp",
    "cup",
    "pack",
    "can",
    "bunch",
    "clove",
    "head",
]


class RequestedIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    quantity: float | None = Field(default=None, ge=0)
    unit: Unit | None = None


class PricesEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estimate_type: Literal["ingredient_list", "recipe_id"]
    ingredients: list[RequestedIngredient] | None = Field(default=None, min_length=1)
    recipe_id: str | None = Field(
        default=None,
        pattern=r"^recipe_[a-zA-Z0-9_\-]{6,}$",
    )
    servings: float | None = Field(default=None, ge=1)
    geography: str | None = None

    @model_validator(mode="after")
    def validate_estimate_input(self) -> "PricesEstimateRequest":
        if self.estimate_type == "ingredient_list":
            if not self.ingredients:
                raise ValueError(
                    "ingredients is required when estimate_type is ingredient_list"
                )
            if self.recipe_id is not None:
                raise ValueError(
                    "recipe_id must not be provided when estimate_type is ingredient_list"
                )

        if self.estimate_type == "recipe_id":
            if not self.recipe_id:
                raise ValueError("recipe_id is required when estimate_type is recipe_id")
            if self.ingredients is not None:
                raise ValueError(
                    "ingredients must not be provided when estimate_type is recipe_id"
                )

        return self


class ItemCost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_name: str = Field(..., min_length=1)
    matched_name: str | None
    quantity: float | None = Field(default=None, ge=0)
    unit: Unit | None
    normalized_quantity: float | None = Field(default=None, ge=0)
    normalized_unit: Unit | None
    unit_price: float | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    match_quality: Literal["exact", "normalized", "assumed", "unmatched"]
    assumptions: list[str] = Field(default_factory=list)


class EstimateQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: float = Field(..., ge=0, le=1)
    coverage: Literal["complete", "partial", "unavailable"]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["egyptian_ingredient_price_kb"]
    source_type: Literal["price_dataset"]
    price_date: date | None
    geography: str | None = None
    fetched_at: datetime


class DataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completeness: Literal["complete", "partial"]
    freshness: Literal["fresh", "stale", "unknown"]


class PricesEstimateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estimate_id: str = Field(..., min_length=1)
    estimate_type: Literal["ingredient_list", "recipe_id"]
    currency: Literal["EGP"]
    item_costs: list[ItemCost]
    total_cost: float | None = Field(default=None, ge=0)
    estimate_quality: EstimateQuality
    source: Source
    data_quality: DataQuality
    warnings: list[str] = Field(default_factory=list)