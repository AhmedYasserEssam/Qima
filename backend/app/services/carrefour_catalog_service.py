from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.db import SessionLocal, init_db
from app.schemas.v1.barcode import (
    Allergen,
    AllergenSeverity,
    BarcodeLookupSuccess,
    DataCompleteness,
    DataQuality,
    Ingredient,
    Nutrition,
    NutritionBasis,
    NutritionFact,
    NutritionValues,
    Source,
    SourceProvider,
)


class CarrefourCatalogService:
    def __init__(self) -> None:
        self._db_initialized = False

    def lookup(self, barcode: str) -> BarcodeLookupSuccess | None:
        row = self._lookup_row_from_db(barcode)
        if row is None:
            return None
        return self._normalize_row(row, barcode)

    def _ensure_db_initialized(self) -> None:
        if self._db_initialized:
            return
        init_db()
        self._db_initialized = True

    def _lookup_row_from_db(self, barcode: str) -> dict[str, str] | None:
        self._ensure_db_initialized()
        with SessionLocal() as session:
            row = session.execute(
                text(
                    """
                    SELECT
                        barcode,
                        product_id,
                        name,
                        brand,
                        nutrition_basis,
                        serving_size,
                        energy_kcal,
                        protein_g,
                        carbohydrates_g,
                        fat_g,
                        sugars_g,
                        fiber_g,
                        sodium_mg,
                        salt_g,
                        ingredients,
                        allergens,
                        source_provider,
                        source_provider_product_id,
                        source_fetched_at,
                        data_quality_completeness,
                        price,
                        category_level_1,
                        category_level_2,
                        category_level_3,
                        category_level_4
                    FROM carrefour_barcode_products
                    WHERE barcode = :barcode
                    """
                ),
                {"barcode": barcode},
            ).mappings().first()

        if row is None:
            return None

        return {str(k): "" if v is None else str(v) for k, v in row.items()}

    def _normalize_row(self, row: dict[str, str], barcode: str) -> BarcodeLookupSuccess:
        basis = _to_basis(row.get("nutrition_basis"))
        values = NutritionValues(
            energy_kcal=_to_float(row.get("energy_kcal")),
            protein_g=_to_float(row.get("protein_g")),
            carbohydrates_g=_to_float(row.get("carbohydrates_g")),
            fat_g=_to_float(row.get("fat_g")),
            sugars_g=_to_float(row.get("sugars_g")),
            fiber_g=_to_float(row.get("fiber_g")),
            sodium_mg=_to_float(row.get("sodium_mg")),
            salt_g=_to_float(row.get("salt_g")),
        )

        ingredients = _parse_ingredients(row.get("ingredients"))
        allergens = _parse_allergens(row.get("allergens"))
        fetched_at = _parse_datetime(row.get("source_fetched_at"))
        completeness = (
            DataCompleteness.COMPLETE
            if str(row.get("data_quality_completeness") or "").strip().lower() == "complete"
            else DataCompleteness.PARTIAL
        )

        return BarcodeLookupSuccess(
            product_id=(row.get("product_id") or "").strip() or f"carrefour:{barcode}",
            name=(row.get("name") or "").strip() or f"Product {barcode}",
            brand=(row.get("brand") or "").strip() or None,
            nutrition=Nutrition(
                basis=basis,
                serving_size=(row.get("serving_size") or "").strip() or None,
                values=values,
                basis_label=_basis_label(basis),
                serving_label=_serving_label(row.get("serving_size")),
                facts=_nutrition_facts(values),
            ),
            ingredients=ingredients,
            allergens=allergens,
            source=Source(
                provider=SourceProvider.CARREFOUR_EGYPT,
                provider_product_id=(row.get("source_provider_product_id") or "").strip()
                or barcode,
                fetched_at=fetched_at,
            ),
            data_quality=DataQuality(completeness=completeness),
        )


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


def _to_basis(value: str | None) -> NutritionBasis:
    normalized = str(value or "").strip().lower()
    if normalized == NutritionBasis.PER_100ML.value:
        return NutritionBasis.PER_100ML
    if normalized == NutritionBasis.PER_SERVING.value:
        return NutritionBasis.PER_SERVING
    return NutritionBasis.PER_100G


def _basis_label(basis: NutritionBasis) -> str:
    if basis == NutritionBasis.PER_100ML:
        return "Per 100 ml"
    if basis == NutritionBasis.PER_SERVING:
        return "Per serving"
    return "Per 100 g"


def _serving_label(serving_size: str | None) -> str | None:
    cleaned = str(serving_size or "").strip()
    if not cleaned:
        return None
    return f"Serving size: {cleaned}"


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _parse_ingredients(raw: str | None) -> list[Ingredient]:
    items = _parse_json_list(raw)
    ingredients: list[Ingredient] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        normalized_text = str(item.get("normalized_text") or "").strip()
        if not text or not normalized_text:
            continue
        ingredients.append(
            Ingredient(
                text=text,
                normalized_text=normalized_text,
                is_allergen=bool(item.get("is_allergen")),
            )
        )
    return ingredients


def _parse_allergens(raw: str | None) -> list[Allergen]:
    items = _parse_json_list(raw)
    allergens: list[Allergen] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        source_text = str(item.get("source_text") or name).strip()
        severity_raw = str(item.get("severity") or "").strip().lower()
        if not name:
            continue

        severity = AllergenSeverity.UNKNOWN
        if severity_raw == AllergenSeverity.CONTAINS.value:
            severity = AllergenSeverity.CONTAINS
        elif severity_raw == AllergenSeverity.MAY_CONTAIN.value:
            severity = AllergenSeverity.MAY_CONTAIN

        allergens.append(
            Allergen(
                name=name,
                severity=severity,
                source_text=source_text or name,
            )
        )
    return allergens


def _parse_json_list(raw: str | None) -> list[Any]:
    cleaned = str(raw or "").strip()
    if not cleaned:
        return []
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _nutrition_facts(values: NutritionValues) -> list[NutritionFact]:
    raw_facts = [
        ("energy_kcal", "Energy", values.energy_kcal, "kcal", 0),
        ("protein_g", "Protein", values.protein_g, "g", 1),
        ("carbohydrates_g", "Carbohydrates", values.carbohydrates_g, "g", 1),
        ("fat_g", "Fat", values.fat_g, "g", 1),
        ("sugars_g", "Sugars", values.sugars_g, "g", 1),
        ("fiber_g", "Fiber", values.fiber_g, "g", 1),
        ("sodium_mg", "Sodium", values.sodium_mg, "mg", 0),
        ("salt_g", "Salt", values.salt_g, "g", 2),
    ]

    facts: list[NutritionFact] = []
    for key, label, value, unit, decimals in raw_facts:
        if value is None:
            continue
        facts.append(
            NutritionFact(
                key=key,
                label=label,
                value=value,
                unit=unit,
                display_value=f"{_fmt(value, decimals)} {unit}",
            )
        )
    return facts


def _fmt(value: float, decimals: int) -> str:
    rounded = round(value, decimals)
    if float(rounded).is_integer():
        return str(int(rounded))
    return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")


carrefour_catalog_service = CarrefourCatalogService()


def lookup_carrefour_product(barcode: str) -> BarcodeLookupSuccess | None:
    return carrefour_catalog_service.lookup(barcode)
