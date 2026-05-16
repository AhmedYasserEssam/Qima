from __future__ import annotations

import math

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.normalizers.ingredient_normalizer import extract_form_tags, normalize_name
from app.services.ingredient_vocabulary_service import IngredientVocabularyEntry
from app.services.recipe_matching_service import BaseSemanticProvider, RecipeMatchingService
from app.services.recipe_retrieval_service import (
    ParsedRecipeIngredient,
    RecipeRecord,
    recipe_retrieval_service,
)
from app.services.recipe_service import RecipeSuggestResult

client = TestClient(app)


def _build_recipe_record(
    recipe_id: str,
    title: str,
    ingredient_texts: list[str],
) -> RecipeRecord:
    ingredients: list[ParsedRecipeIngredient] = []
    display_by_name: dict[str, str] = {}
    for text_value in ingredient_texts:
        normalized = normalize_name(text_value)
        ingredient = ParsedRecipeIngredient(
            display_text=text_value,
            ingredient_name=text_value,
            normalized_name=normalized,
            form_tags=extract_form_tags(normalized),
            role="main",
        )
        ingredients.append(ingredient)
        display_by_name.setdefault(normalized, text_value)

    row = {
        "recipe_id": recipe_id,
        "title": title,
        "source": "allrecipes",
        "source_url": f"https://example.com/{recipe_id}",
        "rating": 4.5,
        "review_count": 100,
        "dietary_flags": {},
        "allergen_flags": [],
        "possible_allergen_flags": [],
        "packaged_ingredient_warnings": [],
        "tags": [],
        "total_minutes": 30,
        "protein_g": 20,
        "sugar_g": 4,
        "sodium_mg": 100,
    }
    return RecipeRecord(
        row=row,
        ingredients=tuple(ingredients),
        ingredient_set=frozenset(display_by_name.keys()),
        ingredient_display_by_name=display_by_name,
    )


def _patch_match_dependencies(monkeypatch, records: list[RecipeRecord]) -> RecipeMatchingService:
    index_by_name: dict[str, set[int]] = {}
    for idx, record in enumerate(records):
        for ingredient_name in record.ingredient_set:
            index_by_name.setdefault(ingredient_name, set()).add(idx)

    entries_grouped: dict[str, dict[str, object]] = {}
    for record in records:
        for ingredient in record.ingredients:
            grouped = entries_grouped.setdefault(
                ingredient.normalized_name,
                {
                    "frequency": 0,
                    "observed_names": set(),
                    "form_tags": set(),
                },
            )
            grouped["frequency"] = int(grouped["frequency"]) + 1
            grouped["observed_names"].add(ingredient.display_text)
            grouped["form_tags"].update(ingredient.form_tags)

    entries_by_name: dict[str, IngredientVocabularyEntry] = {}
    max_frequency = 1
    for name, payload in entries_grouped.items():
        frequency = int(payload["frequency"])
        max_frequency = max(max_frequency, frequency)
        entries_by_name[name] = IngredientVocabularyEntry(
            canonical_name=name,
            observed_names=tuple(sorted(payload["observed_names"])),
            frequency=frequency,
            form_tags=frozenset(payload["form_tags"]),
            category_tags=(),
        )

    def frequency_prior(name: str) -> float:
        entry = entries_by_name.get(name)
        if entry is None:
            return 0.0
        return math.log1p(entry.frequency) / math.log1p(max_frequency)

    monkeypatch.setattr(
        "app.services.recipe_matching_service.recipe_retrieval_service.get_recipe_records",
        lambda: records,
    )
    monkeypatch.setattr(
        "app.services.recipe_matching_service.recipe_retrieval_service.recipe_indices_for_ingredients",
        lambda names: set().union(*(index_by_name.get(name, set()) for name in names)),
    )
    monkeypatch.setattr(
        "app.services.recipe_matching_service.ingredient_vocabulary_service.get_entries_by_name",
        lambda: entries_by_name,
    )
    monkeypatch.setattr(
        "app.services.recipe_matching_service.ingredient_vocabulary_service.get_entries",
        lambda: list(entries_by_name.values()),
    )
    monkeypatch.setattr(
        "app.services.recipe_matching_service.ingredient_vocabulary_service.frequency_prior",
        frequency_prior,
    )

    service = RecipeMatchingService()
    service._semantic_provider = BaseSemanticProvider()
    service._semantic_ready = False
    return service


def test_recipe_retrieval_parser_supports_multiple_shapes() -> None:
    as_strings = recipe_retrieval_service.parse_recipe_ingredients(
        ["ground beef", "hamburger buns"]
    )
    as_dicts = recipe_retrieval_service.parse_recipe_ingredients(
        [
            {"raw": "2 hamburger buns, split", "name_normalized": "hamburger buns"},
            {"name": "shredded cheddar cheese"},
        ]
    )
    as_json = recipe_retrieval_service.parse_recipe_ingredients(
        '[{"raw":"1 lb lean ground beef"}, "2 hamburger buns, split"]'
    )

    assert [item.normalized_name for item in as_strings] == ["ground beef", "hamburger bun"]
    assert [item.normalized_name for item in as_dicts] == ["hamburger bun", "cheddar cheese"]
    assert [item.normalized_name for item in as_json] == ["ground beef", "hamburger bun"]


def test_recipe_normalizer_examples() -> None:
    assert normalize_name("1 lb lean ground beef") == "ground beef"
    assert normalize_name("2 hamburger buns, split") == "hamburger bun"
    assert normalize_name("shredded cheddar cheese") == "cheddar cheese"
    assert normalize_name("fresh milk") == "fresh milk"
    assert normalize_name("powdered milk") == "powdered milk"


