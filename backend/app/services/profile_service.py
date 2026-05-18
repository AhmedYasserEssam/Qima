from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models.lab_report import LabReport, LabReportTest
from app.models.nutrition_profile import NutritionProfile
from app.models.user import User
from app.parsers.lab_report_parser import classify_categorical_band_status
from app.schemas.v1.lab_report import LabReportReferenceInterval, LabReportReferenceType
from app.schemas.v1.profile import (
    NutritionProfileCreateUpdate,
    NutritionProfileResponse,
    ProfileLabResult,
)
from app.services.exceptions import NotFoundError


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_to_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)


def _profile_response(
    *,
    user_id: int,
    profile: NutritionProfile,
    lab_results: list[ProfileLabResult] | None = None,
) -> NutritionProfileResponse:
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
        lab_results=lab_results or [],
        updated_at=_naive_to_utc(profile.updated_at),
    )


def _latest_lab_results_for_user(
    session: Session, *, user_id: int
) -> list[ProfileLabResult]:
    rows = session.execute(
        select(LabReport, LabReportTest)
        .join(LabReportTest, LabReportTest.lab_report_id == LabReport.id)
        .where(LabReport.user_id == user_id)
        .order_by(
            LabReport.confirmed_at.desc(),
            LabReport.id.desc(),
            LabReportTest.id.desc(),
        )
    ).all()

    latest_by_key: list[ProfileLabResult] = []
    seen_keys: set[str] = set()
    for report, test in rows:
        key = str(test.canonical_test_key or "").strip()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        latest_by_key.append(_lab_result_response(report=report, test=test))
    return latest_by_key


def _lab_result_response(*, report: LabReport, test: LabReportTest) -> ProfileLabResult:
    result_value: float | str | None = test.result_value_numeric
    if result_value is None:
        result_value = test.result_value_text
    status = test.status
    if test.reference_interval_type == LabReportReferenceType.CATEGORICAL_BANDS.value:
        status = (
            classify_categorical_band_status(
                canonical_test_key=test.canonical_test_key,
                matched_band=test.matched_band,
            )
            or test.status
        )
    return ProfileLabResult(
        report_id=report.id,
        test_name=test.test_name,
        canonical_test_key=test.canonical_test_key,
        section=test.section,
        result_value=result_value,
        unit=test.unit,
        reference_interval=LabReportReferenceInterval(
            raw=test.reference_interval_raw,
            type=test.reference_interval_type,
            low=test.reference_low,
            high=test.reference_high,
            operator=test.reference_operator,
            bands=test.reference_bands or [],
        ),
        status=status,
        matched_band=test.matched_band,
        confidence=test.confidence,
        confirmed_at=_naive_to_utc(report.confirmed_at),
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

            response = _profile_response(
                user_id=user.id,
                profile=profile,
                lab_results=_latest_lab_results_for_user(session, user_id=user.id),
            )
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

            return _profile_response(
                user_id=user.id,
                profile=profile,
                lab_results=_latest_lab_results_for_user(session, user_id=user.id),
            )


profile_service = ProfileService()
