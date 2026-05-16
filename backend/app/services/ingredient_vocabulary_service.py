from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.normalizers.ingredient_normalizer import extract_form_tags
from app.services.recipe_retrieval_service import (
    ParsedRecipeIngredient,
    recipe_retrieval_service,
)


@dataclass(frozen=True)
class IngredientVocabularyEntry:
    canonical_name: str
    observed_names: tuple[str, ...]
    frequency: int
    form_tags: frozenset[str]
    category_tags: tuple[str, ...]


class IngredientVocabularyService:
    def __init__(self) -> None:
        self._initialized = False
        self._entries_by_name: dict[str, IngredientVocabularyEntry] = {}
        self._max_frequency = 1

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._entries_by_name, self._max_frequency = self._build_vocabulary()
        self._initialized = True

    def get_entry(self, canonical_name: str) -> IngredientVocabularyEntry | None:
        self._ensure_initialized()
        return self._entries_by_name.get(canonical_name)

    def get_entries(self) -> list[IngredientVocabularyEntry]:
        self._ensure_initialized()
        return list(self._entries_by_name.values())

    def get_entries_by_name(self) -> dict[str, IngredientVocabularyEntry]:
        self._ensure_initialized()
        return self._entries_by_name

    def frequency_prior(self, canonical_name: str) -> float:
        self._ensure_initialized()
        entry = self._entries_by_name.get(canonical_name)
        if entry is None or entry.frequency <= 0:
            return 0.0
        return math.log1p(entry.frequency) / math.log1p(self._max_frequency)

    def _build_vocabulary(self) -> tuple[dict[str, IngredientVocabularyEntry], int]:
        grouped: dict[str, dict[str, Any]] = {}
        for recipe in recipe_retrieval_service.get_recipe_records():
            for ingredient in recipe.ingredients:
                self._accumulate(grouped, ingredient)

        entries_by_name: dict[str, IngredientVocabularyEntry] = {}
        max_frequency = 1
        for canonical, payload in grouped.items():
            frequency = int(payload["frequency"])
            max_frequency = max(max_frequency, frequency)
            observed_names = tuple(sorted(payload["observed_names"]))
            category_tags = tuple(sorted(payload["category_tags"]))
            form_tags = frozenset(payload["form_tags"])
            entries_by_name[canonical] = IngredientVocabularyEntry(
                canonical_name=canonical,
                observed_names=observed_names,
                frequency=frequency,
                form_tags=form_tags,
                category_tags=category_tags,
            )

        return entries_by_name, max_frequency

    def _accumulate(
        self,
        grouped: dict[str, dict[str, Any]],
        ingredient: ParsedRecipeIngredient,
    ) -> None:
        key = ingredient.normalized_name
        if not key:
            return
        entry = grouped.setdefault(
            key,
            {
                "frequency": 0,
                "observed_names": set(),
                "form_tags": set(),
                "category_tags": set(),
            },
        )
        entry["frequency"] += 1
        if ingredient.display_text:
            entry["observed_names"].add(ingredient.display_text)
        if ingredient.ingredient_name:
            entry["observed_names"].add(ingredient.ingredient_name)
        entry["form_tags"].update(ingredient.form_tags)
        entry["form_tags"].update(extract_form_tags(ingredient.normalized_name))
        if ingredient.role:
            entry["category_tags"].add(ingredient.role)


ingredient_vocabulary_service = IngredientVocabularyService()
