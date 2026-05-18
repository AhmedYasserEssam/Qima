from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.parsers.lab_report_parser import parse_lab_report_text
from app.schemas.v1.lab_report import (
    LabReportExtractionResponse,
    LabReportInputType,
    LabReportSource,
)
from app.services.image_ocr_service import ImageOcrService, image_ocr_service
from app.services.pdf_text_extraction_service import (
    PdfTextExtractionService,
    pdf_text_extraction_service,
)


class ScannedPdfNotSupportedError(Exception):
    """Raised when a PDF has no usable embedded text."""


class LabReportParseFailedError(Exception):
    """Raised when extracted text does not contain recognizable lab tests."""


@dataclass(frozen=True)
class UploadedImage:
    filename: str
    content: bytes


class LabReportExtractionService:
    def __init__(
        self,
        *,
        pdf_service: PdfTextExtractionService | None = None,
        ocr_service: ImageOcrService | None = None,
    ) -> None:
        self._pdf_service = pdf_service or pdf_text_extraction_service
        self._ocr_service = ocr_service or image_ocr_service

    def extract_from_pdf(
        self, *, filename: str, content: bytes
    ) -> LabReportExtractionResponse:
        del filename
        with TemporaryDirectory(prefix="qima_lab_upload_") as temp_dir:
            pdf_path = Path(temp_dir) / "report.pdf"
            pdf_path.write_bytes(content)
            extraction = self._pdf_service.extract_text(pdf_path)

        if not self._pdf_service.has_usable_text(extraction.text):
            raise ScannedPdfNotSupportedError(
                "This PDF appears to be scanned or image-based. Upload the pages as images instead."
            )

        return self._build_response(
            input_type=LabReportInputType.PDF,
            text=extraction.text,
            source=LabReportSource(
                extraction_method="opendataloader_pdf",
                pages_processed=extraction.pages_processed,
                images_processed=None,
            ),
        )

    def extract_from_images(
        self, *, images: list[UploadedImage]
    ) -> LabReportExtractionResponse:
        with TemporaryDirectory(prefix="qima_lab_images_") as temp_dir:
            image_paths: list[Path] = []
            for index, image in enumerate(images, start=1):
                suffix = Path(image.filename).suffix.lower()
                image_path = Path(temp_dir) / f"page_{index}{suffix}"
                image_path.write_bytes(image.content)
                image_paths.append(image_path)
            extraction = self._ocr_service.extract_text_from_images(image_paths)

        return self._build_response(
            input_type=LabReportInputType.IMAGES,
            text=extraction.text,
            source=LabReportSource(
                extraction_method="paddleocr",
                pages_processed=None,
                images_processed=extraction.images_processed,
            ),
        )

    def _build_response(
        self,
        *,
        input_type: LabReportInputType,
        text: str,
        source: LabReportSource,
    ) -> LabReportExtractionResponse:
        parsed = parse_lab_report_text(text)
        if not parsed.tests:
            raise LabReportParseFailedError(
                "Extracted text did not contain recognizable lab tests."
            )

        return LabReportExtractionResponse(
            input_type=input_type,
            tests=parsed.tests,
            sections_found=parsed.sections_found,
            source=source,
            warnings=parsed.warnings,
            raw_text_preview=_preview_text(text),
        )


def _preview_text(text: str, limit: int = 1200) -> str:
    return text.strip()[:limit]


lab_report_extraction_service = LabReportExtractionService()
