from datetime import UTC, datetime

from fastapi import APIRouter

from app.schemas.v1.recipes import (
    GroundedReference,
    GroundingMetadata,
    PriceReference,
    RecipeCandidate,
    RecipeDiscussRequest,
    RecipeDiscussResponse,
    RecipeSource,
    RecipeSuggestRequest,
    RecipeSuggestResponse,
    SafetyFlags,
    SuggestedSubstitution,
)
from app.schemas.v1.shared_price_context import (
    Coverage,
    EstimatedCost,
    EstimateQuality,
    ItemCost,
    MatchQuality,
    PriceBasis,
    PriceSource,
)

router = APIRouter()


def _ingredient_names(payload: RecipeSuggestRequest) -> list[str]:
    if payload.pantry:
        return [item.name for item in payload.pantry]

    if payload.pantry_items:
        return payload.pantry_items

    if payload.recognized_ingredients:
        names: list[str] = []
        for item in payload.recognized_ingredients:
            names.append(item if isinstance(item, str) else item.name)
        return names

    return []


def _mock_estimated_cost() -> EstimatedCost:
    source = PriceSource(
        source_id="egyptian_ingredient_price_kb",
        source_name="Egyptian ingredient price knowledge base",
        geography="Cairo",
        observed_at=datetime.now(UTC).date(),
        last_updated_at=datetime.now(UTC),
        price_basis=PriceBasis.PANTRY_DELTA,
    )

    return EstimatedCost(
        total_cost=24.5,
        total_purchase_cost=38,
        pantry_delta_cost=12,
        pantry_delta_purchase_cost=18,
        per_serving_cost=12.25,
        currency="EGP",
        coverage=Coverage.PARTIAL,
        confidence=0.72,
        quality=EstimateQuality(
            priced_item_count=2,
            unpriced_item_count=1,
            staleness_warning=False,
        ),
        item_costs=[
            ItemCost(
                ingredient_name="onion",
                normalized_name="onion",
                requested_quantity=1,
                requested_unit="piece",
                usage_cost=4,
                purchase_cost=4,
                purchase_quantity=1,
                purchase_unit="piece",
                estimated_cost=4,
                currency="EGP",
                match_quality=MatchQuality.NORMALIZED,
                assumptions=[],
                warnings=[],
                source=source,
            ),
            ItemCost(
                ingredient_name="tomato sauce",
                normalized_name="tomato sauce",
                requested_quantity=100,
                requested_unit="g",
                usage_cost=8,
                purchase_cost=14,
                purchase_quantity=1,
                purchase_unit="pack",
                estimated_cost=8,
                currency="EGP",
                match_quality=MatchQuality.ASSUMED,
                assumptions=[
                    "Default package size used because exact package size was not supplied."
                ],
                warnings=["Tomato sauce price is assumed."],
                source=source,
            ),
        ],
        assumptions=["Pantry items are treated as already owned."],
        warnings=["Estimate is partial and not based on live market prices."],
        source=source,
    )


@router.post("/suggest", response_model=RecipeSuggestResponse)
async def suggest_recipes(payload: RecipeSuggestRequest) -> RecipeSuggestResponse:
    matched_ingredients = _ingredient_names(payload)
    price_aware = bool(payload.price_preferences and payload.price_preferences.price_aware)

    return RecipeSuggestResponse(
        recipes=[
            RecipeCandidate(
                recipe_id="recipe_stub_001",
                title="Simple Lentil Rice Bowl",
                match_score=0.91,
                matched_ingredients=matched_ingredients,
                missing_ingredients=["onion", "tomato sauce"],
                applied_filters=payload.user_preferences + payload.excluded_ingredients,
                warnings=(
                    ["Price estimate is partial and not a live market price."]
                    if price_aware
                    else []
                ),
                estimated_cost=_mock_estimated_cost() if price_aware else None,
                price_rank=1 if price_aware else None,
                price_explanation=(
                    "Lowest estimated pantry delta among matched mock recipes."
                    if price_aware
                    else None
                ),
                grounding_metadata=GroundingMetadata(
                    retrieved_from="recipe_corpus_primary",
                    matched_count=len(matched_ingredients),
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

    recipe_id = (
        payload.recipe_id
        or (payload.candidate_context.recipe_id if payload.candidate_context else None)
        or "recipe_stub_001"
    )

    wants_cost_help = payload.conversation_intent in {
        "reduce_cost",
        "substitute_ingredient",
        "compare_options",
    }

    price_references: list[PriceReference] = []
    suggested_substitutions: list[SuggestedSubstitution] = []
    updated_estimated_cost: EstimatedCost | None = None

    if wants_cost_help and payload.price_context and payload.price_context.estimated_cost:
        estimated_cost = payload.price_context.estimated_cost

        price_references.append(
            PriceReference(
                reference_type="estimated_cost",
                label="Supplied recipe estimated cost",
                value=estimated_cost.total_cost,
                currency=estimated_cost.currency,
                coverage=estimated_cost.coverage,
                source=estimated_cost.source,
            )
        )

        suggested_substitutions.append(
            SuggestedSubstitution(
                from_ingredient="tomato sauce",
                to_ingredient="fresh tomato",
                estimated_savings=None,
                estimated_purchase_savings=None,
                currency=estimated_cost.currency,
                savings_estimable=False,
                tradeoffs=[
                    "Flavor and texture may change.",
                    "Exact savings cannot be estimated from the supplied mock context.",
                ],
                safety_notes=[],
                price_references=price_references,
            )
        )

        updated_estimated_cost = estimated_cost

    return RecipeDiscussResponse(
        answer=(
            "This is a grounded stub answer based on the selected recipe context. "
            "Cost-related claims are only included when structured price context is supplied."
        ),
        grounded_references=[
            GroundedReference(
                recipe_id=recipe_id,
                title=title,
                reference_type="metadata",
                reference_text="Stub recipe context used for discussion.",
            )
        ],
        price_references=price_references,
        suggested_substitutions=suggested_substitutions,
        updated_estimated_cost=updated_estimated_cost,
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
        applied_filters=[],
        warnings=["Mock recipe detail response."],
        grounding_metadata=GroundingMetadata(
            retrieved_from="recipe_corpus_primary",
            matched_count=2,
            missing_count=2,
        ),
    )