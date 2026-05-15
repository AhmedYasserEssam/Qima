from __future__ import annotations

import uuid
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable

from app.schemas.v1.prices import (
    DataQuality,
    EstimateQuality,
    ItemCost,
    MatchBreakdown,
    MatchedPriceItem,
    PricesEstimateRequest,
    PricesEstimateResponse,
    RequestedIngredient,
    Source,
)
from app.services.price_estimation_service import PriceEstimationService
from scripts.estimate_recipe_prices import DEFAULT_PRODUCTS_CSV, DEFAULT_RECIPES_JSONL


class PriceDataUnavailableError(Exception):
    """Raised when the local price dataset cannot be used."""


class RecipeNotFoundError(Exception):
    """Raised when a requested recipe id is not present in the local corpus."""


class RecipePriceEstimator:
    def __init__(
        self,
        products_csv: str | Path = DEFAULT_PRODUCTS_CSV,
        recipes_path: str | Path = DEFAULT_RECIPES_JSONL,
    ) -> None:
        self.products_csv = Path(products_csv)
        self.recipes_path = Path(recipes_path)
        self.estimation_service = PriceEstimationService(
            products_csv=self.products_csv,
            recipes_path=self.recipes_path,
        )

    def estimate_request(self, payload: PricesEstimateRequest) -> PricesEstimateResponse:
        estimate_type = payload.estimate_type
        if estimate_type == "ingredient_list":
            return self.estimate_ingredient_list(payload.ingredients or [], geography=payload.geography)
        return self.estimate_recipe_id(
            payload.recipe_id or "",
            requested_servings=payload.servings,
            geography=payload.geography,
        )

    def estimate_ingredient_list(
        self,
        ingredients: Iterable[RequestedIngredient],
        *,
        geography: str | None = None,
    ) -> PricesEstimateResponse:
        ingredient_dicts = [
            {"name": item.name, "quantity": item.quantity, "unit": item.unit}
            for item in ingredients
        ]
        raw = self._estimate_with_hybrid(
            estimate_type="ingredient_list",
            ingredient_dicts=ingredient_dicts,
            geography=geography,
        )
        return self._to_response(raw, estimate_type="ingredient_list", geography=geography)

    def estimate_recipe_id(
        self,
        recipe_id: str,
        *,
        requested_servings: float | None = None,
        geography: str | None = None,
    ) -> PricesEstimateResponse:
        try:
            raw = self.estimation_service.estimate_recipe_by_id(
                recipe_id,
                servings=requested_servings,
                geography=geography,
            )
        except FileNotFoundError as exc:
            raise PriceDataUnavailableError(str(exc)) from exc
        except ValueError as exc:
            if "Recipe not found" in str(exc):
                raise RecipeNotFoundError(str(exc)) from exc
            raise
        return self._to_response(raw, estimate_type="recipe_id", geography=geography)

    def _estimate_with_hybrid(
        self,
        *,
        estimate_type: str,
        ingredient_dicts: list[dict[str, Any]],
        geography: str | None,
    ) -> dict[str, Any]:
        del estimate_type
        try:
            return self.estimation_service.estimate_ingredient_list(
                ingredient_dicts,
                geography=geography,
            )
        except FileNotFoundError as exc:
            raise PriceDataUnavailableError(str(exc)) from exc

    def _to_response(
        self,
        payload: dict[str, Any],
        *,
        estimate_type: str,
        geography: str | None,
    ) -> PricesEstimateResponse:
        item_costs = [self._to_item_cost(entry) for entry in payload.get("ingredients", [])]
        total_cost = self._to_float(payload.get("total_estimated_cost"))
        quality_confidence = self._to_float(payload.get("estimate_quality_confidence")) or 0.0
        coverage = payload.get("coverage") or "unavailable"
        if coverage not in {"complete", "partial", "unavailable"}:
            coverage = "unavailable"

        source_metadata = payload.get("source_metadata") or {}
        source_date = self._to_date(source_metadata.get("last_updated"))
        warnings = list(payload.get("warnings") or [])

        unmatched = payload.get("unmatched_ingredients") or []
        if unmatched:
            warnings.append(
                "Unmatched ingredients: " + ", ".join(str(item) for item in unmatched)
            )

        freshness = "unknown"
        if source_date is not None:
            age_days = (datetime.now(UTC).date() - source_date).days
            freshness = "fresh" if age_days <= 45 else "stale"

        return PricesEstimateResponse(
            estimate_id=f"price_est_{uuid.uuid4().hex[:12]}",
            estimate_type=estimate_type,  # type: ignore[arg-type]
            currency="EGP",
            item_costs=item_costs,
            total_cost=total_cost,
            estimate_quality=EstimateQuality(
                confidence=max(0.0, min(1.0, quality_confidence)),
                coverage=coverage,  # type: ignore[arg-type]
            ),
            source=Source(
                provider="carrefour_egypt",
                source_type="price_dataset",
                price_date=source_date,
                geography=geography or source_metadata.get("geography") or "Egypt",
                fetched_at=datetime.now(UTC),
            ),
            data_quality=DataQuality(
                completeness="complete" if coverage == "complete" else "partial",
                freshness=freshness,  # type: ignore[arg-type]
            ),
            warnings=warnings,
            unmatched_ingredients=[str(item) for item in unmatched],
            source_metadata=source_metadata,
        )

    def _to_item_cost(self, payload: dict[str, Any]) -> ItemCost:
        matched = payload.get("matched_item")
        match = payload.get("match") or {}
        requested_quantity = self._to_float(payload.get("requested_quantity"))
        requested_unit = payload.get("requested_unit")
        matched_name = matched.get("name") if isinstance(matched, dict) else None
        estimated_cost = self._to_float(payload.get("estimated_cost"))

        unit_price = None
        if isinstance(matched, dict):
            price = self._to_float(matched.get("price"))
            package_quantity = self._to_float(matched.get("package_quantity"))
            if price is not None and package_quantity and package_quantity > 0:
                unit_price = round(price / package_quantity, 6)
            elif price is not None:
                unit_price = round(price, 6)

        confidence_label = str(match.get("confidence_label") or "")
        if confidence_label == "high":
            match_quality = "exact"
        elif confidence_label == "medium":
            match_quality = "normalized"
        elif confidence_label == "low":
            match_quality = "assumed"
        else:
            match_quality = "unmatched"

        matched_item = None
        if isinstance(matched, dict):
            matched_item = MatchedPriceItem(
                name=str(matched.get("name") or ""),
                source=str(matched.get("source") or "carrefour_egypt"),
                source_id=str(matched.get("source_id") or ""),
                price=self._to_float(matched.get("price")),
                currency=str(matched.get("currency") or "EGP"),
                package_quantity=self._to_float(matched.get("package_quantity")),
                package_unit=matched.get("package_unit"),
                price_date=self._to_date(matched.get("price_date")),
            )

        match_breakdown = MatchBreakdown(
            method=str(match.get("method") or "hybrid"),
            confidence=self._to_float(match.get("confidence")) or 0.0,
            confidence_label=confidence_label or "none",
            lexical_score=self._to_float(match.get("lexical_score")) or 0.0,
            embedding_score=self._to_float(match.get("embedding_score")) or 0.0,
            category_score=self._to_float(match.get("category_score")) or 0.0,
            unit_compatibility_score=self._to_float(match.get("unit_compatibility_score")) or 0.0,
            form_compatibility_score=self._to_float(match.get("form_compatibility_score")) or 0.0,
        )

        return ItemCost(
            requested_name=str(payload.get("ingredient") or "ingredient"),
            matched_name=matched_name,
            quantity=requested_quantity,
            unit=requested_unit,
            normalized_quantity=requested_quantity,
            normalized_unit=requested_unit,
            unit_price=unit_price,
            estimated_cost=estimated_cost,
            match_quality=match_quality,  # type: ignore[arg-type]
            assumptions=[str(value) for value in payload.get("warnings", [])],
            product_price=(self._to_float(matched.get("price")) if isinstance(matched, dict) else None),
            product_package_quantity=(
                self._to_float(matched.get("package_quantity")) if isinstance(matched, dict) else None
            ),
            product_package_unit=(matched.get("package_unit") if isinstance(matched, dict) else None),
            match_score=self._to_float(match.get("confidence")),
            pricing_method=str(match.get("method") or "hybrid"),
            matched_item=matched_item,
            match=match_breakdown,
            warnings=[str(value) for value in payload.get("warnings", [])],
        )

    def _to_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            number = float(value)
            if math.isnan(number):
                return None
            return number
        try:
            number = float(str(value).strip())
            if math.isnan(number):
                return None
            return number
        except ValueError:
            return None

    def _to_date(self, value: Any) -> date | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if "T" in text:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
            return date.fromisoformat(text)
        except ValueError:
            return None


price_estimator = RecipePriceEstimator()


def estimate_price_request(payload: PricesEstimateRequest) -> PricesEstimateResponse:
    return price_estimator.estimate_request(payload)
