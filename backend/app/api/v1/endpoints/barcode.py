from fastapi import APIRouter, HTTPException, status

from app.schemas.v1.barcode import BarcodeLookupRequest, BarcodeLookupSuccess
from app.services.barcode_service import BarcodeService
from app.services.exceptions import NotFoundError, UpstreamUnavailableError


router = APIRouter(prefix="/barcode", tags=["barcode"])


@router.post(
    "/lookup",
    response_model=BarcodeLookupSuccess,
    status_code=status.HTTP_200_OK,
    summary="Look up packaged food by barcode",
)
async def lookup_barcode(payload: BarcodeLookupRequest) -> BarcodeLookupSuccess:
    """
    POST /v1/barcode/lookup

    Looks up a packaged food product by barcode and returns the backend-normalized
    product payload required by the public v1 contract.
    """
    try:
        return await BarcodeService.lookup(payload.barcode)

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
            detail="Unexpected barcode lookup failure.",
        ) from exc