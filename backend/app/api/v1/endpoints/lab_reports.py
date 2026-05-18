from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps.auth import get_current_user
from app.models.user import User
from app.schemas.v1.error import ErrorResponse
from app.schemas.v1.lab_report import (
    LabReportListResponse,
    LabReportRecord,
    LabReportSaveRequest,
    LabReportSaveResponse,
)
from app.services.exceptions import BadRequestError, NotFoundError
from app.services.lab_report_persistence_service import (
    LabReportPersistenceError,
    lab_report_persistence_service,
)

router = APIRouter()


@router.post(
    "/reports",
    response_model=LabReportSaveResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def save_lab_report(
    payload: LabReportSaveRequest,
    current_user: User = Depends(get_current_user),
) -> LabReportSaveResponse:
    try:
        return lab_report_persistence_service.save_report(
            user=current_user,
            payload=payload,
        )
    except BadRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except LabReportPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Lab report could not be saved.",
        ) from exc


@router.get("/reports", response_model=LabReportListResponse)
async def list_lab_reports(
    current_user: User = Depends(get_current_user),
) -> LabReportListResponse:
    return lab_report_persistence_service.list_reports(user=current_user)


@router.get(
    "/reports/{report_id}",
    response_model=LabReportRecord,
    responses={404: {"model": ErrorResponse}},
)
async def get_lab_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
) -> LabReportRecord:
    try:
        return lab_report_persistence_service.get_report(
            user=current_user,
            report_id=report_id,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
