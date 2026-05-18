from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


SAFE_STOPWORDS = {
    "premium",
    "offer",
    "offers",
    "pack",
    "package",
}

# Keep this map intentionally small and stable.
SYNONYM_MAP = {
    "bell pepper": "sweet pepper",
    "capsicum": "sweet pepper",
    "chicken fillet": "chicken breast",
    "chicken filet": "chicken breast",
    "yoghurt": "yogurt",
    "laban": "yogurt",
    "beef patty": "ground beef",
    "burger bun": "hamburger bun",
    "burger buns": "hamburger bun",
    "hamburger buns": "hamburger bun",
    "rolls": "roll",
    "bread rolls": "roll",
    "bread roll": "roll",
    "breadcrumbs": "bread crumb",
    "Ø±Ø²": "rice",
    "Ø¯Ø¬Ø§Ø¬": "chicken",
    "Ø®Ø¨Ø²": "bread",
    "Ù„Ø¨Ù†": "milk",
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
    "ground": "ground",
    "powder": "powder",
    "powdered": "powder",
    "stock": "stock",
    "cube": "cube",
    "cubes": "cube",
    "fresh": "fresh",
    "whole": "whole",
    "smoked": "smoked",
    "low-fat": "low_fat",
    "lowfat": "low_fat",
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

COUNT_UNITS = {
    "teaspoon",
    "teaspoons",
    "tsp",
    "tablespoon",
    "tablespoons",
    "tbsp",
    "cup",
    "cups",
    "ounce",
    "ounces",
    "oz",
    "pound",
    "pounds",
    "lb",
    "lbs",
    "gram",
    "grams",
    "g",
    "gm",
    "kg",
    "kilogram",
    "kilograms",
    "mg",
    "milligram",
    "milligrams",
    "ml",
    "milliliter",
    "milliliters",
    "l",
    "liter",
    "liters",
    "litre",
    "litres",
    "can",
    "cans",
    "jar",
    "jars",
    "packet",
    "packets",
    "package",
    "packages",
    "pack",
    "packs",
    "piece",
    "pieces",
    "pc",
    "pcs",
    "clove",
    "cloves",
    "slice",
    "slices",
    "head",
    "heads",
    "bunch",
    "bunches",
}

PREPARATION_WORDS = {
    "chopped",
    "diced",
    "minced",
    "sliced",
    "shredded",
    "split",
    "peeled",
    "seeded",
    "crushed",
    "cubed",
    "drained",
    "rinsed",
    "washed",
    "trimmed",
    "softened",
    "melted",
    "grated",
    "beaten",
    "deveined",
    "lean",
    "julienned",
    "chilled",
    "finely",
    "coarsely",
    "roughly",
    "thinly",
    "thickly",
    "toasted",
}

MEANINGFUL_FORM_WORDS = {
    "ground",
    "powdered",
    "powder",
    "smoked",
    "fresh",
    "whole",
    "low-fat",
    "lowfat",
}

TRAILING_NOTE_RE = re.compile(
    r"\b(to taste|for garnish|for serving|as needed|if desired|optional)\b"
)
FRACTION_RE = re.compile(r"^\d+\s*/\s*\d+$")
MIXED_FRACTION_RE = re.compile(r"^\d+\s+\d+\s*/\s*\d+$")


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
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = re.sub(r"[^0-9a-zA-Z\u0600-\u06FF\s\-]+", " ", text)
    return _clean_spaces(text)


def _apply_synonyms(text: str) -> str:
    normalized = f" {text} "
    for source, target in sorted(
        SYNONYM_MAP.items(), key=lambda item: len(item[0]), reverse=True
    ):
        pattern = rf"(?<!\S){re.escape(source)}(?!\S)"
        normalized = re.sub(pattern, target, normalized)
    return _clean_spaces(normalized)


def _remove_parenthetical(text: str) -> str:
    return _clean_spaces(re.sub(r"\([^)]*\)", " ", text))


def _strip_trailing_notes(text: str) -> str:
    match = TRAILING_NOTE_RE.search(text)
    if not match:
        return text
    return _clean_spaces(text[: match.start()])


def _looks_numeric(token: str) -> bool:
    compact = token.replace(",", "").strip()
    if not compact:
        return False
    if compact.replace(".", "", 1).isdigit():
        return True
    if FRACTION_RE.match(compact):
        return True
    if MIXED_FRACTION_RE.match(compact):
        return True
    return False


def _singularize_simple(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("oes") and len(token) > 4:
        return token[:-2]
    if token.endswith("ses") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _normalize_tokens(text: str) -> list[str]:
    tokens = text.split()
    normalized: list[str] = []
    skip_next = False
    for idx, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue

        if token in SAFE_STOPWORDS:
            continue
        if _looks_numeric(token):
            if idx + 1 < len(tokens) and tokens[idx + 1] in COUNT_UNITS:
                skip_next = True
            continue
        if token in COUNT_UNITS:
            continue
        if token in PREPARATION_WORDS and token not in MEANINGFUL_FORM_WORDS:
            continue

        cleaned = token.strip("-")
        if not cleaned:
            continue
        normalized.append(_singularize_simple(cleaned))
    return normalized


def normalize_name(name: str) -> str:
    text = normalize_text(name or "")
    if not text:
        return ""

    if text.startswith("[") and text.endswith("]"):
        try:
            loaded = json.loads(text)
            if isinstance(loaded, list):
                joined = " ".join(str(item) for item in loaded)
                text = normalize_text(joined)
        except Exception:
            pass

    text = _remove_parenthetical(text)
    text = _strip_trailing_notes(text)
    if "," in text:
        text = _clean_spaces(text.split(",", 1)[0])

    tokens = _normalize_tokens(text)
    text = _clean_spaces(" ".join(tokens))
    if not text:
        return ""
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
    if "low fat" in text:
        tags.add("low_fat")
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
