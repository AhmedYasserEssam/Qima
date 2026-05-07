from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Double, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class NutritionProfile(Base):
    __tablename__ = "nutrition_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    sex: Mapped[str] = mapped_column(String(16), nullable=False)
    height_cm: Mapped[float] = mapped_column(Double, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Double, nullable=False)
    activity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    nutrition_goal: Mapped[str] = mapped_column(String(64), nullable=False)
    allergens: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    dietary_restrictions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    budget_limit_egp: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user = relationship("User", back_populates="nutrition_profile")
