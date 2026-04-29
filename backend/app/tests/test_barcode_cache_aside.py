import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.v1.barcode import BarcodeLookupSuccess
from app.services.barcode_cache_service import BarcodeCacheEntry, BarcodeCacheStatus
from app.services.barcode_service import BarcodeService
from app.services.exceptions import NotFoundError, UpstreamUnavailableError
from app.services.openfoodfacts_client import OpenFoodFactsNotFound, OpenFoodFactsUnavailable


@dataclass
class FetchCounter:
    count: int = 0


class FakeBarcodeCacheService:
    def __init__(self) -> None:
        self.entries: dict[str, BarcodeCacheEntry] = {}

    def get_fresh(
        self,
        barcode: str,
        *,
        now: datetime | None = None,
    ) -> BarcodeCacheEntry | None:
        now = now or datetime.now(UTC)
        entry = self.entries.get(barcode)
        if entry is None:
            return None
        if entry.expires_at <= now:
            return None
        return entry

    def upsert(
        self,
        barcode: str,
        payload: dict,
        *,
        status: BarcodeCacheStatus,
        ttl: timedelta,
        fetched_at: datetime | None = None,
    ) -> None:
        fetched_at = fetched_at or datetime.now(UTC)
        self.entries[barcode] = BarcodeCacheEntry(
            barcode=barcode,
            payload=payload,
            status=status,
            fetched_at=fetched_at,
            expires_at=fetched_at + ttl,
        )


def _sample_off_product(barcode: str) -> dict:
    return {
        "code": barcode,
        "product_name": "Sample Cola",
        "brands": "Qima Drinks",
        "nutrition_data_per": "100ml",
        "serving_size": "330 ml",
        "nutriments": {
            "energy-kcal_100ml": 42,
            "proteins_100ml": 0.0,
            "carbohydrates_100ml": 10.6,
            "fat_100ml": 0.0,
            "sugars_100ml": 10.6,
            "fiber_100ml": 0.0,
            "sodium_100ml": 0.004,
            "sodium_unit_100ml": "g",
            "salt_100ml": 0.01,
        },
        "ingredients": [{"text": "Carbonated water"}, {"text": "Sugar"}],
        "allergens_tags": [],
        "traces_tags": [],
    }


def _sample_carrefour_success(barcode: str) -> BarcodeLookupSuccess:
    return BarcodeLookupSuccess.model_validate(
        {
            "product_id": f"carrefour:{barcode}",
            "name": "Carrefour Sample Product",
            "brand": "Carrefour",
            "nutrition": {
                "basis": "per_100g",
                "serving_size": None,
                "basis_label": "Per 100 g",
                "serving_label": None,
                "values": {
                    "energy_kcal": 250.0,
                    "protein_g": 5.0,
                    "carbohydrates_g": 30.0,
                    "fat_g": 10.0,
                    "sugars_g": 3.0,
                    "fiber_g": 2.0,
                    "sodium_mg": 120.0,
                    "salt_g": 0.3,
                },
                "facts": [],
            },
            "ingredients": [],
            "allergens": [],
            "source": {
                "provider": "carrefour_egypt",
                "provider_product_id": barcode,
                "fetched_at": "2026-04-19T20:00:00Z",
            },
            "data_quality": {"completeness": "partial"},
        }
    )


def test_carrefour_lookup_has_priority_over_cache_and_openfood() -> None:
    barcode = "5449000000996"
    fake_cache = FakeBarcodeCacheService()
    counter = FetchCounter()

    async def fetcher(_: str) -> dict:
        counter.count += 1
        return _sample_off_product(barcode)

    service = BarcodeService(
        cache_service=fake_cache,
        product_fetcher=fetcher,
        carrefour_lookup=lambda _: _sample_carrefour_success(barcode),
    )
    result = asyncio.run(service.lookup_barcode(barcode))

    assert result.product_id == f"carrefour:{barcode}"
    assert result.source.provider.value == "carrefour_egypt"
    assert counter.count == 0
    assert barcode not in fake_cache.entries


def test_cache_is_checked_after_carrefour_miss() -> None:
    barcode = "5449000000996"
    fake_cache = FakeBarcodeCacheService()
    counter = FetchCounter()

    async def fetcher(_: str) -> dict:
        counter.count += 1
        return _sample_off_product(barcode)

    service = BarcodeService(
        cache_service=fake_cache,
        product_fetcher=fetcher,
        carrefour_lookup=lambda _: None,
    )

    first = asyncio.run(service.lookup_barcode(barcode))
    second = asyncio.run(service.lookup_barcode(barcode))

    assert first.source.provider.value == "open_food_facts"
    assert second.model_dump() == first.model_dump()
    assert counter.count == 1


def test_first_cache_miss_fetches_and_caches_success() -> None:
    barcode = "5449000000996"
    fake_cache = FakeBarcodeCacheService()
    counter = FetchCounter()

    async def fetcher(_: str) -> dict:
        counter.count += 1
        return _sample_off_product(barcode)

    service = BarcodeService(
        cache_service=fake_cache,
        product_fetcher=fetcher,
        carrefour_lookup=lambda _: None,
    )
    result = asyncio.run(service.lookup_barcode(barcode))

    assert isinstance(result, BarcodeLookupSuccess)
    assert counter.count == 1
    assert fake_cache.entries[barcode].status == BarcodeCacheStatus.SUCCESS
    assert result.nutrition.basis_label == "Per 100 ml"
    assert result.nutrition.serving_label == "Serving size: 330 ml"
    assert result.nutrition.facts[0].display_value == "42 kcal"
    assert any(fact.key == "carbohydrates_g" for fact in result.nutrition.facts)


