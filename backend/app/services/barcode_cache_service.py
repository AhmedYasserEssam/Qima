import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import text

from app.db import SessionLocal, init_db


class BarcodeCacheStatus(StrEnum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    UPSTREAM_FAILURE = "upstream_failure"


@dataclass
class BarcodeCacheEntry:
    barcode: str
    payload: dict
    status: BarcodeCacheStatus
    fetched_at: datetime
    expires_at: datetime


class BarcodeCacheService:
    def __init__(self) -> None:
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        init_db()
        self._initialized = True

    def get_fresh(self, barcode: str, *, now: datetime | None = None) -> BarcodeCacheEntry | None:
        self._ensure_initialized()
        now = now or datetime.now(UTC)

        with SessionLocal() as session:
            row = session.execute(
                text(
                    """
                    SELECT barcode, payload, status, fetched_at, expires_at
                    FROM barcode_cache
                    WHERE barcode = :barcode
                    """
                ),
                {"barcode": barcode},
            ).mappings().first()

        if row is None:
            return None

        expires_at = _db_timestamp_to_utc(row["expires_at"])
        if expires_at <= now:
            return None

        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)

        return BarcodeCacheEntry(
            barcode=row["barcode"],
            payload=payload,
            status=BarcodeCacheStatus(row["status"]),
            fetched_at=_db_timestamp_to_utc(row["fetched_at"]),
            expires_at=expires_at,
        )

    def upsert(
        self,
        barcode: str,
        payload: dict,
        *,
        status: BarcodeCacheStatus,
        ttl: timedelta,
        fetched_at: datetime | None = None,
    ) -> None:
        self._ensure_initialized()
        fetched_at = fetched_at or datetime.now(UTC)
        expires_at = fetched_at + ttl

        with SessionLocal.begin() as session:
            session.execute(
                text(
                    """
                    INSERT INTO barcode_cache (barcode, payload, status, fetched_at, expires_at)
                    VALUES (
                        :barcode,
                        CAST(:payload AS JSONB),
                        :status,
                        :fetched_at,
                        :expires_at
                    )
                    ON CONFLICT (barcode)
                    DO UPDATE SET
                        payload = EXCLUDED.payload,
                        status = EXCLUDED.status,
                        fetched_at = EXCLUDED.fetched_at,
                        expires_at = EXCLUDED.expires_at
                    """
                ),
                {
                    "barcode": barcode,
                    "payload": json.dumps(payload),
                    "status": status.value,
                    "fetched_at": _utc_to_db_timestamp(fetched_at),
                    "expires_at": _utc_to_db_timestamp(expires_at),
                },
            )


def _utc_to_db_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _db_timestamp_to_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)
