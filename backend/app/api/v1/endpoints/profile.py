from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps.auth import get_current_user
from app.models.user import User
from app.schemas.v1.profile import NutritionProfileCreateUpdate, NutritionProfileResponse
from app.services.exceptions import NotFoundError
from app.services.profile_service import profile_service

router = APIRouter()


@router.post("/update", response_model=NutritionProfileResponse)
async def update_profile(
    payload: NutritionProfileCreateUpdate,
    current_user: User = Depends(get_current_user),
) -> NutritionProfileResponse:
    return profile_service.upsert_profile(user=current_user, payload=payload)


@router.get("/me", response_model=NutritionProfileResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
) -> NutritionProfileResponse:
    try:
        return profile_service.get_my_profile(user=current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
