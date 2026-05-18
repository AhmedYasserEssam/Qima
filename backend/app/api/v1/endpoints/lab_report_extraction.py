from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.api.v1.error_responses import build_error_response
from app.schemas.v1.error import ErrorCode, ErrorResponse
from app.schemas.v1.lab_report import LabReportExtractionResponse
from app.services.lab_report_extraction_service import (
    LabReportParseFailedError,
    ScannedPdfNotSupportedError,
    UploadedImage,
    lab_report_extraction_service,
)
from app.services.exceptions import UpstreamUnavailableError

router = APIRouter()

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@router.post(
    "/extract-report",
    response_model=LabReportExtractionResponse,
    responses={
        400: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def extract_lab_report(
    input_type: str = Form(...),
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
) -> LabReportExtractionResponse | JSONResponse:
    normalized_input_type = input_type.strip().casefold()
    if normalized_input_type not in {"pdf", "images"}:
        return _error(
            status_code=400,
            code=ErrorCode.BAD_REQUEST,
            message='input_type must be "pdf" or "images".',
        )

    if normalized_input_type == "pdf":
        validation_error = _validate_pdf_upload(file=file, files=files)
        if validation_error is not None:
            return validation_error
        assert file is not None
        content = await file.read()
        try:
            return lab_report_extraction_service.extract_from_pdf(
                filename=file.filename or "report.pdf",
                content=content,
            )
        except ScannedPdfNotSupportedError as exc:
            return _error(
                status_code=400,
                code=ErrorCode.SCANNED_PDF_NOT_SUPPORTED,
                message=str(exc),
            )
        except LabReportParseFailedError as exc:
            return _error(
                status_code=422,
                code=ErrorCode.LAB_REPORT_PARSE_FAILED,
                message=str(exc),
            )

    validation_error = _validate_image_uploads(file=file, files=files)
    if validation_error is not None:
        return validation_error
    assert files is not None
    images = [
        UploadedImage(filename=image.filename or f"page_{index}.jpg", content=await image.read())
        for index, image in enumerate(files, start=1)
    ]
    try:
        return lab_report_extraction_service.extract_from_images(images=images)
    except UpstreamUnavailableError as exc:
        return _error(
            status_code=503,
            code=ErrorCode.UPSTREAM_UNAVAILABLE,
            message=str(exc) or "Image OCR service is currently unavailable.",
            retryable=True,
        )
    except LabReportParseFailedError as exc:
        return _error(
            status_code=422,
            code=ErrorCode.LAB_REPORT_PARSE_FAILED,
            message=str(exc),
        )


def _validate_pdf_upload(
    *,
    file: UploadFile | None,
    files: list[UploadFile] | None,
) -> JSONResponse | None:
    if file is None:
        return _error(
            status_code=400,
            code=ErrorCode.BAD_REQUEST,
            message='A PDF file is required when input_type is "pdf".',
        )
    if files:
        return _error(
            status_code=400,
            code=ErrorCode.BAD_REQUEST,
            message='Upload exactly one PDF file using the "file" field.',
        )
    if Path(file.filename or "").suffix.casefold() != ".pdf":
        return _error(
            status_code=415,
            code=ErrorCode.BAD_REQUEST,
            message="Unsupported file type. Upload a PDF file.",
        )
    return None


def _validate_image_uploads(
    *,
    file: UploadFile | None,
    files: list[UploadFile] | None,
) -> JSONResponse | None:
    if file is not None:
        return _error(
            status_code=400,
            code=ErrorCode.BAD_REQUEST,
            message='Upload image pages using the "files" field.',
        )
    if not files:
        return _error(
            status_code=400,
            code=ErrorCode.BAD_REQUEST,
            message='One or more image files are required when input_type is "images".',
        )
    for image in files:
        if Path(image.filename or "").suffix.casefold() not in SUPPORTED_IMAGE_EXTENSIONS:
            return _error(
                status_code=415,
                code=ErrorCode.BAD_REQUEST,
                message="Unsupported file type. Upload jpg, jpeg, png, or webp images.",
            )
    return None


def _error(
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    retryable: bool = False,
) -> JSONResponse:
    return build_error_response(
        status_code=status_code,
        code=code,
        message=message,
        retryable=retryable,
        details={},
    )
