from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import text

# Allow running this file directly: `py -3 backend\scripts\seed_allrecipes_recipes.py ...`
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal, init_db


REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_JSONL = REPO_ROOT / "data" / "Recipes" / "allrecipes_recipes.jsonl"
DEFAULT_CSV = REPO_ROOT / "data" / "Recipes" / "allrecipes_recipes.csv"

CSV_HEADERS = [
    "source_url",
    "source",
    "recipe_id",
    "stable_slug",
    "title",
    "cuisine",
    "category",
    "meal_type",
    "author_name",
    "servings",
    "prep_minutes",
    "cook_minutes",
    "total_minutes",
    "calories_kcal",
    "protein_g",
    "carbohydrates_g",
    "fat_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
    "rating",
    "review_count",
    "date_published",
    "date_modified",
    "ingredients_json",
    "directions_json",
    "cooking_methods_json",
    "equipment_json",
    "nutrition_facts_raw_json",
    "nutrition_quality_json",
    "tags_json",
    "dietary_flags_json",
    "allergen_flags_json",
    "possible_allergen_flags_json",
    "allergen_basis_json",
    "allergen_confidence_json",
    "difficulty",
    "data_quality_flags_json",
    "completeness_score",
    "normalization_quality_score",
    "recipe_quality_score",
    "attribution_json",
]


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _json_text(value: Any, *, default: Any) -> str:
    if value is None:
        value = default
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_source_url(value: Any) -> str | None:
    text_value = _as_text(value)
    if not text_value:
        return None
    parsed = urlparse(text_value)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", ""))


def _dedupe_key(row: dict[str, Any]) -> str:
    recipe_id = _as_text(row.get("recipe_id"))
    if recipe_id:
        return f"id:{recipe_id}"
    stable_slug = _as_text(row.get("stable_slug"))
    if stable_slug:
        return f"slug:{stable_slug.lower()}"
    source_url = _as_text(row.get("source_url")) or ""
    return f"url:{source_url}"


def _flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    times = record.get("times") if isinstance(record.get("times"), dict) else {}
    nutrition_per_serving = (
        record.get("nutrition_per_serving")
        if isinstance(record.get("nutrition_per_serving"), dict)
        else {}
    )

    return {
        "source_url": _normalize_source_url(record.get("source_url")),
        "source": _as_text(record.get("source")) or "allrecipes",
        "recipe_id": _as_text(record.get("recipe_id")),
        "stable_slug": _as_text(record.get("stable_slug")),
        "title": _as_text(record.get("title")),
        "cuisine": _as_text(record.get("cuisine")),
        "category": _as_text(record.get("category")),
        "meal_type": _as_text(record.get("meal_type")),
        "author_name": _as_text(record.get("author_name")),
        "servings": _as_float(record.get("servings")),
        "prep_minutes": _as_int(times.get("prep_minutes")),
        "cook_minutes": _as_int(times.get("cook_minutes")),
        "total_minutes": _as_int(times.get("total_minutes")),
        "calories_kcal": _as_float(nutrition_per_serving.get("calories_kcal")),
        "protein_g": _as_float(nutrition_per_serving.get("protein_g")),
        "carbohydrates_g": _as_float(nutrition_per_serving.get("carbohydrates_g")),
        "fat_g": _as_float(nutrition_per_serving.get("fat_g")),
        "fiber_g": _as_float(nutrition_per_serving.get("fiber_g")),
        "sugar_g": _as_float(nutrition_per_serving.get("sugar_g")),
        "sodium_mg": _as_float(nutrition_per_serving.get("sodium_mg")),
        "rating": _as_float(record.get("rating")),
        "review_count": _as_int(record.get("review_count")),
        "date_published": _as_text(record.get("date_published")),
        "date_modified": _as_text(record.get("date_modified")),
        "ingredients_json": _json_text(record.get("ingredients"), default=[]),
        "directions_json": _json_text(record.get("directions_json"), default=[]),
        "cooking_methods_json": _json_text(record.get("cooking_methods"), default=[]),
        "equipment_json": _json_text(record.get("equipment"), default=[]),
        "nutrition_facts_raw_json": _json_text(record.get("nutrition_facts_raw"), default={}),
        "nutrition_quality_json": _json_text(record.get("nutrition_quality"), default={}),
        "tags_json": _json_text(record.get("tags"), default=[]),
        "dietary_flags_json": _json_text(record.get("dietary_flags"), default={}),
        "allergen_flags_json": _json_text(record.get("allergen_flags"), default=[]),
        "possible_allergen_flags_json": _json_text(record.get("possible_allergen_flags"), default=[]),
        "allergen_basis_json": _json_text(record.get("allergen_basis"), default={}),
        "allergen_confidence_json": _json_text(record.get("allergen_confidence"), default={}),
        "difficulty": _as_text(record.get("difficulty")),
        "data_quality_flags_json": _json_text(record.get("data_quality_flags"), default=[]),
        "completeness_score": _as_float(record.get("completeness_score")),
        "normalization_quality_score": _as_float(record.get("normalization_quality_score")),
        "recipe_quality_score": _as_float(record.get("recipe_quality_score")),
        "attribution_json": _json_text(record.get("attribution"), default={}),
    }


