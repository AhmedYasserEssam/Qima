from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.v1.shared_price_context import (
    BudgetPreference,
    EstimatedCost,
    PriceBasis,
    PricePreferences,
    RequestedIngredient,
)


class PricesEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_basis: PriceBasis

    ingredients: list[RequestedIngredient] | None = Field(default=None)
    recipe_id: str | None = Field(default=None, min_length=1)
    recipe_ingredients: list[RequestedIngredient] | None = Field(default=None)
    pantry: list[RequestedIngredient] = Field(default_factory=list)

    budget: BudgetPreference
    price_preferences: PricePreferences | None = None

    servings: float | None = Field(
        default=None,
        gt=0,
        description="Optional number of servings used to scale or report per-serving cost. Supports partial servings such as 0.5.",
    )
    currency: str = Field(
        default="EGP",
        min_length=3,
        max_length=3,
        description="Requested currency. v1 does not perform currency conversion.",
    )

    @model_validator(mode="after")
    def validate_estimate_input(self) -> "PricesEstimateRequest":
        if not self.budget.geography:
            raise ValueError("budget.geography is required for price estimation")

        if self.price_basis == PriceBasis.INGREDIENT_LIST:
            if not self.ingredients:
                raise ValueError(
                    "ingredients is required when price_basis is ingredient_list"
                )
            if self.recipe_id is not None or self.recipe_ingredients is not None:
                raise ValueError(
                    "recipe_id and recipe_ingredients must not be provided when price_basis is ingredient_list"
                )

        elif self.price_basis == PriceBasis.RECIPE_ID:
            if not self.recipe_id:
                raise ValueError("recipe_id is required when price_basis is recipe_id")
            if self.ingredients is not None or self.recipe_ingredients is not None:
                raise ValueError(
                    "ingredients and recipe_ingredients must not be provided when price_basis is recipe_id"
                )

        elif self.price_basis == PriceBasis.RECIPE_INGREDIENTS:
            if not self.recipe_ingredients:
                raise ValueError(
                    "recipe_ingredients is required when price_basis is recipe_ingredients"
                )
            if self.ingredients is not None or self.recipe_id is not None:
                raise ValueError(
                    "ingredients and recipe_id must not be provided when price_basis is recipe_ingredients"
                )

        elif self.price_basis == PriceBasis.PANTRY_DELTA:
            has_price_input = bool(self.ingredients) or bool(self.recipe_ingredients) or bool(
                self.recipe_id
            )
            if not has_price_input:
                raise ValueError(
                    "ingredients, recipe_ingredients, or recipe_id is required when price_basis is pantry_delta"
                )

        return self


class PricesEstimateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estimate_id: str = Field(..., min_length=1)
    price_basis: PriceBasis
    recipe_id: str | None = None
    estimated_cost: EstimatedCost
    warnings: list[str] = Field(default_factory=list)
    latency_ms: int = Field(..., ge=0)