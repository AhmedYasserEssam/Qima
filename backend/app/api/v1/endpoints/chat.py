from fastapi import APIRouter

from app.schemas.v1.chat import (
    ChatQueryRequest,
    ChatQueryResponse,
    CostSavingAction,
    PriceReference,
    SafetyFlags,
    SourceReference,
)

router = APIRouter()


def _is_price_sensitive_question(question: str) -> bool:
    normalized = question.lower()
    price_terms = (
        "cheap",
        "cheaper",
        "cost",
        "price",
        "budget",
        "affordable",
        "expensive",
        "save",
        "savings",
        "under",
    )
    return any(term in normalized for term in price_terms)


@router.post("/query", response_model=ChatQueryResponse)
async def query_chat(payload: ChatQueryRequest) -> ChatQueryResponse:
    is_price_sensitive = _is_price_sensitive_question(payload.question)
    has_price_context = bool(
        payload.food_context
        and (
            payload.food_context.estimated_costs
            or any(recipe.estimated_cost for recipe in payload.food_context.recipes)
            or payload.food_context.budget
        )
    )

    source_references = [
        SourceReference(
            source_id=payload.context_id,
            source_type="session_context",
            label="Current session context",
            excerpt=payload.question[:160],
            confidence=0.72,
        )
    ]

    price_references: list[PriceReference] = []
    cost_saving_actions: list[CostSavingAction] = []
    recommended_recipe_ids: list[str] = []

    if payload.food_context and payload.food_context.recipes:
        recommended_recipe_ids = [
            recipe.recipe_id for recipe in payload.food_context.recipes[:2]
        ]

        source_references.append(
            SourceReference(
                source_id="recipe_context",
                source_type="recipe_corpus",
                label="Active recipe context",
                excerpt=", ".join(recipe.title for recipe in payload.food_context.recipes[:3]),
                confidence=0.8,
            )
        )

    if is_price_sensitive and has_price_context:
        source_references.append(
            SourceReference(
                source_id="price_context",
                source_type="price_context",
                label="Structured price context",
                excerpt="Price-aware response grounded in supplied recipe, budget, or estimated cost context.",
                confidence=0.7,
            )
        )

        price_references.append(
            PriceReference(
                reference_type="estimated_cost",
                label="Available structured price context",
                coverage=(
                    payload.food_context.estimated_costs[0].coverage
                    if payload.food_context and payload.food_context.estimated_costs
                    else None
                ),
            )
        )

        cost_saving_actions.append(
            CostSavingAction(
                action_type="choose_lower_cost_recipe",
                description=(
                    "Compare available recipe candidates using estimated cost and choose the lower-cost grounded option."
                ),
                recipe_id=(
                    payload.food_context.recipes[0].recipe_id
                    if payload.food_context and payload.food_context.recipes
                    else None
                ),
                savings_estimable=False,
                warnings=[
                    "Mock action only; exact savings require service-level price estimation."
                ],
            )
        )

        answer = (
            "Mock price-aware answer: use the structured recipe and price context to prefer "
            "lower-cost candidates, pantry-owned ingredients, and substitutions only when "
            "price coverage is available. Prices are estimates, not live market prices."
        )

    elif is_price_sensitive and not has_price_context:
        answer = (
            "Mock limited answer: I cannot estimate cost from this chat request because no "
            "structured price context was provided. Refresh recipe suggestions with price awareness "
            "or call the price estimate flow first."
        )

    else:
        answer = (
            "Mock grounded answer: prioritize balanced meals with recognizable ingredients "
            "and check allergen labels when packaged foods are involved."
        )

    return ChatQueryResponse(
        answer=answer,
        source_references=source_references,
        price_references=price_references,
        recommended_recipe_ids=recommended_recipe_ids,
        cost_saving_actions=cost_saving_actions,
        safety_flags=SafetyFlags(
            grounded=True,
            medical_advice_blocked=False,
            allergen_caution=bool(
                payload.profile_overrides and payload.profile_overrides.allergens
            ),
            low_confidence=False,
            price_context_missing=is_price_sensitive and not has_price_context,
            notes=["Mock response for API integration testing."],
        ),
        latency_ms=95,
    )