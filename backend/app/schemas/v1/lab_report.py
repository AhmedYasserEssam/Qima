from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonEmptyString = Annotated[str, StringConstraints(min_length=1)]


class LabReportInputType(StrEnum):
    PDF = "pdf"
    IMAGES = "images"


class LabReportSection(StrEnum):
    CHEMISTRY = "chemistry"
    HORMONE = "hormone"
    IMMUNOLOGY = "immunology"
    UNKNOWN = "unknown"


class LabReportReferenceType(StrEnum):
    NUMERIC_RANGE = "numeric_range"
    LOWER_BOUND = "lower_bound"
    UPPER_BOUND = "upper_bound"
    CATEGORICAL_BANDS = "categorical_bands"
    TEXT = "text"
    UNKNOWN = "unknown"


class LabReportStatus(StrEnum):
    BELOW_RANGE = "below_range"
    WITHIN_RANGE = "within_range"
    ABOVE_RANGE = "above_range"
    INDETERMINATE = "indeterminate"


class LabReportBand(StrictBaseModel):
    label: NonEmptyString
    operator: str | None = None
    low: float | None = None
    high: float | None = None
    raw: NonEmptyString


class LabReportReferenceInterval(StrictBaseModel):
    raw: str | None = None
    type: LabReportReferenceType
    low: float | None = None
    high: float | None = None
    operator: str | None = None
    bands: list[LabReportBand] = Field(default_factory=list)


class LabReportTest(StrictBaseModel):
    section: LabReportSection
    test_name: NonEmptyString
    canonical_test_key: NonEmptyString
    result_value: float | str | None
    unit: str | None = None
    reference_interval: LabReportReferenceInterval
    status: LabReportStatus
    raw_text: NonEmptyString
    confidence: float | None = Field(default=None, ge=0, le=1)
    matched_band: str | None = None


class LabReportSource(StrictBaseModel):
    extraction_method: Literal["opendataloader_pdf", "paddleocr"]
    pages_processed: int | None = None
    images_processed: int | None = None


class LabReportExtractionResponse(StrictBaseModel):
    input_type: LabReportInputType
    report_type: Literal["lab_report"] = "lab_report"
    tests: list[LabReportTest]
    sections_found: list[LabReportSection]
    source: LabReportSource
    warnings: list[str]
    raw_text_preview: str


class LabReportSaveRequest(StrictBaseModel):
    input_type: LabReportInputType
    report_type: Literal["lab_report"] = "lab_report"
    tests: list[LabReportTest] = Field(min_length=1)
    sections_found: list[LabReportSection] = Field(default_factory=list)
    source: LabReportSource
    warnings: list[str] = Field(default_factory=list)
    raw_text_preview: str | None = None


class LabReportRecord(StrictBaseModel):
    id: int
    input_type: LabReportInputType
    report_type: Literal["lab_report"] = "lab_report"
    tests: list[LabReportTest]
    sections_found: list[LabReportSection]
    source: LabReportSource
    warnings: list[str]
    raw_text_preview: str | None = None
    extracted_at: datetime
    confirmed_at: datetime
    created_at: datetime
    updated_at: datetime


class LabReportSaveResponse(StrictBaseModel):
    report: LabReportRecord


class LabReportListResponse(StrictBaseModel):
    reports: list[LabReportRecord]
