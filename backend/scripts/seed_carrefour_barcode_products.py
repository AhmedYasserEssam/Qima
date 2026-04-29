from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

# Allow running this file directly: `py -3 scripts\seed_carrefour_barcode_products.py ...`
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal, init_db


REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_CSV = REPO_ROOT / "data" / "Food" / "carrefour_barcode_products.csv"

def seed(csv_path: Path, *, truncate: bool = False, batch_size: int = 500) -> int:
    init_db()

    inserted = 0
    batch: list[dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            barcode = (row.get("barcode") or "").strip()
            if not barcode:
                continue
            batch.append(
                {
                    "barcode": barcode,
                    "product_id": row.get("product_id") or None,
                    "name": row.get("name") or None,
                    "brand": row.get("brand") or None,
                    "nutrition_basis": row.get("nutrition_basis") or None,
                    "serving_size": row.get("serving_size") or None,
                    "energy_kcal": row.get("energy_kcal") or None,
                    "protein_g": row.get("protein_g") or None,
                    "carbohydrates_g": row.get("carbohydrates_g") or None,
                    "fat_g": row.get("fat_g") or None,
                    "sugars_g": row.get("sugars_g") or None,
                    "fiber_g": row.get("fiber_g") or None,
                    "sodium_mg": row.get("sodium_mg") or None,
                    "salt_g": row.get("salt_g") or None,
                    "ingredients": row.get("ingredients") or None,
                    "allergens": row.get("allergens") or None,
                    "source_provider": row.get("source_provider") or None,
                    "source_provider_product_id": row.get("source_provider_product_id") or None,
                    "source_fetched_at": row.get("source_fetched_at") or None,
                    "data_quality_completeness": row.get("data_quality_completeness") or None,
                    "price": row.get("price") or None,
                    "category_level_1": row.get("category_level_1") or None,
                    "category_level_2": row.get("category_level_2") or None,
                    "category_level_3": row.get("category_level_3") or None,
                    "category_level_4": row.get("category_level_4") or None,
                }
            )
            if len(batch) >= batch_size:
                inserted += _flush_batch(batch, truncate=truncate and inserted == 0)
                batch.clear()

    if batch:
        inserted += _flush_batch(batch, truncate=truncate and inserted == 0)

    return inserted


def _flush_batch(rows: list[dict[str, Any]], *, truncate: bool) -> int:
    with SessionLocal.begin() as session:
        if truncate:
            session.execute(text("TRUNCATE TABLE carrefour_barcode_products"))
        session.execute(
            text(
                """
                INSERT INTO carrefour_barcode_products (
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
                )
                VALUES (
                    :barcode,
                    :product_id,
                    :name,
                    :brand,
                    :nutrition_basis,
                    :serving_size,
                    :energy_kcal,
                    :protein_g,
                    :carbohydrates_g,
                    :fat_g,
                    :sugars_g,
                    :fiber_g,
                    :sodium_mg,
                    :salt_g,
                    :ingredients,
                    :allergens,
                    :source_provider,
                    :source_provider_product_id,
                    :source_fetched_at,
                    :data_quality_completeness,
                    :price,
                    :category_level_1,
                    :category_level_2,
                    :category_level_3,
                    :category_level_4
                )
                ON CONFLICT (barcode)
                DO UPDATE SET
                    product_id = EXCLUDED.product_id,
                    name = EXCLUDED.name,
                    brand = EXCLUDED.brand,
                    nutrition_basis = EXCLUDED.nutrition_basis,
                    serving_size = EXCLUDED.serving_size,
                    energy_kcal = EXCLUDED.energy_kcal,
                    protein_g = EXCLUDED.protein_g,
                    carbohydrates_g = EXCLUDED.carbohydrates_g,
                    fat_g = EXCLUDED.fat_g,
                    sugars_g = EXCLUDED.sugars_g,
                    fiber_g = EXCLUDED.fiber_g,
                    sodium_mg = EXCLUDED.sodium_mg,
                    salt_g = EXCLUDED.salt_g,
                    ingredients = EXCLUDED.ingredients,
                    allergens = EXCLUDED.allergens,
                    source_provider = EXCLUDED.source_provider,
                    source_provider_product_id = EXCLUDED.source_provider_product_id,
                    source_fetched_at = EXCLUDED.source_fetched_at,
                    data_quality_completeness = EXCLUDED.data_quality_completeness,
                    price = EXCLUDED.price,
                    category_level_1 = EXCLUDED.category_level_1,
                    category_level_2 = EXCLUDED.category_level_2,
                    category_level_3 = EXCLUDED.category_level_3,
                    category_level_4 = EXCLUDED.category_level_4
                """
            ),
            rows,
        )
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed carrefour_barcode_products table from CSV."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Path to carrefour_barcode_products.csv",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate table before loading.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows per DB batch insert.",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        raise FileNotFoundError(f"CSV not found: {args.csv}")

    count = seed(args.csv, truncate=args.truncate, batch_size=args.batch_size)
    print(f"Upserted {count} rows into carrefour_barcode_products.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
