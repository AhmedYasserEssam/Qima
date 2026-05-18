from __future__ import annotations

import json
from pathlib import Path

from app.schemas.v1.prices import RequestedIngredient
from app.services.price_service import RecipePriceEstimator
from scripts.estimate_recipe_prices import (
    estimate_ingredient_cost,
    estimate_recipes,
    prepare_products,
)


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


def test_estimate_ingredient_cost_supports_groq_meal_ingredient_shape(tmp_path: Path) -> None:
    products_csv = tmp_path / "products.csv"
    products_csv.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand",
                "White Rice - 200g,100,Food Cupboard,Rice,,,Qima Test",
            ]
        ),
        encoding="utf-8",
    )

    products = prepare_products(products_csv)
    detail = estimate_ingredient_cost(
        {
            "item": "rice",
            "amount": 100,
            "unit": "g",
            "notes": "",
        },
        products,
    )

    assert detail["matched_product"] == "White Rice - 200g"
    assert detail["product_price_egp"] == 100
    assert detail["product_package_quantity"] == 200
    assert detail["estimated_used_cost_egp"] == 50.0
    assert detail["pricing_method"] == "proportional_by_package_size"


def test_estimator_prices_canned_tuna_when_product_name_omits_canned(tmp_path: Path) -> None:
    products_csv = tmp_path / "products.csv"
    products_csv.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand",
                "John West Solid Tuna In Sunflower Oil - 170gm,119.99,Food Cupboard,Tins Jars Packets,Tuna Seafood,Tuna,John West",
            ]
        ),
        encoding="utf-8",
    )

    products = prepare_products(products_csv)
    detail = estimate_ingredient_cost(
        {
            "item": "canned tuna",
            "amount": 150,
            "unit": "g",
        },
        products,
    )

    assert detail["matched_product"] == "John West Solid Tuna In Sunflower Oil - 170gm"
    assert detail["product_package_quantity"] == 170
    assert detail["estimated_used_cost_egp"] == 105.87
    assert detail["pricing_method"] == "proportional_by_package_size"


def test_estimator_prioritizes_food_kind_over_descriptor_overlap(tmp_path: Path) -> None:
    products_csv = tmp_path / "products.csv"
    products_csv.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand",
                "Whole Chicken Curry,108.5,Fresh Food,,,,",
                "Breadway Soft Roll Bread - 170 gram,27.95,Bakery & Pastry,Bread,,,Breadway",
            ]
        ),
        encoding="utf-8",
    )

    products = prepare_products(products_csv)
    detail = estimate_ingredient_cost(
        {
            "item": "whole grain bread",
            "amount": 30,
            "unit": "g",
            "notes": "",
        },
        products,
    )

    assert detail["matched_product"] == "Breadway Soft Roll Bread - 170 gram"
    assert detail["matched_brand"] == "Breadway"
    assert detail["product_package_quantity"] == 170
    assert detail["estimated_used_cost_egp"] == 4.93
    assert detail["pricing_method"] == "proportional_by_package_size"


def test_price_service_uses_carrefour_product_dataset(tmp_path: Path) -> None:
    products_csv = tmp_path / "products.csv"
    products_csv.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand,source_fetched_at",
                "White Rice - 200g,100,Food Cupboard,Rice,,,Qima Test,2026-04-28T23:57:40+00:00",
            ]
        ),
        encoding="utf-8",
    )

    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [RequestedIngredient(name="rice", quantity=100, unit="g")],
        geography="Cairo",
    )

    assert response.source.provider == "carrefour_egypt"
    assert response.total_cost == 50.0
    assert response.item_costs[0].matched_name == "White Rice - 200g"
    assert response.item_costs[0].product_package_quantity == 200
    assert response.item_costs[0].estimated_cost == 50.0


def test_fruits_and_vegetables_prices_are_per_kg_even_when_name_has_size(tmp_path: Path) -> None:
    products_csv = tmp_path / "products.csv"
    products_csv.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand",
                "Belco Red Onion - 500 gram,26.95,Fruits & Vegetables,Vegetables,Onions,,Belco",
            ]
        ),
        encoding="utf-8",
    )

    products = prepare_products(products_csv)
    detail = estimate_ingredient_cost(
        {
            "name_normalized": "red onion",
            "canonical_ingredient_id": "red_onion",
            "quantity": 250,
            "unit": "g",
        },
        products,
    )

    assert detail["matched_product"] == "Belco Red Onion - 500 gram"
    assert detail["product_package_quantity"] == 1000
    assert detail["estimated_used_cost_egp"] == 6.74


def test_estimator_prefers_scraped_package_size_columns(tmp_path: Path) -> None:
    products_csv = tmp_path / "products.csv"
    products_csv.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand,serving_size,package_size_quantity,package_size_unit,package_size_raw",
                "White Rice Family Pack,100,Food Cupboard,Rice,,,Qima Test,Average Nutritional Value As Per 30g,1000,g,1 Kg",
            ]
        ),
        encoding="utf-8",
    )

    products = prepare_products(products_csv)
    detail = estimate_ingredient_cost(
        {
            "name_normalized": "rice",
            "canonical_ingredient_id": "rice",
            "quantity": 250,
            "unit": "g",
        },
        products,
    )

    assert detail["matched_product"] == "White Rice Family Pack"
    assert detail["product_package_quantity"] == 1000
    assert detail["estimated_used_cost_egp"] == 25.0


def test_estimator_never_uses_serving_size_as_package_size(tmp_path: Path) -> None:
    products_csv = tmp_path / "products.csv"
    products_csv.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand,serving_size,package_size_quantity,package_size_unit,package_size_raw",
                "White Rice Family Pack,100,Food Cupboard,Rice,,,Qima Test,Average Nutritional Value As Per 30g,,,",
            ]
        ),
        encoding="utf-8",
    )

    products = prepare_products(products_csv)
    detail = estimate_ingredient_cost(
        {
            "name_normalized": "rice",
            "canonical_ingredient_id": "rice",
            "quantity": 250,
            "unit": "g",
        },
        products,
    )

    assert detail["matched_product"] == "White Rice Family Pack"
    assert detail["product_package_quantity"] is None
    assert detail["estimated_used_cost_egp"] == 100
    assert detail["pricing_method"] == "fallback_full_package_price"
