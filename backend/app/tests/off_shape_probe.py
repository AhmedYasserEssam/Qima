r"""
Quick script to inspect the raw Open Food Facts payload shape.

Usage (from repo root):
    $env:PYTHONPATH='backend'
    .\.venv\Scripts\python.exe backend\app\tests\off_shape_probe.py 5449000000996
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


def _load_env() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    load_dotenv(backend_root / ".env")


async def _fetch(barcode: str) -> dict:
    base_url = os.getenv("OPENFOODFACTS_BASE_URL", "https://world.openfoodfacts.org").rstrip("/")
    user_agent = os.getenv("OPENFOODFACTS_USER_AGENT", "Qima/1.0 (contact@qima.local)")
    url = f"{base_url}/api/v2/product/{barcode}.json"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers={"User-Agent": user_agent})
        response.raise_for_status()
        return response.json()


def _shape_preview(payload: dict) -> dict:
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    nutriments = product.get("nutriments") if isinstance(product.get("nutriments"), dict) else {}

    return {
        "top_level_keys": sorted(payload.keys()),
        "status": payload.get("status"),
        "status_verbose": payload.get("status_verbose"),
        "product_keys": sorted(product.keys()),
        "nutriments_keys_sample": sorted(nutriments.keys())[:40],
    }


async def _main() -> int:
    _load_env()
    barcode = sys.argv[1] if len(sys.argv) > 1 else "5449000000996"
    payload = await _fetch(barcode)

    print("=== Shape Preview ===")
    print(json.dumps(_shape_preview(payload), indent=2))
    print("\n=== Raw Snippet (first 1500 chars) ===")
    print(json.dumps(payload, ensure_ascii=True)[:1500])
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(_main()))
