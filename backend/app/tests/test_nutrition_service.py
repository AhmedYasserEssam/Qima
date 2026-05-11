import json
from pathlib import Path

import pandas as pd
import pytest

from app.schemas.v1.nutrition import NutritionEstimateRequest
from app.services.exceptions import NotFoundError, UpstreamUnavailableError
from app.services.nutrition_service import (
    FDC_FOUNDATION_JSON,
    NutritionService,
)


def _write_nutrition_xlsx(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_excel(path, index=False)


def _write_egyptian_food_csv(path: Path, rows: list[dict]) -> None:
    columns = [
        "FOOD",
        "REFUSE (%)",
        "WATER (g)",
        "ENERGY (Kcal)",
        "PROTEIN (g)",
        "FAT (g)",
        "ASH (g)",
        "FIBER (g)",
        "CARBOHYDRATE  (g)",
        "SODIUM (mg)",
        "POTASSIUM (mg)",
        "CALCIUM (mg)",
        "PHOSPHORUS (mg)",
        "MAGNESIUM (mg)",
        "IRON (mg)",
        "ZINC (mg)",
        "COPPER (mg)",
        "VITAMIN A (ugre)",
        "VITAMIN C (mg)",
        "THIAMIN (mg)",
        "REBOFLAVIN (mg)",
        "Unnamed: 21",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    path.write_bytes(frame.to_csv(index=False).encode("cp1252"))


def _base_row(name: str, **overrides: object) -> dict:
    row = {
        "name": name,
        "serving_size": "100 g",
        "calories": 100,
        "protein": "2 g",
        "carbohydrate": "20 g",
        "fat": "1 g",
        "fiber": "1 g",
        "sugars": "0.5 g",
        "sodium": "5 mg",
    }
    row.update(overrides)
    return row


def _egyptian_row(food: str, **overrides: object) -> dict:
    row = {
        "FOOD": food,
        "REFUSE (%)": 0,
        "WATER (g)": 50,
        "ENERGY (Kcal)": 100,
        "PROTEIN (g)": 5,
        "FAT (g)": 2,
        "ASH (g)": 1,
        "FIBER (g)": 1,
        "CARBOHYDRATE  (g)": 20,
        "SODIUM (mg)": 10,
        "POTASSIUM (mg)": 20,
        "CALCIUM (mg)": 30,
        "PHOSPHORUS (mg)": 40,
        "MAGNESIUM (mg)": 50,
        "IRON (mg)": 1,
        "ZINC (mg)": 1,
        "COPPER (mg)": 0.1,
        "VITAMIN A (ugre)": "T",
        "VITAMIN C (mg)": 0,
        "THIAMIN (mg)": 0.1,
        "REBOFLAVIN (mg)": 0.1,
        "Unnamed: 21": None,
    }
    row.update(overrides)
    return row


def test_estimate_exact_xlsx_food_match(tmp_path: Path) -> None:
    _write_nutrition_xlsx(
        tmp_path / "nutrition.xlsx",
        [_base_row("Cornstarch", calories=381, protein="0.26 g", carbohydrate="91.27 g")],
    )
    service = NutritionService(data_dir=tmp_path)

    result = service.estimate(
        NutritionEstimateRequest(
            input_type="recognized_dish",
            recognized_dish="Cornstarch",
        )
    )

    assert result.matched_dish.name == "Cornstarch"
    assert result.matched_dish.match_type == "dish"
    assert result.nutrients.calories_kcal == 381
    assert result.nutrients.protein_g == 0.26
    assert result.nutrients.carbohydrates_g == 91.27
    assert result.source.dataset == "nutrition_xlsx"
    assert result.data_quality.completeness == "complete"
    assert result.warnings == []


def test_short_query_matches_base_food_not_qualifier(tmp_path: Path) -> None:
    _write_nutrition_xlsx(
        tmp_path / "nutrition.xlsx",
        [
            _base_row("Butter, without salt", calories=717, sodium="11 mg"),
            _base_row(
                "Salt, table",
                calories=0,
                protein="0 g",
                carbohydrate="0 g",
                fat="0 g",
                sodium="38758 mg",
            ),
        ],
    )
    service = NutritionService(data_dir=tmp_path)

    result = service.estimate(
        NutritionEstimateRequest(
            input_type="recognized_dish",
            recognized_dish="salt",
        )
    )

    assert result.matched_dish.name == "Salt, table"
    assert result.nutrients.calories_kcal == 0
    assert result.nutrients.sodium_mg == 38758
    assert result.source.dataset == "nutrition_xlsx"


def test_short_ingredient_query_ignores_qualifier_only_matches(
    tmp_path: Path,
) -> None:
    _write_nutrition_xlsx(
        tmp_path / "nutrition.xlsx",
        [_base_row("Butter, without salt", calories=717, sodium="11 mg")],
    )
    service = NutritionService(data_dir=tmp_path)

    with pytest.raises(NotFoundError):
        service.estimate(
            NutritionEstimateRequest(
                input_type="ingredient_set",
                ingredients=["salt"],
            )
        )


def test_estimate_uses_cp1252_egyptian_csv_after_xlsx_miss(tmp_path: Path) -> None:
    _write_nutrition_xlsx(tmp_path / "nutrition.xlsx", [_base_row("Cornstarch")])
    _write_egyptian_food_csv(
        tmp_path / "Egyptian Food.csv",
        [
            _egyptian_row(
                "rice\xa0(koshari)",
                **{
                    "ENERGY (Kcal)": 172,
                    "PROTEIN (g)": 6.5,
                    "FAT (g)": 5.2,
                    "CARBOHYDRATE  (g)": 24.7,
                    "FIBER (g)": 1.1,
                    "SODIUM (mg)": 324,
                },
            )
        ],
    )
    service = NutritionService(data_dir=tmp_path)

    result = service.estimate(
        NutritionEstimateRequest(
            input_type="recognized_dish",
            recognized_dish="koshari",
        )
    )

    assert result.matched_dish.name == "rice\xa0(koshari)"
    assert result.nutrients.calories_kcal == 172
    assert result.nutrients.protein_g == 6.5
    assert result.nutrients.fat_g == 5.2
    assert result.nutrients.carbohydrates_g == 24.7
    assert result.nutrients.fiber_g == 1.1
    assert result.nutrients.sodium_mg == 324
    assert result.serving_assumptions.basis == "100 g"
    assert result.source.dataset == "egyptian_food_csv"
    assert result.source.source_type == "egyptian_food_dataset"
    assert result.data_quality.completeness == "complete"


def test_estimate_uses_egyptian_csv_for_local_food_alias(tmp_path: Path) -> None:
    _write_nutrition_xlsx(tmp_path / "nutrition.xlsx", [_base_row("Cornstarch")])
    _write_egyptian_food_csv(
        tmp_path / "Egyptian Food.csv",
        [
            _egyptian_row(
                "beans , broad (foulmedames)",
                **{
                    "ENERGY (Kcal)": 98,
                    "PROTEIN (g)": 5.6,
                    "FAT (g)": 0.7,
                    "CARBOHYDRATE  (g)": 17.2,
                    "FIBER (g)": 2.0,
                    "SODIUM (mg)": 24,
                },
            )
        ],
    )
    service = NutritionService(data_dir=tmp_path)

    result = service.estimate(
        NutritionEstimateRequest(
            input_type="recognized_dish",
            recognized_dish="foulmedames",
        )
    )

    assert result.matched_dish.name == "beans , broad (foulmedames)"
    assert result.nutrients.calories_kcal == 98
    assert result.source.dataset == "egyptian_food_csv"


def test_egyptian_csv_partial_nutrients_mark_partial_quality(tmp_path: Path) -> None:
    _write_nutrition_xlsx(tmp_path / "nutrition.xlsx", [_base_row("Cornstarch")])
    _write_egyptian_food_csv(
        tmp_path / "Egyptian Food.csv",
        [
            _egyptian_row(
                "beans , broad (taamia), fride",
                **{
                    "ENERGY (Kcal)": 355,
                    "PROTEIN (g)": 10.9,
                    "FAT (g)": None,
                    "CARBOHYDRATE  (g)": 32.6,
                    "FIBER (g)": 1.5,
                    "SODIUM (mg)": 524,
                },
            )
        ],
    )
    service = NutritionService(data_dir=tmp_path)

    result = service.estimate(
        NutritionEstimateRequest(
            input_type="recognized_dish",
            recognized_dish="taamia",
        )
    )

    assert result.matched_dish.name == "beans , broad (taamia), fride"
    assert result.nutrients.fat_g is None
    assert result.data_quality.completeness == "partial"
    assert "One or more core nutrient values are unavailable." in (result.warnings or [])


def test_estimate_ingredient_set_averages_matched_xlsx_foods(tmp_path: Path) -> None:
    _write_nutrition_xlsx(
        tmp_path / "nutrition.xlsx",
        [
            _base_row("Rice", calories=120, protein="2 g", carbohydrate="25 g", fat="1 g"),
            _base_row("Lentils", calories=180, protein="9 g", carbohydrate="30 g", fat="2 g"),
        ],
    )
    service = NutritionService(data_dir=tmp_path)

    result = service.estimate(
        NutritionEstimateRequest(
            input_type="ingredient_set",
            ingredients=["Rice", "Lentils"],
        )
    )

    assert result.matched_dish.match_type == "ingredient_set"
    assert result.serving_assumptions.basis == "100 g composite serving"
    assert result.nutrients.calories_kcal == 150
    assert result.nutrients.protein_g == 5.5
    assert result.nutrients.carbohydrates_g == 27.5
    assert result.nutrients.fat_g == 1.5
    assert result.confidence == 0.9
    assert result.data_quality.completeness == "complete"


def test_recognized_dish_falls_back_to_supplied_ingredients(tmp_path: Path) -> None:
    _write_nutrition_xlsx(
        tmp_path / "nutrition.xlsx",
        [
            _base_row("Rice", calories=120),
            _base_row("Lentils", calories=180),
        ],
    )
    service = NutritionService(data_dir=tmp_path)

    result = service.estimate(
        NutritionEstimateRequest(
            input_type="recognized_dish",
            recognized_dish="Koshari",
            ingredients=["Rice", "Lentils"],
        )
    )

    assert result.matched_dish.match_type == "ingredient_set"
    assert result.nutrients.calories_kcal == 150
    assert any("No direct nutrition match found for 'Koshari'" in warning for warning in result.warnings or [])


def test_estimate_uses_fooddata_central_fallback(tmp_path: Path) -> None:
    _write_nutrition_xlsx(tmp_path / "nutrition.xlsx", [_base_row("Cornstarch")])
    (tmp_path / FDC_FOUNDATION_JSON).write_text(
        json.dumps(
            {
                "FoundationFoods": [
                    {
                        "fdcId": 42,
                        "description": "Dragon fruit, raw",
                        "foodNutrients": [
                            {"nutrient": {"id": 1008, "name": "Energy", "unitName": "kcal"}, "amount": 60},
                            {"nutrient": {"id": 1003, "name": "Protein", "unitName": "g"}, "amount": 1.2},
                            {
                                "nutrient": {
                                    "id": 1005,
                                    "name": "Carbohydrate, by difference",
                                    "unitName": "g",
                                },
                                "amount": 13,
                            },
                            {
                                "nutrient": {"id": 1004, "name": "Total lipid (fat)", "unitName": "g"},
                                "amount": 0.4,
                            },
                            {
                                "nutrient": {"id": 1093, "name": "Sodium, Na", "unitName": "mg"},
                                "amount": 1,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = NutritionService(data_dir=tmp_path)

    result = service.estimate(
        NutritionEstimateRequest(
            input_type="recognized_dish",
            recognized_dish="dragon fruit",
        )
    )

    assert result.matched_dish.name == "Dragon fruit, raw"
    assert result.nutrients.calories_kcal == 60
    assert result.source.dataset == "fdc_foundation"
    assert result.source.source_type == "fooddata_central"
    assert any("fuzzy matching" in warning for warning in result.warnings or [])


def test_estimate_no_match_raises_not_found(tmp_path: Path) -> None:
    _write_nutrition_xlsx(tmp_path / "nutrition.xlsx", [_base_row("Cornstarch")])
    service = NutritionService(data_dir=tmp_path)

    with pytest.raises(NotFoundError):
        service.estimate(
            NutritionEstimateRequest(
                input_type="recognized_dish",
                recognized_dish="No Such Food",
            )
        )


def test_missing_nutrition_xlsx_raises_upstream_unavailable(tmp_path: Path) -> None:
    service = NutritionService(data_dir=tmp_path)

    with pytest.raises(UpstreamUnavailableError):
        service.estimate(
            NutritionEstimateRequest(
                input_type="recognized_dish",
                recognized_dish="Cornstarch",
            )
        )
