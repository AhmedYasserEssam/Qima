from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token, hash_password, normalize_email, verify_password
from app.db import SessionLocal, init_db
from app.models.user import User
from app.schemas.v1.auth import (
    AuthUserResponse,
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
)
from app.services.exceptions import (
    AccountAlreadyExistsError,
    AccountNotFoundError,
    InvalidPasswordError,
)


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _is_unique_email_violation(exc: IntegrityError) -> bool:
    message = str(exc).lower()
    return "email" in message and "unique" in message


def _to_auth_user(user: User) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
    )


class AuthService:
    def __init__(self) -> None:
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        init_db()
        self._initialized = True

    def signup(self, payload: SignupRequest) -> SignupResponse:
        self._ensure_initialized()
        email = normalize_email(str(payload.email))
        now = _utc_now_naive()
        password_hash = hash_password(payload.password)
        friendly_message = "An account with this email already exists. Please log in instead."

        with SessionLocal.begin() as session:
            existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if existing is not None:
                raise AccountAlreadyExistsError(friendly_message)

            user = User(
                name=payload.name.strip(),
                email=email,
                password_hash=password_hash,
                is_email_verified=True,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            try:
                session.flush()
            except IntegrityError as exc:
                if _is_unique_email_violation(exc):
                    raise AccountAlreadyExistsError(friendly_message) from exc
                raise

            created_user = _to_auth_user(user)

        return SignupResponse(
            message="Account created successfully. You can now log in.",
            user=created_user,
        )

    def login(self, payload: LoginRequest) -> LoginResponse:
        self._ensure_initialized()
        email = normalize_email(str(payload.email))
        now = _utc_now_naive()

        with SessionLocal.begin() as session:
            user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user is None:
                raise AccountNotFoundError(
                    "No account was found with this email. Please sign up first."
                )
            if not verify_password(payload.password, user.password_hash):
                raise InvalidPasswordError("Incorrect password. Please try again.")

            user.last_login_at = now
            user.updated_at = now
            access_token = create_access_token(subject=str(user.id))
            auth_user = _to_auth_user(user)

        return LoginResponse(
            message="Logged in successfully.",
            access_token=access_token,
            token_type="bearer",
            user=auth_user,
        )


auth_service = AuthService()
