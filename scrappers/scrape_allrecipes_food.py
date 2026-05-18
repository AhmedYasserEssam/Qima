from __future__ import annotations

import argparse
import json
import logging
import random
import re
import runpy
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse, urlunparse

try:
    from scrapling.fetchers import FetcherSession
except ImportError:  # pragma: no cover
    FetcherSession = None  # type: ignore[assignment]


SOURCE = "allrecipes"
SOURCE_NAME = "Allrecipes"
ROBOTS_URL = "https://www.allrecipes.com/robots.txt"
SITEMAP_INDEX_URL = "https://www.allrecipes.com/sitemap.xml"
DEFAULT_OUTPUT = Path("data/Recipes/allrecipes_recipes.jsonl")
DEFAULT_CSV_OUTPUT = Path("data/Recipes/allrecipes_recipes.csv")

SCRIPT_JSONLD_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    flags=re.IGNORECASE | re.DOTALL,
)
NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

QUANTITY_RE = re.compile(
    r"^\s*(?P<q>(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)(?:\s*(?:to|-)\s*(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?))?)\s+(?P<rest>.+)$",
    flags=re.IGNORECASE,
)
PACKAGE_SIZE_RE = re.compile(
    r"\((?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]+(?:\s+[a-zA-Z]+)?)\)",
    flags=re.IGNORECASE,
)

TEMP_RANGE_WITH_PAREN_RE = re.compile(
    r"\b\d+\s*(?:to|-)\s*\d+\s*(?:degrees?\s*)?(?:\u00b0\s*)?[Ff]\s*\(\s*\d+\s*(?:to|-)\s*\d+\s*(?:degrees?\s*)?(?:\u00b0\s*)?[Cc]\s*\)"
    r"|\b\d+\s*(?:to|-)\s*\d+\s*(?:degrees?\s*)?(?:\u00b0\s*)?[Cc]\s*\(\s*\d+\s*(?:to|-)\s*\d+\s*(?:degrees?\s*)?(?:\u00b0\s*)?[Ff]\s*\)",
)
TEMP_SINGLE_WITH_PAREN_RE = re.compile(
    r"\b\d+\s*(?:degrees?\s*)?(?:\u00b0\s*)?[Ff]\s*\(\s*\d+\s*(?:degrees?\s*)?(?:\u00b0\s*)?[Cc]\s*\)"
    r"|\b\d+\s*(?:degrees?\s*)?(?:\u00b0\s*)?[Cc]\s*\(\s*\d+\s*(?:degrees?\s*)?(?:\u00b0\s*)?[Ff]\s*\)",
)
TEMP_RANGE_SIMPLE_RE = re.compile(
    r"\b\d+\s*(?:to|-)\s*\d+\s*(?:degrees?\s*|\u00b0\s*)[Ff]\b"
    r"|\b\d+\s*(?:to|-)\s*\d+\s*(?:degrees?\s*|\u00b0\s*)[Cc]\b",
)
TEMP_SINGLE_SIMPLE_RE = re.compile(
    r"\b\d+\s*(?:degrees?\s*|\u00b0\s*)[Ff]\b|\b\d+\s*(?:degrees?\s*|\u00b0\s*)[Cc]\b",
)

HEAT_DESCRIPTOR_RE = re.compile(
    r"\bmedium(?:-high|-low)?\s+heat\b|\blow\s+heat\b|\bhigh\s+heat\b|\brefrigerator\b|\bfridge\b|\bfreezer\b",
    flags=re.IGNORECASE,
)

DURATION_RE = re.compile(
    r"(?:about|around|at least|at most|for)?\s*"
    r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
    r"(?:\s*(?:to|-)\s*(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?))?\s*"
    r"(?:seconds?|minutes?|hours?|days?)(?:\s+per\s+side)?"
    r"|\bovernight\b",
    flags=re.IGNORECASE,
)

SMOKING_CONTEXT_RE = re.compile(
    r"\b(smoke at|smoke for|smoker|outdoor smoker|place in smoker|smoked in)\b",
    flags=re.IGNORECASE,
)
EXPLICIT_GRILL_ACTION_RE = re.compile(
    r"\bgrill(?:ed|ing)?\b(?:\s+\w+){0,4}",
    flags=re.IGNORECASE,
)

STEP_EQUIPMENT_PATTERNS: list[tuple[str, str]] = [
    ("instant-read thermometer", "instant-read thermometer"),
    ("heavy deep skillet", "heavy deep skillet"),
    ("9x13 inch baking dish", "9x13 inch baking dish"),
    ("outdoor smoker", "outdoor smoker"),
    ("resealable plastic bag", "resealable plastic bag"),
    ("nonstick skillet", "nonstick skillet"),
    ("frying pan", "frying pan"),
    ("deep skillet", "deep skillet"),
    ("deep fryer", "deep fryer"),
    ("roasting rack", "roasting rack"),
    ("parchment paper", "parchment paper"),
    ("cutting board", "cutting board"),
    ("pizza cutter", "pizza cutter"),
    ("food processor", "food processor"),
    ("cookie sheet", "cookie sheet"),
    ("baking sheets", "baking sheets"),
    ("baking sheet", "baking sheet"),
    ("baking dish", "baking dish"),
    ("wire rack", "wire rack"),
    ("jar holder", "jar holder"),
    ("paper towels", "paper towels"),
    ("shallow dish", "shallow dish"),
    ("grill grate", "grill grate"),
    ("large saucepan", "large saucepan"),
    ("large stockpot", "stockpot"),
    ("large pot", "large pot"),
    ("saucepan", "saucepan"),
    ("stockpot", "stockpot"),
    ("loaf pan", "loaf pan"),
    ("tube pan", "tube pan"),
    ("blender", "blender"),
    ("skillet", "skillet"),
    ("smoker", "smoker"),
    ("freezer", "freezer"),
    ("fridge", "refrigerator"),
    ("refrigerator", "refrigerator"),
    ("thermometer", "thermometer"),
    ("wax paper", "wax paper"),
    ("plate", "plate"),
    ("grill", "grill"),
    ("jars", "jars"),
    ("lids", "lids"),
    ("rings", "rings"),
    ("oven", "oven"),
    ("bowl", "bowl"),
]

UNIT_ALIASES = {
    "teaspoon": "teaspoon",
    "teaspoons": "teaspoon",
    "tsp": "teaspoon",
    "tablespoon": "tablespoon",
    "tablespoons": "tablespoon",
    "tbsp": "tablespoon",
    "cup": "cup",
    "cups": "cup",
    "ounce": "ounce",
    "ounces": "ounce",
    "oz": "ounce",
    "pound": "pound",
    "pounds": "pound",
    "lb": "pound",
    "lbs": "pound",
    "gram": "gram",
    "grams": "gram",
    "g": "gram",
    "kg": "kilogram",
    "kilogram": "kilogram",
    "kilograms": "kilogram",
    "ml": "milliliter",
    "milliliter": "milliliter",
    "milliliters": "milliliter",
    "l": "liter",
    "liter": "liter",
    "liters": "liter",
    "pinch": "pinch",
    "pinches": "pinch",
    "dash": "dash",
    "dashes": "dash",
    "clove": "clove",
    "cloves": "clove",
    "slice": "slice",
    "slices": "slice",
    "can": "can",
    "cans": "can",
    "package": "package",
    "packages": "package",
    "box": "box",
    "boxes": "box",
    "packet": "packet",
    "packets": "packet",
    "envelope": "envelope",
    "envelopes": "envelope",
    "jar": "jar",
    "jars": "jar",
    "piece": "piece",
    "pieces": "piece",
    "inch": "inch",
    "inches": "inch",
    "head": "head",
    "heads": "head",
    "bunch": "bunch",
    "bunches": "bunch",
    "quart": "quart",
    "quarts": "quart",
}

ALLERGEN_TAXONOMY = [
    "milk",
    "egg",
    "fish",
    "crustacean_shellfish",
    "tree_nuts",
    "peanuts",
    "wheat_gluten",
    "soy",
    "sesame",
    "mustard",
]

ALLERGEN_RULES = {
    "milk": ["milk", "buttermilk", "butter", "cream", "cheese", "yogurt", "whey", "casein", "ranch"],
    "egg": ["egg", "eggs", "albumen", "mayonnaise"],
    "fish": ["fish", "anchovy", "sardine", "salmon", "tuna", "cod"],
    "crustacean_shellfish": ["shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster", "scallop"],
    "tree_nuts": ["almond", "walnut", "pecan", "cashew", "pistachio", "hazelnut"],
    "peanuts": ["peanut", "groundnut"],
    "wheat_gluten": ["wheat", "gluten", "all-purpose flour", "flour", "breadcrumbs", "bread", "pasta", "wrapper", "tortilla"],
    "soy": ["soy", "soya", "tofu", "edamame", "miso", "tempeh", "soy sauce"],
    "sesame": ["sesame", "tahini", "sesame oil", "sesame seeds"],
    "mustard": ["mustard"],
}

POSSIBLE_ALLERGEN_RULES = {
    "fish": ["seafood seasoning"],
    "crustacean_shellfish": ["seafood seasoning"],
}

EXPLICIT_ALLERGEN_EVIDENCE: dict[str, list[str]] = {
    "milk": ["milk", "buttermilk", "butter", "cheese", "cream", "yogurt", "whey", "casein"],
    "egg": ["egg", "eggs", "albumen", "mayonnaise"],
    "fish": ["fish", "anchovy", "sardine", "salmon", "tuna", "cod"],
    "crustacean_shellfish": ["shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster", "scallop"],
    "tree_nuts": ["almond", "walnut", "pecan", "cashew", "pistachio", "hazelnut"],
    "peanuts": ["peanut", "groundnut"],
    "wheat_gluten": ["wheat", "gluten", "flour", "bread", "pasta", "wrapper", "tortilla"],
    "soy": ["soy", "soya", "tofu", "edamame", "miso", "tempeh", "soy sauce"],
    "sesame": ["sesame", "tahini"],
    "mustard": ["mustard"],
}

INGREDIENT_ID_ALIASES = {
    "all-purpose flour": "flour_all_purpose",
    "ground beef": "beef_ground",
    "prepared yellow mustard": "mustard_yellow",
    "yellow mustard": "mustard_yellow",
}

