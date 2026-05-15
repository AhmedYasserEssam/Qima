from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.normalizers.ingredient_normalizer import normalize_ingredient, normalize_unit
from app.services.price_embedding_service import PriceEmbeddingService
from app.services.price_matching_service import (
    PriceCatalogItem,
    PriceMatchingService,
    build_price_catalog_item,
)
from scripts.estimate_recipe_prices import DEFAULT_PRODUCTS_CSV, DEFAULT_RECIPES_JSONL, load_recipes


PACKAGE_SIZE_RE = re.compile(
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>kg|kilogram|kilograms|g|gm|gram|grams|mg|ml|l|liter|liters|litre|litres)\b",
    re.IGNORECASE,
)

UNIT_TO_BASE = {
    "mg": ("g", 0.001),
    "g": ("g", 1.0),
    "kg": ("g", 1000.0),
    "ml": ("ml", 1.0),
    "l": ("ml", 1000.0),
    "piece": ("piece", 1.0),
    "pack": ("pack", 1.0),
}


class PriceEstimationService:
    def __init__(
        self,
        *,
        products_csv: str | Path = DEFAULT_PRODUCTS_CSV,
        recipes_path: str | Path = DEFAULT_RECIPES_JSONL,
    ) -> None:
        self.products_csv = Path(products_csv)
        self.recipes_path = Path(recipes_path)
        self.embedding_service = PriceEmbeddingService(
            cache_path=self.products_csv.parent / ".price_embeddings_cache.json"
        )
        self.matching_service = PriceMatchingService(
            embedding_service=self.embedding_service
        )
        self._catalog: list[PriceCatalogItem] | None = None
        self._latest_source_fetched_at: datetime | None = None

    def estimate_ingredient_list(
        self,
        ingredients: list[dict[str, Any]],
        *,
        geography: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_catalog()

        ingredient_rows: list[dict[str, Any]] = []
        unmatched: list[str] = []
        warnings = [
            "Prices are estimated and may vary by store, geography, brand, and date."
        ]
        total = 0.0
        matched_count = 0
        confidence_scores: list[float] = []

        for ingredient in ingredients:
            normalized = normalize_ingredient(ingredient)
            match = self.matching_service.match_ingredient_to_price_item(normalized)
            estimated_cost, cost_warning = self._estimate_cost(normalized, match.matched_item)
            ingredient_warnings = list(match.warnings)
            if cost_warning:
                ingredient_warnings.append(cost_warning)

            matched_payload = self._matched_payload(match.matched_item)
            ingredient_payload = {
                "ingredient": normalized.original_name,
                "requested_quantity": normalized.quantity,
                "requested_unit": normalized.unit,
                "matched_item": matched_payload,
                "estimated_cost": round(estimated_cost, 2) if estimated_cost is not None else None,
                "match": {
                    "method": match.method,
                    "confidence": round(match.confidence, 3),
                    "confidence_label": match.confidence_label,
                    "lexical_score": round(match.lexical_score, 3),
                    "embedding_score": round(match.embedding_score, 3),
                    "category_score": round(match.category_score, 3),
                    "unit_compatibility_score": round(match.unit_compatibility_score, 3),
                    "form_compatibility_score": round(match.form_compatibility_score, 3),
                },
                "warnings": ingredient_warnings,
            }
            ingredient_rows.append(ingredient_payload)

            if estimated_cost is None:
                unmatched.append(normalized.original_name)
            else:
                total += estimated_cost
                matched_count += 1
                confidence_scores.append(match.confidence)

        if unmatched:
            warnings.append(
                f"{len(unmatched)} ingredient(s) were unmatched or not reliably priced."
            )

        quality = self._estimate_quality(
            ingredient_count=len(ingredient_rows),
            matched_count=matched_count,
            confidence_scores=confidence_scores,
        )

        return {
            "currency": "EGP",
            "total_estimated_cost": round(total, 2) if matched_count > 0 else None,
            "estimate_quality": quality["label"],
            "estimate_quality_confidence": quality["confidence"],
            "coverage": quality["coverage"],
            "ingredients": ingredient_rows,
            "unmatched_ingredients": unmatched,
            "warnings": warnings,
            "source_metadata": {
                "price_source": "carrefour_dataset",
                "last_updated": (
                    self._latest_source_fetched_at.date().isoformat()
                    if self._latest_source_fetched_at is not None
                    else None
                ),
                "geography": geography or "Egypt",
            },
        }

    def estimate_recipe_by_id(
        self,
        recipe_id: str,
        *,
        servings: float | None = None,
        geography: str | None = None,
    ) -> dict[str, Any]:
        recipe = self._find_recipe(recipe_id)
        ingredients = recipe.get("ingredients")
        if not isinstance(ingredients, list):
            ingredients = []

        scale = 1.0
        if servings is not None and servings > 0:
            recipe_servings = self._to_float(recipe.get("servings")) or 1.0
            if recipe_servings > 0:
                scale = servings / recipe_servings

        scaled = [self._scale_ingredient(ingredient, scale) for ingredient in ingredients]
        result = self.estimate_ingredient_list(scaled, geography=geography)
        result["recipe_id"] = recipe_id
        if servings is not None:
            result["servings"] = servings
            result["warnings"].append(
                f"Recipe quantities were scaled to {round(servings, 2)} serving(s)."
            )
        return result

    def _ensure_catalog(self) -> None:
        if self._catalog is not None:
            return
        if not self.products_csv.exists():
            raise FileNotFoundError(
                f"Carrefour product dataset not found: {self.products_csv}"
            )

        df = pd.read_csv(self.products_csv)
        items: list[PriceCatalogItem] = []
        latest: datetime | None = None

        for _, row in df.iterrows():
            package_quantity, package_unit = self._package_size_from_row(row)
            item = build_price_catalog_item(
                item_id=row.get("product_id") or row.get("barcode") or row.get("name"),
                name=row.get("name"),
                category_level_1=row.get("category_level_1"),
                category_level_2=row.get("category_level_2"),
                category_level_3=row.get("category_level_3"),
                category_level_4=row.get("category_level_4"),
                source="carrefour_egypt",
                source_id=row.get("source_provider_product_id") or row.get("barcode"),
                price=row.get("price"),
                currency="EGP",
                package_quantity=package_quantity,
                package_unit=package_unit,
                price_date=row.get("source_fetched_at"),
                geography="Egypt",
            )
            items.append(item)

            parsed_timestamp = self._parse_datetime(row.get("source_fetched_at"))
            if parsed_timestamp is not None and (latest is None or parsed_timestamp > latest):
                latest = parsed_timestamp

        self._catalog = items
        self._latest_source_fetched_at = latest
        self.matching_service.build_index(items)

    def _package_size_from_row(self, row: Any) -> tuple[float | None, str | None]:
        quantity = self._to_float(row.get("package_size_quantity"))
        unit = normalize_unit(row.get("package_size_unit"))
        if quantity is not None and unit in UNIT_TO_BASE:
            return quantity, unit

        name = str(row.get("name") or "")
        matches = list(PACKAGE_SIZE_RE.finditer(name))
        if not matches:
            return None, None

        match = matches[-1]
        qty = self._to_float(match.group("qty").replace(",", "."))
        parsed_unit = normalize_unit(match.group("unit"))
        if qty is None or parsed_unit not in UNIT_TO_BASE:
            return None, None
        return qty, parsed_unit

    def _estimate_cost(
        self,
        ingredient: Any,
        item: PriceCatalogItem | None,
    ) -> tuple[float | None, str | None]:
        if item is None:
            return None, "No matched price item."
        if item.price is None or item.price <= 0:
            return None, "Matched item has no usable price."
        if ingredient.quantity is None or ingredient.unit is None:
            return None, "Requested quantity or unit is missing."
        if item.package_quantity is None or item.package_unit is None:
            return None, "Matched item has no usable package size."

        requested_base = self._to_base_unit(ingredient.quantity, ingredient.unit)
        package_base = self._to_base_unit(item.package_quantity, item.package_unit)
        if requested_base is None:
            return None, "Requested unit could not be normalized."
        if package_base is None:
            return None, "Matched item package unit could not be normalized."

        requested_unit, requested_qty = requested_base
        package_unit, package_qty = package_base
        if requested_unit != package_unit:
            return None, "Requested unit is incompatible with matched package unit."
        if package_qty <= 0:
            return None, "Matched item package quantity is invalid."

        estimated = item.price * (requested_qty / package_qty)
        return estimated, None

    def _to_base_unit(self, quantity: float, unit: str) -> tuple[str, float] | None:
        normalized = normalize_unit(unit)
        if normalized not in UNIT_TO_BASE:
            return None
        base_unit, factor = UNIT_TO_BASE[normalized]
        return base_unit, quantity * factor

    def _find_recipe(self, recipe_id: str) -> dict[str, Any]:
        if not recipe_id.strip():
            raise ValueError("Recipe id is empty.")
        if not self.recipes_path.exists():
            raise FileNotFoundError(f"Recipe dataset not found: {self.recipes_path}")

        if self.recipes_path.suffix.lower() == ".jsonl":
            with self.recipes_path.open("r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue
                    recipe = json.loads(line)
                    if self._recipe_matches(recipe, recipe_id):
                        return recipe
        else:
            for recipe in load_recipes(self.recipes_path):
                if self._recipe_matches(recipe, recipe_id):
                    return recipe
        raise ValueError(f"Recipe not found: {recipe_id}")

    def _recipe_matches(self, recipe: dict[str, Any], requested_id: str) -> bool:
        query = requested_id.strip()
        query_without_prefix = query.removeprefix("recipe_")
        recipe_id = str(recipe.get("recipe_id") or "").strip()
        stable_slug = str(recipe.get("stable_slug") or "").strip()
        source_url = str(recipe.get("source_url") or "").strip()
        candidates = {
            recipe_id,
            f"recipe_{recipe_id}" if recipe_id else "",
            stable_slug,
            source_url,
        }
        return query in candidates or query_without_prefix in candidates

    def _scale_ingredient(self, ingredient: Any, scale: float) -> dict[str, Any]:
        if not isinstance(ingredient, dict):
            return {}
        if math.isclose(scale, 1.0):
            return dict(ingredient)

        scaled = dict(ingredient)
        for field_name in ("quantity", "amount"):
            value = self._to_float(scaled.get(field_name))
            if value is not None:
                scaled[field_name] = value * scale
        return scaled

    def _matched_payload(self, item: PriceCatalogItem | None) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "name": item.name,
            "source": item.source,
            "source_id": item.source_id,
            "price": item.price,
            "currency": item.currency,
            "package_quantity": item.package_quantity,
            "package_unit": item.package_unit,
            "price_date": item.price_date,
        }

    def _estimate_quality(
        self,
        *,
        ingredient_count: int,
        matched_count: int,
        confidence_scores: list[float],
    ) -> dict[str, Any]:
        if ingredient_count <= 0 or matched_count <= 0:
            return {"label": "low", "confidence": 0.0, "coverage": "unavailable"}

        average_confidence = sum(confidence_scores) / max(1, len(confidence_scores))
        coverage_ratio = matched_count / ingredient_count
        confidence = round(max(0.0, min(1.0, average_confidence * coverage_ratio)), 2)

        if confidence >= 0.85:
            label = "high"
        elif confidence >= 0.70:
            label = "medium"
        else:
            label = "low"

        coverage = "complete" if matched_count == ingredient_count else "partial"
        return {"label": label, "confidence": confidence, "coverage": coverage}

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _to_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            number = float(value)
            if math.isnan(number):
                return None
            return number
        try:
            return float(str(value).strip())
        except ValueError:
            return None
