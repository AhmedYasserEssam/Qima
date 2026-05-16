from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.db import SessionLocal, init_db
from app.normalizers.ingredient_normalizer import extract_form_tags, normalize_name
from app.services.exceptions import UpstreamUnavailableError


@dataclass(frozen=True)
class ParsedRecipeIngredient:
    display_text: str
    ingredient_name: str
    normalized_name: str
    form_tags: frozenset[str]
    role: str | None = None


@dataclass(frozen=True)
class RecipeRecord:
    row: dict[str, Any]
    ingredients: tuple[ParsedRecipeIngredient, ...]
    ingredient_set: frozenset[str]
    ingredient_display_by_name: dict[str, str]


class RecipeRetrievalService:
    def __init__(self) -> None:
        self._initialized = False
        self._records: list[RecipeRecord] = []
        self._recipe_index_by_ingredient: dict[str, set[int]] = {}

    def _ensure_loaded(self) -> None:
        if self._initialized:
            return
        init_db()
        records, by_ingredient = self._load_records_from_db()
        if not records:
            raise UpstreamUnavailableError(
                "Recipe dataset is unavailable or empty. Seed allrecipes_recipes first."
            )
        self._records = records
        self._recipe_index_by_ingredient = by_ingredient
        self._initialized = True

    def get_recipe_records(self) -> list[RecipeRecord]:
        self._ensure_loaded()
        return self._records

    def recipe_indices_for_ingredient(self, ingredient_name: str) -> set[int]:
        self._ensure_loaded()
        return set(self._recipe_index_by_ingredient.get(ingredient_name, set()))

    def recipe_indices_for_ingredients(self, ingredient_names: list[str]) -> set[int]:
        self._ensure_loaded()
        indices: set[int] = set()
        for name in ingredient_names:
            indices.update(self._recipe_index_by_ingredient.get(name, set()))
        return indices

    def parse_recipe_ingredients(
        self,
        payload: Any,
    ) -> list[ParsedRecipeIngredient]:
        values = self._coerce_ingredient_values(payload)
        parsed: list[ParsedRecipeIngredient] = []
        seen: set[str] = set()

        for value in values:
            if isinstance(value, str):
                display = value.strip()
                ingredient_name = display
                role = None
            elif isinstance(value, dict):
                display = self._extract_display_text(value)
                ingredient_name = self._extract_ingredient_name(value) or display
                role = str(value.get("ingredient_role") or "").strip() or None
            else:
                continue

            if not display and not ingredient_name:
                continue

            normalized = normalize_name(display or ingredient_name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(
                ParsedRecipeIngredient(
                    display_text=display or ingredient_name,
                    ingredient_name=ingredient_name or display,
                    normalized_name=normalized,
                    form_tags=extract_form_tags(normalized),
                    role=role,
                )
            )

        return parsed

    def _coerce_ingredient_values(self, payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload

        if isinstance(payload, str):
            text_value = payload.strip()
            if not text_value:
                return []
            try:
                loaded = json.loads(text_value)
            except json.JSONDecodeError:
                return []
            if isinstance(loaded, list):
                return loaded
            if isinstance(loaded, dict):
                nested = loaded.get("ingredients") or loaded.get("items")
                if isinstance(nested, list):
                    return nested
            return []

        if isinstance(payload, dict):
            nested = payload.get("ingredients") or payload.get("items")
            if isinstance(nested, list):
                return nested
            return []

        return []

    def _extract_display_text(self, value: dict[str, Any]) -> str:
        candidates = [
            value.get("name_normalized"),
            value.get("name"),
            value.get("item"),
            value.get("canonical_ingredient_id"),
            value.get("raw"),
        ]
        for candidate in candidates:
            text_candidate = str(candidate or "").strip()
            if not text_candidate:
                continue
            if "_" in text_candidate:
                text_candidate = text_candidate.replace("_", " ")
            return text_candidate
        return ""

    def _extract_ingredient_name(self, value: dict[str, Any]) -> str:
        candidates = [
            value.get("name"),
            value.get("item"),
            value.get("name_normalized"),
            value.get("canonical_ingredient_id"),
        ]
        for candidate in candidates:
            text_candidate = str(candidate or "").strip()
            if not text_candidate:
                continue
            if "_" in text_candidate:
                text_candidate = text_candidate.replace("_", " ")
            return text_candidate
        return ""

    def _load_records_from_db(
        self,
    ) -> tuple[list[RecipeRecord], dict[str, set[int]]]:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT
                        source_url,
                        source,
                        recipe_id,
                        stable_slug,
                        title,
                        servings,
                        total_minutes,
                        protein_g,
                        sugar_g,
                        sodium_mg,
                        rating,
                        review_count,
                        ingredients,
                        dietary_flags,
                        allergen_flags,
                        possible_allergen_flags,
                        packaged_ingredient_warnings,
                        tags
                    FROM allrecipes_recipes
                    ORDER BY COALESCE(rating, 0) DESC, COALESCE(review_count, 0) DESC
                    """
                )
            ).mappings().all()

        records: list[RecipeRecord] = []
        by_ingredient: dict[str, set[int]] = {}

        for raw_row in rows:
            row = dict(raw_row)
            parsed_ingredients = self.parse_recipe_ingredients(row.get("ingredients"))
            if not parsed_ingredients:
                continue

            ingredient_display_by_name: dict[str, str] = {}
            for item in parsed_ingredients:
                ingredient_display_by_name.setdefault(item.normalized_name, item.display_text)

            ingredient_set = frozenset(ingredient_display_by_name.keys())
            record = RecipeRecord(
                row=row,
                ingredients=tuple(parsed_ingredients),
                ingredient_set=ingredient_set,
                ingredient_display_by_name=ingredient_display_by_name,
            )
            recipe_index = len(records)
            records.append(record)

            for ingredient_name in ingredient_set:
                by_ingredient.setdefault(ingredient_name, set()).add(recipe_index)

        return records, by_ingredient


recipe_retrieval_service = RecipeRetrievalService()
