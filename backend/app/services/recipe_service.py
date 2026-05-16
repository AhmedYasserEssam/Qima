from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.db import SessionLocal, init_db
from app.normalizers.ingredient_normalizer import normalize_name
from app.schemas.v1.recipes import (
    GroundedReference,
    GroundingMetadata,
    RecipeCandidate,
    RecipeDiscussResponse,
    SafetyFlags,
)
from app.services.exceptions import NotFoundError, UpstreamUnavailableError
from app.services.recipe_matching_service import recipe_matching_service

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALLRECIPES_JSONL = REPO_ROOT / "data" / "Recipes" / "allrecipes_recipes.jsonl"


@dataclass(frozen=True)
class RecipeSuggestResult:
    recipes: list[RecipeCandidate]
    warnings: list[str]
    debug: dict[str, Any] | None = None


class RecipeService:
    def __init__(self) -> None:
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        init_db()
        self._initialized = True

    def suggest_recipes(
        self,
        *,
        requested_ingredients: list[str],
        dietary_filters: list[str],
        excluded_ingredients: list[str],
        max_results: int | None,
    ) -> RecipeSuggestResult:
        self._ensure_initialized()
        matching_result = recipe_matching_service.match_and_rank(
            requested_ingredients=requested_ingredients,
            dietary_filters=dietary_filters,
            excluded_ingredients=excluded_ingredients,
            max_results=max_results,
        )
        recipes: list[RecipeCandidate] = []
        for scored_recipe in matching_result.scored_recipes:
            row = scored_recipe.recipe.row
            recipe_id = self._public_recipe_id(row)
            candidate_warnings = list(dict.fromkeys(scored_recipe.warnings))
            recipes.append(
                RecipeCandidate(
                    recipe_id=recipe_id,
                    title=str(row.get("title") or "Untitled recipe"),
                    match_score=scored_recipe.score,
                    matched_ingredients=scored_recipe.matched_input_ingredients,
                    missing_ingredients=scored_recipe.missing_recipe_ingredients,
                    missing_input_ingredients=scored_recipe.missing_input_ingredients,
                    recipe_ingredients_used_for_matching=scored_recipe.matched_recipe_ingredients,
                    exclusions=[],
                    warnings=candidate_warnings,
                    source={
                        "source": str(row.get("source") or ""),
                        "source_url": str(row.get("source_url") or ""),
                        "source_type": "recipe_corpus",
                    },
                    grounding_metadata=GroundingMetadata(
                        retrieved_from="recipe_corpus_primary",
                        matched_count=len(scored_recipe.matched_input_ingredients),
                        missing_count=len(scored_recipe.missing_recipe_ingredients),
                    ),
                )
            )

        return RecipeSuggestResult(
            recipes=recipes,
            warnings=matching_result.warnings,
            debug=matching_result.debug,
        )

    def discuss_recipe(
        self,
        *,
        recipe_id: str | None,
        candidate_title: str | None,
        question: str,
    ) -> RecipeDiscussResponse:
        self._ensure_initialized()
        row = self._resolve_recipe_row(recipe_id=recipe_id, candidate_title=candidate_title)
        if row is None:
            raise NotFoundError("Recipe not found in allrecipes dataset.")

        title = str(row.get("title") or "Untitled recipe")
        servings = _to_float(row.get("servings"))
        total_minutes = _to_float(row.get("total_minutes"))
        ingredients = [display for display, _ in self._recipe_ingredient_names(row)]
        first_step = self._first_direction_text(row)

        answer_parts = [f"From Allrecipes: {title}."]
        if servings is not None:
            answer_parts.append(f"Serves about {servings:g}.")
        if total_minutes is not None and total_minutes > 0:
            answer_parts.append(f"Estimated total time is about {total_minutes:g} minutes.")
        if ingredients:
            answer_parts.append("Key ingredients: " + ", ".join(ingredients[:6]) + ".")
        if first_step:
            answer_parts.append("First step: " + first_step)
        if question.strip():
            answer_parts.append(
                "This answer is grounded in the dataset recipe record you selected."
            )

        allergen_flags = _ensure_json_list(row.get("allergen_flags"))
        allergen_names = [
            str(item).strip()
            for item in allergen_flags
            if str(item).strip()
        ]

        references: list[GroundedReference] = [
            GroundedReference(
                recipe_id=self._public_recipe_id(row),
                title=title,
                reference_type="metadata",
                reference_text="Allrecipes dataset record.",
            )
        ]
        if ingredients:
            references.append(
                GroundedReference(
                    recipe_id=self._public_recipe_id(row),
                    title=title,
                    reference_type="ingredient",
                    reference_text=", ".join(ingredients[:5]),
                )
            )
        if first_step:
            references.append(
                GroundedReference(
                    recipe_id=self._public_recipe_id(row),
                    title=title,
                    reference_type="instruction",
                    reference_text=first_step,
                )
            )

        safety_notes: list[str] = []
        if allergen_names:
            safety_notes.append("Potential allergens: " + ", ".join(allergen_names))

        return RecipeDiscussResponse(
            answer=" ".join(answer_parts),
            grounded_references=references,
            safety_flags=SafetyFlags(
                allergen_risk=bool(allergen_names),
                undercooked_risk=False,
                cross_contamination_risk=False,
                diet_conflict=False,
                notes=safety_notes,
            ),
            warnings=[],
            latency_ms=120,
        )

    def get_recipe_candidate(self, recipe_id: str) -> RecipeCandidate:
        self._ensure_initialized()
        row = self._resolve_recipe_row(recipe_id=recipe_id, candidate_title=None)
        if row is None:
            raise NotFoundError("Recipe not found in allrecipes dataset.")

        ingredient_names = [display for display, _ in self._recipe_ingredient_names(row)]
        matched_preview = ingredient_names[:5]

        return RecipeCandidate(
            recipe_id=self._public_recipe_id(row),
            title=str(row.get("title") or "Untitled recipe"),
            match_score=1.0,
            matched_ingredients=matched_preview,
            missing_ingredients=[],
            exclusions=[],
            warnings=[],
            grounding_metadata=GroundingMetadata(
                retrieved_from="recipe_corpus_primary",
                matched_count=len(matched_preview),
                missing_count=0,
            ),
        )

    def _query_candidate_rows(
        self,
        requested_normalized: list[str],
        *,
        max_results: int | None,
    ) -> list[dict[str, Any]]:
        search_terms = list(dict.fromkeys(requested_normalized))[:8]
        candidate_limit = max(100, min(1200, (max_results or 5) * 150))

        where_fragments: list[str] = []
        params: dict[str, Any] = {"candidate_limit": candidate_limit}
        for idx, term in enumerate(search_terms):
            key = f"term_{idx}"
            params[key] = f"%{term}%"
            where_fragments.append(
                f"(LOWER(title) LIKE :{key} OR CAST(ingredients AS TEXT) ILIKE :{key})"
            )

        where_clause = " OR ".join(where_fragments) if where_fragments else "TRUE"

        with SessionLocal() as session:
            rows = session.execute(
                text(
                    f"""
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
                        directions_json,
                        dietary_flags,
                        allergen_flags
                    FROM allrecipes_recipes
                    WHERE {where_clause}
                    ORDER BY COALESCE(rating, 0) DESC, COALESCE(review_count, 0) DESC
                    LIMIT :candidate_limit
                    """
                ),
                params,
            ).mappings().all()

        return [dict(row) for row in rows]

    def _resolve_recipe_row(
        self,
        *,
        recipe_id: str | None,
        candidate_title: str | None,
    ) -> dict[str, Any] | None:
        normalized_recipe_id = (recipe_id or "").strip()
        if normalized_recipe_id.startswith("recipe_stub_"):
            return self._top_rated_recipe()

        if normalized_recipe_id:
            row = self._find_recipe_by_identifier(normalized_recipe_id)
            if row is not None:
                return row

        normalized_title = (candidate_title or "").strip()
        if normalized_title:
            row = self._find_recipe_by_title(normalized_title)
            if row is not None:
                return row

        return None

    def _find_recipe_by_identifier(self, recipe_id: str) -> dict[str, Any] | None:
        slug_candidate = recipe_id
        source_url_candidate = recipe_id
        if recipe_id.startswith("id:"):
            recipe_id = recipe_id[3:].strip()
        elif recipe_id.startswith("slug:"):
            slug_candidate = recipe_id[5:].strip()
        elif recipe_id.startswith("url:"):
            source_url_candidate = recipe_id[4:].strip()

        with SessionLocal() as session:
            row = session.execute(
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
                        directions_json,
                        dietary_flags,
                        allergen_flags
                    FROM allrecipes_recipes
                    WHERE recipe_id = :recipe_id
                       OR stable_slug = :stable_slug
                       OR source_url = :source_url
                    LIMIT 1
                    """
                ),
                {
                    "recipe_id": recipe_id,
                    "stable_slug": slug_candidate,
                    "source_url": source_url_candidate,
                },
            ).mappings().first()

        return dict(row) if row else None

    def _find_recipe_by_title(self, title: str) -> dict[str, Any] | None:
        with SessionLocal() as session:
            row = session.execute(
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
                        directions_json,
                        dietary_flags,
                        allergen_flags
                    FROM allrecipes_recipes
                    WHERE LOWER(title) = LOWER(:title)
                       OR LOWER(title) LIKE LOWER(:title_like)
                    ORDER BY COALESCE(rating, 0) DESC, COALESCE(review_count, 0) DESC
                    LIMIT 1
                    """
                ),
                {"title": title, "title_like": f"%{title}%"},
            ).mappings().first()

        return dict(row) if row else None

    def _top_rated_recipe(self) -> dict[str, Any] | None:
        with SessionLocal() as session:
            row = session.execute(
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
                        directions_json,
                        dietary_flags,
                        allergen_flags
                    FROM allrecipes_recipes
                    ORDER BY COALESCE(rating, 0) DESC, COALESCE(review_count, 0) DESC
                    LIMIT 1
                    """
                )
            ).mappings().first()
        return dict(row) if row else None

    def _recipe_ingredient_names(self, row: dict[str, Any]) -> list[tuple[str, str]]:
        raw_ingredients = _ensure_json_list(row.get("ingredients"))
        seen: set[str] = set()
        names: list[tuple[str, str]] = []
        for item in raw_ingredients:
            if not isinstance(item, dict):
                continue
            display = (
                str(item.get("name_normalized") or "").strip()
                or str(item.get("canonical_ingredient_id") or "").replace("_", " ").strip()
                or str(item.get("raw") or "").strip()
            )
            if not display:
                continue
            normalized = normalize_name(display)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            names.append((display, normalized))
        return names

    def _first_direction_text(self, row: dict[str, Any]) -> str | None:
        directions = _ensure_json_list(row.get("directions_json"))
        if not directions:
            return None
        for item in directions:
            if not isinstance(item, dict):
                continue
            text_value = str(
                item.get("action_summary")
                or item.get("raw_text")
                or item.get("step_text")
                or ""
            ).strip()
            if text_value:
                return text_value
        return None

    def _has_excluded_ingredient(
        self,
        recipe_ingredient_norm_set: set[str],
        excluded_normalized: list[str],
    ) -> bool:
        if not excluded_normalized:
            return False
        for excluded in excluded_normalized:
            for ingredient in recipe_ingredient_norm_set:
                if excluded == ingredient or excluded in ingredient or ingredient in excluded:
                    return True
        return False

    def _passes_dietary_filters(self, row: dict[str, Any], filters: list[str]) -> bool:
        if not filters:
            return True

        dietary_flags = _ensure_json_dict(row.get("dietary_flags"))
        total_minutes = _to_float(row.get("total_minutes"))
        protein_g = _to_float(row.get("protein_g"))
        sugar_g = _to_float(row.get("sugar_g"))
        sodium_mg = _to_float(row.get("sodium_mg"))

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
                tags = [str(tag).strip().lower() for tag in _ensure_json_list(row.get("tags"))]
                if not any("egypt" in tag for tag in tags):
                    return False

        return True

    def _prepare_requested_ingredients(
        self, requested_ingredients: list[str]
    ) -> list[tuple[str, str]]:
        seen: set[str] = set()
        pairs: list[tuple[str, str]] = []
        for raw in requested_ingredients:
            display = str(raw).strip()
            if not display:
                continue
            normalized = normalize_name(display)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            pairs.append((display, normalized))
        return pairs

    def _score_match(
        self,
        *,
        overlap: int,
        requested_count: int,
        recipe_ingredient_count: int,
        rating: float | None,
        review_count: float | None,
    ) -> float:
        if overlap <= 0 or requested_count <= 0 or recipe_ingredient_count <= 0:
            return 0.0

        requested_coverage = overlap / requested_count
        recipe_coverage = overlap / recipe_ingredient_count
        rating_component = min(1.0, max(0.0, (rating or 0.0) / 5.0))
        review_component = min(1.0, max(0.0, (review_count or 0.0) / 1000.0))

        score = (
            0.70 * requested_coverage
            + 0.20 * recipe_coverage
            + 0.07 * rating_component
            + 0.03 * review_component
        )
        return round(max(0.0, min(1.0, score)), 4)

    def _public_recipe_id(self, row: dict[str, Any]) -> str:
        recipe_id = str(row.get("recipe_id") or "").strip()
        if recipe_id:
            return recipe_id
        stable_slug = str(row.get("stable_slug") or "").strip()
        if stable_slug:
            return stable_slug
        return str(row.get("source_url") or "unknown_recipe").strip() or "unknown_recipe"


def _ensure_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _ensure_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


recipe_service = RecipeService()
