from datetime import UTC, datetime

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


def normalize_openfoodfacts_product(
    barcode: str,
    product: dict,
    *,
    fetched_at: datetime | None = None,
) -> BarcodeLookupSuccess:
    fetched_at = fetched_at or datetime.now(UTC)

    product_name = (
        product.get("product_name")
        or product.get("product_name_en")
        or product.get("generic_name")
        or f"Product {barcode}"
    )
    brand = _first_non_empty_token(product.get("brands"))

    ingredients = _normalize_ingredients(product)
    allergens = _normalize_allergens(product)

    allergen_names = {entry.name.lower() for entry in allergens}
    ingredients = [
        Ingredient(
            text=ingredient.text,
            normalized_text=ingredient.normalized_text,
            is_allergen=_ingredient_has_allergen(ingredient.normalized_text, allergen_names),
        )
        for ingredient in ingredients
    ]

    nutrition = _normalize_nutrition(product)

    has_core_nutrition = all(
        value is not None
        for value in [
            nutrition.values.energy_kcal,
            nutrition.values.protein_g,
            nutrition.values.carbohydrates_g,
            nutrition.values.fat_g,
        ]
    )
    completeness = (
        DataCompleteness.COMPLETE
        if has_core_nutrition and len(ingredients) > 0
        else DataCompleteness.PARTIAL
    )

    return BarcodeLookupSuccess(
        product_id=f"off:{barcode}",
        name=product_name.strip(),
        brand=brand,
        nutrition=nutrition,
        ingredients=ingredients,
        allergens=allergens,
        source=Source(
            provider=SourceProvider.OPEN_FOOD_FACTS,
            provider_product_id=str(product.get("code") or barcode),
            fetched_at=fetched_at,
        ),
        data_quality=DataQuality(completeness=completeness),
    )


def _normalize_nutrition(product: dict) -> Nutrition:
    nutriments = product.get("nutriments") or {}
    basis = _resolve_nutrition_basis(product)
    suffix = _basis_suffix(basis)

    sodium_key = f"sodium{suffix}"
    sodium_unit_key = f"sodium_unit{suffix}"
    sodium_value = _to_float(nutriments.get(sodium_key))
    sodium_unit = nutriments.get(sodium_unit_key) or nutriments.get("sodium_unit")

    values = NutritionValues(
        energy_kcal=_pick_float(
            nutriments,
            [f"energy-kcal{suffix}", "energy-kcal_100g", "energy-kcal_100ml"],
        ),
        protein_g=_pick_float(
            nutriments,
            [f"proteins{suffix}", "proteins_100g", "proteins_100ml"],
        ),
        carbohydrates_g=_pick_float(
            nutriments,
            [f"carbohydrates{suffix}", "carbohydrates_100g", "carbohydrates_100ml"],
        ),
        fat_g=_pick_float(nutriments, [f"fat{suffix}", "fat_100g", "fat_100ml"]),
        sugars_g=_pick_float(
            nutriments,
            [f"sugars{suffix}", "sugars_100g", "sugars_100ml"],
        ),
        fiber_g=_pick_float(
            nutriments,
            [f"fiber{suffix}", "fiber_100g", "fiber_100ml"],
        ),
        sodium_mg=_to_mg(sodium_value, sodium_unit),
        salt_g=_pick_float(nutriments, [f"salt{suffix}", "salt_100g", "salt_100ml"]),
    )

    return Nutrition(
        basis=basis,
        serving_size=product.get("serving_size"),
        values=values,
        basis_label=_nutrition_basis_label(basis),
        serving_label=_nutrition_serving_label(product.get("serving_size")),
        facts=_nutrition_facts(values),
    )


