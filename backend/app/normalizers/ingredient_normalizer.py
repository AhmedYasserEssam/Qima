from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SAFE_STOPWORDS = {
    "fresh",
    "premium",
    "offer",
    "offers",
    "pack",
    "package",
}

SYNONYM_MAP = {
    "ground beef": "minced beef",
    "bell pepper": "sweet pepper",
    "capsicum": "sweet pepper",
    "chicken fillet": "chicken breast",
    "chicken filet": "chicken breast",
    "yoghurt": "yogurt",
    "laban": "yogurt",
    "رز": "rice",
    "دجاج": "chicken",
    "خبز": "bread",
    "لبن": "milk",
}

UNIT_ALIASES = {
    "gram": "g",
    "grams": "g",
    "gm": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "milliliter": "ml",
    "milliliters": "ml",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "piece": "piece",
    "pieces": "piece",
    "pc": "piece",
    "pcs": "piece",
    "pack": "pack",
    "packet": "pack",
    "packets": "pack",
    "package": "pack",
    "packages": "pack",
}

FORM_TAGS = {
    "powder": "powder",
    "stock": "stock",
    "cube": "cube",
    "cubes": "cube",
    "chocolate": "chocolate",
    "pudding": "dessert",
    "curry": "prepared",
    "flavor": "flavored",
    "flavoured": "flavored",
    "mix": "processed",
    "seasoning": "processed",
    "instant": "processed",
    "sauce": "processed",
}


@dataclass(frozen=True)
class NormalizedIngredient:
    original_name: str
    normalized_name: str
    canonical_name: str
    quantity: float | None
    unit: str | None
    tokens: tuple[str, ...]
    form_tags: frozenset[str]


def _clean_spaces(text: str) -> str:
    return " ".join(text.split())


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^0-9a-zA-Z\u0600-\u06FF\s]+", " ", text)
    return _clean_spaces(text)


def _apply_synonyms(text: str) -> str:
    normalized = f" {text} "
    for source, target in sorted(SYNONYM_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"(?<!\S){re.escape(source)}(?!\S)"
        normalized = re.sub(pattern, target, normalized)
    return _clean_spaces(normalized)


def normalize_name(name: str) -> str:
    text = normalize_text(name)
    if not text:
        return ""

    words = [word for word in text.split() if word not in SAFE_STOPWORDS]
    text = _clean_spaces(" ".join(words))
    return _apply_synonyms(text)


def normalize_unit(unit: Any) -> str | None:
    if unit is None:
        return None
    text = normalize_text(unit).replace(".", "")
    if not text:
        return None
    return UNIT_ALIASES.get(text, text)


def parse_quantity(value: Any) -> float | None:
    if value is None:
        return None
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        return None
    return quantity if quantity >= 0 else None


def extract_form_tags(text: str) -> frozenset[str]:
    tags = {FORM_TAGS[token] for token in text.split() if token in FORM_TAGS}
    return frozenset(tags)


def normalize_ingredient(ingredient: dict[str, Any]) -> NormalizedIngredient:
    raw_name = str(
        ingredient.get("name")
        or ingredient.get("item")
        or ingredient.get("name_normalized")
        or ingredient.get("canonical_ingredient_id")
        or ingredient.get("raw")
        or ""
    ).strip()
    quantity = parse_quantity(ingredient.get("quantity", ingredient.get("amount")))
    unit = normalize_unit(ingredient.get("unit"))

    normalized = normalize_name(raw_name)
    canonical = normalize_name(_apply_synonyms(normalized))

    return NormalizedIngredient(
        original_name=raw_name,
        normalized_name=normalized,
        canonical_name=canonical,
        quantity=quantity,
        unit=unit,
        tokens=tuple(canonical.split()),
        form_tags=extract_form_tags(canonical),
    )
