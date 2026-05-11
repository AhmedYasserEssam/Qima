from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.security import verify_password
from app.db import SessionLocal, init_db
from app.main import app
from app.models.nutrition_profile import NutritionProfile
from app.models.user import User


client = TestClient(app)


def _email() -> str:
    return f"auth-test-{uuid4().hex[:10]}@example.com"


def _signup_payload(email: str, *, name: str = "Test User") -> dict[str, str]:
    return {
        "email": email,
        "password": "StrongPass123!",
        "name": name,
    }


def _safety_none_payload() -> dict[str, bool]:
    return {
        "pregnant": False,
        "breastfeeding": False,
        "eating_disorder_history": False,
        "under_18": False,
        "medical_condition_affects_diet": False,
        "abnormal_labs_or_health_concerns": False,
        "none_of_above": True,
    }


def _cleanup_user(email: str) -> None:
    normalized = email.strip().lower()
    init_db()
    with SessionLocal.begin() as session:
        user = session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()
        if user is not None:
            session.execute(delete(User).where(User.id == user.id))


def test_signup_creates_user_and_hashes_password() -> None:
    email = _email()
    try:
        response = client.post("/v1/auth/signup", json=_signup_payload(email, name="User Name"))
        assert response.status_code == 201
        body = response.json()
        assert body["message"] == "Account created successfully. You can now log in."
        assert body["user"]["email"] == email.lower()
        assert body["user"]["name"] == "User Name"
        assert isinstance(body["user"]["id"], int)

        with SessionLocal() as session:
            user = session.execute(select(User).where(User.email == email.lower())).scalar_one()

        assert user.password_hash != "StrongPass123!"
        assert verify_password("StrongPass123!", user.password_hash)
        assert user.name == "User Name"
        assert user.is_email_verified is True
    finally:
        _cleanup_user(email)


def test_duplicate_signup_is_blocked_with_shared_error_shape() -> None:
    email = _email()
    try:
        first = client.post("/v1/auth/signup", json=_signup_payload(email))
        assert first.status_code == 201

        second = client.post("/v1/auth/signup", json=_signup_payload(email, name="Another User"))
        assert second.status_code == 409
        assert second.json() == {
            "error": {
                "code": "ACCOUNT_ALREADY_EXISTS",
                "message": "An account with this email already exists. Please log in instead.",
                "retryable": False,
                "request_id": second.json()["error"]["request_id"],
                "details": {},
            }
        }
        assert second.json()["error"]["request_id"].startswith("req_")
    finally:
        _cleanup_user(email)


def test_login_succeeds_with_valid_credentials() -> None:
    email = _email()
    try:
        signup = client.post("/v1/auth/signup", json=_signup_payload(email, name="Login User"))
        assert signup.status_code == 201

        login = client.post(
            "/v1/auth/login",
            json={"email": email, "password": "StrongPass123!"},
        )
        assert login.status_code == 200
        body = login.json()
        assert body["message"] == "Logged in successfully."
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user"]["email"] == email.lower()
        assert body["user"]["name"] == "Login User"
        assert isinstance(body["user"]["id"], int)
    finally:
        _cleanup_user(email)


def test_login_unknown_email_returns_not_found_error() -> None:
    email = _email()
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "StrongPass123!"},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert body["error"]["message"] == "No account was found with this email. Please sign up first."
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"].startswith("req_")
    assert body["error"]["details"] == {}


def test_login_wrong_password_returns_unauthorized_error() -> None:
    email = _email()
    try:
        signup = client.post("/v1/auth/signup", json=_signup_payload(email))
        assert signup.status_code == 201

        login = client.post(
            "/v1/auth/login",
            json={"email": email, "password": "WrongPass123!"},
        )
        assert login.status_code == 401
        body = login.json()
        assert body["error"]["code"] == "INVALID_PASSWORD"
        assert body["error"]["message"] == "Incorrect password. Please try again."
        assert body["error"]["retryable"] is False
        assert body["error"]["request_id"].startswith("req_")
        assert body["error"]["details"] == {}
    finally:
        _cleanup_user(email)


