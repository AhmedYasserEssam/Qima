from datetime import UTC, datetime

from fastapi import APIRouter

from app.schemas.v1.profile import (
    NormalizedProfile,
    ProfileUpdateRequest,
    ProfileUpdateResponse,
    SupportStatus,
)

router = APIRouter()


@router.post("/update", response_model=ProfileUpdateResponse)
async def update_profile(payload: ProfileUpdateRequest) -> ProfileUpdateResponse:
    return ProfileUpdateResponse(
        profile_id=payload.profile_id or "profile_stub_001",
        normalized_profile=NormalizedProfile(
            age_years=payload.age_years,
            sex=payload.sex,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
            activity_level=payload.activity_level,
            goal=payload.goal,
            allergens=payload.allergens,
            dietary_exclusions=payload.dietary_exclusions,
            dietary_preferences=payload.dietary_preferences,
            exclusion_flags=payload.exclusion_flags,
        ),
        validation_flags=[],
        limitation_flags=["guest_or_session_scoped"],
        support_status=SupportStatus(
            status="supported",
            reason="Stub profile accepted for bounded guidance.",
        ),
        updated_at=datetime.now(UTC),
        warnings=[
            "Stub response. Profile context is not diagnosis or treatment."
        ],
    )