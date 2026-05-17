from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Double, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


JsonColumn = JSON().with_variant(JSONB, "postgresql")


class LabReport(Base):
    __tablename__ = "lab_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    input_type: Mapped[str] = mapped_column(String(16), nullable=False)
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sections_found: Mapped[list[str]] = mapped_column(
        JsonColumn,
        nullable=False,
        default=list,
    )
    source_extraction_method: Mapped[str] = mapped_column(String(64), nullable=False)
    pages_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    images_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list[str]] = mapped_column(
        JsonColumn, nullable=False, default=list
    )
    raw_text_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user = relationship("User", back_populates="lab_reports")
    tests = relationship(
        "LabReportTest",
        back_populates="lab_report",
        cascade="all, delete-orphan",
        order_by="LabReportTest.id",
    )


class LabReportTest(Base):
    __tablename__ = "lab_report_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lab_report_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("lab_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    test_name: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_test_key: Mapped[str] = mapped_column(String(128), nullable=False)
    result_value_numeric: Mapped[float | None] = mapped_column(Double, nullable=True)
    result_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_interval_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_interval_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_low: Mapped[float | None] = mapped_column(Double, nullable=True)
    reference_high: Mapped[float | None] = mapped_column(Double, nullable=True)
    reference_operator: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reference_bands: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonColumn,
        nullable=False,
        default=list,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    matched_band: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    lab_report = relationship("LabReport", back_populates="tests")
