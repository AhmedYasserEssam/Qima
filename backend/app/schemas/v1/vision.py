from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VisionIdentifyRequestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str | None = None


class DishCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0, le=1)


class IngredientCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0, le=1)


class VisionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["google_gemini"]
    model: Literal["gemini-2.5-flash"]
    source_type: Literal["vision_model"]


class VisionDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completeness: Literal["complete", "partial"]


class VisionIdentifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: str = Field(..., min_length=1)
    dish_candidates: list[DishCandidate] = Field(default_factory=list)
    ingredients: list[IngredientCandidate] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    source: VisionSource
    data_quality: VisionDataQuality
    warnings: list[str] = Field(default_factory=list)
    latency_ms: int = Field(..., ge=0)