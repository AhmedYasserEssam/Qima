import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")

OPENFOODFACTS_BASE_URL = os.getenv(
    "OPENFOODFACTS_BASE_URL", "https://world.openfoodfacts.org"
).rstrip("/")
OPENFOODFACTS_USER_AGENT = os.getenv(
    "OPENFOODFACTS_USER_AGENT", "Qima/1.0 (contact@qima.local)"
)


class OpenFoodFactsError(Exception):
    """Base Open Food Facts provider error."""


class OpenFoodFactsNotFound(OpenFoodFactsError):
    """Raised when OFF has no product for barcode."""


class OpenFoodFactsUnavailable(OpenFoodFactsError):
    """Raised for network, timeout, rate-limit, or 5xx errors."""


async def get_product_by_barcode(barcode: str) -> dict:
    url = f"{OPENFOODFACTS_BASE_URL}/api/v2/product/{barcode}.json"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"User-Agent": OPENFOODFACTS_USER_AGENT},
            )
    except httpx.TimeoutException as exc:
        raise OpenFoodFactsUnavailable("Open Food Facts request timed out.") from exc
    except httpx.HTTPError as exc:
        raise OpenFoodFactsUnavailable("Open Food Facts is unavailable.") from exc

    if response.status_code == 404:
        raise OpenFoodFactsNotFound("Product not found.")

    if response.status_code in {429, 500, 502, 503, 504}:
        raise OpenFoodFactsUnavailable("Open Food Facts is temporarily unavailable.")

    if response.status_code >= 400:
        raise OpenFoodFactsUnavailable("Open Food Facts returned an unexpected error.")

    try:
        data = response.json()
    except ValueError as exc:
        raise OpenFoodFactsUnavailable("Open Food Facts returned invalid JSON.") from exc

    if data.get("status") != 1 or not data.get("product"):
        raise OpenFoodFactsNotFound("Product not found.")

    return data["product"]
