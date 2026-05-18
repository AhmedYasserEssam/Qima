from __future__ import annotations

from pathlib import Path

from app.schemas.v1.prices import RequestedIngredient
from app.services.price_service import RecipePriceEstimator


def _write_products_csv(path: Path, rows: list[str]) -> Path:
    path.write_text(
        "\n".join(
            [
                "name,price,category_level_1,category_level_2,category_level_3,category_level_4,brand,package_size_quantity,package_size_unit,source_provider_product_id,source_fetched_at",
                *rows,
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_exact_match_and_mass_unit_conversion(tmp_path: Path) -> None:
    products_csv = _write_products_csv(
        tmp_path / "products.csv",
        [
            "Rice,100,Food Cupboard,Rice,,,,1000,g,sku_rice_1,2026-05-01T00:00:00+00:00",
        ],
    )
    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [RequestedIngredient(name="rice", quantity=100, unit="g")]
    )

    assert response.total_cost == 10.0
    assert response.item_costs[0].matched_name == "Rice"
    assert response.item_costs[0].estimated_cost == 10.0
    assert response.item_costs[0].match is not None
    assert response.item_costs[0].match.confidence_label in {"high", "medium"}


def test_fuzzy_typo_matches_chicken_breast(tmp_path: Path) -> None:
    products_csv = _write_products_csv(
        tmp_path / "products.csv",
        [
            "Fresh Chicken Breast,260,Fresh Food,Chicken,,,,1000,g,sku_chicken_breast,2026-05-01T00:00:00+00:00",
        ],
    )
    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [RequestedIngredient(name="chiken breast", quantity=200, unit="g")]
    )

    assert response.total_cost == 52.0
    assert response.item_costs[0].matched_name == "Fresh Chicken Breast"


def test_semantic_synonym_ground_beef_to_minced_beef(tmp_path: Path) -> None:
    products_csv = _write_products_csv(
        tmp_path / "products.csv",
        [
            "Minced Beef,300,Fresh Food,Beef,,,,1000,g,sku_minced_beef,2026-05-01T00:00:00+00:00",
        ],
    )
    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [RequestedIngredient(name="ground beef", quantity=250, unit="g")]
    )

    assert response.total_cost == 75.0
    assert response.item_costs[0].matched_name == "Minced Beef"


def test_arabic_synonym_maps_to_canonical_ingredient(tmp_path: Path) -> None:
    products_csv = _write_products_csv(
        tmp_path / "products.csv",
        [
            "Whole Milk,60,Fresh Food,Dairy,,,,1000,ml,sku_milk_1l,2026-05-01T00:00:00+00:00",
        ],
    )
    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [RequestedIngredient(name="لبن", quantity=250, unit="ml")]
    )

    assert response.total_cost == 15.0
    assert response.item_costs[0].matched_name == "Whole Milk"


def test_bad_semantic_matches_are_rejected(tmp_path: Path) -> None:
    products_csv = _write_products_csv(
        tmp_path / "products.csv",
        [
            "Milk Chocolate Bar,40,Food Cupboard,Chocolate,,,,100,g,sku_milk_chocolate,2026-05-01T00:00:00+00:00",
            "Chicken Stock Cube,20,Food Cupboard,Seasoning,,,,100,g,sku_stock_cube,2026-05-01T00:00:00+00:00",
            "Rice Pudding Cup,30,Food Cupboard,Dessert,,,,200,g,sku_rice_pudding,2026-05-01T00:00:00+00:00",
        ],
    )
    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [
            RequestedIngredient(name="milk", quantity=200, unit="ml"),
            RequestedIngredient(name="chicken breast", quantity=200, unit="g"),
            RequestedIngredient(name="rice", quantity=100, unit="g"),
        ]
    )

    assert response.total_cost is None
    assert len(response.unmatched_ingredients) == 3
    assert response.item_costs[0].matched_name is None
    assert response.item_costs[1].matched_name is None
    assert response.item_costs[2].matched_name is None


def test_volume_unit_conversion_from_liter_package(tmp_path: Path) -> None:
    products_csv = _write_products_csv(
        tmp_path / "products.csv",
        [
            "Plain Yogurt Drink,40,Fresh Food,Dairy,,,,1,l,sku_yogurt_1l,2026-05-01T00:00:00+00:00",
        ],
    )
    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [RequestedIngredient(name="yoghurt", quantity=250, unit="ml")]
    )

    assert response.total_cost == 10.0
    assert response.item_costs[0].matched_name == "Plain Yogurt Drink"


def test_low_confidence_match_adds_warning(tmp_path: Path) -> None:
    products_csv = _write_products_csv(
        tmp_path / "products.csv",
        [
            "Beef Seasoning Mix,45,Food Cupboard,Seasoning,,,,100,g,sku_beef_seasoning,2026-05-01T00:00:00+00:00",
        ],
    )
    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [RequestedIngredient(name="beef seasoning powder", quantity=20, unit="g")]
    )

    assert response.item_costs[0].match is not None
    assert response.item_costs[0].match.confidence_label == "low"
    assert any("Low-confidence" in warning for warning in response.item_costs[0].warnings)


def test_missing_price_goes_to_unmatched_and_lowers_quality(tmp_path: Path) -> None:
    products_csv = _write_products_csv(
        tmp_path / "products.csv",
        [
            "Chicken Breast,,Fresh Food,Chicken,,,,1000,g,sku_missing_price,2026-05-01T00:00:00+00:00",
        ],
    )
    estimator = RecipePriceEstimator(products_csv=products_csv)
    response = estimator.estimate_ingredient_list(
        [RequestedIngredient(name="chicken breast", quantity=100, unit="g")]
    )

    assert response.total_cost is None
    assert response.estimate_quality.coverage == "unavailable"
    assert response.unmatched_ingredients == ["chicken breast"]
