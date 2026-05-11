from __future__ import annotations

import json
from pathlib import Path

from scripts.estimate_recipe_prices import estimate_recipes


def test_estimate_recipes_prices_known_recipe(tmp_path: Path) -> None:
    products_csv = tmp_path / "products.csv"
    products_csv.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand",
                "White Rice - 1kg,100,Food Cupboard,Rice,,,Qima Test",
                "Whole Milk - 1L,60,Dairy,Milk,,,Qima Test",
            ]
        ),
        encoding="utf-8",
    )

    recipes_json = tmp_path / "recipes.json"
    recipes_json.write_text(
        json.dumps(
            [
                {
                    "recipe_id": "recipe_test_001",
                    "title": "Rice Pudding",
                    "servings": 2,
                    "ingredients": [
                        {
                            "raw": "500 g rice",
                            "name_normalized": "rice",
                            "canonical_ingredient_id": "rice",
                            "quantity": 500,
                            "unit": "g",
                        },
                        {
                            "raw": "1 cup milk",
                            "name_normalized": "milk",
                            "canonical_ingredient_id": "milk",
                            "quantity": 1,
                            "unit": "cup",
                        },
                        {
                            "raw": "1 cup water",
                            "name_normalized": "water",
                            "canonical_ingredient_id": "water",
                            "quantity": 1,
                            "unit": "cup",
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    summary_df, details_df = estimate_recipes(
        products_csv,
        recipes_json,
        progress_every=0,
    )

    summary = summary_df.iloc[0].to_dict()
    assert summary["recipe_id"] == "recipe_test_001"
    assert summary["priced_ingredient_count"] == 3
    assert summary["unpriced_ingredient_count"] == 0
    assert summary["estimated_total_cost_egp"] == 64.4
    assert summary["estimated_cost_per_serving_egp"] == 32.2

    detail_by_name = {
        row["ingredient_name"]: row for row in details_df.to_dict(orient="records")
    }
    assert detail_by_name["rice"]["estimated_used_cost_egp"] == 50.0
    assert detail_by_name["milk"]["estimated_used_cost_egp"] == 14.4
    assert detail_by_name["water"]["estimated_used_cost_egp"] == 0.0
