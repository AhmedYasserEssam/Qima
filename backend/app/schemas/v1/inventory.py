from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.v1.barcode import BarcodeString


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventorySourceMethod(StrEnum):
    MANUAL = "manual"
    IMAGE = "image"
    BARCODE = "barcode"


class InventoryItemRecord(StrictBaseModel):
    id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1)
    normalized_name: str = Field(..., min_length=1)
    source_method: InventorySourceMethod
    source_ref: str | None = None
    source_product_id: str | None = None
    created_at: datetime
    updated_at: datetime


class InventoryItemsResponse(StrictBaseModel):
    items: list[InventoryItemRecord] = Field(default_factory=list)


class InventoryManualAddRequest(StrictBaseModel):
    items: list[str] = Field(..., min_length=1)

    @field_validator("items")
    @classmethod
    def validate_items(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("All inventory item names must be non-empty strings.")
        return cleaned


class InventoryImageAddRequest(StrictBaseModel):
    image_id: str = Field(..., min_length=1)
    recognized_ingredients: list[str] = Field(..., min_length=1)
    selected_ingredients: list[str] = Field(..., min_length=1)

    @field_validator("recognized_ingredients", "selected_ingredients")
    @classmethod
    def validate_ingredient_lists(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Ingredient names must be non-empty strings.")
        return cleaned


class InventoryBarcodeAddRequest(StrictBaseModel):
    barcode: BarcodeString


class InventoryDeleteResponse(StrictBaseModel):
    deleted_item_id: int = Field(..., ge=1)