def test_email_uniqueness_is_enforced_at_database_level() -> None:
    email = _email().upper()
    normalized = email.strip().lower()
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        init_db()
        with SessionLocal() as session:
            first_user = User(
                name="First User",
                email=normalized,
                password_hash="hash-1",
                is_email_verified=True,
                created_at=now,
                updated_at=now,
            )
            session.add(first_user)
            session.commit()

            duplicate_user = User(
                name="Second User",
                email=normalized,
                password_hash="hash-2",
                is_email_verified=True,
                created_at=now,
                updated_at=now,
            )
            session.add(duplicate_user)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        _cleanup_user(normalized)


def test_profile_endpoints_require_authentication() -> None:
    me = client.get("/v1/profile/me")
    assert me.status_code == 401


def test_profile_me_returns_onboarding_guidance_when_profile_missing() -> None:
    email = _email()
    try:
        signup = client.post("/v1/auth/signup", json=_signup_payload(email, name="No Profile User"))
        assert signup.status_code == 201

        login = client.post("/v1/auth/login", json={"email": email, "password": "StrongPass123!"})
        assert login.status_code == 200
        access_token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        me = client.get("/v1/profile/me", headers=headers)
        assert me.status_code == 404
        assert me.json() == {
            "error": {
                "code": "NOT_FOUND",
                "message": "Profile not found. Complete onboarding by calling POST /v1/profile/update first.",
                "retryable": False,
                "request_id": me.json()["error"]["request_id"],
                "details": {},
            }
        }
        assert me.json()["error"]["request_id"].startswith("req_")
    finally:
        _cleanup_user(email)


def test_profile_create_update_and_me_for_authenticated_user() -> None:
    email = _email()
    try:
        signup = client.post(
            "/v1/auth/signup",
            json=_signup_payload(email, name="Profile User"),
        )
        assert signup.status_code == 201
        login = client.post("/v1/auth/login", json={"email": email, "password": "StrongPass123!"})
        assert login.status_code == 200

        access_token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        create_payload = {
            "age": 29,
            "sex": "male",
            "height_cm": 180.2,
            "weight_kg": 83.1,
            "activity_level": "moderately_active",
            "goal": "improve_general_health",
            "allergens": ["Milk", " milk ", "PEANUT"],
            "dietary_restrictions": ["Halal", " halal ", "Low_Sodium"],
            "safety_screening": _safety_none_payload(),
            "agreement_accepted": True,
        }
        create_response = client.post("/v1/profile/update", json=create_payload, headers=headers)
        assert create_response.status_code == 200
        body = create_response.json()
        assert body["allergens"] == ["milk", "peanut"]
        assert body["dietary_restrictions"] == ["halal", "low_sodium"]
        assert body["safety_screening"]["none_of_above"] is True
        assert body["agreement_accepted"] is True

        update_payload = {
            "age": 30,
            "sex": "male",
            "height_cm": 181.0,
            "weight_kg": 82.0,
            "activity_level": "lightly_active",
            "goal": "reduce_sugar",
            "allergens": ["sesame"],
            "dietary_restrictions": ["vegetarian"],
            "safety_screening": {
                **_safety_none_payload(),
                "none_of_above": False,
                "medical_condition_affects_diet": True,
            },
            "agreement_accepted": True,
        }
        update_response = client.post("/v1/profile/update", json=update_payload, headers=headers)
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["age"] == 30
        assert updated["allergens"] == ["sesame"]
        assert updated["dietary_restrictions"] == ["vegetarian"]
        assert updated["goal"] == "reduce_sugar"
        assert updated["safety_screening"]["medical_condition_affects_diet"] is True
        assert updated["safety_screening"]["none_of_above"] is False

        me = client.get("/v1/profile/me", headers=headers)
        assert me.status_code == 200
        me_body = me.json()
        assert me_body["allergens"] == ["sesame"]
        assert me_body["dietary_restrictions"] == ["vegetarian"]
        assert me_body["agreement_accepted"] is True

        with SessionLocal() as session:
            user = session.execute(select(User).where(User.email == email.lower())).scalar_one()
            profiles = session.execute(
                select(NutritionProfile).where(NutritionProfile.user_id == user.id)
            ).scalars().all()
        assert len(profiles) == 1
    finally:
        _cleanup_user(email)
