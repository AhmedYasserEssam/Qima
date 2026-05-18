from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.db import SessionLocal, init_db
from app.models.lab_report import LabReport, LabReportTest
from app.models.user import User
from app.parsers.lab_report_parser import classify_result, match_categorical_band
from app.schemas.v1.lab_report import (
    LabReportListResponse,
    LabReportRecord,
    LabReportReferenceInterval,
    LabReportReferenceType,
    LabReportSaveRequest,
    LabReportSaveResponse,
    LabReportSource,
    LabReportStatus,
    LabReportTest as LabReportTestSchema,
)
from app.services.exceptions import BadRequestError, NotFoundError, ServiceError


class LabReportPersistenceError(ServiceError):
    """Raised when a lab report cannot be persisted safely."""


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_to_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)


class LabReportPersistenceService:
    def __init__(self) -> None:
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        init_db()
        self._initialized = True

    def save_report(
        self, *, user: User, payload: LabReportSaveRequest
    ) -> LabReportSaveResponse:
        self._ensure_initialized()
        if not payload.tests:
            raise BadRequestError("At least one lab test is required.")

        now = _utc_now_naive()
        try:
            with SessionLocal.begin() as session:
                report = LabReport(
                    user_id=user.id,
                    input_type=payload.input_type.value,
                    report_type=payload.report_type,
                    sections_found=[
                        section.value for section in payload.sections_found
                    ],
                    source_extraction_method=payload.source.extraction_method,
                    pages_processed=payload.source.pages_processed,
                    images_processed=payload.source.images_processed,
                    warnings=list(payload.warnings),
                    raw_text_preview=payload.raw_text_preview,
                    extracted_at=now,
                    confirmed_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(report)
                session.flush()

                for test in payload.tests:
                    report.tests.append(
                        _to_test_row(report_id=report.id, test=test, now=now)
                    )

                session.flush()
                created = self._to_record(report)
        except SQLAlchemyError as exc:
            raise LabReportPersistenceError("Lab report could not be saved.") from exc

        return LabReportSaveResponse(report=created)

    def list_reports(self, *, user: User) -> LabReportListResponse:
        self._ensure_initialized()
        with SessionLocal() as session:
            reports = (
                session.execute(
                    select(LabReport)
                    .options(selectinload(LabReport.tests))
                    .where(LabReport.user_id == user.id)
                    .order_by(LabReport.created_at.desc(), LabReport.id.desc())
                )
                .scalars()
                .all()
            )
            records = [self._to_record(report) for report in reports]
        return LabReportListResponse(reports=records)

    def get_report(self, *, user: User, report_id: int) -> LabReportRecord:
        self._ensure_initialized()
        with SessionLocal() as session:
            report = session.execute(
                select(LabReport)
                .options(selectinload(LabReport.tests))
                .where(LabReport.id == report_id, LabReport.user_id == user.id)
            ).scalar_one_or_none()
            if report is None:
                raise NotFoundError("Lab report not found.")
            return self._to_record(report)

    def _to_record(self, report: LabReport) -> LabReportRecord:
        return LabReportRecord(
            id=report.id,
            input_type=report.input_type,
            report_type="lab_report",
            tests=[_to_test_schema(test) for test in report.tests],
            sections_found=report.sections_found,
            source=LabReportSource(
                extraction_method=report.source_extraction_method,
                pages_processed=report.pages_processed,
                images_processed=report.images_processed,
            ),
            warnings=report.warnings,
            raw_text_preview=report.raw_text_preview,
            extracted_at=_naive_to_utc(report.extracted_at),
            confirmed_at=_naive_to_utc(report.confirmed_at),
            created_at=_naive_to_utc(report.created_at),
            updated_at=_naive_to_utc(report.updated_at),
        )


def _to_test_row(
    *, report_id: int, test: LabReportTestSchema, now: datetime
) -> LabReportTest:
    result_numeric, result_text = _split_result_value(test.result_value)
    status = _status_for_test(test)
    matched_band = _matched_band_for_test(test)
    reference = test.reference_interval
    return LabReportTest(
        lab_report_id=report_id,
        section=test.section.value,
        test_name=test.test_name,
        canonical_test_key=test.canonical_test_key,
        result_value_numeric=result_numeric,
        result_value_text=result_text,
        unit=test.unit,
        reference_interval_raw=reference.raw,
        reference_interval_type=reference.type.value,
        reference_low=reference.low,
        reference_high=reference.high,
        reference_operator=reference.operator,
        reference_bands=[band.model_dump(mode="json") for band in reference.bands],
        status=status.value,
        matched_band=matched_band,
        raw_text=test.raw_text,
        confidence=test.confidence,
        created_at=now,
    )


def _split_result_value(value: float | str | None) -> tuple[float | None, str | None]:
    if isinstance(value, int | float):
        return float(value), None
    if value is None:
        return None, None
    return None, str(value)


def _status_for_test(test: LabReportTestSchema) -> LabReportStatus:
    if test.reference_interval.type == LabReportReferenceType.CATEGORICAL_BANDS:
        return LabReportStatus.INDETERMINATE
    return classify_result(test.result_value, test.reference_interval)


def _matched_band_for_test(test: LabReportTestSchema) -> str | None:
    if test.reference_interval.type != LabReportReferenceType.CATEGORICAL_BANDS:
        return test.matched_band
    return match_categorical_band(test.result_value, test.reference_interval.bands)


def _to_test_schema(row: LabReportTest) -> LabReportTestSchema:
    reference_interval = LabReportReferenceInterval(
        raw=row.reference_interval_raw,
        type=row.reference_interval_type,
        low=row.reference_low,
        high=row.reference_high,
        operator=row.reference_operator,
        bands=row.reference_bands,
    )
    result_value: float | str | None = row.result_value_numeric
    if result_value is None:
        result_value = row.result_value_text
    return LabReportTestSchema(
        section=row.section,
        test_name=row.test_name,
        canonical_test_key=row.canonical_test_key,
        result_value=result_value,
        unit=row.unit,
        reference_interval=reference_interval,
        status=row.status,
        matched_band=row.matched_band,
        raw_text=row.raw_text,
        confidence=row.confidence,
    )


lab_report_persistence_service = LabReportPersistenceService()
