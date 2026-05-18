from fastapi import APIRouter

from app.schemas.v1.chat import (
    ChatQueryRequest,
    ChatQueryResponse,
    SafetyFlags,
    SourceReference,
)

router = APIRouter()


@router.post("/query", response_model=ChatQueryResponse)
async def query_chat(payload: ChatQueryRequest) -> ChatQueryResponse:
    return ChatQueryResponse(
        answer=(
            "Mock grounded answer: prioritize balanced meals with recognizable "
            "ingredients and check allergen labels when packaged foods are involved."
        ),
        source_references=[
            SourceReference(
                source_id=payload.context_id,
                source_type="session_context",
                label="Current session context",
                excerpt=payload.question[:160],
                confidence=0.72,
            )
        ],
        safety_flags=SafetyFlags(
            grounded=True,
            medical_advice_blocked=False,
            allergen_caution=bool(payload.profile_overrides and payload.profile_overrides.allergens),
            low_confidence=False,
            notes=["Mock response for API integration testing."],
        ),
        latency_ms=95,
    )
