#!/usr/bin/env python3
"""
Estimate recipe prices from:
1) Carrefour product CSV
2) Recipe JSON / JSONL / concatenated JSON objects

Example:
    py backend/scripts/estimate_recipe_prices.py --limit 10

Notes:
- Product prices are treated as EGP.
- If category_level_1 == "Fresh Food" and no size is found in the product name,
  the product price is treated as price per 1 kg.
- Matching is heuristic. Review low-confidence matches before trusting totals.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

import pandas as pd


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_PRODUCTS_CSV = REPO_ROOT / "data" / "Food" / "carrefour_barcode_products.csv"
DEFAULT_RECIPES_JSONL = REPO_ROOT / "data" / "Recipes" / "allrecipes_recipes.jsonl"
DEFAULT_SUMMARY_CSV = REPO_ROOT / "data" / "Recipes" / "recipe_price_estimates.csv"
DEFAULT_DETAILS_CSV = REPO_ROOT / "data" / "Recipes" / "ingredient_price_details.csv"


# -----------------------------
# Unit conversion assumptions
# -----------------------------

GRAM_UNITS = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "gm": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "mg": 0.001,
    "milligram": 0.001,
    "milligrams": 0.001,
    "oz": 28.349523125,
    "ounce": 28.349523125,
    "ounces": 28.349523125,
    "lb": 453.59237,
    "lbs": 453.59237,
    "pound": 453.59237,
    "pounds": 453.59237,
}

ML_UNITS = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
    "litre": 1000.0,
    "litres": 1000.0,
    "cup": 240.0,
    "cups": 240.0,
    "tablespoon": 15.0,
    "tablespoons": 15.0,
    "tbsp": 15.0,
    "teaspoon": 5.0,
    "teaspoons": 5.0,
    "tsp": 5.0,
    "quart": 946.352946,
    "quarts": 946.352946,
    "pint": 473.176473,
    "pints": 473.176473,
    "fluid ounce": 29.5735295625,
    "fl oz": 29.5735295625,
}

# Approximate density g/ml for common ingredients measured by volume.
# These are practical kitchen-pricing estimates, not lab-grade measurements.
DENSITY_G_PER_ML = {
    "water": 1.00,
    "milk": 1.03,
    "buttermilk": 1.03,
    "yogurt": 1.03,
    "plain_yogurt": 1.03,
    "oil": 0.92,
    "vegetable_oil": 0.92,
    "olive_oil": 0.91,
    "vinegar": 1.00,
    "distilled_white_vinegar": 1.00,
    "honey": 1.42,
    "sugar": 0.85,
    "brown_sugar": 0.85,
    "powdered_sugar": 0.50,
    "flour_all_purpose": 0.53,
    "all_purpose_flour": 0.53,
    "flour": 0.53,
    "rice": 0.78,
    "uncooked_instant_rice": 0.78,
    "cornmeal": 0.67,
    "fine_cornmeal": 0.67,
    "salt": 1.20,
    "black_pepper": 0.50,
    "chili_powder": 0.50,
    "cumin": 0.45,
    "garlic_powder": 0.55,
    "dried_oregano": 0.20,
    "dried_basil": 0.20,
    "red_pepper_flakes": 0.25,
}

# Approximate edible weights for whole-count ingredients.
# Use only when the recipe gives quantity without weight/volume.
EACH_WEIGHT_G = {
    "onion": 150.0,
    "onions": 150.0,
    "white_onions": 150.0,
    "small_onion": 110.0,
    "large_onion": 225.0,
    "lime": 67.0,
    "lemon": 84.0,
    "garlic": 3.0,          # clove
    "garlic_clove": 3.0,
    "ginger": 15.0,        # 1-inch piece
    "green_bell_peppers": 164.0,
    "bell_pepper": 164.0,
    "egg": 50.0,
    "eggs": 50.0,
    "chicken_breasts": 174.0,
    "chicken_breast": 174.0,
}

# Ingredients that should not contribute to grocery cost.
FREE_INGREDIENTS = {"water"}

# Ingredients that should not be priced when no exact quantity exists.
# Examples: "salt and pepper to taste", "seasoning to taste".
SKIP_IF_NO_QUANTITY_KEYWORDS = {
    "to_taste", "salt_and_pepper", "salt_and_black_pepper",
    "salt_and_freshly_ground_black_pepper", "seasoning",
}

# Ingredient-specific reject words. These prevent false matches such as:
#   "salt and pepper" -> "Red Bell Pepper"
#   "rice" -> "Chicken and Herbs Flavor Instant Rice - 90 gm"
PRODUCT_REJECT_RULES = {
    "rice": {"chicken", "beef", "shrimp", "herbs", "flavor", "flavoured", "flavored", "ready", "meal", "cup", "noodles"},
    "uncooked_instant_rice": {"chicken", "beef", "shrimp", "herbs", "flavor", "flavoured", "flavored", "ready", "meal", "cup", "noodles"},
    "black_pepper": {"bell", "green", "red", "yellow", "capsicum", "vegetable", "fresh"},
    "salt_and_pepper": {"bell", "green", "red", "yellow", "capsicum", "vegetable", "fresh"},
    "salt_and_black_pepper": {"bell", "green", "red", "yellow", "capsicum", "vegetable", "fresh"},
}

STAPLE_KEYS = {"rice", "uncooked_instant_rice", "flour", "flour_all_purpose", "all_purpose_flour", "sugar", "salt"}
GLOBAL_MIN_MATCH_SCORE = 0.65

# Product-name words that add noise during matching.
STOPWORDS = {
    "fresh", "frozen", "pack", "packet", "can", "jar", "bottle", "box", "bag",
    "large", "small", "medium", "chopped", "sliced", "ground", "minced", "dried",
    "organic", "premium", "classic", "natural", "original", "plain", "for", "with",
    "and", "the", "of", "in", "a", "an", "to", "taste", "added", "no", "salt",
}

SIZE_RE = re.compile(
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>kg|kilogram|kilograms|g|gm|gram|grams|mg|ml|l|liter|liters|litre|litres|oz|ounce|ounces|lb|lbs|pound|pounds)\b",
    re.IGNORECASE,
)


@dataclass
class Amount:
    quantity: float
    unit_type: str  # "g", "ml", "unit", or "unknown"


@dataclass
class ProductMatch:
    idx: Optional[int]
    name: Optional[str]
    brand: Optional[str]
    category_level_1: Optional[str]
    price: Optional[float]
    package_amount: Optional[Amount]
    score: float
    confidence: str


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [w for w in text.split() if w and w not in STOPWORDS]
    return " ".join(words)


def normalize_unit(unit: Any) -> Optional[str]:
    if unit is None or (isinstance(unit, float) and math.isnan(unit)):
        return None
    unit = str(unit).strip().lower().replace(".", "")
    aliases = {
        "kgs": "kg",
        "kilograms": "kg",
        "kilogram": "kg",
        "grams": "gram",
        "grammes": "gram",
        "gms": "gm",
        "milliliters": "ml",
        "milliliter": "ml",
        "liters": "liter",
        "litres": "liter",
        "tablespoons": "tablespoon",
        "tbsp": "tablespoon",
        "teaspoons": "teaspoon",
        "tsp": "teaspoon",
        "ounces": "ounce",
        "oz": "ounce",
        "pounds": "pound",
        "lbs": "pound",
        "lb": "pound",
    }
    return aliases.get(unit, unit)


def convert_package_size(size: dict[str, Any] | None, multiplier: float = 1.0) -> Optional[Amount]:
    if not size:
        return None
    try:
        qty = float(size.get("quantity")) * multiplier
    except Exception:
        return None
    unit = normalize_unit(size.get("unit"))
    return convert_quantity(qty, unit, ingredient_key=None)


def convert_quantity(qty: Optional[float], unit: Optional[str], ingredient_key: Optional[str]) -> Optional[Amount]:
    if qty is None:
        return None
    try:
        qty = float(qty)
    except Exception:
        return None

    unit = normalize_unit(unit)
    key = normalize_ingredient_key(ingredient_key)

    if unit is None:
        if key in EACH_WEIGHT_G:
            return Amount(qty * EACH_WEIGHT_G[key], "g")
        return Amount(qty, "unit")

    if unit in GRAM_UNITS:
        return Amount(qty * GRAM_UNITS[unit], "g")

    if unit in ML_UNITS:
        ml = qty * ML_UNITS[unit]
        # For dry ingredients measured by volume, estimate grams using density.
        if key in DENSITY_G_PER_ML and key not in {"water", "milk", "buttermilk", "yogurt", "plain_yogurt", "oil", "vegetable_oil", "olive_oil", "vinegar", "distilled_white_vinegar"}:
            return Amount(ml * DENSITY_G_PER_ML[key], "g")
        return Amount(ml, "ml")

    if unit in {"clove", "cloves"}:
        return Amount(qty * 3.0, "g")

    if unit in {"pinch"}:
        return Amount(qty * 0.35, "g")

    if unit in {"dash"}:
        return Amount(qty * 0.6, "ml")

    if unit in {"can", "jar", "packet", "package", "bottle", "box", "bag"}:
        return Amount(qty, "unit")

    if key in EACH_WEIGHT_G:
        return Amount(qty * EACH_WEIGHT_G[key], "g")

    return Amount(qty, "unit")


def normalize_ingredient_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value).lower().strip().replace("-", "_").replace(" ", "_")


def parse_product_size_from_name(name: str) -> Optional[Amount]:
    if not isinstance(name, str):
        return None

    matches = list(SIZE_RE.finditer(name))
    if not matches:
        return None

    # Use the last size in the product name, usually the package size.
    match = matches[-1]
    qty = float(match.group("qty").replace(",", "."))
    unit = normalize_unit(match.group("unit"))
    return convert_quantity(qty, unit, ingredient_key=None)


def amount_compatible(a: Optional[Amount], b: Optional[Amount]) -> bool:
    if a is None or b is None:
        return False
    if a.unit_type == b.unit_type:
        return True
    # Allow gram/ml comparison for liquids using approximate density.
    return {a.unit_type, b.unit_type} == {"g", "ml"}


def convert_between_g_ml(amount: Amount, target_unit_type: str, ingredient_key: str) -> Amount:
    if amount.unit_type == target_unit_type:
        return amount
    density = DENSITY_G_PER_ML.get(normalize_ingredient_key(ingredient_key), 1.0)
    if amount.unit_type == "ml" and target_unit_type == "g":
        return Amount(amount.quantity * density, "g")
    if amount.unit_type == "g" and target_unit_type == "ml":
        return Amount(amount.quantity / density, "ml")
    return amount


def load_recipes(path: str | Path, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Load JSON array, JSONL, or concatenated JSON objects."""
    path = Path(path)
    # Fast path for JSONL: stream line by line so huge files do not appear stuck.
    if path.suffix.lower() == ".jsonl":
        recipes = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                recipes.append(json.loads(line))
                if limit is not None and len(recipes) >= limit:
                    break
        return recipes

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    # Normal JSON array or single object.
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj[:limit] if limit is not None else obj
        if isinstance(obj, dict):
            return [obj]
    except json.JSONDecodeError:
        pass

    # JSONL.
    recipes = []
    jsonl_ok = True
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recipes.append(json.loads(line))
        except json.JSONDecodeError:
            jsonl_ok = False
            recipes = []
            break
    if jsonl_ok and recipes:
        return recipes[:limit] if limit is not None else recipes

    # Concatenated JSON objects: {...}{...}{...}
    decoder = json.JSONDecoder()
    idx = 0
    recipes = []
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        obj, end = decoder.raw_decode(text, idx)
        if isinstance(obj, dict):
            recipes.append(obj)
        elif isinstance(obj, list):
            recipes.extend(obj)
        if limit is not None and len(recipes) >= limit:
            return recipes[:limit]
        idx = end
    return recipes[:limit] if limit is not None else recipes


