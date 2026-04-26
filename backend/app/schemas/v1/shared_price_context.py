from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceBasis(str, Enum):
    INGREDIENT_LIST = "ingredient_list"
    RECIPE_INGREDIENTS = "recipe_ingredients"
    PANTRY_DELTA = "pantry_delta"
    RECIPE_ID = "recipe_id"


class Coverage(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class MatchQuality(str, Enum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    ASSUMED = "assumed"
    UNMATCHED = "unmatched"


class RequestedIngredient(StrictBaseModel):
    id: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Optional stable client or backend id used to link requested ingredients to item-level cost rows.",
    )
    name: str = Field(min_length=1)
    quantity: Optional[float] = Field(default=None, gt=0)
    unit: Optional[str] = Field(default=None, min_length=1)
    notes: Optional[str] = None


class PriceSource(StrictBaseModel):
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    geography: Optional[str] = None
    observed_at: Optional[date] = Field(
        default=None,
        description="Date when the price was observed.",
    )
    last_updated_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the backend price record was last updated.",
    )
    price_basis: Optional[PriceBasis] = None


class ItemCost(StrictBaseModel):
    requested_item_id: Optional[str] = Field(
        default=None,
        description="Optional link to RequestedIngredient.id. Prefer this over name matching when available.",
    )
    ingredient_name: str = Field(min_length=1)
    normalized_name: Optional[str] = None

    requested_quantity: Optional[float] = Field(default=None, gt=0)
    requested_unit: Optional[str] = None

    usage_cost: Optional[float] = Field(
        default=None,
        ge=0,
        description="Estimated pro-rated cost of the quantity actually used by the recipe or meal.",
    )
    purchase_cost: Optional[float] = Field(
        default=None,
        ge=0,
        description="Estimated checkout cost required to buy the purchasable package or unit.",
    )
    purchase_quantity: Optional[float] = Field(
        default=None,
        gt=0,
        description="Quantity of the purchasable package or unit used to estimate purchase_cost.",
    )
    purchase_unit: Optional[str] = Field(
        default=None,
        description="Unit of the purchasable package or unit used to estimate purchase_cost.",
    )

    estimated_cost: Optional[float] = Field(
        default=None,
        ge=0,
        description="Backward-compatible item-level estimated cost. Prefer usage_cost and purchase_cost when both are available.",
    )

    currency: str = Field(min_length=3, max_length=3)
    match_quality: MatchQuality

    assumptions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    source: Optional[PriceSource] = None


class EstimateQuality(StrictBaseModel):
    priced_item_count: Optional[int] = Field(default=None, ge=0)
    unpriced_item_count: Optional[int] = Field(default=None, ge=0)
    staleness_warning: bool = False


class EstimatedCost(StrictBaseModel):
    total_cost: Optional[float] = Field(
        default=None,
        ge=0,
        description="Estimated total usage cost for the requested ingredients, recipe, or meal.",
    )
    total_purchase_cost: Optional[float] = Field(
        default=None,
        ge=0,
        description="Estimated total checkout cost if the user must buy full purchasable units.",
    )
    pantry_delta_cost: Optional[float] = Field(
        default=None,
        ge=0,
        description="Estimated usage cost for missing ingredients after treating pantry items as already owned.",
    )
    pantry_delta_purchase_cost: Optional[float] = Field(
        default=None,
        ge=0,
        description="Estimated checkout cost for missing purchasable units after treating pantry items as already owned.",
    )
    per_serving_cost: Optional[float] = Field(default=None, ge=0)

    currency: str = Field(min_length=3, max_length=3)
    coverage: Coverage
    confidence: Optional[float] = Field(default=None, ge=0, le=1)

    quality: Optional[EstimateQuality] = None
    item_costs: List[ItemCost] = Field(default_factory=list)

    assumptions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    source: Optional[PriceSource] = None


class BudgetPreference(StrictBaseModel):
    max_total_cost: Optional[float] = Field(
        default=None,
        gt=0,
        description="Maximum allowed estimated usage cost.",
    )
    max_total_purchase_cost: Optional[float] = Field(
        default=None,
        gt=0,
        description="Maximum allowed estimated checkout cost.",
    )
    max_per_serving_cost: Optional[float] = Field(default=None, gt=0)

    currency: str = Field(default="EGP", min_length=3, max_length=3)
    geography: Optional[str] = None


class RankingMode(str, Enum):
    BEST_MATCH = "best_match"
    BUDGET_FRIENDLY = "budget_friendly"
    LOWEST_COST = "lowest_cost"
    COST_PER_PROTEIN = "cost_per_protein"
    BALANCED = "balanced"


class PricePreferences(StrictBaseModel):
    price_aware: bool = False
    ranking_mode: RankingMode = RankingMode.BEST_MATCH
    include_item_costs: bool = False
    use_pantry_as_owned: bool = True


class PriceContext(StrictBaseModel):
    price_basis: Optional[PriceBasis] = None
    ingredients: List[RequestedIngredient] = Field(default_factory=list)
    estimated_cost: Optional[EstimatedCost] = None
    budget: Optional[BudgetPreference] = None
    price_preferences: Optional[PricePreferences] = None
    source: Optional[PriceSource] = None