def test_second_lookup_hits_cache_without_refetch() -> None:
    barcode = "5449000000996"
    fake_cache = FakeBarcodeCacheService()
    counter = FetchCounter()

    async def fetcher(_: str) -> dict:
        counter.count += 1
        return _sample_off_product(barcode)

    service = BarcodeService(
        cache_service=fake_cache,
        product_fetcher=fetcher,
        carrefour_lookup=lambda _: None,
    )
    first = asyncio.run(service.lookup_barcode(barcode))
    second = asyncio.run(service.lookup_barcode(barcode))

    assert counter.count == 1
    assert first.model_dump() == second.model_dump()


def test_expired_cache_refetches() -> None:
    barcode = "5449000000996"
    fake_cache = FakeBarcodeCacheService()
    counter = FetchCounter()

    async def fetcher(_: str) -> dict:
        counter.count += 1
        return _sample_off_product(barcode)

    service = BarcodeService(
        cache_service=fake_cache,
        product_fetcher=fetcher,
        carrefour_lookup=lambda _: None,
    )
    asyncio.run(service.lookup_barcode(barcode))
    fake_cache.entries[barcode].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    asyncio.run(service.lookup_barcode(barcode))
    assert counter.count == 2


def test_unknown_barcode_caches_not_found_for_24_hours() -> None:
    barcode = "0000000000000"
    fake_cache = FakeBarcodeCacheService()
    counter = FetchCounter()

    async def fetcher(_: str) -> dict:
        counter.count += 1
        raise OpenFoodFactsNotFound("missing")

    service = BarcodeService(
        cache_service=fake_cache,
        product_fetcher=fetcher,
        carrefour_lookup=lambda _: None,
    )

    with pytest.raises(NotFoundError):
        asyncio.run(service.lookup_barcode(barcode))

    assert counter.count == 1
    cached = fake_cache.entries[barcode]
    assert cached.status == BarcodeCacheStatus.NOT_FOUND
    assert int((cached.expires_at - cached.fetched_at).total_seconds()) == 24 * 60 * 60


def test_unknown_barcode_returns_not_found_from_cache() -> None:
    barcode = "0000000000000"
    fake_cache = FakeBarcodeCacheService()
    counter = FetchCounter()

    async def fetcher(_: str) -> dict:
        counter.count += 1
        raise OpenFoodFactsNotFound("missing")

    service = BarcodeService(
        cache_service=fake_cache,
        product_fetcher=fetcher,
        carrefour_lookup=lambda _: None,
    )

    with pytest.raises(NotFoundError):
        asyncio.run(service.lookup_barcode(barcode))
    with pytest.raises(NotFoundError):
        asyncio.run(service.lookup_barcode(barcode))

    assert counter.count == 1


def test_upstream_timeout_returns_503_and_is_not_long_cached() -> None:
    barcode = "5449000000996"
    fake_cache = FakeBarcodeCacheService()

    async def fetcher(_: str) -> dict:
        raise OpenFoodFactsUnavailable("timeout")

    service = BarcodeService(
        cache_service=fake_cache,
        product_fetcher=fetcher,
        carrefour_lookup=lambda _: None,
        cache_upstream_failures=False,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(service.lookup_barcode(barcode))

    assert barcode not in fake_cache.entries


def test_invalid_barcode_returns_422() -> None:
    client = TestClient(app)
    response = client.post("/v1/barcode/lookup", json={"barcode": "abc123"})

    assert response.status_code == 422


def test_barcode_response_shape_matches_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)

    async def fake_lookup(_: str) -> BarcodeLookupSuccess:
        return BarcodeLookupSuccess.model_validate(
            {
                "product_id": "off:5449000000996",
                "name": "Sample Cola",
                "brand": "Qima Drinks",
                "nutrition": {
                    "basis": "per_100ml",
                    "serving_size": "330 ml",
                    "basis_label": "Per 100 ml",
                    "serving_label": "Serving size: 330 ml",
                    "values": {
                        "energy_kcal": 42.0,
                        "protein_g": 0.0,
                        "carbohydrates_g": 10.6,
                        "fat_g": 0.0,
                        "sugars_g": 10.6,
                        "fiber_g": 0.0,
                        "sodium_mg": 4.0,
                        "salt_g": 0.01,
                    },
                    "facts": [
                        {
                            "key": "energy_kcal",
                            "label": "Energy",
                            "value": 42.0,
                            "unit": "kcal",
                            "display_value": "42 kcal",
                        }
                    ],
                },
                "ingredients": [
                    {
                        "text": "Carbonated water",
                        "normalized_text": "carbonated water",
                        "is_allergen": False,
                    }
                ],
                "allergens": [],
                "source": {
                    "provider": "open_food_facts",
                    "provider_product_id": "5449000000996",
                    "fetched_at": "2026-04-19T20:00:00Z",
                },
                "data_quality": {"completeness": "partial"},
            }
        )

    monkeypatch.setattr("app.api.v1.endpoints.barcode.lookup_barcode", fake_lookup)

    response = client.post("/v1/barcode/lookup", json={"barcode": "5449000000996"})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "product_id",
        "name",
        "brand",
        "nutrition",
        "ingredients",
        "allergens",
        "source",
        "data_quality",
    }
    assert body["nutrition"]["basis_label"] == "Per 100 ml"
    assert body["nutrition"]["serving_label"] == "Serving size: 330 ml"
    assert body["nutrition"]["facts"][0]["display_value"] == "42 kcal"