def prepare_products(products_csv: str | Path) -> pd.DataFrame:
    df = pd.read_csv(products_csv)
    required = {"name", "price", "category_level_1"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Products CSV is missing required columns: {sorted(missing)}")

    df = df.copy()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["name", "price"]).reset_index(drop=True)
    df["match_text"] = (
        df["name"].fillna("").astype(str) + " " +
        df.get("brand", "").fillna("").astype(str) + " " +
        df.get("category_level_2", "").fillna("").astype(str) + " " +
        df.get("category_level_3", "").fillna("").astype(str) + " " +
        df.get("category_level_4", "").fillna("").astype(str)
    ).map(normalize_text)
    df["product_size"] = df["name"].map(parse_product_size_from_name)

    # User-provided rule: Fresh Food without explicit product size is treated as 1 kg.
    fresh_mask = df["category_level_1"].astype(str).str.lower().eq("fresh food")
    df.loc[fresh_mask & df["product_size"].isna(), "product_size"] = [Amount(1000.0, "g")] * int((fresh_mask & df["product_size"].isna()).sum())
    return df


def token_overlap_score(query: str, candidate: str) -> float:
    q_tokens = set(query.split())
    c_tokens = set(candidate.split())
    if not q_tokens or not c_tokens:
        return 0.0
    return len(q_tokens & c_tokens) / len(q_tokens)


