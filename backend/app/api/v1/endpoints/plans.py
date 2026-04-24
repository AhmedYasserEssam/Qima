from fastapi import APIRouter, HTTPException, status

from app.schemas.plans import PlansGenerateRequest, PlansGenerateSuccess
from app.services.exceptions import UpstreamUnavailableError
from app.services.plans_service import PlansService


router = APIRouter(prefix="/plans", tags=["plans"])


@router.post(
    "/generate",
    response_model=PlansGenerateSuccess,
    status_code=status.HTTP_200_OK,
    summary="Generate bounded goal-based meal guidance",
)
async def generate_plan(payload: PlansGenerateRequest) -> PlansGenerateSuccess:
    """
    POST /v1/plans/generate

    Generates grounded, non-clinical meal guidance using either a saved
    profile_id or an inline profile.
    """
    try:
        return await PlansService.generate(payload)

    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected plan generation failure.",
        ) from exc