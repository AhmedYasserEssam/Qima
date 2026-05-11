from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models.nutrition_profile import NutritionProfile
from app.models.user import User
from app.schemas.v1.profile import NutritionProfileCreateUpdate, NutritionProfileResponse
from app.services.exceptions import NotFoundError


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_to_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)


def _profile_response(*, user_id: int, profile: NutritionProfile) -> NutritionProfileResponse:
    return NutritionProfileResponse(
        user_id=user_id,
        age=profile.age,
        sex=profile.sex,
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
        activity_level=profile.activity_level,
        goal=profile.nutrition_goal,
        allergens=profile.allergens or [],
        dietary_restrictions=profile.dietary_restrictions or [],
        safety_screening=profile.safety_screening
        or {
            "pregnant": False,
            "breastfeeding": False,
            "eating_disorder_history": False,
            "under_18": False,
            "medical_condition_affects_diet": False,
            "abnormal_labs_or_health_concerns": False,
            "none_of_above": True,
        },
        agreement_accepted=profile.agreement_accepted,
        updated_at=_naive_to_utc(profile.updated_at),
    )


class ProfileService:
    def __init__(self) -> None:
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        init_db()
        self._initialized = True

    def upsert_profile(
        self,
        *,
        user: User,
        payload: NutritionProfileCreateUpdate,
    ) -> NutritionProfileResponse:
        self._ensure_initialized()
        now = _utc_now_naive()

        with SessionLocal.begin() as session:
            profile = session.execute(
                select(NutritionProfile).where(NutritionProfile.user_id == user.id)
            ).scalar_one_or_none()

            if profile is None:
                profile = NutritionProfile(
                    user_id=user.id,
                    age=payload.age,
                    sex=payload.sex.value,
                    height_cm=payload.height_cm,
                    weight_kg=payload.weight_kg,
                    activity_level=payload.activity_level.value,
                    nutrition_goal=payload.goal.value,
                    allergens=payload.allergens,
                    dietary_restrictions=payload.dietary_restrictions,
                    safety_screening=payload.safety_screening.model_dump(),
                    agreement_accepted=payload.agreement_accepted,
                    created_at=now,
                    updated_at=now,
                )
                session.add(profile)
                session.flush()
            else:
                profile.age = payload.age
                profile.sex = payload.sex.value
                profile.height_cm = payload.height_cm
                profile.weight_kg = payload.weight_kg
                profile.activity_level = payload.activity_level.value
                profile.nutrition_goal = payload.goal.value
                profile.allergens = payload.allergens
                profile.dietary_restrictions = payload.dietary_restrictions
                profile.safety_screening = payload.safety_screening.model_dump()
                profile.agreement_accepted = payload.agreement_accepted
                profile.updated_at = now
                session.flush()

            response = _profile_response(user_id=user.id, profile=profile)
        return response

    def get_my_profile(self, *, user: User) -> NutritionProfileResponse:
        self._ensure_initialized()
        with SessionLocal() as session:
            profile = session.execute(
                select(NutritionProfile).where(NutritionProfile.user_id == user.id)
            ).scalar_one_or_none()

        if profile is None:
            raise NotFoundError(
                "Profile not found. Complete onboarding by calling POST /v1/profile/update first."
            )

        return _profile_response(user_id=user.id, profile=profile)


profile_service = ProfileService()