def test_recipe_matching_positive_examples(monkeypatch) -> None:
    records = [
        _build_recipe_record(
            "recipe_1",
            "Burger Plate",
            ["ground beef", "hamburger buns", "cheddar cheese"],
        ),
        _build_recipe_record("recipe_2", "Simple Salad", ["lettuce", "tomato"]),
    ]
    service = _patch_match_dependencies(monkeypatch, records)

    result = service.match_and_rank(
        requested_ingredients=["beef patty", "burger bun", "shredded cheddar cheese"],
        dietary_filters=[],
        excluded_ingredients=[],
        max_results=3,
    )

    assert result.scored_recipes
    best = result.scored_recipes[0]
    assert best.recipe.row["recipe_id"] == "recipe_1"
    assert set(best.matched_input_ingredients) == {
        "beef patty",
        "burger bun",
        "shredded cheddar cheese",
    }
    assert "ground beef" in best.matched_recipe_ingredients
    assert any("hamburger bun" in value for value in best.matched_recipe_ingredients)


def test_recipe_matching_rejects_milk_chocolate_for_milk(monkeypatch) -> None:
    records = [_build_recipe_record("recipe_milk_choco", "Chocolate Drink", ["milk chocolate"])]
    service = _patch_match_dependencies(monkeypatch, records)

    result = service.match_and_rank(
        requested_ingredients=["milk"],
        dietary_filters=[],
        excluded_ingredients=[],
        max_results=3,
    )

    assert result.scored_recipes == []
    assert any(
        "milk-to-milk-chocolate mismatch" in " ".join(item.get("reasons", []))
        for item in result.debug.get("rejected_candidates", [])
    )


def test_recipe_matching_rejects_rice_pudding_for_rice(monkeypatch) -> None:
    records = [_build_recipe_record("recipe_rice_pudding", "Rice Pudding", ["rice pudding"])]
    service = _patch_match_dependencies(monkeypatch, records)

    result = service.match_and_rank(
        requested_ingredients=["rice"],
        dietary_filters=[],
        excluded_ingredients=[],
        max_results=3,
    )

    assert result.scored_recipes == []
    assert any(
        "rice-to-rice-pudding mismatch" in " ".join(item.get("reasons", []))
        for item in result.debug.get("rejected_candidates", [])
    )


def test_recipe_matching_rejects_stock_cube_for_chicken_breast(monkeypatch) -> None:
    records = [
        _build_recipe_record(
            "recipe_stock_cube",
            "Stock Cube Soup",
            ["chicken stock cube"],
        )
    ]
    service = _patch_match_dependencies(monkeypatch, records)

    result = service.match_and_rank(
        requested_ingredients=["chicken breast"],
        dietary_filters=[],
        excluded_ingredients=[],
        max_results=3,
    )

    assert result.scored_recipes == []
    assert any(
        "chicken-breast-to-stock-cube mismatch" in " ".join(item.get("reasons", []))
        for item in result.debug.get("rejected_candidates", [])
    )


def test_suggest_endpoint_valid_no_match_returns_200(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.endpoints.recipes.recipe_service.suggest_recipes",
        lambda **kwargs: RecipeSuggestResult(
            recipes=[],
            warnings=["No strong recipe matches were found for the supplied ingredients."],
            debug={"received_ingredients": kwargs.get("requested_ingredients", [])},
        ),
    )

    response = client.post("/v1/recipes/suggest", json={"pantry_items": ["unknown ingredient"]})
    assert response.status_code == 200
    body = response.json()
    assert body["recipes"] == []
    assert body["warnings"]


def test_suggest_endpoint_debug_is_gated_by_env_and_query(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.endpoints.recipes.recipe_service.suggest_recipes",
        lambda **kwargs: RecipeSuggestResult(
            recipes=[],
            warnings=["No strong recipe matches were found for the supplied ingredients."],
            debug={"received_ingredients": kwargs.get("requested_ingredients", [])},
        ),
    )

    monkeypatch.setenv("QIMA_RECIPE_DEBUG_ENABLED", "true")
    get_settings.cache_clear()
    response_with_debug = client.post(
        "/v1/recipes/suggest?debug=true",
        json={"pantry_items": ["rice"]},
    )
    assert response_with_debug.status_code == 200
    assert "debug" in response_with_debug.json()

    response_without_query = client.post(
        "/v1/recipes/suggest",
        json={"pantry_items": ["rice"]},
    )
    assert response_without_query.status_code == 200
    assert "debug" not in response_without_query.json()

    monkeypatch.setenv("QIMA_RECIPE_DEBUG_ENABLED", "false")
    get_settings.cache_clear()
    response_env_false = client.post(
        "/v1/recipes/suggest?debug=true",
        json={"pantry_items": ["rice"]},
    )
    assert response_env_false.status_code == 200
    assert "debug" not in response_env_false.json()
    get_settings.cache_clear()


def test_suggest_endpoint_merges_pantry_and_recognized_sources(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_suggest_recipes(**kwargs) -> RecipeSuggestResult:
        captured["requested_ingredients"] = kwargs.get("requested_ingredients")
        return RecipeSuggestResult(
            recipes=[],
            warnings=[],
            debug={},
        )

    monkeypatch.setattr(
        "app.api.v1.endpoints.recipes.recipe_service.suggest_recipes",
        fake_suggest_recipes,
    )

    response = client.post(
        "/v1/recipes/suggest",
        json={
            "pantry_items": ["Rice"],
            "recognized_ingredients": ["Onion", "Rice"],
        },
    )
    assert response.status_code == 200
    assert captured["requested_ingredients"] == ["Rice", "Onion"]
