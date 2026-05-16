from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.normalizers.ingredient_normalizer import extract_form_tags, normalize_name
from app.services.ingredient_vocabulary_service import (
    IngredientVocabularyEntry,
    ingredient_vocabulary_service,
)
from app.services.recipe_retrieval_service import RecipeRecord, recipe_retrieval_service
from app.services.recipe_semantic_service import PgvectorRecipeSemanticProvider

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency
    fuzz = None


PROCESSED_TERMS = {
    "chocolate",
    "pudding",
    "stock",
    "cube",
    "cubes",
    "seasoning",
    "flavor",
    "flavored",
    "flavoured",
    "instant",
    "mix",
    "sauce",
    "prepared",
}
POWDER_TERMS = {"powder", "powdered"}
FRESH_TERMS = {"fresh"}

MIN_INGREDIENT_MATCH_SCORE = 0.45
MIN_INGREDIENT_STRONG_MATCH_SCORE = 0.55
DEFAULT_RECIPE_LIMIT = 5


@dataclass(frozen=True)
class InputIngredient:
    display_text: str
    normalized_name: str
    form_tags: frozenset[str]
    tokens: tuple[str, ...]


@dataclass
class CandidateScore:
    canonical_name: str
    lexical_score: float
    semantic_score: float
    token_overlap_score: float
    form_compatibility_score: float
    frequency_prior: float
    final_score: float
    rejected: bool = False
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass
class InputIngredientMatch:
    input_ingredient: InputIngredient
    matched_canonical_name: str | None
    matched_display_name: str | None
    score: float
    lexical_score: float
    semantic_score: float
    token_overlap_score: float
    form_compatibility_score: float
    frequency_prior: float
    rejected_candidates: list[dict[str, Any]]
    top_candidates: list[dict[str, Any]]


@dataclass
class ScoredRecipe:
    recipe: RecipeRecord
    score: float
    matched_input_ingredients: list[str]
    missing_input_ingredients: list[str]
    matched_recipe_ingredients: list[str]
    missing_recipe_ingredients: list[str]
    warnings: list[str]


@dataclass
class RecipeMatchingResult:
    scored_recipes: list[ScoredRecipe]
    ingredient_matches: list[InputIngredientMatch]
    warnings: list[str]
    debug: dict[str, Any]


class BaseSemanticProvider:
    @property
    def available(self) -> bool:
        return False

    def build_index(self, entries: list[IngredientVocabularyEntry]) -> None:
        del entries

    def query(self, text: str, top_n: int) -> dict[str, float]:
        del text, top_n
        return {}

    @property
    def warning(self) -> str | None:
        return None


