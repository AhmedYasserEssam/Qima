from __future__ import annotations

import math
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.normalizers.ingredient_normalizer import (
    NormalizedIngredient,
    extract_form_tags,
    normalize_name,
    normalize_unit,
)
from app.services.price_embedding_service import EmbeddingCandidate, PriceEmbeddingService

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency at runtime.
    fuzz = None


PROCESSED_KEYWORDS = {
    "curry",
    "chocolate",
    "pudding",
    "cube",
    "stock",
    "seasoning",
    "mix",
    "instant",
    "flavor",
    "flavored",
    "flavoured",
    "sauce",
    "snack",
}

CATEGORY_HINTS = {
    "bread": {"bakery", "bakery & pastry"},
    "milk": {"dairy", "fresh food", "beverages"},
    "chicken": {"fresh food", "frozen food"},
    "beef": {"fresh food", "frozen food"},
    "rice": {"food cupboard"},
    "yogurt": {"fresh food", "dairy"},
}

UNIT_GROUPS = {
    "g": "mass",
    "kg": "mass",
    "mg": "mass",
    "ml": "volume",
    "l": "volume",
    "piece": "count",
    "pack": "count",
}


@dataclass(frozen=True)
class PriceCatalogItem:
    id: str
    name: str
    canonical_name: str
    normalized_name: str
    tokens: tuple[str, ...]
    form_tags: frozenset[str]
    category_level_1: str
    category_level_2: str
    category_level_3: str
    category_level_4: str
    source: str
    source_id: str
    price: float | None
    currency: str
    package_quantity: float | None
    package_unit: str | None
    price_date: str | None = None
    geography: str | None = None


@dataclass
class CandidateScore:
    item: PriceCatalogItem
    lexical_score: float = 0.0
    embedding_score: float = 0.0
    category_score: float = 0.0
    unit_compatibility_score: float = 0.0
    form_compatibility_score: float = 0.0
    final_score: float = 0.0
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    ingredient: NormalizedIngredient
    matched_item: PriceCatalogItem | None
    method: str
    confidence: float
    confidence_label: str
    lexical_score: float
    embedding_score: float
    category_score: float
    unit_compatibility_score: float
    form_compatibility_score: float
    warnings: list[str]


