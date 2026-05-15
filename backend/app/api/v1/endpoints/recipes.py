from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps.auth import get_optional_current_user
from app.models.user import User
from app.schemas.v1.recipes import (
    RecipeCandidate,
    RecipeDiscussRequest,
    RecipeDiscussResponse,
    RecipeSource,
    RecipeSuggestRequest,
    RecipeSuggestResponse,
)
from app.services.exceptions import (
    BadRequestError,
    NotFoundError,
    UpstreamUnavailableError,
)
from app.services.inventory_service import inventory_service
from app.services.recipe_service import recipe_service

router = APIRouter()


@router.post("/suggest", response_model=RecipeSuggestResponse)
async def suggest_recipes(
    payload: RecipeSuggestRequest,
    current_user: User | None = Depends(get_optional_current_user),
) -> RecipeSuggestResponse:
    merged_ingredients = _merge_ingredients(
        pantry_items=payload.pantry_items,
        recognized_ingredients=payload.recognized_ingredients,
    )

    if payload.inventory_item_ids:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication is required when using inventory_item_ids.",
            )
        try:
            inventory_items = inventory_service.resolve_item_names_for_user(
                user=current_user,
                item_ids=payload.inventory_item_ids,
            )
        except BadRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        merged_ingredients = _merge_ingredients(
            pantry_items=merged_ingredients,
            recognized_ingredients=inventory_items,
        )

    dietary_filters = list(payload.dietary_filters)
    if payload.budget_level == "low" and "budget_friendly" not in dietary_filters:
        dietary_filters.append("budget_friendly")

    try:
        recipes = recipe_service.suggest_recipes(
            requested_ingredients=merged_ingredients,
            dietary_filters=dietary_filters,
            excluded_ingredients=payload.excluded_ingredients,
            max_results=payload.max_results,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    for candidate in recipes:
        candidate.exclusions = list(
            dict.fromkeys(dietary_filters + payload.excluded_ingredients)
        )

    return RecipeSuggestResponse(
        recipes=recipes,
        source=RecipeSource(
            dataset="recipe_corpus_primary",
            retrieval_mode="retrieval_first",
            source_type="recipe_corpus",
        ),
        latency_ms=120,
    )


def _merge_ingredients(
    *,
    pantry_items: list[str] | None,
    recognized_ingredients: list[str] | None,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in (pantry_items or []) + (recognized_ingredients or []):
        cleaned = str(item).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged


@router.post("/discuss", response_model=RecipeDiscussResponse)
async def discuss_recipe(payload: RecipeDiscussRequest) -> RecipeDiscussResponse:
    try:
        return recipe_service.discuss_recipe(
            recipe_id=payload.recipe_id,
            candidate_title=payload.candidate_context.title
            if payload.candidate_context
            else None,
            question=payload.question,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/{recipe_id}", response_model=RecipeCandidate)
async def get_recipe(recipe_id: str) -> RecipeCandidate:
    try:
        return recipe_service.get_recipe_candidate(recipe_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
