from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select

from app.core.security import decode_access_token, is_jwt_invalid
from app.db import SessionLocal
from app.models.user import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/v1/auth/login",
    auto_error=False,
)


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        user_id = int(sub)
    except Exception as exc:  # noqa: BLE001
        if is_jwt_invalid(exc) or isinstance(exc, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials.",
            ) from exc
        raise

    with SessionLocal() as session:
        user = session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
        )
    return user


def get_optional_current_user(
    token: str | None = Depends(oauth2_scheme_optional),
) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        user_id = int(sub)
    except Exception as exc:  # noqa: BLE001
        if is_jwt_invalid(exc) or isinstance(exc, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials.",
            ) from exc
        raise

    with SessionLocal() as session:
        user = session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
        )

    return user