class PriceMatchingService:
    def __init__(
        self,
        *,
        embedding_service: PriceEmbeddingService | None = None,
    ) -> None:
        self.embedding_service = embedding_service or PriceEmbeddingService()
        self.items: list[PriceCatalogItem] = []
        self.by_id: dict[str, PriceCatalogItem] = {}
        self.by_canonical: dict[str, list[PriceCatalogItem]] = {}

    def build_index(self, items: list[PriceCatalogItem]) -> None:
        self.items = items
        self.by_id = {item.id: item for item in items}
        self.by_canonical = {}
        for item in items:
            self.by_canonical.setdefault(item.canonical_name, []).append(item)
            self.by_canonical.setdefault(item.normalized_name, []).append(item)
        self.embedding_service.build_index(
            [{"id": item.id, "name": item.canonical_name or item.name} for item in items]
        )

    def match_ingredient_to_price_item(self, ingredient: NormalizedIngredient) -> MatchResult:
        warnings: list[str] = []
        if not ingredient.canonical_name:
            return self._unmatched_result(
                ingredient,
                warnings=["Ingredient name is empty after normalization."],
            )

        exact_candidates = self._exact_candidates(ingredient)
        fuzzy_candidates = self._fuzzy_candidates(ingredient, top_n=25)
        embedding_candidates = self._embedding_candidates(ingredient, top_n=25)
        candidate_scores = self._merge_candidates(
            exact_candidates=exact_candidates,
            fuzzy_candidates=fuzzy_candidates,
            embedding_candidates=embedding_candidates,
            ingredient=ingredient,
        )

        if not candidate_scores:
            return self._unmatched_result(
                ingredient,
                warnings=["No candidates were found from exact, fuzzy, or embedding retrieval."],
            )

        ranked = sorted(candidate_scores, key=lambda score: score.final_score, reverse=True)
        best = ranked[0]
        confidence = round(best.final_score, 3)
        confidence_label = self._confidence_label(confidence)

        if confidence < 0.55:
            return self._unmatched_result(
                ingredient,
                warnings=["No reliable match passed the minimum confidence threshold."],
            )

        if confidence < 0.70:
            warnings.append(
                "Low-confidence ingredient match was used because no better candidate was available."
            )

        if best.rejection_reasons:
            warnings.extend(best.rejection_reasons)

        return MatchResult(
            ingredient=ingredient,
            matched_item=best.item,
            method="hybrid",
            confidence=confidence,
            confidence_label=confidence_label,
            lexical_score=round(best.lexical_score, 3),
            embedding_score=round(best.embedding_score, 3),
            category_score=round(best.category_score, 3),
            unit_compatibility_score=round(best.unit_compatibility_score, 3),
            form_compatibility_score=round(best.form_compatibility_score, 3),
            warnings=warnings,
        )

    def _unmatched_result(
        self,
        ingredient: NormalizedIngredient,
        warnings: list[str],
    ) -> MatchResult:
        return MatchResult(
            ingredient=ingredient,
            matched_item=None,
            method="hybrid",
            confidence=0.0,
            confidence_label="none",
            lexical_score=0.0,
            embedding_score=0.0,
            category_score=0.0,
            unit_compatibility_score=0.0,
            form_compatibility_score=0.0,
            warnings=warnings,
        )

    def _exact_candidates(self, ingredient: NormalizedIngredient) -> dict[str, float]:
        result: dict[str, float] = {}
        direct = self.by_canonical.get(ingredient.canonical_name, [])
        for item in direct:
            result[item.id] = 1.0
        return result

    def _fuzzy_candidates(self, ingredient: NormalizedIngredient, top_n: int) -> dict[str, float]:
        query = ingredient.canonical_name
        if not query:
            return {}
        candidates: list[tuple[str, float]] = []
        for item in self.items:
            candidate = item.canonical_name
            if not candidate:
                continue
            score = self._lexical_similarity(query, candidate)
            candidates.append((item.id, score))

        candidates.sort(key=lambda pair: pair[1], reverse=True)
        top = candidates[:top_n]
        return {item_id: score for item_id, score in top if score > 0}

    def _embedding_candidates(
        self,
        ingredient: NormalizedIngredient,
        top_n: int,
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        for candidate in self.embedding_service.query(ingredient.canonical_name, top_n=top_n):
            if not isinstance(candidate, EmbeddingCandidate):
                continue
            result[candidate.item_id] = max(0.0, min(1.0, float(candidate.score)))
        return result

    def _merge_candidates(
        self,
        *,
        exact_candidates: dict[str, float],
        fuzzy_candidates: dict[str, float],
        embedding_candidates: dict[str, float],
        ingredient: NormalizedIngredient,
    ) -> list[CandidateScore]:
        ids = set(exact_candidates) | set(fuzzy_candidates) | set(embedding_candidates)
        merged: list[CandidateScore] = []
        for item_id in ids:
            item = self.by_id.get(item_id)
            if item is None:
                continue

            score = CandidateScore(
                item=item,
                lexical_score=max(exact_candidates.get(item_id, 0.0), fuzzy_candidates.get(item_id, 0.0)),
                embedding_score=embedding_candidates.get(item_id, 0.0),
            )

            score.category_score = self._category_score(ingredient, item)
            score.unit_compatibility_score = self._unit_compatibility_score(ingredient, item)
            score.form_compatibility_score = self._form_compatibility_score(ingredient, item)
            rejection_reasons = self._hard_rejection_reasons(ingredient, item)
            score.rejection_reasons = rejection_reasons

            score.final_score = (
                0.30 * score.lexical_score
                + 0.30 * score.embedding_score
                + 0.20 * score.category_score
                + 0.10 * score.unit_compatibility_score
                + 0.10 * score.form_compatibility_score
            )
            if rejection_reasons:
                score.final_score *= 0.2
            score.final_score = max(0.0, min(1.0, score.final_score))
            merged.append(score)
        return merged

    def _lexical_similarity(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if fuzz is None:
            return SequenceMatcher(None, left, right).ratio()

        token_set = fuzz.token_set_ratio(left, right) / 100.0
        token_sort = fuzz.token_sort_ratio(left, right) / 100.0
        partial = fuzz.partial_ratio(left, right) / 100.0
        return (0.45 * token_set) + (0.35 * token_sort) + (0.20 * partial)

    def _category_score(self, ingredient: NormalizedIngredient, item: PriceCatalogItem) -> float:
        categories = " ".join(
            [
                item.category_level_1,
                item.category_level_2,
                item.category_level_3,
                item.category_level_4,
            ]
        ).lower()
        score = 0.5
        for token in ingredient.tokens:
            preferred = CATEGORY_HINTS.get(token)
            if not preferred:
                continue
            if any(preference in categories for preference in preferred):
                score = max(score, 1.0)
            else:
                score = min(score, 0.2)
        return score

    def _unit_group(self, unit: str | None) -> str | None:
        if unit is None:
            return None
        normalized = normalize_unit(unit)
        return UNIT_GROUPS.get(str(normalized))

    def _unit_compatibility_score(
        self,
        ingredient: NormalizedIngredient,
        item: PriceCatalogItem,
    ) -> float:
        if ingredient.unit is None:
            return 0.6
        ingredient_group = self._unit_group(ingredient.unit)
        item_group = self._unit_group(item.package_unit)
        if ingredient_group is None or item_group is None:
            return 0.3
        if ingredient_group == item_group:
            return 1.0
        return 0.0

    def _form_compatibility_score(
        self,
        ingredient: NormalizedIngredient,
        item: PriceCatalogItem,
    ) -> float:
        if "powder" in ingredient.form_tags and "powder" not in item.form_tags:
            if item.form_tags:
                return 0.0
            return 0.1
        if not ingredient.form_tags:
            if item.form_tags & {"processed", "flavored", "stock", "dessert"}:
                return 0.25
            return 0.9
        if ingredient.form_tags & item.form_tags:
            return 1.0
        if item.form_tags:
            return 0.2
        return 0.7

    def _hard_rejection_reasons(
        self,
        ingredient: NormalizedIngredient,
        item: PriceCatalogItem,
    ) -> list[str]:
        reasons: list[str] = []
        item_tokens = set(item.tokens)
        ingredient_tokens = set(ingredient.tokens)
        name = item.canonical_name

        if item.price is None or item.price <= 0:
            reasons.append("Candidate has missing or invalid price.")
        if item.package_quantity is None or item.package_quantity <= 0:
            reasons.append("Candidate has missing or invalid package quantity.")

        if "milk" in ingredient_tokens and "chocolate" in item_tokens and "chocolate" not in ingredient_tokens:
            reasons.append("Rejected milk-to-chocolate mismatch.")
        if {"chicken", "breast"} <= ingredient_tokens and {"stock", "cube"} & item_tokens:
            reasons.append("Rejected chicken breast to stock-cube mismatch.")
        if "rice" in ingredient_tokens and {"pudding", "curry"} & item_tokens:
            reasons.append("Rejected rice to prepared dessert/curry mismatch.")

        if ingredient_tokens.isdisjoint(item_tokens):
            if any(token in name for token in PROCESSED_KEYWORDS):
                reasons.append("Candidate is processed/flavored while ingredient is generic.")

        category_score = self._category_score(ingredient, item)
        if category_score <= 0.15:
            reasons.append("Candidate category is clearly incompatible.")

        if self._unit_compatibility_score(ingredient, item) <= 0 and ingredient.unit is not None:
            reasons.append("Candidate unit is incompatible with requested unit.")
        return reasons

    def _confidence_label(self, confidence: float) -> str:
        if confidence >= 0.85:
            return "high"
        if confidence >= 0.70:
            return "medium"
        if confidence >= 0.55:
            return "low"
        return "none"


def build_price_catalog_item(
    *,
    item_id: Any,
    name: Any,
    category_level_1: Any,
    category_level_2: Any,
    category_level_3: Any,
    category_level_4: Any,
    source: str,
    source_id: Any,
    price: Any,
    currency: str,
    package_quantity: Any,
    package_unit: Any,
    price_date: Any = None,
    geography: Any = None,
) -> PriceCatalogItem:
    normalized_name = normalize_name(name)
    canonical_name = normalized_name
    tokens = tuple(normalized_name.split())
    form_tags = extract_form_tags(normalized_name)

    try:
        parsed_price = float(price) if price is not None else None
    except (TypeError, ValueError):
        parsed_price = None
    if parsed_price is not None and math.isnan(parsed_price):
        parsed_price = None

    try:
        parsed_package_quantity = (
            float(package_quantity) if package_quantity is not None else None
        )
    except (TypeError, ValueError):
        parsed_package_quantity = None
    if parsed_package_quantity is not None and math.isnan(parsed_package_quantity):
        parsed_package_quantity = None

    normalized_package_unit = normalize_unit(package_unit)
    if normalized_package_unit not in UNIT_GROUPS:
        normalized_package_unit = normalize_unit(package_unit)

    return PriceCatalogItem(
        id=str(item_id),
        name=str(name or "").strip(),
        canonical_name=canonical_name,
        normalized_name=normalized_name,
        tokens=tokens,
        form_tags=form_tags,
        category_level_1=str(category_level_1 or "").strip(),
        category_level_2=str(category_level_2 or "").strip(),
        category_level_3=str(category_level_3 or "").strip(),
        category_level_4=str(category_level_4 or "").strip(),
        source=source,
        source_id=str(source_id or item_id),
        price=parsed_price,
        currency=currency,
        package_quantity=parsed_package_quantity,
        package_unit=normalized_package_unit,
        price_date=str(price_date) if price_date else None,
        geography=str(geography) if geography else None,
    )