DESCRIPTOR_WORDS = {
    "skinless",
    "boneless",
    "fresh",
    "large",
    "small",
    "medium",
    "peeled",
    "seeded",
    "shredded",
    "chopped",
    "minced",
    "sliced",
    "diced",
    "crushed",
    "ground",
    "packed",
    "chilled",
    "unsalted",
    "reduced-fat",
    "refrigerated",
    "toasted",
    "cooked",
    "raw",
    "lean",
    "finely",
    "coarsely",
    "roughly",
    "thinly",
    "freshly",
    "trimmed",
    "deveined",
    "softened",
    "melted",
}
STYLE_WORDS = {"diced", "chopped", "crushed", "stewed"}
STRUCTURAL_WORDS = {"and", "or", "of", "the", "a", "an", "into", "in", "with", "for", "to"}
CONTAINER_WORDS = {"piece", "pieces", "packet", "envelope", "box", "can", "jar", "package", "bunch", "head"}

MEAT_TERMS = [
    "beef",
    "pork",
    "lamb",
    "veal",
    "bacon",
    "ham",
    "sausage",
    "ground sausage",
    "tenderloin",
    "steak",
    "roast",
    "meat",
]
POULTRY_TERMS = ["chicken", "turkey", "duck"]
SEAFOOD_TERMS = [
    "shrimp",
    "crab",
    "lobster",
    "fish",
    "salmon",
    "tuna",
    "cod",
    "anchovy",
    "clam",
    "mussel",
    "oyster",
    "scallop",
]

SEASONING_KEYWORDS = [
    "salt",
    "pepper",
    "oregano",
    "basil",
    "cumin",
    "seasoning",
    "spice",
    "paprika",
    "cayenne",
    "chile powder",
    "chili powder",
    "garlic powder",
    "onion powder",
    "red pepper flakes",
    "lime juice",
    "lemon juice",
    "vinegar",
    "vanilla extract",
    "thyme",
    "brown sugar",
    "sugar",
    "garlic",
    "ginger",
]
MAIN_KEYWORDS = [
    "beans",
    "lentils",
    "chickpeas",
    "tomatoes",
    "tomato sauce",
    "rice",
    "grits",
    "pasta",
    "ground beef",
    "ground turkey",
    "ground sausage",
    "pork butt roast",
    "chicken breast",
    "shrimp",
    "lamb",
    "beef",
    "sausage",
]
MAIN_VEG_KEYWORDS = [
    "zucchini",
    "cabbage",
    "carrot",
    "kale",
    "onion",
    "bell pepper",
    "mushroom",
    "potato",
    "squash",
    "corn",
]
AROMATIC_KEYWORDS = ["onion", "garlic", "celery", "bell pepper", "shallot", "green onion", "scallion"]
LIQUID_KEYWORDS = ["water", "milk", "buttermilk", "broth", "stock", "beer", "wine", "juice"]
FAT_KEYWORDS = ["oil", "butter", "ghee", "shortening"]
COATING_KEYWORDS = ["flour", "cornmeal", "breadcrumbs", "panko", "batter"]
SAUCE_KEYWORDS = ["dressing", "sauce", "ketchup", "mustard", "mayonnaise", "mayo", "paste"]
GARNISH_KEYWORDS = ["parsley", "cilantro", "chives", "mint", "for garnish"]
LEAVENING_KEYWORDS = ["baking soda", "baking powder", "yeast"]
THICKENER_KEYWORDS = ["cornstarch"]
SWEETENER_KEYWORDS = ["sugar", "brown sugar", "powdered sugar", "confectioners sugar", "honey", "syrup"]
WRAPPER_KEYWORDS = ["tortilla", "wonton wrapper", "wonton wrappers", "bread", "crescent roll", "dinner roll"]
BASE_KEYWORDS = ["cake mix", "cookie mix", "brownie mix", "crescent roll", "dough"]
BINDER_KEYWORDS = ["egg", "eggs", "flax", "oats"]
FILLING_KEYWORDS = ["cheese", "cream cheese", "ricotta", "mozzarella", "cheddar"]

PACKAGED_PATTERN_TO_ALLERGENS: list[tuple[list[str], list[str]]] = [
    (["crescent roll", "dinner roll"], ["wheat_gluten", "milk", "soy"]),
    (["tortilla", "wonton wrapper", "bread", "pasta"], ["wheat_gluten"]),
    (["chocolate chips", "hot chocolate mix", "instant hot chocolate mix"], ["milk", "soy"]),
    (["cake mix", "cookie mix", "brownie mix", "boxed mix"], ["wheat_gluten", "milk", "egg", "soy"]),
    (["ranch dressing"], ["milk", "egg"]),
    (["worcestershire sauce"], ["fish"]),
    (["curry paste", "seasoning packet", "sazon seasoning", "fajita seasoning"], ["wheat_gluten", "soy", "sesame"]),
    (["canned soup", "tomato soup", "cream soup"], ["wheat_gluten", "milk", "soy"]),
    (["jell-o", "gelatin mix"], []),
]

PACKAGED_TRIGGER_TERMS = [
    "crescent roll",
    "dinner roll",
    "cake mix",
    "cookie mix",
    "brownie mix",
    "hot chocolate mix",
    "chocolate chips",
    "instant hot chocolate mix",
    "jell-o",
    "gelatin mix",
    "ranch dressing",
    "worcestershire sauce",
    "fajita seasoning",
    "seasoning packet",
    "sazon seasoning",
    "curry paste",
    "barbeque sauce",
    "barbecue sauce",
    "canned soup",
    "tomato soup",
    "cream soup",
    "boxed mix",
    "bottled sauce",
    "dressing",
]

FRACTION_REPLACEMENTS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}


@dataclass(frozen=True)
class RecipeUrl:
    url: str
    lastmod: str | None = None