def _normalize_ingredients(product: dict) -> list[Ingredient]:
    ingredients: list[Ingredient] = []
    raw_ingredients = product.get("ingredients")
    if isinstance(raw_ingredients, list):
        for item in raw_ingredients:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or item.get("id") or "").strip()
            if not text:
                continue
            normalized = text.casefold().strip()
            ingredients.append(
                Ingredient(
                    text=text,
                    normalized_text=normalized,
                    is_allergen=False,
                )
            )

    if ingredients:
        return ingredients

    ingredients_text = (product.get("ingredients_text") or "").strip()
    if not ingredients_text:
        return []

    for chunk in ingredients_text.split(","):
        text = chunk.strip()
        if not text:
            continue
        ingredients.append(
            Ingredient(
                text=text,
                normalized_text=text.casefold(),
                is_allergen=False,
            )
        )
    return ingredients


def _normalize_allergens(product: dict) -> list[Allergen]:
    contains_tags = _extract_tag_names(product.get("allergens_tags"))
    traces_tags = _extract_tag_names(product.get("traces_tags"))

    allergens: list[Allergen] = []
    for name in sorted(contains_tags):
        allergens.append(
            Allergen(
                name=name,
                severity=AllergenSeverity.CONTAINS,
                source_text=name,
            )
        )

    for name in sorted(traces_tags - contains_tags):
        allergens.append(
            Allergen(
                name=name,
                severity=AllergenSeverity.MAY_CONTAIN,
                source_text=name,
            )
        )

    return allergens


def _extract_tag_names(raw_tags: object) -> set[str]:
    if not isinstance(raw_tags, list):
        return set()

    names: set[str] = set()
    for tag in raw_tags:
        if not isinstance(tag, str) or not tag.strip():
            continue
        _, _, tail = tag.partition(":")
        cleaned = (tail or tag).replace("-", " ").strip().casefold()
        if cleaned:
            names.add(cleaned)
    return names


def _resolve_nutrition_basis(product: dict) -> NutritionBasis:
    nutrition_data_per = str(product.get("nutrition_data_per") or "").strip().casefold()
    if nutrition_data_per == "100ml":
        return NutritionBasis.PER_100ML
    if nutrition_data_per == "serving":
        return NutritionBasis.PER_SERVING
    return NutritionBasis.PER_100G


def _nutrition_basis_label(basis: NutritionBasis) -> str:
    if basis == NutritionBasis.PER_100ML:
        return "Per 100 ml"
    if basis == NutritionBasis.PER_SERVING:
        return "Per serving"
    return "Per 100 g"


def _nutrition_serving_label(serving_size: object) -> str | None:
    if not isinstance(serving_size, str):
        return None
    cleaned = serving_size.strip()
    if not cleaned:
        return None
    return f"Serving size: {cleaned}"


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
        formatted = _format_nutrition_value(value, decimals=decimals)
        facts.append(
            NutritionFact(
                key=key,
                label=label,
                value=value,
                unit=unit,
                display_value=f"{formatted} {unit}",
            )
        )
    return facts


def _format_nutrition_value(value: float, *, decimals: int) -> str:
    rounded = round(value, decimals)
    if float(rounded).is_integer():
        return str(int(rounded))
    return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")


def _basis_suffix(basis: NutritionBasis) -> str:
    if basis == NutritionBasis.PER_100ML:
        return "_100ml"
    if basis == NutritionBasis.PER_SERVING:
        return "_serving"
    return "_100g"


def _pick_float(values: dict, keys: list[str]) -> float | None:
    for key in keys:
        value = _to_float(values.get(key))
        if value is not None:
            return value
    return None


def _to_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _to_mg(value: float | None, unit: object) -> float | None:
    if value is None:
        return None

    normalized_unit = str(unit or "").strip().casefold()
    if normalized_unit == "mg":
        return value
    if normalized_unit == "g" or normalized_unit == "":
        return value * 1000.0
    if normalized_unit == "ug":
        return value / 1000.0
    return value


def _ingredient_has_allergen(normalized_ingredient: str, allergen_names: set[str]) -> bool:
    return any(allergen in normalized_ingredient for allergen in allergen_names)


def _first_non_empty_token(value: object) -> str | None:
    if isinstance(value, str):
        for token in value.split(","):
            cleaned = token.strip()
            if cleaned:
                return cleaned
    return None
