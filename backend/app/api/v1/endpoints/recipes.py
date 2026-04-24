from fastapi import APIRouter

from app.schemas.v1.recipes import (
    GroundedReference,
    GroundingMetadata,
    RecipeCandidate,
    RecipeDiscussRequest,
    RecipeDiscussResponse,
    RecipeSource,
    RecipeSuggestRequest,
    RecipeSuggestResponse,
    SafetyFlags,
)

router = APIRouter()


@router.post("/suggest", response_model=RecipeSuggestResponse)
async def suggest_recipes(payload: RecipeSuggestRequest) -> RecipeSuggestResponse:
    return RecipeSuggestResponse(
        recipes=[
            RecipeCandidate(
                recipe_id="recipe_stub_001",
                title="Simple Lentil Rice Bowl",
                match_score=0.91,
                matched_ingredients=payload.pantry_items
                or payload.recognized_ingredients
                or [],
                missing_ingredients=["onion", "tomato sauce"],
                exclusions=payload.dietary_filters + payload.excluded_ingredients,
                warnings=[],
                grounding_metadata=GroundingMetadata(
                    retrieved_from="recipe_corpus_primary",
                    matched_count=len(
                        payload.pantry_items or payload.recognized_ingredients or []
                    ),
                    missing_count=2,
                ),
            )
        ],
        source=RecipeSource(
            dataset="recipe_corpus_primary",
            retrieval_mode="retrieval_first",
            source_type="recipe_corpus",
        ),
        latency_ms=120,
    )


@router.post("/discuss", response_model=RecipeDiscussResponse)
async def discuss_recipe(payload: RecipeDiscussRequest) -> RecipeDiscussResponse:
    title = (
        payload.candidate_context.title
        if payload.candidate_context
        else "Simple Lentil Rice Bowl"
    )

    recipe_id = payload.recipe_id or "recipe_stub_001"

    return RecipeDiscussResponse(
        answer="This is a grounded stub answer based on the selected recipe context.",
        grounded_references=[
            GroundedReference(
                recipe_id=recipe_id,
                title=title,
                reference_type="metadata",
                reference_text="Stub recipe context used for discussion.",
            )
        ],
        safety_flags=SafetyFlags(
            allergen_risk=False,
            undercooked_risk=False,
            cross_contamination_risk=False,
            diet_conflict=False,
            notes=[],
        ),
        warnings=["Stub response. Replace with retrieved recipe context later."],
        latency_ms=140,
    )


@router.get("/{recipe_id}", response_model=RecipeCandidate)
async def get_recipe(recipe_id: str) -> RecipeCandidate:
    return RecipeCandidate(
        recipe_id=recipe_id,
        title="Simple Lentil Rice Bowl",
        match_score=0.88,
        matched_ingredients=["rice", "lentils"],
        missing_ingredients=["onion", "tomato sauce"],
        exclusions=[],
        warnings=["Mock recipe detail response."],
        grounding_metadata=GroundingMetadata(
            retrieved_from="recipe_corpus_primary",
            matched_count=2,
            missing_count=2,
        ),
    )
