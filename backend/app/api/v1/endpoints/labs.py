from fastapi import APIRouter, HTTPException, status

from app.schemas.v1.labs import LabsInterpretRequest, LabsInterpretSuccess
from app.services.exceptions import NotFoundError, UpstreamUnavailableError
from app.services.labs_service import LabsService


router = APIRouter(prefix="/labs", tags=["labs"])


@router.post(
    "/interpret",
    response_model=LabsInterpretSuccess,
    status_code=status.HTTP_200_OK,
    summary="Interpret a supported lab marker for food-oriented guidance",
)
async def interpret_labs(payload: LabsInterpretRequest) -> LabsInterpretSuccess:
    """
    POST /v1/labs/interpret

    Returns whitelist-only, food-oriented, non-diagnostic lab-marker guidance.
    """
    try:
        return await LabsService.interpret(payload)

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected lab interpretation failure.",
        ) from exc