from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from app.normalizers.product_normalizer import normalize_openfoodfacts_product
from app.schemas.v1.barcode import BarcodeLookupSuccess
from app.services.barcode_cache_service import (
    BarcodeCacheService,
    BarcodeCacheStatus,
)
from app.services.exceptions import NotFoundError, UpstreamUnavailableError
from app.services.openfoodfacts_client import (
    OpenFoodFactsNotFound,
    OpenFoodFactsUnavailable,
    get_product_by_barcode,
)

SUCCESS_TTL = timedelta(days=30)
NOT_FOUND_TTL = timedelta(hours=24)
UPSTREAM_FAILURE_TTL = timedelta(minutes=5)


class BarcodeService:
    def __init__(
        self,
        *,
        cache_service: BarcodeCacheService | None = None,
        product_fetcher: Callable[[str], Awaitable[dict]] = get_product_by_barcode,
        cache_upstream_failures: bool = False,
    ) -> None:
        self._cache = cache_service or BarcodeCacheService()
        self._product_fetcher = product_fetcher
        self._cache_upstream_failures = cache_upstream_failures

    async def lookup_barcode(self, barcode: str) -> BarcodeLookupSuccess:
        now = datetime.now(UTC)

        cached_entry = self._cache.get_fresh(barcode, now=now)
        if cached_entry is not None:
            if cached_entry.status == BarcodeCacheStatus.SUCCESS:
                try:
                    return BarcodeLookupSuccess.model_validate(cached_entry.payload)
                except ValidationError:
                    pass
            elif cached_entry.status == BarcodeCacheStatus.NOT_FOUND:
                raise NotFoundError("No product found for the supplied barcode.")
            elif cached_entry.status == BarcodeCacheStatus.UPSTREAM_FAILURE:
                raise UpstreamUnavailableError(
                    "Barcode provider is currently unavailable."
                )

        try:
            product = await self._product_fetcher(barcode)
        except OpenFoodFactsNotFound as exc:
            self._cache.upsert(
                barcode,
                {"barcode": barcode},
                status=BarcodeCacheStatus.NOT_FOUND,
                ttl=NOT_FOUND_TTL,
                fetched_at=now,
            )
            raise NotFoundError("No product found for the supplied barcode.") from exc
        except OpenFoodFactsUnavailable as exc:
            if self._cache_upstream_failures:
                self._cache.upsert(
                    barcode,
                    {"barcode": barcode, "reason": "upstream_failure"},
                    status=BarcodeCacheStatus.UPSTREAM_FAILURE,
                    ttl=UPSTREAM_FAILURE_TTL,
                    fetched_at=now,
                )
            raise UpstreamUnavailableError(
                "Barcode provider is currently unavailable."
            ) from exc

        normalized = normalize_openfoodfacts_product(
            barcode=barcode,
            product=product,
            fetched_at=now,
        )
        self._cache.upsert(
            barcode,
            normalized.model_dump(mode="json"),
            status=BarcodeCacheStatus.SUCCESS,
            ttl=SUCCESS_TTL,
            fetched_at=now,
        )
        return normalized


barcode_service = BarcodeService(cache_upstream_failures=False)


async def lookup_barcode(barcode: str) -> BarcodeLookupSuccess:
    return await barcode_service.lookup_barcode(barcode)
