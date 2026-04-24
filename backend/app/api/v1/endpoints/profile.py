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


@router.get("/{profile_id}", response_model=ProfileUpdateResponse)
async def get_profile(profile_id: str) -> ProfileUpdateResponse:
    return ProfileUpdateResponse(
        profile_id=profile_id,
        normalized_profile=NormalizedProfile(
            age_years=30,
            sex="prefer_not_to_say",
            height_cm=170,
            weight_kg=70,
            activity_level="moderately_active",
            goal="improve_general_health",
            allergens=[],
            dietary_exclusions=[],
            dietary_preferences=["egyptian_foods"],
            exclusion_flags=[],
        ),
        validation_flags=[],
        limitation_flags=["guest_or_session_scoped"],
        support_status=SupportStatus(
            status="supported",
            reason="Mock profile loaded for API integration testing.",
        ),
        updated_at=datetime.now(UTC),
        warnings=["Mock response. Profile storage is not implemented yet."],
    )
