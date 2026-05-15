from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models.inventory_item import InventoryItem
from app.models.user import User
from app.normalizers.ingredient_normalizer import normalize_name
from app.schemas.v1.barcode import BarcodeLookupSuccess
from app.schemas.v1.inventory import (
    InventoryDeleteResponse,
    InventoryItemRecord,
    InventoryItemsResponse,
    InventorySourceMethod,
)
from app.services.barcode_service import lookup_barcode
from app.services.exceptions import BadRequestError, NotFoundError


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_to_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class _PreparedItem:
    raw_name: str
    normalized_name: str


class InventoryService:
    def __init__(self) -> None:
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        init_db()
        self._initialized = True

    def list_items(self, *, user: User) -> InventoryItemsResponse:
        self._ensure_initialized()
        with SessionLocal() as session:
            rows = session.execute(
                select(InventoryItem)
                .where(InventoryItem.user_id == user.id)
                .order_by(InventoryItem.created_at.asc(), InventoryItem.id.asc())
            ).scalars().all()
        return InventoryItemsResponse(items=[self._to_record(row) for row in rows])

    def add_manual_items(self, *, user: User, item_names: list[str]) -> InventoryItemsResponse:
        prepared = self._prepare_names(item_names)
        return self._insert_items(
            user=user,
            prepared=prepared,
            source_method=InventorySourceMethod.MANUAL,
            source_ref=None,
            source_product_id=None,
        )

    def add_image_selected_items(
        self,
        *,
        user: User,
        image_id: str,
        recognized_ingredients: list[str],
        selected_ingredients: list[str],
    ) -> InventoryItemsResponse:
        if not image_id.strip():
            raise BadRequestError("image_id is required.")

        normalized_recognized = {
            normalized
            for ingredient in recognized_ingredients
            for normalized in [normalize_name(ingredient)]
            if normalized
        }
        if not normalized_recognized:
            raise BadRequestError(
                "recognized_ingredients must include at least one valid ingredient."
            )

        prepared_selected = self._prepare_names(selected_ingredients)
        invalid = [
            item.raw_name
            for item in prepared_selected
            if item.normalized_name not in normalized_recognized
        ]
        if invalid:
            raise BadRequestError(
                "selected_ingredients must be a subset of recognized_ingredients. "
                f"Invalid selections: {', '.join(invalid)}"
            )

        return self._insert_items(
            user=user,
            prepared=prepared_selected,
            source_method=InventorySourceMethod.IMAGE,
            source_ref=image_id.strip(),
            source_product_id=None,
        )

    async def add_item_from_barcode(
        self,
        *,
        user: User,
        barcode: str,
        barcode_lookup: Callable[[str], Awaitable[BarcodeLookupSuccess]] | None = None,
    ) -> InventoryItemsResponse:
        lookup_callable = barcode_lookup or lookup_barcode
        result = await lookup_callable(barcode)
        prepared = self._prepare_names([result.name])
        return self._insert_items(
            user=user,
            prepared=prepared,
            source_method=InventorySourceMethod.BARCODE,
            source_ref=barcode,
            source_product_id=result.product_id,
        )

    def delete_item(self, *, user: User, item_id: int) -> InventoryDeleteResponse:
        self._ensure_initialized()
        with SessionLocal.begin() as session:
            row = session.execute(
                select(InventoryItem).where(
                    InventoryItem.id == item_id,
                    InventoryItem.user_id == user.id,
                )
            ).scalar_one_or_none()
            if row is None:
                raise NotFoundError("Inventory item not found.")
            session.delete(row)

        return InventoryDeleteResponse(deleted_item_id=item_id)

    def resolve_item_names_for_user(self, *, user: User, item_ids: list[int]) -> list[str]:
        self._ensure_initialized()
        if not item_ids:
            return []

        ordered_unique_ids = list(dict.fromkeys(item_ids))
        with SessionLocal() as session:
            rows = session.execute(
                select(InventoryItem).where(
                    InventoryItem.user_id == user.id,
                    InventoryItem.id.in_(ordered_unique_ids),
                )
            ).scalars().all()

        by_id = {row.id: row for row in rows}
        missing_ids = [item_id for item_id in ordered_unique_ids if item_id not in by_id]
        if missing_ids:
            raise BadRequestError(
                "Some inventory_item_ids do not exist or are not owned by the current user: "
                + ", ".join(str(item_id) for item_id in missing_ids)
            )

        return [by_id[item_id].name for item_id in ordered_unique_ids]

    def _prepare_names(self, item_names: list[str]) -> list[_PreparedItem]:
        if not item_names:
            raise BadRequestError("At least one inventory item is required.")

        prepared: list[_PreparedItem] = []
        seen_normalized: dict[str, str] = {}
        for raw in item_names:
            cleaned = str(raw).strip()
            if not cleaned:
                raise BadRequestError("Inventory item names must be non-empty strings.")

            normalized = normalize_name(cleaned)
            if not normalized:
                raise BadRequestError(
                    f"Inventory item name '{cleaned}' could not be normalized."
                )

            duplicate_original = seen_normalized.get(normalized)
            if duplicate_original is not None:
                raise BadRequestError(
                    "Duplicate inventory items in request are not allowed: "
                    f"'{duplicate_original}' and '{cleaned}'."
                )
            seen_normalized[normalized] = cleaned
            prepared.append(_PreparedItem(raw_name=cleaned, normalized_name=normalized))

        return prepared

    def _insert_items(
        self,
        *,
        user: User,
        prepared: list[_PreparedItem],
        source_method: InventorySourceMethod,
        source_ref: str | None,
        source_product_id: str | None,
    ) -> InventoryItemsResponse:
        self._ensure_initialized()
        normalized_names = [entry.normalized_name for entry in prepared]
        now = _utc_now_naive()

        with SessionLocal.begin() as session:
            existing = session.execute(
                select(InventoryItem).where(
                    InventoryItem.user_id == user.id,
                    InventoryItem.normalized_name.in_(normalized_names),
                )
            ).scalars().all()

            if existing:
                existing_names = ", ".join(sorted(item.name for item in existing))
                raise BadRequestError(
                    f"Inventory already contains these items: {existing_names}"
                )

            created_rows: list[InventoryItem] = []
            for entry in prepared:
                row = InventoryItem(
                    user_id=user.id,
                    name=entry.raw_name,
                    normalized_name=entry.normalized_name,
                    source_method=source_method.value,
                    source_ref=source_ref,
                    source_product_id=source_product_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                created_rows.append(row)

            session.flush()
            records = [self._to_record(row) for row in created_rows]

        return InventoryItemsResponse(items=records)

    def _to_record(self, row: InventoryItem) -> InventoryItemRecord:
        return InventoryItemRecord(
            id=row.id,
            name=row.name,
            normalized_name=row.normalized_name,
            source_method=InventorySourceMethod(row.source_method),
            source_ref=row.source_ref,
            source_product_id=row.source_product_id,
            created_at=_naive_to_utc(row.created_at),
            updated_at=_naive_to_utc(row.updated_at),
        )


inventory_service = InventoryService()