def load_jsonl_rows(jsonl_path: Path) -> tuple[list[dict[str, Any]], int]:
    deduped: dict[str, dict[str, Any]] = {}
    raw_count = 0
    with jsonl_path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line:
                continue
            raw_count += 1
            record = json.loads(line)
            flat = _flatten_record(record)
            if flat["source_url"] and flat["title"]:
                deduped[_dedupe_key(flat)] = flat
    return list(deduped.values()), raw_count


def write_csv(rows: list[dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def _flush_batch(rows: list[dict[str, Any]], *, truncate: bool) -> int:
    with SessionLocal.begin() as session:
        if truncate:
            session.execute(text("TRUNCATE TABLE allrecipes_recipes"))
        session.execute(
            text(
                """
                INSERT INTO allrecipes_recipes (
                    source_url,
                    source,
                    recipe_id,
                    stable_slug,
                    title,
                    cuisine,
                    category,
                    meal_type,
                    author_name,
                    servings,
                    prep_minutes,
                    cook_minutes,
                    total_minutes,
                    calories_kcal,
                    protein_g,
                    carbohydrates_g,
                    fat_g,
                    fiber_g,
                    sugar_g,
                    sodium_mg,
                    rating,
                    review_count,
                    date_published,
                    date_modified,
                    ingredients,
                    directions_json,
                    cooking_methods,
                    equipment,
                    nutrition_facts_raw,
                    nutrition_quality,
                    tags,
                    dietary_flags,
                    allergen_flags,
                    possible_allergen_flags,
                    allergen_basis,
                    allergen_confidence,
                    difficulty,
                    data_quality_flags,
                    completeness_score,
                    normalization_quality_score,
                    recipe_quality_score,
                    attribution
                )
                VALUES (
                    :source_url,
                    :source,
                    :recipe_id,
                    :stable_slug,
                    :title,
                    :cuisine,
                    :category,
                    :meal_type,
                    :author_name,
                    :servings,
                    :prep_minutes,
                    :cook_minutes,
                    :total_minutes,
                    :calories_kcal,
                    :protein_g,
                    :carbohydrates_g,
                    :fat_g,
                    :fiber_g,
                    :sugar_g,
                    :sodium_mg,
                    :rating,
                    :review_count,
                    :date_published,
                    :date_modified,
                    CAST(:ingredients_json AS jsonb),
                    CAST(:directions_json AS jsonb),
                    CAST(:cooking_methods_json AS jsonb),
                    CAST(:equipment_json AS jsonb),
                    CAST(:nutrition_facts_raw_json AS jsonb),
                    CAST(:nutrition_quality_json AS jsonb),
                    CAST(:tags_json AS jsonb),
                    CAST(:dietary_flags_json AS jsonb),
                    CAST(:allergen_flags_json AS jsonb),
                    CAST(:possible_allergen_flags_json AS jsonb),
                    CAST(:allergen_basis_json AS jsonb),
                    CAST(:allergen_confidence_json AS jsonb),
                    :difficulty,
                    CAST(:data_quality_flags_json AS jsonb),
                    :completeness_score,
                    :normalization_quality_score,
                    :recipe_quality_score,
                    CAST(:attribution_json AS jsonb)
                )
                ON CONFLICT (source_url)
                DO UPDATE SET
                    source = EXCLUDED.source,
                    recipe_id = EXCLUDED.recipe_id,
                    stable_slug = EXCLUDED.stable_slug,
                    title = EXCLUDED.title,
                    cuisine = EXCLUDED.cuisine,
                    category = EXCLUDED.category,
                    meal_type = EXCLUDED.meal_type,
                    author_name = EXCLUDED.author_name,
                    servings = EXCLUDED.servings,
                    prep_minutes = EXCLUDED.prep_minutes,
                    cook_minutes = EXCLUDED.cook_minutes,
                    total_minutes = EXCLUDED.total_minutes,
                    calories_kcal = EXCLUDED.calories_kcal,
                    protein_g = EXCLUDED.protein_g,
                    carbohydrates_g = EXCLUDED.carbohydrates_g,
                    fat_g = EXCLUDED.fat_g,
                    fiber_g = EXCLUDED.fiber_g,
                    sugar_g = EXCLUDED.sugar_g,
                    sodium_mg = EXCLUDED.sodium_mg,
                    rating = EXCLUDED.rating,
                    review_count = EXCLUDED.review_count,
                    date_published = EXCLUDED.date_published,
                    date_modified = EXCLUDED.date_modified,
                    ingredients = EXCLUDED.ingredients,
                    directions_json = EXCLUDED.directions_json,
                    cooking_methods = EXCLUDED.cooking_methods,
                    equipment = EXCLUDED.equipment,
                    nutrition_facts_raw = EXCLUDED.nutrition_facts_raw,
                    nutrition_quality = EXCLUDED.nutrition_quality,
                    tags = EXCLUDED.tags,
                    dietary_flags = EXCLUDED.dietary_flags,
                    allergen_flags = EXCLUDED.allergen_flags,
                    possible_allergen_flags = EXCLUDED.possible_allergen_flags,
                    allergen_basis = EXCLUDED.allergen_basis,
                    allergen_confidence = EXCLUDED.allergen_confidence,
                    difficulty = EXCLUDED.difficulty,
                    data_quality_flags = EXCLUDED.data_quality_flags,
                    completeness_score = EXCLUDED.completeness_score,
                    normalization_quality_score = EXCLUDED.normalization_quality_score,
                    recipe_quality_score = EXCLUDED.recipe_quality_score,
                    attribution = EXCLUDED.attribution
                """
            ),
            rows,
        )
    return len(rows)


def upsert_rows(rows: list[dict[str, Any]], *, truncate: bool, batch_size: int) -> int:
    init_db()
    total = 0
    batch: list[dict[str, Any]] = []

    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            total += _flush_batch(batch, truncate=truncate and total == 0)
            batch.clear()

    if batch:
        total += _flush_batch(batch, truncate=truncate and total == 0)

    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Allrecipes JSONL into CSV and upsert into allrecipes_recipes."
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEFAULT_JSONL,
        help="Path to input JSONL scraped from Allrecipes.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Path to output CSV file.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate allrecipes_recipes before loading.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Rows per batch insert.",
    )
    args = parser.parse_args()

    if not args.jsonl.exists():
        raise FileNotFoundError(f"JSONL not found: {args.jsonl}")

    rows, raw_count = load_jsonl_rows(args.jsonl)
    write_csv(rows, args.csv)
    upserted = upsert_rows(rows, truncate=args.truncate, batch_size=args.batch_size)

    print(f"Loaded {raw_count} JSONL records ({len(rows)} after dedupe).")
    print(f"Wrote {len(rows)} rows to CSV: {args.csv}")
    print(f"Upserted {upserted} rows into allrecipes_recipes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