def _normalize_text_artifacts(text: str) -> str:
    out = text
    replacements = {
        "Â°": "°",
        "Ã‚Â°": "°",
        "â„¢": "™",
        "Ã¢â€žÂ¢": "™",
    }
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    return out


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return _normalize_text_artifacts(unescape(" ".join(str(value).replace("\xa0", " ").split())))


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def extract_jsonld_objects(html: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for raw in SCRIPT_JSONLD_RE.findall(html):
        parsed = parse_json(raw.strip())
        if parsed is None:
            continue
        stack: list[Any] = [parsed]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                objects.append(item)
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
                for value in item.values():
                    if isinstance(value, list):
                        stack.extend(value)
                    elif isinstance(value, dict):
                        stack.append(value)
            elif isinstance(item, list):
                stack.extend(item)
    return objects


def has_recipe_type(type_value: Any) -> bool:
    normalized = {clean_text(t).lower() for t in as_list(type_value)}
    return "recipe" in normalized


def find_recipe_object(objects: list[dict[str, Any]]) -> dict[str, Any] | None:
    for obj in objects:
        if has_recipe_type(obj.get("@type")):
            return obj
    return None


def parse_iso_duration_to_minutes(value: Any) -> int | None:
    text = clean_text(value).upper()
    if not text:
        return None
    match = re.fullmatch(r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?", text)
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    return days * 24 * 60 + hours * 60 + minutes


def parse_numeric(value: Any) -> float | None:
    match = NUMBER_RE.search(clean_text(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def parse_nutrition_number(value: Any, expected: str) -> float | None:
    number = parse_numeric(value)
    if number is None:
        return None
    text = clean_text(value).lower()
    if expected == "mg":
        if " g" in f" {text}":
            return number * 1000
        return number
    if expected == "g":
        if "mg" in text:
            return number / 1000
        return number
    return number


def recipe_id_and_slug(url: str) -> tuple[str | None, str | None]:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) < 2 or parts[0].lower() != "recipe":
        return None, None
    recipe_id = clean_text(parts[1]) or None
    slug = clean_text(parts[2]) if len(parts) > 2 else None
    return recipe_id, slug or None


def canonicalize_recipe_url(url: str) -> str:
    parsed = urlparse(clean_text(url))
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", ""))


def recipe_unique_key(url: str, recipe_id: str | None) -> str:
    return f"id:{recipe_id}" if recipe_id else f"url:{canonicalize_recipe_url(url)}"


def normalize_fraction_text(text: str) -> str:
    out = text
    for src, dst in FRACTION_REPLACEMENTS.items():
        out = out.replace(src, dst)
    return out


def _slugify(text: str) -> str:
    lowered = clean_text(text).lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    return lowered.strip("_")


def _normalize_unit(token: str) -> str | None:
    return UNIT_ALIASES.get(token.lower().strip(".,;:"))


def _parse_quantity_token(token: str) -> float | str | None:
    token = clean_text(token)
    if not token:
        return None
    if " to " in token or "-" in token:
        range_match = re.fullmatch(r"(.+?)\s*(?:to|-)\s*(.+)", token, flags=re.IGNORECASE)
        if range_match:
            left = _parse_quantity_token(range_match.group(1))
            right = _parse_quantity_token(range_match.group(2))
            if left is not None and right is not None:
                return f"{left}-{right}"
    mixed_match = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", token)
    if mixed_match:
        whole = float(mixed_match.group(1))
        num = float(mixed_match.group(2))
        den = float(mixed_match.group(3))
        if den == 0:
            return None
        return whole + (num / den)
    frac_match = re.fullmatch(r"(\d+)/(\d+)", token)
    if frac_match:
        num = float(frac_match.group(1))
        den = float(frac_match.group(2))
        if den == 0:
            return None
        return num / den
    try:
        return float(token)
    except ValueError:
        return None


def _extract_package_size(text: str) -> tuple[dict[str, Any] | None, str]:
    match = PACKAGE_SIZE_RE.search(text)
    if not match:
        return None, text
    qty = parse_numeric(match.group("qty"))
    unit = _normalize_unit(match.group("unit"))
    if qty is None or not unit:
        return None, text
    quantity_value: int | float = int(qty) if float(qty).is_integer() else qty
    stripped = (text[: match.start()] + " " + text[match.end() :]).strip()
    return {"quantity": quantity_value, "unit": unit}, re.sub(r"\s+", " ", stripped)


def _tokenize_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'-]*", clean_text(text).lower())


def _is_descriptor_only_phrase(text: str) -> bool:
    tokens = _tokenize_words(text)
    if not tokens:
        return True
    meaningful = [t for t in tokens if t not in DESCRIPTOR_WORDS and t not in STRUCTURAL_WORDS]
    return not meaningful


def _extract_name_and_notes(text: str) -> tuple[str, str | None]:
    working = clean_text(text)
    notes_parts: list[str] = []
    if "," in working:
        parts = [clean_text(part) for part in working.split(",") if clean_text(part)]
        if len(parts) >= 2:
            candidate_name = clean_text(", ".join(parts[:-1]))
            last_part = parts[-1]
            prep_markers = [
                "chopped",
                "sliced",
                "diced",
                "minced",
                "cut",
                "divided",
                "drained",
                "peeled",
                "seeded",
                "shredded",
                "coarsely",
                "roughly",
                "finely",
                "thinly",
                "softened",
                "melted",
                "trimmed",
                "undrained",
                "rinsed",
                "deveined",
            ]
            if not _is_descriptor_only_phrase(candidate_name) and any(marker in last_part.lower() for marker in prep_markers):
                notes_parts.append(last_part)
                working = candidate_name
            else:
                left, right = working.split(",", 1)
                if not _is_descriptor_only_phrase(left):
                    right_text = clean_text(right)
                    if right_text:
                        notes_parts.append(right_text)
                    working = clean_text(left)
    for pattern in [
        r"\bfor frying\b",
        r"\bfor garnish\b",
        r"\bfor dusting\b",
        r"\bto taste\b",
        r"\bsuch as .+$",
        r"\bdivided\b",
    ]:
        match = re.search(pattern, working, flags=re.IGNORECASE)
        if not match:
            continue
        note = clean_text(match.group(0))
        if note:
            notes_parts.append(note)
        working = clean_text(working[: match.start()] + " " + working[match.end() :])
    notes = "; ".join(unique_preserve_order(notes_parts)) if notes_parts else None
    return working, notes


def _extract_secondary_unit(working: str, unit: str | None) -> tuple[str, str | None]:
    if unit:
        return working, unit
    tokens = working.split()
    for idx, token in enumerate(tokens[:3]):
        maybe = _normalize_unit(token)
        if maybe:
            unit = maybe
            del tokens[idx]
            return clean_text(" ".join(tokens)), unit
    return working, unit


def _normalize_combined_seasoning_name(text: str) -> str | None:
    lowered = clean_text(text).lower()
    if "salt" not in lowered or "pepper" not in lowered or " and " not in lowered:
        return None
    if "black pepper" in lowered:
        if "freshly" in lowered and "ground" in lowered:
            return "salt and freshly ground black pepper"
        if "ground" in lowered:
            return "salt and ground black pepper"
        return "salt and black pepper"
    return "salt and pepper"


def normalize_ingredient_name(name_part: str) -> tuple[str, list[str]]:
    text = clean_text(name_part).lower()
    combined = _normalize_combined_seasoning_name(text)
    if combined:
        return combined, []
    tokens = _tokenize_words(text)
    modifiers: list[str] = []
    core: list[str] = []

    for token in tokens:
        token_clean = token.strip(".,;:()")
        if not token_clean:
            continue
        if token_clean in DESCRIPTOR_WORDS:
            modifiers.append(token_clean)
            continue
        if token_clean in STRUCTURAL_WORDS or token_clean in CONTAINER_WORDS:
            continue
        if token_clean in UNIT_ALIASES:
            continue
        core.append(token_clean)

    if not core:
        fallback_tokens = [t for t in tokens if t not in STRUCTURAL_WORDS]
        core = fallback_tokens[-2:] if len(fallback_tokens) >= 2 else fallback_tokens

    if ("tomato" in core or "tomatoes" in core) and any(style in modifiers for style in STYLE_WORDS):
        style = next(style for style in modifiers if style in STYLE_WORDS)
        core = [style] + [t for t in core if t != style]
        modifiers = [m for m in modifiers if m != style]

    if core[:2] == ["cloves", "garlic"] or core[:2] == ["clove", "garlic"]:
        core = ["garlic"]

    if len(core) > 1 and core[0] in {"finely", "coarsely", "roughly", "thinly", "freshly"}:
        core = core[1:]

    normalized = clean_text(" ".join(core))
    if not normalized or _is_descriptor_only_phrase(normalized):
        normalized = clean_text(name_part).lower()
    return normalized, unique_preserve_order(modifiers)


def infer_canonical_id(name_normalized: str) -> str:
    alias = INGREDIENT_ID_ALIASES.get(name_normalized)
    if alias:
        return alias
    return _slugify(name_normalized)


def _infer_packaged_label_info(ingredient_text: str) -> tuple[bool, list[str]]:
    text = ingredient_text.lower()
    requires_label_check = any(term in text for term in PACKAGED_TRIGGER_TERMS)
    possible_allergens: list[str] = []
    for patterns, allergens in PACKAGED_PATTERN_TO_ALLERGENS:
        if any(pattern in text for pattern in patterns):
            requires_label_check = True
            possible_allergens.extend(allergens)
    return requires_label_check, unique_preserve_order(possible_allergens)


def parse_ingredient(raw: Any) -> dict[str, Any]:
    raw_text = clean_text(raw)
    if not raw_text:
        return {
            "raw": "",
            "name_normalized": "",
            "canonical_ingredient_id": "",
            "quantity": None,
            "unit": None,
            "package_size": None,
            "notes": None,
            "modifiers": [],
            "ingredient_role": "unknown",
            "confidence": "low",
            "requires_label_check": False,
            "ingredient_requires_label_check": False,
            "possible_allergens": [],
        }

    text = normalize_fraction_text(raw_text)
    working = text
    quantity: float | str | None = None
    unit: str | None = None
    confidence = "medium"

    qty_match = QUANTITY_RE.match(working)
    if qty_match:
        quantity = _parse_quantity_token(qty_match.group("q"))
        working = qty_match.group("rest")
        confidence = "high" if quantity is not None else "medium"

    package_size, working = _extract_package_size(working)

    tokens = working.split()
    if tokens:
        maybe_unit = _normalize_unit(tokens[0])
        if maybe_unit:
            unit = maybe_unit
            working = " ".join(tokens[1:])

    working, unit = _extract_secondary_unit(working, unit)
    name_part, notes = _extract_name_and_notes(working)
    name_normalized, modifiers = normalize_ingredient_name(name_part)
    canonical_ingredient_id = infer_canonical_id(name_normalized)

    if not quantity and not unit and not package_size:
        confidence = "low"

    packaged_text = " ".join(
        [raw_text.lower(), name_normalized.lower(), canonical_ingredient_id.replace("_", " ").lower()]
    )
    requires_label_check, possible_allergens = _infer_packaged_label_info(packaged_text)

    return {
        "raw": raw_text,
        "name_normalized": name_normalized,
        "canonical_ingredient_id": canonical_ingredient_id,
        "quantity": quantity,
        "unit": unit,
        "package_size": package_size,
        "notes": notes,
        "modifiers": modifiers,
        "ingredient_role": "unknown",
        "confidence": confidence,
        "requires_label_check": requires_label_check,
        "ingredient_requires_label_check": requires_label_check,
        "possible_allergens": possible_allergens,
    }


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _has_explicit_allergen_evidence(text: str, allergen: str) -> bool:
    lowered = clean_text(text).lower()
    patterns = EXPLICIT_ALLERGEN_EVIDENCE.get(allergen, [])
    return any(pattern in lowered for pattern in patterns)


def _build_recipe_context_text(directions_json: list[dict[str, Any]], title: str) -> str:
    parts = [clean_text(title)]
    parts.extend(clean_text(step.get("raw_text")) for step in directions_json if isinstance(step, dict))
    return " ".join(part.lower() for part in parts if part)


def infer_ingredient_role(
    ingredient: dict[str, Any],
    recipe_methods: list[str],
    recipe_context_text: str = "",
) -> tuple[str, str]:
    name = clean_text(ingredient.get("name_normalized")).lower()
    canonical = clean_text(ingredient.get("canonical_ingredient_id")).replace("_", " ").lower()
    notes = clean_text(ingredient.get("notes")).lower()
    joined = f"{name} {canonical} {notes}".strip()
    context = recipe_context_text.lower()

    if "for frying" in joined and "oil" in joined:
        return "frying_medium", "high"
    if _contains_any(
        joined,
        [
            "garlic powder",
            "onion powder",
            "rice wine vinegar",
            "vinegar",
            "vanilla extract",
            "dried thyme",
            "dried oregano",
            "dried basil",
            "thyme",
            "oregano",
            "basil",
        ],
    ):
        return "seasoning", "high"
    if "ranch dressing" in joined:
        return "sauce", "high"
    if _contains_any(joined, ["tomato soup", "canned soup", "cream soup"]):
        return "sauce", "high"
    if "sesame seeds" in joined:
        if "sprinkle" in context or "for garnish" in notes:
            return "garnish", "medium"
        return "seasoning", "medium"
    if "whipped cream" in joined:
        return "garnish", "high"
    if "grits" in joined:
        if "baking" in recipe_methods or "bake" in context:
            return "base", "medium"
        return "main", "high"
    if _contains_any(joined, WRAPPER_KEYWORDS):
        if "stuffed" in context:
            return "wrapper", "high"
        return "base", "medium"
    if _contains_any(joined, BASE_KEYWORDS):
        return "base", "high"
    if _contains_any(joined, LEAVENING_KEYWORDS):
        return "leavening", "high"
    if _contains_any(joined, SWEETENER_KEYWORDS):
        return "sweetener", "high"
    if _contains_any(joined, THICKENER_KEYWORDS):
        return "thickener", "high"
    if "flour" in joined:
        if any(token in context for token in ["glaze", "sauce", "thicken", "whisk water and flour", "stir into"]):
            return "thickener", "high"
        if "baking" in recipe_methods or "cake" in context or "cookie" in context:
            return "base", "high"
        if any(method in recipe_methods for method in ["frying", "deep_frying", "coating"]):
            return "coating", "high"
        return "base", "medium"
    if _contains_any(joined, BINDER_KEYWORDS):
        if any(token in context for token in ["batter", "loaf", "dumpling", "french toast", "mixture", "stuffed"]):
            return "binder", "high"
        return "binder", "medium"
    if _contains_any(joined, FILLING_KEYWORDS):
        if "stuffed" in context or "fill" in context:
            return "filling", "high"
        if "dairy" in joined:
            return "filling", "medium"
        return "filling", "medium"
    if _contains_any(joined, MEAT_TERMS + POULTRY_TERMS + SEAFOOD_TERMS + MAIN_KEYWORDS):
        return "main", "high"
    if _contains_any(joined, MAIN_VEG_KEYWORDS):
        if "stuffed" in context:
            return "main", "high"
        if _contains_any(joined, AROMATIC_KEYWORDS) and any(m in recipe_methods for m in ["sauteing", "stirring", "stovetop_cooking", "simmering"]):
            return "aromatic", "medium"
        return "main", "medium"
    if _contains_any(joined, AROMATIC_KEYWORDS) and any(m in recipe_methods for m in ["sauteing", "stirring", "stovetop_cooking", "simmering"]):
        return "aromatic", "high"
    if _contains_any(joined, SEASONING_KEYWORDS):
        return "seasoning", "high"
    if _contains_any(joined, SAUCE_KEYWORDS):
        return "sauce", "high"
    if _contains_any(joined, LIQUID_KEYWORDS):
        return "liquid", "high"
    if _contains_any(joined, FAT_KEYWORDS):
        return "fat_or_oil", "high"
    if _contains_any(joined, COATING_KEYWORDS):
        return "coating", "high"
    if _contains_any(joined, GARNISH_KEYWORDS):
        return "garnish", "medium"
    return "unknown", ingredient.get("confidence") or "low"


def enrich_ingredients(
    ingredients: list[dict[str, Any]],
    recipe_methods: list[str],
    recipe_context_text: str = "",
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in ingredients:
        role, role_confidence = infer_ingredient_role(item, recipe_methods, recipe_context_text)
        merged = dict(item)
        merged["ingredient_role"] = role
        if merged.get("confidence") == "low" and role_confidence == "high":
            merged["confidence"] = "medium"
        if merged.get("confidence") == "medium" and role_confidence == "high":
            merged["confidence"] = "high"
        enriched.append(merged)
    return enriched


def extract_tags(recipe: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    keywords = recipe.get("keywords")
    if isinstance(keywords, str):
        tags.extend([clean_text(k) for k in keywords.split(",") if clean_text(k)])
    elif isinstance(keywords, list):
        tags.extend(clean_text(k) for k in keywords if clean_text(k))
    tags.extend(clean_text(x) for x in as_list(recipe.get("recipeCategory")))
    tags.extend(clean_text(x) for x in as_list(recipe.get("recipeCuisine")))
    return unique_preserve_order(tags)


def first_author_name(author_value: Any) -> str | None:
    for author in as_list(author_value):
        if isinstance(author, dict):
            name = clean_text(author.get("name"))
            if name:
                return name
        elif isinstance(author, str):
            name = clean_text(author)
            if name:
                return name
    return None


def extract_url_value(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        for key in ("@id", "url"):
            candidate = clean_text(value.get(key))
            if candidate:
                return candidate
    return ""


def parse_servings(recipe_yield: Any) -> int | float | str | None:
    for value in as_list(recipe_yield):
        num = parse_numeric(value)
        if num is None:
            continue
        return int(num) if float(num).is_integer() else num
    return None


def parse_rating_and_count(aggregate_rating: Any) -> tuple[float | None, int | None]:
    if not isinstance(aggregate_rating, dict):
        return None, None
    rating = parse_numeric(aggregate_rating.get("ratingValue"))
    count_val = parse_numeric(aggregate_rating.get("ratingCount"))
    review_count = int(count_val) if count_val is not None else None
    return rating, review_count


def _collect_instruction_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = clean_text(value)
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_collect_instruction_texts(item))
        return out
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            text = clean_text(value.get("text"))
            if text:
                return [text]
        if isinstance(value.get("name"), str):
            text = clean_text(value.get("name"))
            if text:
                return [text]
        if "itemListElement" in value:
            return _collect_instruction_texts(value.get("itemListElement"))
    return []


def extract_equipment(raw_text: str) -> list[str]:
    lowered = clean_text(raw_text).lower()
    hits: list[str] = []
    for pattern, canonical in STEP_EQUIPMENT_PATTERNS:
        if pattern in lowered:
            if canonical == "grill" and SMOKING_CONTEXT_RE.search(lowered):
                # Avoid smoker context leaking grill equipment when only preheating a smoker.
                if not re.search(r"\bgrill(?:ed|ing)?\b", lowered):
                    continue
            hits.append(canonical)
    return unique_preserve_order(hits)


def _extract_explicit_temperature_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    covered: list[tuple[int, int]] = []
    for regex in [TEMP_RANGE_WITH_PAREN_RE, TEMP_SINGLE_WITH_PAREN_RE, TEMP_RANGE_SIMPLE_RE, TEMP_SINGLE_SIMPLE_RE]:
        for match in regex.finditer(text):
            span = (match.start(), match.end())
            if any(start <= span[0] and span[1] <= end for start, end in covered):
                continue
            spans.append((span[0], span[1], clean_text(match.group(0))))
            covered.append(span)
    spans.sort(key=lambda item: item[0])
    return spans


def _extract_internal_target_temperature(raw_text: str) -> str | None:
    text = clean_text(raw_text)
    lowered = text.lower()
    if "internal" not in lowered or "temperature" not in lowered:
        return None
    spans = _extract_explicit_temperature_spans(text)
    if not spans:
        return None
    internal_idx = lowered.find("internal")
    after_internal = [value for start, _, value in spans if start >= internal_idx]
    if after_internal:
        return after_internal[0]
    return spans[-1][2]


def extract_temperatures(raw_text: str) -> list[str]:
    text = clean_text(raw_text)
    hits: list[str] = []
    for _, _, value in _extract_explicit_temperature_spans(text):
        hits.append(value)

    for match in HEAT_DESCRIPTOR_RE.finditer(text):
        hits.append(clean_text(match.group(0)))

    return unique_preserve_order(hits)


def extract_durations(raw_text: str) -> list[str]:
    durations: list[str] = []
    for match in DURATION_RE.finditer(clean_text(raw_text)):
        value = clean_text(match.group(0))
        value = re.sub(r"^for\s+", "", value, flags=re.IGNORECASE)
        durations.append(value)
    return unique_preserve_order(durations)


def _duration_to_minutes(duration_text: str) -> float | None:
    text = clean_text(duration_text).lower()
    range_match = re.search(
        r"(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(hours?|minutes?|days?)",
        text,
    )
    single_match = re.search(r"(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(hours?|minutes?|days?)", text)

    def parse_amount(token: str) -> float | None:
        value = _parse_quantity_token(token)
        if isinstance(value, str):
            return None
        return value

    quantity: float | None = None
    unit = ""
    if range_match:
        left = parse_amount(range_match.group(1))
        right = parse_amount(range_match.group(2))
        if left is None or right is None:
            return None
        quantity = max(left, right)
        unit = range_match.group(3)
    elif single_match:
        quantity = parse_amount(single_match.group(1))
        unit = single_match.group(2)
    if quantity is None:
        return None
    if unit.startswith("day"):
        return quantity * 24 * 60
    if unit.startswith("hour"):
        return quantity * 60
    return quantity


def _extract_min_fahrenheit(temperatures: list[str]) -> float | None:
    values: list[float] = []
    for value in temperatures:
        text = clean_text(value)
        for match in re.finditer(
            r"(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*(?:degrees?\s*)?(?:°\s*)?F",
            text,
            flags=re.IGNORECASE,
        ):
            values.extend([float(match.group(1)), float(match.group(2))])
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:degrees?\s*)?(?:°\s*)?F", text, flags=re.IGNORECASE):
            values.append(float(match.group(1)))
        for match in re.finditer(
            r"(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*(?:degrees?\s*|°\s*)C",
            text,
            flags=re.IGNORECASE,
        ):
            values.extend([float(match.group(1)) * 9 / 5 + 32, float(match.group(2)) * 9 / 5 + 32])
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:degrees?\s*|°\s*)C", text, flags=re.IGNORECASE):
            values.append(float(match.group(1)) * 9 / 5 + 32)
    return min(values) if values else None


def _has_explicit_grill_action(text: str) -> bool:
    match = EXPLICIT_GRILL_ACTION_RE.search(text)
    if not match:
        return False
    segment = match.group(0).lower()
    return not any(token in segment for token in ["preheat", "preheats", "grate"])


def infer_cooking_methods(raw_text: str, equipment: list[str]) -> list[str]:
    lowered = clean_text(raw_text).lower()
    methods: list[str] = []
    smoker_context = bool(SMOKING_CONTEXT_RE.search(lowered))
    explicit_grill = _has_explicit_grill_action(lowered)

    if "deep fry" in lowered or "deep-fry" in lowered or "deep fryer" in lowered:
        methods.append("deep_frying")
    if re.search(r"\bfry\b", lowered):
        methods.append("frying")
    if smoker_context:
        methods.append("smoking")
    if re.search(r"\bbrine\b", lowered) or re.search(r"\bsoak\b", lowered) and "brine" in lowered:
        methods.append("brining")
    if re.search(r"\bmarinate\b", lowered):
        methods.append("marinating")
    if re.search(r"\brub\b", lowered):
        methods.append("dry_rub")
    if explicit_grill:
        methods.append("grilling")
    if re.search(r"\bbroil\b", lowered):
        methods.append("broiling")
    if re.search(r"\broast\b", lowered):
        methods.append("roasting")
    if re.search(r"\bbake\b", lowered):
        methods.append("baking")
    if re.search(r"\bsimmer\b", lowered):
        methods.append("simmering")
    if re.search(r"\bboil\b", lowered):
        methods.append("boiling")
    if re.search(r"\bsaute\b|\bsauté\b", lowered):
        methods.append("sauteing")
    if re.search(r"\bstir\b", lowered):
        methods.append("stirring")
    if re.search(r"\bmix\b|\bwhisk\b", lowered):
        methods.append("mixing")
    if re.search(r"\bcoat\b|\bdredge\b", lowered):
        methods.append("coating")
    if re.search(r"\bdrain\b", lowered):
        methods.append("draining")

    has_stovetop_equipment = any(
        eq in {"skillet", "deep skillet", "heavy deep skillet", "saucepan", "large saucepan", "frying pan", "large pot", "stockpot"}
        for eq in equipment
    )
    if has_stovetop_equipment and any(term in lowered for term in ["cook", "heat", "stir", "simmer", "boil", "fry", "saute"]):
        methods.append("stovetop_cooking")
    if any("skillet" in eq for eq in equipment) and methods:
        methods.append("skillet_cooking")

    if "smoking" in methods:
        durations = extract_durations(raw_text)
        max_duration = max((_duration_to_minutes(d) or 0 for d in durations), default=0)
        min_f = _extract_min_fahrenheit(extract_temperatures(raw_text))
        if max_duration >= 240 or (min_f is not None and min_f <= 250):
            methods.append("low_and_slow_cooking")

    return unique_preserve_order(methods)


def extract_step_food_safety_notes(raw_text: str) -> list[str]:
    text = clean_text(raw_text)
    lowered = text.lower()
    notes: list[str] = []

    if "discard" in lowered and "marinade" in lowered:
        notes.append("Discard used marinade after raw meat contact.")

    if ("marinate" in lowered or "brine" in lowered or "soak" in lowered) and ("refrigerator" in lowered or "fridge" in lowered):
        if "chicken" in lowered:
            notes.append("Keep raw chicken refrigerated while marinating.")
        elif any(token in lowered for token in ["beef", "pork", "turkey", "lamb", "meat"]):
            notes.append("Keep raw meat refrigerated while marinating or brining.")

    if "drain" in lowered and any(token in lowered for token in ["beef", "pork", "chicken", "turkey", "lamb", "meat"]):
        notes.append("Drain cooked meat safely before combining with other ingredients.")

    if "no longer pink" in lowered or "juices run clear" in lowered:
        if "chicken" in lowered:
            notes.append("Cook chicken until it reaches a safe internal temperature and juices run clear.")
        else:
            notes.append("Continue cooking until meat is no longer pink and juices run clear.")

    if "shrimp" in lowered and "opaque" in lowered:
        notes.append("Cook shrimp until fully opaque.")

    if re.search(r"internal[^.]{0,50}temperature", lowered) or "thermometer" in lowered:
        explicit_temps = [value for _, _, value in _extract_explicit_temperature_spans(text)]
        target_temp = _extract_internal_target_temperature(text) or (explicit_temps[-1] if explicit_temps else "safe internal temperature")
        if "chicken" in lowered:
            notes.append(f"Cook chicken until internal temperature reaches {target_temp}.")
        elif "pork" in lowered:
            notes.append(f"Cook pork until internal temperature reaches {target_temp}.")
        else:
            notes.append(f"Cook until internal temperature reaches {target_temp}.")

    return unique_preserve_order(notes)


def summarize_action(raw_text: str) -> str:
    raw = clean_text(raw_text)
    lowered = raw.lower()
    if not raw:
        return ""
    if len(raw) <= 80:
        return raw

    if "stir" in lowered and "saucepan" in lowered and "tomato" in lowered:
        return "Cook beans, tomatoes, lime juice, and spices in a saucepan until the tomatoes soften."

    if "smoke at" in lowered and ("internal" in lowered or "temperature reaches" in lowered):
        target_temp = _extract_internal_target_temperature(raw) or "safe internal temperature"
        protein = "pork" if "pork" in lowered else "meat"
        return f"Smoke {protein} at low temperature until it reaches {target_temp} internal temperature."

    if "preheat" in lowered and "smoker" in lowered:
        return "Preheat the smoker and set up the rack and drip pan."

    clauses = [clean_text(part).strip(".") for part in re.split(r"[.;]\s+", raw) if clean_text(part)]
    if not clauses:
        return raw
    first = re.sub(r"\s+", " ", clauses[0]).strip()
    second = re.sub(r"\s+", " ", clauses[1]).strip() if len(clauses) > 1 else ""
    summary = first
    if second and len(first) < 90:
        summary = f"{first}; {second}"
    summary = re.sub(r"\s{2,}", " ", summary).strip(" ,")
    similarity = SequenceMatcher(None, summary.lower(), raw.lower()).ratio()
    if similarity > 0.9 and len(clauses) > 1:
        summary = f"{clauses[0]}. {clauses[1]}".strip()
    if len(summary) > 170:
        summary = summary[:170].rsplit(" ", 1)[0].strip()
    if summary and summary[-1] not in ".!?":
        summary += "."
    return summary


def parse_directions(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = _collect_instruction_texts(recipe.get("recipeInstructions"))
    directions: list[dict[str, Any]] = []
    for idx, raw_step in enumerate(raw_steps, start=1):
        if not raw_step:
            continue
        equipment = extract_equipment(raw_step)
        methods = infer_cooking_methods(raw_step, equipment)
        temperatures = extract_temperatures(raw_step)
        durations = extract_durations(raw_step)
        food_safety_notes = extract_step_food_safety_notes(raw_step)
        directions.append(
            {
                "step_number": idx,
                "raw_text": clean_text(raw_step),
                "action_summary": summarize_action(raw_step),
                "equipment": equipment,
                "method": methods[0] if methods else None,
                "temperature": temperatures,
                "duration": durations,
                "food_safety_notes": food_safety_notes,
                "quality_flags": [],
                "equipment_or_method": "; ".join(equipment) if equipment else None,
                "safety_note": food_safety_notes[0] if food_safety_notes else None,
            }
        )
    return directions


def derive_recipe_methods(directions_json: list[dict[str, Any]]) -> list[str]:
    methods: list[str] = []
    for step in directions_json:
        raw_text = clean_text(step.get("raw_text"))
        equipment = [clean_text(x) for x in as_list(step.get("equipment"))]
        methods.extend(infer_cooking_methods(raw_text, equipment))
    return unique_preserve_order(methods)


def derive_recipe_equipment(directions_json: list[dict[str, Any]]) -> list[str]:
    equipment: list[str] = []
    for step in directions_json:
        for item in as_list(step.get("equipment")):
            equipment.append(clean_text(item))
    return unique_preserve_order(equipment)


def infer_allergens(
    ingredients: list[dict[str, Any]],
) -> tuple[list[str], list[str], dict[str, list[str]], dict[str, str]]:
    confirmed: set[str] = set()
    possible: set[str] = set()
    basis: dict[str, list[str]] = {key: [] for key in ALLERGEN_TAXONOMY}
    confidence: dict[str, str] = {}

    for ingredient in ingredients:
        name = clean_text(ingredient.get("name_normalized")).lower()
        canonical = clean_text(ingredient.get("canonical_ingredient_id")).replace("_", " ").lower()
        raw = clean_text(ingredient.get("raw"))
        joined = f"{name} {canonical}".strip()
        requires_label_check = bool(ingredient.get("requires_label_check"))
        if not joined:
            continue
        for allergen, patterns in ALLERGEN_RULES.items():
            if any(pattern in joined for pattern in patterns):
                evidence_text = f"{joined} {clean_text(raw).lower()}".strip()
                if requires_label_check and not _has_explicit_allergen_evidence(evidence_text, allergen):
                    possible.add(allergen)
                    basis[allergen].append(raw or joined)
                    confidence.setdefault(allergen, "possible")
                else:
                    confirmed.add(allergen)
                    basis[allergen].append(raw or joined)
                    confidence[allergen] = "high"
        for allergen, patterns in POSSIBLE_ALLERGEN_RULES.items():
            if any(pattern in joined for pattern in patterns) and allergen not in confirmed:
                possible.add(allergen)
                basis[allergen].append(raw or joined)
                confidence.setdefault(allergen, "possible")
        for allergen in as_list(ingredient.get("possible_allergens")):
            allergen_name = clean_text(allergen)
            if not allergen_name:
                continue
            if allergen_name not in confirmed:
                possible.add(allergen_name)
                basis.setdefault(allergen_name, []).append(raw or joined)
                confidence.setdefault(allergen_name, "possible")
        if "soy sauce" in joined:
            confirmed.add("soy")
            basis["soy"].append(raw or joined)
            confidence["soy"] = "high"
            if "gluten-free" not in joined and "gluten free" not in joined:
                confirmed.add("wheat_gluten")
                basis["wheat_gluten"].append(raw or joined)
                confidence["wheat_gluten"] = "high"

    basis_clean = {k: unique_preserve_order(v) for k, v in basis.items() if v}
    allergen_flags = sorted(confirmed)
    possible_flags = sorted(possible - confirmed)
    for item in possible_flags:
        confidence.setdefault(item, "possible")
    return allergen_flags, possible_flags, basis_clean, confidence


def _has_ambiguous_or_with_poultry(text: str) -> bool:
    return bool(re.search(r"\b(chicken|turkey|duck)\b\s+or\s+\w+", text))


def infer_dietary_flags(
    ingredients: list[dict[str, Any]],
    cooking_methods: list[str],
    nutrition_per_serving: dict[str, Any],
    allergen_flags: list[str] | None = None,
    possible_allergen_flags: list[str] | None = None,
) -> tuple[dict[str, bool | str], dict[str, str]]:
    allergen_flags = allergen_flags or []
    possible_allergen_flags = possible_allergen_flags or []

    has_meat = False
    has_beef = False
    has_poultry = False
    has_seafood = False
    poultry_ambiguous = False
    has_dairy = False
    has_egg = False
    has_gluten_explicit = False
    has_gluten_possible = "wheat_gluten" in possible_allergen_flags
    has_packaged_uncertainty = False
    vegan_uncertain = False

    for ingredient in ingredients:
        name = clean_text(ingredient.get("name_normalized")).lower()
        canonical = clean_text(ingredient.get("canonical_ingredient_id")).replace("_", " ").lower()
        raw = clean_text(ingredient.get("raw")).lower()
        joined = f"{name} {canonical} {raw}"
        if not joined.strip():
            continue

        if _has_ambiguous_or_with_poultry(joined):
            poultry_ambiguous = True

        if any(term in joined for term in MEAT_TERMS):
            has_meat = True
        if "beef" in joined:
            has_beef = True
        if any(term in joined for term in POULTRY_TERMS):
            has_poultry = True
            has_meat = True
        if any(term in joined for term in SEAFOOD_TERMS):
            has_seafood = True
            has_meat = True

        if any(term in joined for term in ["milk", "buttermilk", "cheese", "cream", "yogurt", "butter", "ranch"]):
            has_dairy = True
        if any(term in joined for term in ["egg", "eggs", "albumen"]):
            has_egg = True
        if any(term in joined for term in ["wheat", "flour", "breadcrumbs", "bread", "pasta", "wrapper", "tortilla"]):
            has_gluten_explicit = True

        if bool(ingredient.get("requires_label_check")):
            has_packaged_uncertainty = True
            possible = {clean_text(a) for a in as_list(ingredient.get("possible_allergens"))}
            if any(item in possible for item in ["milk", "egg", "fish"]):
                vegan_uncertain = True
            if "wheat_gluten" in possible:
                has_gluten_possible = True

        if any(term in joined for term in ["gelatin", "jell-o", "jello"]):
            vegan_uncertain = True

    has_dairy = has_dairy or ("milk" in allergen_flags)
    has_egg = has_egg or ("egg" in allergen_flags)
    has_gluten_explicit = has_gluten_explicit or ("wheat_gluten" in allergen_flags)
    if "wheat_gluten" in possible_allergen_flags:
        has_gluten_possible = True

    vegetarian: bool | str = not (has_meat or has_seafood)
    vegan: bool | str = not (has_meat or has_seafood or has_dairy or has_egg or vegan_uncertain)

    if vegan is True and has_packaged_uncertainty and vegan_uncertain:
        vegan = "unknown"
    if vegetarian is True and has_packaged_uncertainty and vegan_uncertain:
        vegetarian = "unknown"

    contains_gluten: bool | str
    if has_gluten_explicit:
        contains_gluten = True
    elif has_gluten_possible:
        contains_gluten = "unknown"
    else:
        contains_gluten = False

    contains_poultry: bool | str
    if has_poultry and poultry_ambiguous:
        contains_poultry = "unknown"
    else:
        contains_poultry = has_poultry

    sodium = nutrition_per_serving.get("sodium_mg")
    high_sodium: bool | str = "unknown" if sodium is None else float(sodium) >= 600
    fried = any(method in {"frying", "deep_frying"} for method in cooking_methods)

    dietary_flags = {
        "vegetarian": vegetarian,
        "vegan": vegan,
        "contains_meat": has_meat,
        "contains_beef": has_beef,
        "contains_poultry": contains_poultry,
        "contains_fish_or_shellfish": has_seafood,
        "contains_dairy": has_dairy,
        "contains_egg": has_egg,
        "contains_gluten": contains_gluten,
        "fried": fried,
        "high_sodium": high_sodium,
    }

    vegetarian_conf = "high"
    if vegetarian == "unknown":
        vegetarian_conf = "low"
    elif vegetarian is True and has_packaged_uncertainty:
        vegetarian_conf = "medium"

    vegan_conf = "high"
    if vegan == "unknown":
        vegan_conf = "low"
    elif vegan is True and has_packaged_uncertainty:
        vegan_conf = "medium"

    gluten_conf = "high"
    if contains_gluten == "unknown":
        gluten_conf = "low"
    elif contains_gluten is False and has_packaged_uncertainty:
        gluten_conf = "medium"

    dietary_confidence = {
        "vegetarian": vegetarian_conf,
        "vegan": vegan_conf,
        "contains_gluten": gluten_conf,
    }
    return dietary_flags, dietary_confidence


def build_nutrition_quality(
    nutrition_facts_raw: dict[str, Any] | None,
    nutrition_per_serving: dict[str, Any],
    servings: int | float | str | None,
) -> dict[str, Any]:
    issues: list[str] = []
    if isinstance(nutrition_facts_raw, dict):
        unsat = clean_text(nutrition_facts_raw.get("unsaturatedFatContent")).lower().replace(" ", "")
        if unsat in {"0", "0g", ""}:
            issues.append("unsaturated_fat_reported_as_zero_or_missing")
    if any(nutrition_per_serving.get(k) is None for k in ["calories_kcal", "protein_g", "carbohydrates_g", "fat_g"]):
        issues.append("incomplete_macros")
    return {
        "source": "source_reported",
        "per_serving": True,
        "servings": servings,
        "verified_by_qima": False,
        "issues": unique_preserve_order(issues),
    }


def infer_difficulty(directions_json: list[dict[str, Any]], cooking_methods: list[str], total_minutes: int | None) -> str:
    step_count = len(directions_json)
    has_major_method = any(m in {"deep_frying", "grilling", "marinating"} for m in cooking_methods)
    if step_count >= 7 or (total_minutes is not None and total_minutes > 90):
        return "hard"
    if (
        1 <= step_count <= 3
        and (total_minutes is None or total_minutes <= 45)
        and not any(m in {"deep_frying", "grilling", "marinating"} for m in cooking_methods)
    ):
        return "easy"
    return "medium"


def build_data_quality_flags(record: dict[str, Any]) -> list[str]:
    flags: list[str] = ["source_reported_nutrition_only", "dietary_flags_inferred", "allergens_inferred"]
    directions = as_list(record.get("directions_json"))
    if directions:
        flags.extend(["directions_available", "instructions_structured"])
    else:
        flags.append("directions_missing")
    if any(m in {"frying", "deep_frying"} for m in as_list(record.get("cooking_methods"))):
        flags.append("contains_frying_method")
    has_raw_meat_handling = False
    has_food_temp = False
    for step in directions:
        for note in as_list(step.get("food_safety_notes")):
            lowered = clean_text(note).lower()
            if any(x in lowered for x in ["raw chicken", "raw meat", "discard", "no longer pink", "juices run clear", "drain"]):
                has_raw_meat_handling = True
            if any(x in lowered for x in ["internal temperature", "degrees f", "degrees c"]):
                has_food_temp = True
        for temp in as_list(step.get("temperature")):
            t = clean_text(temp).lower()
            if "degrees f" in t or "degrees c" in t or "°" in t:
                has_food_temp = True
    if has_raw_meat_handling:
        flags.append("contains_raw_meat_handling")
    if has_food_temp:
        flags.append("contains_food_safety_temperature")
    if len(directions) == 1:
        flags.append("single_step_recipe")
    if record.get("servings") is None:
        flags.append("missing_servings")
    times = record.get("times") if isinstance(record.get("times"), dict) else {}
    if not any(times.get(k) is not None for k in ("prep_minutes", "cook_minutes", "total_minutes")):
        flags.append("missing_times")
    nutrition = record.get("nutrition_per_serving")
    if not isinstance(nutrition, dict) or all(v is None for v in nutrition.values()):
        flags.append("missing_nutrition")
    ingredients = as_list(record.get("ingredients"))
    if any(clean_text(item.get("confidence")).lower() == "low" for item in ingredients if isinstance(item, dict)):
        flags.append("low_ingredient_parse_confidence")
    return unique_preserve_order(flags)


def compute_completeness_score(record: dict[str, Any]) -> float:
    score = 0.0
    if clean_text(record.get("source_url")):
        score += 0.10
    if clean_text(record.get("title")):
        score += 0.10
    if as_list(record.get("ingredients")):
        score += 0.15
    if as_list(record.get("directions_json")):
        score += 0.15
    times = record.get("times") if isinstance(record.get("times"), dict) else {}
    if any(times.get(k) is not None for k in ("prep_minutes", "cook_minutes", "total_minutes")):
        score += 0.10
    if record.get("servings") is not None:
        score += 0.10
    nutrition = record.get("nutrition_per_serving")
    if isinstance(nutrition, dict) and any(v is not None for v in nutrition.values()):
        score += 0.10
    if as_list(record.get("allergen_flags")) or as_list(record.get("possible_allergen_flags")):
        score += 0.10
    if isinstance(record.get("dietary_flags"), dict):
        score += 0.05
    if as_list(record.get("equipment")) or as_list(record.get("cooking_methods")):
        score += 0.05
    return round(min(score, 1.0), 4)


def _is_descriptor_only_value(value: str) -> bool:
    tokens = _tokenize_words(value)
    if not tokens:
        return True
    return all(token in DESCRIPTOR_WORDS for token in tokens)


def _is_obvious_role_candidate(text: str) -> bool:
    return _contains_any(
        text,
        MAIN_KEYWORDS
        + MAIN_VEG_KEYWORDS
        + SEASONING_KEYWORDS
        + MEAT_TERMS
        + POULTRY_TERMS
        + SEAFOOD_TERMS
        + LIQUID_KEYWORDS
        + FAT_KEYWORDS
        + SAUCE_KEYWORDS,
    )


def _is_malformed_ingredient_name(name: str, canonical: str) -> bool:
    malformed_tokens = {"finely", "coarsely", "roughly", "thinly", "freshly", "trimmed"}
    name_tokens = set(_tokenize_words(name))
    canonical_tokens = set(_tokenize_words(canonical))
    if re.search(r"\d", name) or re.search(r"\d", canonical):
        return True
    if malformed_tokens.intersection(name_tokens) or malformed_tokens.intersection(canonical_tokens):
        return True
    if "inch" in name_tokens or "inch" in canonical_tokens:
        return True
    return False


def _has_obvious_wrong_role(joined: str, role: str) -> bool:
    expectations: list[tuple[list[str], set[str]]] = [
        (["garlic powder"], {"seasoning"}),
        (["onion powder"], {"seasoning"}),
        (["rice wine vinegar", "vinegar"], {"seasoning"}),
        (["ranch dressing"], {"sauce"}),
        (["tomato soup"], {"sauce", "liquid"}),
        (["sesame seeds"], {"seasoning", "garnish"}),
        (["grits"], {"main", "base"}),
        (["vanilla extract"], {"seasoning"}),
        (["whipped cream"], {"garnish"}),
        (["thyme", "oregano", "basil"], {"seasoning"}),
    ]
    for patterns, expected_roles in expectations:
        if any(pattern in joined for pattern in patterns):
            return role not in expected_roles
    return False


def build_normalization_warnings(record: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    dietary = record.get("dietary_flags") if isinstance(record.get("dietary_flags"), dict) else {}

    if dietary.get("contains_meat") is True and dietary.get("vegetarian") is True:
        warnings.append("meat_detection_conflict")
    if dietary.get("contains_poultry") is True and dietary.get("vegetarian") is True:
        warnings.append("meat_detection_conflict")
    if dietary.get("contains_fish_or_shellfish") is True and dietary.get("vegetarian") is True:
        warnings.append("meat_detection_conflict")

    ingredients = [i for i in as_list(record.get("ingredients")) if isinstance(i, dict)]
    for ingredient in ingredients:
        name = clean_text(ingredient.get("name_normalized")).lower()
        canonical = clean_text(ingredient.get("canonical_ingredient_id")).replace("_", " ").lower()
        role = clean_text(ingredient.get("ingredient_role")).lower()
        raw = clean_text(ingredient.get("raw")).lower()
        joined = f"{name} {canonical} {raw}".strip()

        if _is_descriptor_only_value(name) or _is_descriptor_only_value(canonical):
            warnings.append("descriptor_only_ingredient_name")
        if _is_malformed_ingredient_name(name, canonical):
            warnings.append("malformed_ingredient_name")
        if role == "unknown" and _is_obvious_role_candidate(joined):
            warnings.append("unknown_role_obvious_ingredient")
        if _has_obvious_wrong_role(joined, role):
            warnings.append("obvious_wrong_ingredient_role")
        if any(term in joined for term in PACKAGED_TRIGGER_TERMS) and not bool(ingredient.get("requires_label_check")):
            warnings.append("packaged_ingredient_needs_label_check")

    cooking_methods = as_list(record.get("cooking_methods"))
    directions = [d for d in as_list(record.get("directions_json")) if isinstance(d, dict)]
    if "smoking" in cooking_methods:
        if not any(SMOKING_CONTEXT_RE.search(clean_text(step.get("raw_text")).lower()) for step in directions):
            warnings.append("method_false_positive_possible")

    expected_low_and_slow = False
    for step in directions:
        step_methods = infer_cooking_methods(clean_text(step.get("raw_text")), [clean_text(x) for x in as_list(step.get("equipment"))])
        if "low_and_slow_cooking" in step_methods:
            expected_low_and_slow = True
            break
    if expected_low_and_slow and "low_and_slow_cooking" not in cooking_methods:
        warnings.append("missing_low_and_slow_method")

    for step in directions:
        raw_text = clean_text(step.get("raw_text"))
        step_equipment = [clean_text(x) for x in as_list(step.get("equipment")) if clean_text(x)]
        temperatures = [clean_text(x) for x in as_list(step.get("temperature")) if clean_text(x)]
        durations = [clean_text(x) for x in as_list(step.get("duration")) if clean_text(x)]
        summary = clean_text(step.get("action_summary"))
        notes = [clean_text(x) for x in as_list(step.get("food_safety_notes")) if clean_text(x)]

        if extract_equipment(raw_text) and not step_equipment:
            warnings.append("equipment_mentioned_but_missing")
        if any(re.fullmatch(r"\d+\s*[cC]", temp.strip()) for temp in temperatures):
            warnings.append("fake_temperature_detected")
        if re.search(r"\b\d+\s+\d+/\d+\s*(?:to|-)\s*\d+\s*hours?\b", raw_text.lower()):
            if not any("/" in duration and ("to" in duration or "-" in duration) for duration in durations):
                warnings.append("duration_range_maybe_corrupted")
        if "..." in summary:
            warnings.append("summary_truncated")
        if raw_text and summary and len(raw_text) > 90:
            similarity = SequenceMatcher(None, summary.lower(), raw_text.lower()).ratio()
            if similarity >= 0.9:
                warnings.append("summary_near_identical")
        if (
            (re.search(r"internal[^.]{0,50}temperature", raw_text.lower()) or "no longer pink" in raw_text.lower() or "marinate" in raw_text.lower())
            and not notes
        ):
            warnings.append("missing_step_safety_note")
        internal_target = _extract_internal_target_temperature(raw_text)
        if internal_target and notes:
            note_temp_values: list[str] = []
            for note in notes:
                note_temp_values.extend(value.lower() for _, _, value in _extract_explicit_temperature_spans(note))
            if note_temp_values and internal_target.lower() not in note_temp_values:
                warnings.append("internal_temp_confused_with_cooking_temp")

    allergen_flags = {clean_text(a) for a in as_list(record.get("allergen_flags"))}
    allergen_confidence = record.get("allergen_confidence") if isinstance(record.get("allergen_confidence"), dict) else {}
    for ingredient in ingredients:
        joined = f"{clean_text(ingredient.get('name_normalized')).lower()} {clean_text(ingredient.get('canonical_ingredient_id')).replace('_', ' ').lower()} {clean_text(ingredient.get('raw')).lower()}"
        if any(token in joined for token in ["milk", "cheese", "butter", "yogurt", "cream"]) and "milk" not in allergen_flags:
            warnings.append("obvious_allergen_missing")
        if "soy sauce" in joined and "soy" not in allergen_flags:
            warnings.append("obvious_allergen_missing")
        if "flour" in joined and "wheat_gluten" not in allergen_flags:
            warnings.append("obvious_allergen_missing")
        if bool(ingredient.get("requires_label_check")):
            for allergen in as_list(ingredient.get("possible_allergens")):
                allergen_name = clean_text(allergen)
                if not allergen_name:
                    continue
                if (
                    allergen_name in allergen_flags
                    and clean_text(allergen_confidence.get(allergen_name)).lower() == "high"
                    and not _has_explicit_allergen_evidence(joined, allergen_name)
                ):
                    warnings.append("packaged_allergen_overconfidence")

    return unique_preserve_order(warnings)


def compute_normalization_quality_score(record: dict[str, Any]) -> float:
    warnings = build_normalization_warnings(record)
    penalties = {
        "meat_detection_conflict": 0.20,
        "descriptor_only_ingredient_name": 0.12,
        "malformed_ingredient_name": 0.10,
        "fake_temperature_detected": 0.18,
        "internal_temp_confused_with_cooking_temp": 0.12,
        "method_false_positive_possible": 0.15,
        "packaged_ingredient_needs_label_check": 0.10,
        "packaged_allergen_overconfidence": 0.10,
        "unknown_role_obvious_ingredient": 0.08,
        "obvious_wrong_ingredient_role": 0.10,
        "duration_range_maybe_corrupted": 0.12,
        "equipment_mentioned_but_missing": 0.10,
        "summary_truncated": 0.08,
        "summary_near_identical": 0.08,
        "missing_step_safety_note": 0.10,
        "obvious_allergen_missing": 0.10,
        "missing_low_and_slow_method": 0.15,
    }
    score = 1.0
    for warning in warnings:
        score -= penalties.get(warning, 0.05)
    return round(max(0.0, min(1.0, score)), 4)


def build_quality_scores(record: dict[str, Any]) -> tuple[float, float, float]:
    completeness = compute_completeness_score(record)
    normalization = compute_normalization_quality_score(record)
    return completeness, normalization, completeness


def build_record(recipe_url: str, recipe: dict[str, Any]) -> dict[str, Any]:
    directions_json = parse_directions(recipe)
    cooking_methods = derive_recipe_methods(directions_json)
    equipment = derive_recipe_equipment(directions_json)

    base_ingredients = [parse_ingredient(x) for x in as_list(recipe.get("recipeIngredient"))]
    recipe_context_text = _build_recipe_context_text(directions_json, clean_text(recipe.get("name") or ""))
    ingredients = enrich_ingredients(base_ingredients, cooking_methods, recipe_context_text)

    tags = extract_tags(recipe)
    nutrition = recipe.get("nutrition") if isinstance(recipe.get("nutrition"), dict) else {}
    rating, review_count = parse_rating_and_count(recipe.get("aggregateRating"))
    canonical_recipe_url = canonicalize_recipe_url(recipe_url)
    recipe_id, stable_slug = recipe_id_and_slug(canonical_recipe_url)

    source_url = (
        extract_url_value(recipe.get("mainEntityOfPage"))
        or extract_url_value(recipe.get("url"))
        or clean_text(canonical_recipe_url)
    )
    source_url = canonicalize_recipe_url(source_url)

    prep_minutes = parse_iso_duration_to_minutes(recipe.get("prepTime"))
    cook_minutes = parse_iso_duration_to_minutes(recipe.get("cookTime"))
    total_minutes = parse_iso_duration_to_minutes(recipe.get("totalTime"))
    if total_minutes is None and (prep_minutes is not None or cook_minutes is not None):
        total_minutes = (prep_minutes or 0) + (cook_minutes or 0)

    calories = parse_nutrition_number(nutrition.get("calories"), expected="kcal")
    protein_g = parse_nutrition_number(nutrition.get("proteinContent"), expected="g")
    carbs_g = parse_nutrition_number(nutrition.get("carbohydrateContent"), expected="g")
    fat_g = parse_nutrition_number(nutrition.get("fatContent"), expected="g")
    fiber_g = parse_nutrition_number(nutrition.get("fiberContent"), expected="g")
    sugar_g = parse_nutrition_number(nutrition.get("sugarContent"), expected="g")
    sodium_mg = parse_nutrition_number(nutrition.get("sodiumContent"), expected="mg")

    nutrition_per_serving = {
        "calories_kcal": calories,
        "protein_g": protein_g,
        "carbohydrates_g": carbs_g,
        "fat_g": fat_g,
        "fiber_g": fiber_g,
        "sugar_g": sugar_g,
        "sodium_mg": sodium_mg,
    }

    servings = parse_servings(recipe.get("recipeYield"))
    allergen_flags, possible_allergen_flags, allergen_basis, allergen_confidence = infer_allergens(ingredients)
    dietary_flags, dietary_confidence = infer_dietary_flags(
        ingredients,
        cooking_methods,
        nutrition_per_serving,
        allergen_flags=allergen_flags,
        possible_allergen_flags=possible_allergen_flags,
    )
    nutrition_quality = build_nutrition_quality(nutrition or None, nutrition_per_serving, servings)

    packaged_ingredient_warnings = unique_preserve_order(
        clean_text(item.get("raw"))
        for item in ingredients
        if bool(item.get("requires_label_check")) and clean_text(item.get("raw"))
    )

    cuisine_values = unique_preserve_order(clean_text(x) for x in as_list(recipe.get("recipeCuisine")))
    category_values = unique_preserve_order(clean_text(x) for x in as_list(recipe.get("recipeCategory")))

    meal_type: str | None = None
    for tag in tags:
        low = tag.lower()
        if low in {"breakfast", "brunch", "lunch", "dinner", "dessert", "snack"}:
            meal_type = low
            break

    difficulty = infer_difficulty(directions_json, cooking_methods, total_minutes)

    record = {
        "source": SOURCE,
        "source_url": source_url,
        "recipe_id": recipe_id,
        "stable_slug": stable_slug,
        "title": clean_text(recipe.get("name") or recipe.get("headline")),
        "cuisine": cuisine_values[0] if cuisine_values else None,
        "category": category_values[0] if category_values else None,
        "meal_type": meal_type,
        "author_name": first_author_name(recipe.get("author")),
        "servings": servings,
        "times": {
            "prep_minutes": prep_minutes,
            "cook_minutes": cook_minutes,
            "total_minutes": total_minutes,
        },
        "ingredients": ingredients,
        "directions_json": directions_json,
        "cooking_methods": cooking_methods,
        "equipment": equipment,
        "nutrition_facts_raw": nutrition or None,
        "nutrition_per_serving": nutrition_per_serving,
        "nutrition_quality": nutrition_quality,
        "tags": tags,
        "dietary_flags": dietary_flags,
        "dietary_confidence": dietary_confidence,
        "allergen_flags": allergen_flags,
        "possible_allergen_flags": possible_allergen_flags,
        "allergen_basis": allergen_basis,
        "allergen_confidence": allergen_confidence,
        "packaged_ingredient_warnings": packaged_ingredient_warnings,
        "difficulty": difficulty,
        "rating": rating,
        "review_count": review_count,
        "date_published": clean_text(recipe.get("datePublished")) or None,
        "date_modified": clean_text(recipe.get("dateModified")) or None,
        "attribution": {
            "source_name": SOURCE_NAME,
            "source_url": source_url,
        },
    }

    record["data_quality_flags"] = build_data_quality_flags(record)
    record["normalization_warnings"] = build_normalization_warnings(record)
    completeness_score, normalization_quality_score, recipe_quality_score = build_quality_scores(record)
    record["completeness_score"] = completeness_score
    record["normalization_quality_score"] = normalization_quality_score
    record["recipe_quality_score"] = recipe_quality_score
    return record


# Backward-compatible aliases used by older callers.
derive_allergen_metadata = infer_allergens
derive_dietary_flags = infer_dietary_flags
extract_step_equipment = extract_equipment
extract_step_temperatures = extract_temperatures
extract_step_durations = extract_durations
extract_step_methods = infer_cooking_methods
build_canonical_ingredient_id = infer_canonical_id
build_normalization_warnings = build_normalization_warnings


def fetch_text(session: Any, url: str, retries: int) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url)
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            return response.body.decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                backoff = min(2**attempt, 10)
                logging.warning("Retrying %s after %s (%s/%s)", url, exc, attempt, retries)
                time.sleep(backoff)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def parse_robots_sitemaps(text: str) -> list[str]:
    sitemaps: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            candidate = clean_text(stripped.split(":", 1)[1])
            if candidate:
                sitemaps.append(candidate)
    return unique_preserve_order(sitemaps)


def parse_xml_locs(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8", errors="ignore"))
    except ET.ParseError:
        return []
    return [clean_text(node.text) for node in root.findall(".//{*}loc") if clean_text(node.text)]


def discover_recipe_urls(session: Any, max_urls: int | None, retries: int) -> list[RecipeUrl]:
    try:
        robots_text = fetch_text(session, ROBOTS_URL, retries=retries)
        sitemap_urls = parse_robots_sitemaps(robots_text)
    except Exception:
        sitemap_urls = []
    if not sitemap_urls:
        sitemap_urls = [SITEMAP_INDEX_URL]

    seen_sitemap: set[str] = set()
    queue = list(sitemap_urls)
    recipe_urls: list[RecipeUrl] = []
    seen_recipe: set[str] = set()

    while queue:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemap:
            continue
        seen_sitemap.add(sitemap_url)
        try:
            xml_text = fetch_text(session, sitemap_url, retries=retries)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Skipping sitemap %s due to error: %s", sitemap_url, exc)
            continue
        locs = parse_xml_locs(xml_text)
        if not locs:
            continue
        for loc in locs:
            if "/sitemap" in loc and loc.endswith(".xml"):
                queue.append(loc)
                continue
            if "/recipe/" not in loc:
                continue
            canonical_loc = canonicalize_recipe_url(loc)
            recipe_id, _ = recipe_id_and_slug(canonical_loc)
            dedupe_key = recipe_unique_key(canonical_loc, recipe_id)
            if dedupe_key in seen_recipe:
                continue
            seen_recipe.add(dedupe_key)
            recipe_urls.append(RecipeUrl(url=canonical_loc))
            if max_urls and len(recipe_urls) >= max_urls:
                return recipe_urls
    return recipe_urls


def scrape_allrecipes(args: argparse.Namespace) -> Iterator[dict[str, Any]]:
    if FetcherSession is None:  # pragma: no cover
        raise RuntimeError("scrapling[fetchers] is required to scrape Allrecipes.")

    with FetcherSession(
        impersonate=args.impersonate,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=1,
        follow_redirects=True,
    ) as session:
        recipe_targets = [RecipeUrl(url=u) for u in args.urls] if args.urls else discover_recipe_urls(session, args.max_urls, args.retries)
        logging.info("Discovered %s recipe URLs", len(recipe_targets))
        emitted = 0
        emitted_keys: set[str] = set()

        for recipe_target in recipe_targets:
            try:
                html = fetch_text(session, recipe_target.url, retries=args.retries)
                recipe = find_recipe_object(extract_jsonld_objects(html))
                if not recipe:
                    logging.debug("No recipe JSON-LD found at %s", recipe_target.url)
                    continue
                record = build_record(recipe_target.url, recipe)
                dedupe_key = recipe_unique_key(record["source_url"], record.get("recipe_id"))
                if dedupe_key in emitted_keys:
                    continue
                emitted_keys.add(dedupe_key)
                yield record
                emitted += 1
            except Exception as exc:  # noqa: BLE001
                logging.warning("Failed to parse %s: %s", recipe_target.url, exc)
                continue
            if args.max_urls and emitted >= args.max_urls:
                break
            if args.delay > 0:
                time.sleep(args.delay + random.uniform(0, args.jitter))


def write_jsonl(rows: Iterable[dict[str, Any]], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def _load_allrecipes_seed_helpers() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    seed_script = repo_root / "backend" / "scripts" / "seed_allrecipes_recipes.py"
    if not seed_script.exists():
        raise FileNotFoundError(f"Required loader script not found: {seed_script}")
    return runpy.run_path(str(seed_script))


def postprocess_jsonl_output(
    jsonl_output: Path,
    *,
    csv_output: Path | None,
    upsert_postgres: bool,
    truncate_postgres: bool,
    postgres_batch_size: int,
) -> None:
    if csv_output is None and not upsert_postgres:
        return

    helpers = _load_allrecipes_seed_helpers()
    load_jsonl_rows = helpers["load_jsonl_rows"]
    write_csv = helpers["write_csv"]
    upsert_rows = helpers["upsert_rows"]

    rows, raw_count = load_jsonl_rows(jsonl_output)
    logging.info("Post-processing %s JSONL records (%s after dedupe).", raw_count, len(rows))

    if csv_output is not None:
        write_csv(rows, csv_output)
        logging.info("Wrote %s rows to CSV: %s", len(rows), csv_output)

    if upsert_postgres:
        upserted = upsert_rows(rows, truncate=truncate_postgres, batch_size=postgres_batch_size)
        logging.info("Upserted %s rows into allrecipes_recipes.", upserted)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape Allrecipes recipe data and normalize into JSONL records.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSONL path.")
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=DEFAULT_CSV_OUTPUT,
        help="Output CSV path for flattened records.",
    )
    parser.add_argument("--url", dest="urls", action="append", help="Specific recipe URL to scrape.")
    parser.add_argument("--max-urls", type=int, default=None, help="Maximum recipe URLs to process.")
    parser.add_argument("--delay", type=float, default=0.75, help="Delay between recipe fetches.")
    parser.add_argument("--jitter", type=float, default=0.25, help="Random extra delay.")
    parser.add_argument("--timeout", type=float, default=45, help="Request timeout in seconds.")
    parser.add_argument("--retries", type=int, default=3, help="Retries per request.")
    parser.add_argument("--impersonate", default="chrome124", help="scrapling browser impersonation profile.")
    parser.add_argument(
        "--skip-csv",
        action="store_true",
        help="Skip CSV export after writing JSONL.",
    )
    parser.add_argument(
        "--skip-postgres",
        action="store_true",
        help="Skip upserting records into Postgres after writing JSONL.",
    )
    parser.add_argument(
        "--truncate-postgres",
        action="store_true",
        help="Truncate allrecipes_recipes before Postgres upsert.",
    )
    parser.add_argument(
        "--postgres-batch-size",
        type=int,
        default=200,
        help="Rows per Postgres upsert batch.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console log level.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.postgres_batch_size <= 0:
        parser.error("--postgres-batch-size must be a positive integer.")

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("scrapling").setLevel(logging.WARNING)
    try:
        count = write_jsonl(scrape_allrecipes(args), args.output)
        csv_output = None if args.skip_csv else args.csv_output
        postprocess_jsonl_output(
            args.output,
            csv_output=csv_output,
            upsert_postgres=not args.skip_postgres,
            truncate_postgres=args.truncate_postgres,
            postgres_batch_size=args.postgres_batch_size,
        )
    except KeyboardInterrupt:
        logging.error("Interrupted")
        return 130
    logging.info("Saved %s recipes to %s", count, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