def similarity_score(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    seq = SequenceMatcher(None, query, candidate).ratio()
    overlap = token_overlap_score(query, candidate)
    contains = 1.0 if query in candidate else 0.0
    return 0.50 * overlap + 0.35 * seq + 0.15 * contains


def confidence_from_score(score: float) -> str:
    if score >= 0.72:
        return "high"
    if score >= 0.50:
        return "medium"
    if score >= 0.35:
        return "low"
    return "very_low"


def ingredient_family(key_or_name: str) -> str:
    key = normalize_ingredient_key(key_or_name)
    if "rice" in key:
        return "rice"
    if "black_pepper" in key or key in {"pepper", "salt_and_pepper", "salt_and_black_pepper"}:
        return "black_pepper"
    if "cheddar" in key:
        return "cheddar_cheese"
    if "bell_pepper" in key or "green_bell_pepper" in key:
        return "bell_pepper"
    if "tomato_soup" in key:
        return "tomato_soup"
    return key


def product_rejected_for_ingredient(ingredient_key: str, product_match_text: str) -> bool:
    family = ingredient_family(ingredient_key)
    tokens = set(str(product_match_text).split())
    reject = PRODUCT_REJECT_RULES.get(family, set()) | PRODUCT_REJECT_RULES.get(normalize_ingredient_key(ingredient_key), set())
    return bool(tokens & reject)


def product_bonus_or_penalty(ingredient_key: str, needed_amount: Optional[Amount], product_amount: Optional[Amount], product_match_text: str) -> float:
    key = normalize_ingredient_key(ingredient_key)
    family = ingredient_family(key)
    tokens = set(str(product_match_text).split())
    score_delta = 0.0

    # For dry staples, prefer normal grocery packages over tiny flavored snack/meal packs.
    if family in {"rice"}:
        if product_amount and product_amount.unit_type == "g":
            if product_amount.quantity < 250:
                score_delta -= 0.25
            elif product_amount.quantity >= 500:
                score_delta += 0.10
        if {"basmati", "egyptian", "white", "jasmine", "brown", "rice"} & tokens:
            score_delta += 0.04

    # Black pepper should not match bell peppers; prefer powder/ground/spice products.
    if family == "black_pepper":
        if {"powder", "ground", "spice", "black"} & tokens:
            score_delta += 0.10
        if {"bell", "green", "red", "yellow", "capsicum"} & tokens:
            score_delta -= 0.40

    # Bell pepper should prefer Fresh Food vegetables, not spice pepper.
    if family == "bell_pepper":
        if {"bell", "pepper"} <= tokens:
            score_delta += 0.10
        if {"powder", "ground", "spice"} & tokens:
            score_delta -= 0.25

    return score_delta


def find_best_product(products: pd.DataFrame, ingredient_name: str, needed_amount: Optional[Amount], ingredient_key: Optional[str] = None) -> ProductMatch:
    ingredient_key = ingredient_key or ingredient_name
    query = normalize_text(ingredient_name)
    if not query:
        return ProductMatch(None, None, None, None, None, None, 0.0, "very_low")

    # First restrict to candidates with at least one token overlap when possible.
    q_tokens = set(query.split())
    candidates = products
    if q_tokens:
        mask = products["match_text"].map(lambda x: bool(q_tokens & set(str(x).split())))
        if mask.any():
            candidates = products[mask]

    best = None
    best_score = -1.0

    # Avoid scanning too many rows when candidate set is large.
    for idx, row in candidates.iterrows():
        product_text = row["match_text"]
        if product_rejected_for_ingredient(str(ingredient_key), product_text):
            continue

        score = similarity_score(query, product_text)

        # Slight bonus when product package unit is compatible with recipe amount.
        product_amount = row.get("product_size")
        if amount_compatible(needed_amount, product_amount):
            score += 0.07

        score += product_bonus_or_penalty(str(ingredient_key), needed_amount, product_amount, product_text)

        # Penalize unrelated beverage matches for solid food ingredients.
        cat1 = str(row.get("category_level_1", "")).lower()
        if needed_amount and needed_amount.unit_type == "g" and cat1 == "beverages":
            score -= 0.08

        if score > best_score:
            best_score = score
            best = (idx, row)

    if best is None:
        return ProductMatch(None, None, None, None, None, None, 0.0, "very_low")

    idx, row = best
    score = max(0.0, min(1.0, best_score))
    return ProductMatch(
        idx=int(idx),
        name=row.get("name"),
        brand=row.get("brand"),
        category_level_1=row.get("category_level_1"),
        price=float(row.get("price")),
        package_amount=row.get("product_size"),
        score=score,
        confidence=confidence_from_score(score),
    )


def ingredient_needed_amount(ingredient: dict[str, Any]) -> Optional[Amount]:
    key = ingredient.get("canonical_ingredient_id") or ingredient.get("name_normalized") or ingredient.get("raw")
    qty = ingredient.get("quantity")
    unit = ingredient.get("unit")

    # If recipe says "1 (15 ounce) can beans", use quantity * package_size.
    package_size = ingredient.get("package_size")
    unit_norm = normalize_unit(unit)
    if package_size and unit_norm in {"can", "jar", "packet", "package", "bottle", "box", "bag"}:
        amount = convert_package_size(package_size, multiplier=float(qty or 1.0))
        if amount:
            return amount

    return convert_quantity(qty, unit_norm, key)


def estimate_ingredient_cost(ingredient: dict[str, Any], products: pd.DataFrame) -> dict[str, Any]:
    name = ingredient.get("name_normalized") or ingredient.get("canonical_ingredient_id") or ingredient.get("raw") or ""
    key = ingredient.get("canonical_ingredient_id") or name
    key_norm = normalize_ingredient_key(key)
    needed = ingredient_needed_amount(ingredient)
    raw_text = str(ingredient.get("raw") or "").lower()

    # Do not price vague ingredients such as "salt and pepper to taste".
    if needed is None or (ingredient.get("quantity") is None and ("to taste" in raw_text or key_norm in SKIP_IF_NO_QUANTITY_KEYWORDS)):
        return {
            "ingredient_raw": ingredient.get("raw"),
            "ingredient_name": name,
            "needed_quantity": None,
            "needed_unit_type": None,
            "matched_product": None,
            "matched_brand": None,
            "matched_category_level_1": None,
            "product_price_egp": None,
            "product_package_quantity": None,
            "product_package_unit_type": None,
            "estimated_used_cost_egp": None,
            "match_score": 0.0,
            "match_confidence": "skipped",
            "pricing_method": "skipped_missing_or_vague_quantity",
        }

    if key_norm in FREE_INGREDIENTS:
        return {
            "ingredient_raw": ingredient.get("raw"),
            "ingredient_name": name,
            "needed_quantity": needed.quantity if needed else None,
            "needed_unit_type": needed.unit_type if needed else None,
            "matched_product": None,
            "matched_brand": None,
            "matched_category_level_1": None,
            "product_price_egp": 0.0,
            "product_package_quantity": None,
            "product_package_unit_type": None,
            "estimated_used_cost_egp": 0.0,
            "match_score": 1.0,
            "match_confidence": "free_ingredient",
            "pricing_method": "ignored_free_ingredient",
        }

    match = find_best_product(products, str(name), needed, ingredient_key=str(key_norm))

    if match.score < GLOBAL_MIN_MATCH_SCORE:
        return {
            "ingredient_raw": ingredient.get("raw"),
            "ingredient_name": name,
            "needed_quantity": needed.quantity if needed else None,
            "needed_unit_type": needed.unit_type if needed else None,
            "matched_product": match.name,
            "matched_brand": match.brand,
            "matched_category_level_1": match.category_level_1,
            "product_price_egp": match.price,
            "product_package_quantity": match.package_amount.quantity if match.package_amount else None,
            "product_package_unit_type": match.package_amount.unit_type if match.package_amount else None,
            "estimated_used_cost_egp": None,
            "match_score": round(match.score, 3),
            "match_confidence": "rejected_low_score",
            "pricing_method": "rejected_below_min_match_score",
        }

    cost = None
    method = "unpriced"
    package_qty = None
    package_unit = None

    if match.price is not None:
        if needed and match.package_amount and amount_compatible(needed, match.package_amount):
            adjusted_needed = convert_between_g_ml(needed, match.package_amount.unit_type, key_norm)
            package_qty = match.package_amount.quantity
            package_unit = match.package_amount.unit_type
            if package_qty and package_qty > 0:
                cost = (adjusted_needed.quantity / package_qty) * match.price
                method = "proportional_by_package_size"
        elif needed and needed.unit_type == "unit":
            # If the recipe asks for one can/jar/packet but no comparable package size exists,
            # treat it as buying/using one matched product package.
            cost = needed.quantity * match.price
            method = "unit_count_times_package_price"
        elif needed is None:
            cost = None
            method = "missing_recipe_quantity"
        else:
            # Fallback: full package price. This is safer than pretending precision.
            cost = match.price
            method = "fallback_full_package_price"

    return {
        "ingredient_raw": ingredient.get("raw"),
        "ingredient_name": name,
        "needed_quantity": needed.quantity if needed else None,
        "needed_unit_type": needed.unit_type if needed else None,
        "matched_product": match.name,
        "matched_brand": match.brand,
        "matched_category_level_1": match.category_level_1,
        "product_price_egp": match.price,
        "product_package_quantity": package_qty,
        "product_package_unit_type": package_unit,
        "estimated_used_cost_egp": round(cost, 2) if cost is not None else None,
        "match_score": round(match.score, 3),
        "match_confidence": match.confidence,
        "pricing_method": method,
    }


def estimate_recipes(products_csv: str | Path, recipes_path: str | Path, limit: Optional[int] = None, progress_every: int = 100) -> tuple[pd.DataFrame, pd.DataFrame]:
    products = prepare_products(products_csv)
    recipes = load_recipes(recipes_path, limit=limit)

    if not recipes:
        raise ValueError("No recipes found. Expected JSON array, JSONL, or concatenated JSON objects.")

    recipe_rows = []
    detail_rows = []

    for recipe_index, recipe in enumerate(recipes, start=1):
        if progress_every and recipe_index % progress_every == 0:
            print(f"Processed {recipe_index}/{len(recipes)} recipes...", flush=True)
        recipe_id = recipe.get("recipe_id")
        title = recipe.get("title")
        servings = recipe.get("servings") or 1
        try:
            servings_float = float(servings)
        except Exception:
            servings_float = 1.0

        ingredients = recipe.get("ingredients") or []
        priced_costs = []
        low_confidence_count = 0
        unpriced_count = 0

        for ing in ingredients:
            detail = estimate_ingredient_cost(ing, products)
            detail.update({
                "recipe_id": recipe_id,
                "recipe_title": title,
                "servings": servings,
            })
            detail_rows.append(detail)

            cost = detail["estimated_used_cost_egp"]
            if cost is None:
                unpriced_count += 1
            else:
                priced_costs.append(float(cost))

            if detail["match_confidence"] in {"low", "very_low"}:
                low_confidence_count += 1

        total = round(sum(priced_costs), 2)
        recipe_rows.append({
            "recipe_id": recipe_id,
            "title": title,
            "servings": servings,
            "estimated_total_cost_egp": total,
            "estimated_cost_per_serving_egp": round(total / servings_float, 2) if servings_float else None,
            "ingredient_count": len(ingredients),
            "priced_ingredient_count": len(priced_costs),
            "unpriced_ingredient_count": unpriced_count,
            "low_confidence_match_count": low_confidence_count,
            "source_url": recipe.get("source_url") or (recipe.get("attribution") or {}).get("source_url"),
        })

    return pd.DataFrame(recipe_rows), pd.DataFrame(detail_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate recipe prices from Carrefour products and recipe JSON.")
    parser.add_argument(
        "--products",
        type=Path,
        default=DEFAULT_PRODUCTS_CSV,
        help="Path to Carrefour products CSV.",
    )
    parser.add_argument(
        "--recipes",
        type=Path,
        default=DEFAULT_RECIPES_JSONL,
        help="Path to recipe JSON, JSONL, or concatenated JSON objects.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_SUMMARY_CSV,
        help="Output summary CSV.",
    )
    parser.add_argument(
        "--details",
        type=Path,
        default=DEFAULT_DETAILS_CSV,
        help="Output ingredient-level CSV.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional output summary JSON.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N recipes")
    parser.add_argument("--min-match-score", type=float, default=0.65, help="Reject product matches below this score")
    parser.add_argument("--progress-every", type=int, default=100, help="Print progress every N recipes; use 0 to disable")
    args = parser.parse_args()

    global GLOBAL_MIN_MATCH_SCORE
    GLOBAL_MIN_MATCH_SCORE = args.min_match_score

    summary_df, details_df = estimate_recipes(
        args.products,
        args.recipes,
        limit=args.limit,
        progress_every=args.progress_every,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.details.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(args.out, index=False, encoding="utf-8-sig")
    details_df.to_csv(args.details, index=False, encoding="utf-8-sig")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        summary_df.to_json(args.json_out, orient="records", force_ascii=False, indent=2)

    print(f"Recipes priced: {len(summary_df)}")
    print(f"Summary saved to: {args.out}")
    print(f"Ingredient details saved to: {args.details}")
    print("\nPreview:")
    print(summary_df.head(10).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