class RecipeMatchingService:
    def __init__(self) -> None:
        self._semantic_provider: BaseSemanticProvider = PgvectorRecipeSemanticProvider()
        self._semantic_ready = False
        self._entries_by_name: dict[str, IngredientVocabularyEntry] = {}
        self._entry_names: list[str] = []

    def match_and_rank(
        self,
        *,
        requested_ingredients: list[str],
        dietary_filters: list[str],
        excluded_ingredients: list[str],
        max_results: int | None,
    ) -> RecipeMatchingResult:
        inputs = self._prepare_inputs(requested_ingredients)
        if not inputs:
            return RecipeMatchingResult(
                scored_recipes=[],
                ingredient_matches=[],
                warnings=["No valid ingredients were provided for recipe matching."],
                debug={
                    "received_ingredients": requested_ingredients,
                    "normalized_ingredients": [],
                    "candidate_ingredient_matches": [],
                    "recipe_candidate_count": 0,
                    "top_recipe_scores": [],
                    "rejected_candidates": [],
                    "retrieval_stage_counts": {"input_ingredient_count": 0},
                },
            )

        self._ensure_semantic_index()
        ingredient_matches: list[InputIngredientMatch] = []
        rejected_candidates: list[dict[str, Any]] = []
        retrieval_stage_counts = {
            "input_ingredient_count": len(inputs),
            "exact_candidates": 0,
            "fuzzy_candidates": 0,
            "semantic_candidates": 0,
            "merged_candidates": 0,
        }

        for input_ingredient in inputs:
            exact_candidates = self._exact_candidates(input_ingredient.normalized_name)
            fuzzy_candidates = self._fuzzy_candidates(input_ingredient.normalized_name, top_n=40)
            semantic_candidates = self._semantic_provider.query(
                input_ingredient.normalized_name, top_n=40
            )

            retrieval_stage_counts["exact_candidates"] += len(exact_candidates)
            retrieval_stage_counts["fuzzy_candidates"] += len(fuzzy_candidates)
            retrieval_stage_counts["semantic_candidates"] += len(semantic_candidates)

            merged = self._merge_candidates(
                input_ingredient=input_ingredient,
                exact_candidates=exact_candidates,
                fuzzy_candidates=fuzzy_candidates,
                semantic_candidates=semantic_candidates,
            )
            retrieval_stage_counts["merged_candidates"] += len(merged)

            merged.sort(key=lambda item: item.final_score, reverse=True)
            top_candidates = merged[:5]
            rejected = [candidate for candidate in merged if candidate.rejected]
            for candidate in rejected[:5]:
                rejected_candidates.append(
                    {
                        "input": input_ingredient.display_text,
                        "candidate": candidate.canonical_name,
                        "reasons": candidate.rejection_reasons,
                    }
                )

            best = top_candidates[0] if top_candidates else None
            if best is None or best.final_score < MIN_INGREDIENT_MATCH_SCORE:
                ingredient_matches.append(
                    InputIngredientMatch(
                        input_ingredient=input_ingredient,
                        matched_canonical_name=None,
                        matched_display_name=None,
                        score=0.0,
                        lexical_score=0.0,
                        semantic_score=0.0,
                        token_overlap_score=0.0,
                        form_compatibility_score=0.0,
                        frequency_prior=0.0,
                        rejected_candidates=[
                            {
                                "candidate": item.canonical_name,
                                "reasons": item.rejection_reasons,
                            }
                            for item in rejected[:5]
                        ],
                        top_candidates=[self._candidate_debug_payload(item) for item in top_candidates],
                    )
                )
                continue

            entry = self._entries_by_name.get(best.canonical_name)
            matched_display = None
            if entry and entry.observed_names:
                matched_display = entry.observed_names[0]

            ingredient_matches.append(
                InputIngredientMatch(
                    input_ingredient=input_ingredient,
                    matched_canonical_name=best.canonical_name,
                    matched_display_name=matched_display or best.canonical_name,
                    score=round(best.final_score, 4),
                    lexical_score=round(best.lexical_score, 4),
                    semantic_score=round(best.semantic_score, 4),
                    token_overlap_score=round(best.token_overlap_score, 4),
                    form_compatibility_score=round(best.form_compatibility_score, 4),
                    frequency_prior=round(best.frequency_prior, 4),
                    rejected_candidates=[
                        {
                            "candidate": item.canonical_name,
                            "reasons": item.rejection_reasons,
                        }
                        for item in rejected[:5]
                    ],
                    top_candidates=[self._candidate_debug_payload(item) for item in top_candidates],
                )
            )

        strong_matches = [
            match
            for match in ingredient_matches
            if match.matched_canonical_name is not None
            and match.score >= MIN_INGREDIENT_STRONG_MATCH_SCORE
        ]

        if not strong_matches:
            warnings = [
                "No strong recipe matches were found for the supplied ingredients."
            ]
            return RecipeMatchingResult(
                scored_recipes=[],
                ingredient_matches=ingredient_matches,
                warnings=warnings,
                debug={
                    "received_ingredients": requested_ingredients,
                    "normalized_ingredients": [item.normalized_name for item in inputs],
                    "candidate_ingredient_matches": self._ingredient_match_debug(ingredient_matches),
                    "recipe_candidate_count": 0,
                    "top_recipe_scores": [],
                    "rejected_candidates": rejected_candidates,
                    "retrieval_stage_counts": retrieval_stage_counts,
                    "semantic_warning": self._semantic_provider.warning,
                },
            )

        candidate_recipe_indices = recipe_retrieval_service.recipe_indices_for_ingredients(
            [match.matched_canonical_name for match in strong_matches if match.matched_canonical_name]
        )

        scored_recipes: list[ScoredRecipe] = []
        excluded_normalized = [
            normalized
            for normalized in (normalize_name(item) for item in excluded_ingredients)
            if normalized
        ]
        normalized_dietary_filters = [
            item.strip().lower() for item in dietary_filters if item and item.strip()
        ]

        requested_count = len(inputs)
        for recipe_index in candidate_recipe_indices:
            recipe = recipe_retrieval_service.get_recipe_records()[recipe_index]
            if self._has_excluded_ingredient(recipe.ingredient_set, excluded_normalized):
                continue
            if not self._passes_dietary_filters(recipe.row, normalized_dietary_filters):
                continue

            matched_inputs: list[str] = []
            matched_scores: list[float] = []
            matched_recipe_ingredient_names: list[str] = []
            matched_recipe_set: set[str] = set()
            for match in strong_matches:
                if (
                    match.matched_canonical_name is None
                    or match.matched_canonical_name not in recipe.ingredient_set
                ):
                    continue
                matched_inputs.append(match.input_ingredient.display_text)
                matched_scores.append(match.score)
                matched_recipe_set.add(match.matched_canonical_name)
                display_name = recipe.ingredient_display_by_name.get(
                    match.matched_canonical_name
                )
                if display_name:
                    matched_recipe_ingredient_names.append(display_name)

            if not matched_inputs:
                continue

            missing_input_ingredients = [
                item.display_text
                for item in inputs
                if item.display_text not in set(matched_inputs)
            ]
            missing_recipe_ingredients = [
                display
                for name, display in recipe.ingredient_display_by_name.items()
                if name not in matched_recipe_set
            ][:8]

            coverage_ratio = len(matched_inputs) / max(1, requested_count)
            average_confidence = sum(matched_scores) / max(1, len(matched_scores))
            matched_recipe_ratio = len(matched_recipe_set) / max(1, len(recipe.ingredient_set))
            rating_component = min(
                1.0,
                max(0.0, (self._to_float(recipe.row.get("rating")) or 0.0) / 5.0),
            )
            review_component = min(
                1.0,
                max(0.0, (self._to_float(recipe.row.get("review_count")) or 0.0) / 1000.0),
            )

            score = (
                0.45 * coverage_ratio
                + 0.25 * average_confidence
                + 0.15 * matched_recipe_ratio
                + 0.10 * rating_component
                + 0.05 * review_component
            )
            warnings = self._build_recipe_warnings(recipe.row)
            scored_recipes.append(
                ScoredRecipe(
                    recipe=recipe,
                    score=round(max(0.0, min(1.0, score)), 4),
                    matched_input_ingredients=matched_inputs,
                    missing_input_ingredients=missing_input_ingredients,
                    matched_recipe_ingredients=matched_recipe_ingredient_names,
                    missing_recipe_ingredients=missing_recipe_ingredients,
                    warnings=warnings,
                )
            )

        scored_recipes.sort(
            key=lambda item: (
                item.score,
                self._to_float(item.recipe.row.get("rating")) or 0.0,
                self._to_float(item.recipe.row.get("review_count")) or 0.0,
            ),
            reverse=True,
        )
        top_limit = max_results or DEFAULT_RECIPE_LIMIT
        limited = scored_recipes[:top_limit]

        warnings: list[str] = []
        if not limited:
            warnings.append("No strong recipe matches were found for the supplied ingredients.")

        return RecipeMatchingResult(
            scored_recipes=limited,
            ingredient_matches=ingredient_matches,
            warnings=warnings,
            debug={
                "received_ingredients": requested_ingredients,
                "normalized_ingredients": [item.normalized_name for item in inputs],
                "candidate_ingredient_matches": self._ingredient_match_debug(ingredient_matches),
                "recipe_candidate_count": len(candidate_recipe_indices),
                "top_recipe_scores": [
                    {
                        "recipe_id": self.public_recipe_id(item.recipe.row),
                        "title": str(item.recipe.row.get("title") or "Untitled recipe"),
                        "score": item.score,
                    }
                    for item in limited[:10]
                ],
                "rejected_candidates": rejected_candidates,
                "retrieval_stage_counts": retrieval_stage_counts,
                "semantic_warning": self._semantic_provider.warning,
            },
        )

    def _prepare_inputs(self, requested_ingredients: list[str]) -> list[InputIngredient]:
        seen: set[str] = set()
        prepared: list[InputIngredient] = []
        for raw in requested_ingredients:
            display = str(raw).strip()
            if not display:
                continue
            normalized = normalize_name(display)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            prepared.append(
                InputIngredient(
                    display_text=display,
                    normalized_name=normalized,
                    form_tags=extract_form_tags(normalized),
                    tokens=tuple(normalized.split()),
                )
            )
        return prepared

    def _ensure_semantic_index(self) -> None:
        self._entries_by_name = ingredient_vocabulary_service.get_entries_by_name()
        self._entry_names = list(self._entries_by_name.keys())
        if self._semantic_ready:
            return
        self._semantic_provider.build_index([])
        self._semantic_ready = True

    def _exact_candidates(self, query: str) -> dict[str, float]:
        if query in self._entries_by_name:
            return {query: 1.0}
        return {}

    def _fuzzy_candidates(self, query: str, top_n: int) -> dict[str, float]:
        candidates: list[tuple[str, float]] = []
        for candidate in self._entry_names:
            score = self._lexical_similarity(query, candidate)
            if score <= 0.25:
                continue
            candidates.append((candidate, score))
        candidates.sort(key=lambda item: item[1], reverse=True)
        return {name: score for name, score in candidates[:top_n]}

    def _merge_candidates(
        self,
        *,
        input_ingredient: InputIngredient,
        exact_candidates: dict[str, float],
        fuzzy_candidates: dict[str, float],
        semantic_candidates: dict[str, float],
    ) -> list[CandidateScore]:
        names = set(exact_candidates) | set(fuzzy_candidates) | set(semantic_candidates)
        merged: list[CandidateScore] = []
        semantic_available = bool(semantic_candidates)

        if semantic_available:
            lexical_weight = 0.35
            semantic_weight = 0.35
            token_weight = 0.15
        else:
            lexical_weight = 0.55
            semantic_weight = 0.0
            token_weight = 0.30
        form_weight = 0.10
        frequency_weight = 0.05

        for name in names:
            entry = self._entries_by_name.get(name)
            if entry is None:
                continue
            lexical_score = max(exact_candidates.get(name, 0.0), fuzzy_candidates.get(name, 0.0))
            semantic_score = semantic_candidates.get(name, 0.0) if semantic_available else 0.0
            token_overlap_score = self._token_overlap(
                input_ingredient.normalized_name, name
            )
            form_score = self._form_compatibility_score(
                input_ingredient.form_tags, entry.form_tags
            )
            frequency_prior = ingredient_vocabulary_service.frequency_prior(name)

            final_score = (
                lexical_weight * lexical_score
                + semantic_weight * semantic_score
                + token_weight * token_overlap_score
                + form_weight * form_score
                + frequency_weight * frequency_prior
            )

            rejected, rejection_reasons, penalty_factor = self._rejection_and_penalty(
                query=input_ingredient.normalized_name,
                candidate=name,
                query_form_tags=input_ingredient.form_tags,
                candidate_form_tags=entry.form_tags,
            )
            if rejected:
                final_score = 0.0
            else:
                final_score *= penalty_factor

            merged.append(
                CandidateScore(
                    canonical_name=name,
                    lexical_score=round(lexical_score, 4),
                    semantic_score=round(semantic_score, 4),
                    token_overlap_score=round(token_overlap_score, 4),
                    form_compatibility_score=round(form_score, 4),
                    frequency_prior=round(frequency_prior, 4),
                    final_score=round(max(0.0, min(1.0, final_score)), 4),
                    rejected=rejected,
                    rejection_reasons=rejection_reasons,
                )
            )
        return merged

    def _lexical_similarity(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if fuzz is None:
            return SequenceMatcher(None, left, right).ratio()
        token_set = fuzz.token_set_ratio(left, right) / 100.0
        token_sort = fuzz.token_sort_ratio(left, right) / 100.0
        return (0.6 * token_set) + (0.4 * token_sort)

    def _token_overlap(self, left: str, right: str) -> float:
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return intersection / max(1, union)

    def _form_compatibility_score(
        self,
        query_form_tags: frozenset[str],
        candidate_form_tags: frozenset[str],
    ) -> float:
        if not query_form_tags and not candidate_form_tags:
            return 1.0
        if query_form_tags and candidate_form_tags and query_form_tags & candidate_form_tags:
            return 1.0
        if query_form_tags and candidate_form_tags and not (query_form_tags & candidate_form_tags):
            return 0.25
        if query_form_tags and not candidate_form_tags:
            return 0.65
        if candidate_form_tags and not query_form_tags:
            processed_only = {"processed", "flavored", "stock", "dessert", "chocolate"}
            if candidate_form_tags & processed_only:
                return 0.25
            return 0.75
        return 0.7

    def _rejection_and_penalty(
        self,
        *,
        query: str,
        candidate: str,
        query_form_tags: frozenset[str],
        candidate_form_tags: frozenset[str],
    ) -> tuple[bool, list[str], float]:
        query_tokens = set(query.split())
        candidate_tokens = set(candidate.split())
        rejection_reasons: list[str] = []
        penalty = 1.0

        if "milk" in query_tokens and "chocolate" in candidate_tokens and "chocolate" not in query_tokens:
            return True, ["Rejected milk-to-milk-chocolate mismatch."], 0.0
        if {"chicken", "breast"} <= query_tokens and (
            {"stock", "cube"} & candidate_tokens
        ):
            return True, ["Rejected chicken-breast-to-stock-cube mismatch."], 0.0
        if "rice" in query_tokens and "pudding" in candidate_tokens and "pudding" not in query_tokens:
            return True, ["Rejected rice-to-rice-pudding mismatch."], 0.0

        query_processed = bool(query_tokens & PROCESSED_TERMS)
        candidate_processed = bool(candidate_tokens & PROCESSED_TERMS)
        if candidate_processed and not query_processed:
            penalty *= 0.35
            rejection_reasons.append(
                "Penalized processed/flavored candidate for generic ingredient query."
            )

        if query_form_tags and candidate_form_tags and not (query_form_tags & candidate_form_tags):
            penalty *= 0.6
            rejection_reasons.append("Penalized incompatible ingredient form tags.")

        if (query_tokens & POWDER_TERMS) and (candidate_tokens & FRESH_TERMS):
            penalty *= 0.5
            rejection_reasons.append("Penalized powder-versus-fresh mismatch.")
        if (query_tokens & FRESH_TERMS) and (candidate_tokens & POWDER_TERMS):
            penalty *= 0.5
            rejection_reasons.append("Penalized fresh-versus-powder mismatch.")

        return False, rejection_reasons, penalty

    def _build_recipe_warnings(self, row: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        possible_allergens = [
            str(item).strip()
            for item in self._ensure_json_list(row.get("possible_allergen_flags"))
            if str(item).strip()
        ]
        if possible_allergens:
            warnings.append(
                "Possible allergens: " + ", ".join(sorted(set(possible_allergens)))
            )
        packaged_warnings = [
            str(item).strip()
            for item in self._ensure_json_list(row.get("packaged_ingredient_warnings"))
            if str(item).strip()
        ]
        if packaged_warnings:
            warnings.extend(packaged_warnings[:2])
        return warnings

    def _has_excluded_ingredient(
        self,
        recipe_ingredient_set: frozenset[str],
        excluded_normalized: list[str],
    ) -> bool:
        if not excluded_normalized:
            return False
        for excluded in excluded_normalized:
            for ingredient in recipe_ingredient_set:
                if excluded == ingredient or excluded in ingredient or ingredient in excluded:
                    return True
        return False

    def _passes_dietary_filters(self, row: dict[str, Any], filters: list[str]) -> bool:
        if not filters:
            return True

        dietary_flags = self._ensure_json_dict(row.get("dietary_flags"))
        total_minutes = self._to_float(row.get("total_minutes"))
        protein_g = self._to_float(row.get("protein_g"))
        sugar_g = self._to_float(row.get("sugar_g"))
        sodium_mg = self._to_float(row.get("sodium_mg"))

        for item in filters:
            name = item.strip().lower()
            if not name:
                continue

            if name == "vegetarian" and dietary_flags.get("vegetarian") is not True:
                return False
            if name == "vegan" and dietary_flags.get("vegan") is not True:
                return False
            if name == "quick_meals" and total_minutes is not None and total_minutes > 30:
                return False
            if name == "high_protein" and protein_g is not None and protein_g < 15:
                return False
            if name == "low_sugar" and sugar_g is not None and sugar_g > 10:
                return False
            if name == "low_sodium" and sodium_mg is not None and sodium_mg > 600:
                return False
            if name == "budget_friendly" and total_minutes is not None and total_minutes > 45:
                return False
            if name == "egyptian_foods":
                tags = [str(tag).strip().lower() for tag in self._ensure_json_list(row.get("tags"))]
                if not any("egypt" in tag for tag in tags):
                    return False

        return True

    def _candidate_debug_payload(self, candidate: CandidateScore) -> dict[str, Any]:
        return {
            "candidate": candidate.canonical_name,
            "final_score": candidate.final_score,
            "lexical_score": candidate.lexical_score,
            "semantic_score": candidate.semantic_score,
            "token_overlap_score": candidate.token_overlap_score,
            "form_compatibility_score": candidate.form_compatibility_score,
            "frequency_prior": candidate.frequency_prior,
            "rejected": candidate.rejected,
            "reasons": candidate.rejection_reasons,
        }

    def _ingredient_match_debug(
        self,
        matches: list[InputIngredientMatch],
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for match in matches:
            payload.append(
                {
                    "input": match.input_ingredient.display_text,
                    "normalized_input": match.input_ingredient.normalized_name,
                    "matched_canonical_name": match.matched_canonical_name,
                    "score": match.score,
                    "top_candidates": match.top_candidates,
                }
            )
        return payload

    def _ensure_json_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        return []

    def _ensure_json_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}

    def _to_float(self, value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except ValueError:
            return None

    def public_recipe_id(self, row: dict[str, Any]) -> str:
        recipe_id = str(row.get("recipe_id") or "").strip()
        if recipe_id:
            return recipe_id
        stable_slug = str(row.get("stable_slug") or "").strip()
        if stable_slug:
            return stable_slug
        return str(row.get("source_url") or "unknown_recipe").strip() or "unknown_recipe"


recipe_matching_service = RecipeMatchingService()
