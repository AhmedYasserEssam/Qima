from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlencode, urljoin

from scrapling.fetchers import Fetcher, FetcherSession
from sqlalchemy import create_engine, text


BASE_URL = "https://www.carrefouregypt.com"
STORE_PREFIX = "/mafegy/en"

DEFAULT_FOOD_CATEGORIES: "OrderedDict[str, str]" = OrderedDict(
    [
        ("FEGY1600000", "Fresh Food"),
        ("FEGY1660000", "Fruits & Vegetables"),
        ("FEGY1700000", "Food Cupboard"),
        ("FEGY1500000", "Beverages"),
        ("FEGY6000000", "Frozen Food"),
        ("FEGY1200000", "Bio & Organic Food"),
        ("FEGY1610000", "Bakery"),
        ("FEGY1040000", "Baby Milk, Food & Juices"),
    ]
)

CSV_FIELDS = [
    "barcode",
    "product_id",
    "name",
    "brand",
    "nutrition_basis",
    "serving_size",
    "energy_kcal",
    "protein_g",
    "carbohydrates_g",
    "fat_g",
    "sugars_g",
    "fiber_g",
    "sodium_mg",
    "salt_g",
    "ingredients",
    "allergens",
    "source_provider",
    "source_provider_product_id",
    "source_fetched_at",
    "data_quality_completeness",
    "price",
    "category_level_1",
    "category_level_2",
    "category_level_3",
    "category_level_4",
]

DB_TABLE = "carrefour_barcode_products"
DB_NUMERIC_FIELDS = {
    "energy_kcal",
    "protein_g",
    "carbohydrates_g",
    "fat_g",
    "sugars_g",
    "fiber_g",
    "sodium_mg",
    "salt_g",
    "price",
}

SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", flags=re.IGNORECASE | re.DOTALL)
NEXT_PUSH_RE = re.compile(
    r"^\s*self\.__next_f\.push\((.*)\)\s*;?\s*$", flags=re.DOTALL
)
BARCODE_RE = re.compile(r"^[0-9]{8,14}$")
NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

ALLERGEN_TERMS = {
    "celery",
    "crustacean",
    "dairy",
    "egg",
    "fish",
    "gluten",
    "lupin",
    "milk",
    "mollusc",
    "mustard",
    "nut",
    "peanut",
    "sesame",
    "shellfish",
    "soy",
    "soya",
    "sulphite",
    "wheat",
}


@dataclass(frozen=True)
class CategoryPage:
    category_id: str
    category_name: str
    current_page: int
    total_pages: int | None
    total_products: int | None
    products: list[dict[str, Any]]
    url: str


@dataclass(frozen=True)
class ProductDetails:
    nutrition_basis: str = "per_serving"
    serving_size: str = ""
    energy_kcal: float | str = ""
    protein_g: float | str = ""
    carbohydrates_g: float | str = ""
    fat_g: float | str = ""
    sugars_g: float | str = ""
    fiber_g: float | str = ""
    sodium_mg: float | str = ""
    salt_g: float | str = ""
    ingredients: str = "[]"
    allergens: str = "[]"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_database_url(raw_url: str | None) -> str:
    if not raw_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Pass --database-url or set DATABASE_URL env var."
        )

    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return raw_url


def init_carrefour_table(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS carrefour_barcode_products (
                    barcode TEXT PRIMARY KEY,
                    product_id TEXT,
                    name TEXT,
                    brand TEXT,
                    nutrition_basis TEXT,
                    serving_size TEXT,
                    energy_kcal DOUBLE PRECISION,
                    protein_g DOUBLE PRECISION,
                    carbohydrates_g DOUBLE PRECISION,
                    fat_g DOUBLE PRECISION,
                    sugars_g DOUBLE PRECISION,
                    fiber_g DOUBLE PRECISION,
                    sodium_mg DOUBLE PRECISION,
                    salt_g DOUBLE PRECISION,
                    ingredients TEXT,
                    allergens TEXT,
                    source_provider TEXT,
                    source_provider_product_id TEXT,
                    source_fetched_at TEXT,
                    data_quality_completeness TEXT,
                    price DOUBLE PRECISION,
                    category_level_1 TEXT,
                    category_level_2 TEXT,
                    category_level_3 TEXT,
                    category_level_4 TEXT
                );
                """
            )
        )
    engine.dispose()


def _as_db_value(value: Any, *, numeric: bool) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "":
            return None
        if numeric:
            try:
                return float(cleaned)
            except ValueError:
                return None
        return cleaned
    if numeric:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return value


def upsert_rows_db(
    rows: Iterable[dict[str, Any]],
    database_url: str,
    *,
    batch_size: int = 500,
) -> int:
    engine = create_engine(database_url, pool_pre_ping=True)
    sql = text(
        """
        INSERT INTO carrefour_barcode_products (
            barcode,
            product_id,
            name,
            brand,
            nutrition_basis,
            serving_size,
            energy_kcal,
            protein_g,
            carbohydrates_g,
            fat_g,
            sugars_g,
            fiber_g,
            sodium_mg,
            salt_g,
            ingredients,
            allergens,
            source_provider,
            source_provider_product_id,
            source_fetched_at,
            data_quality_completeness,
            price,
            category_level_1,
            category_level_2,
            category_level_3,
            category_level_4
        )
        VALUES (
            :barcode,
            :product_id,
            :name,
            :brand,
            :nutrition_basis,
            :serving_size,
            :energy_kcal,
            :protein_g,
            :carbohydrates_g,
            :fat_g,
            :sugars_g,
            :fiber_g,
            :sodium_mg,
            :salt_g,
            :ingredients,
            :allergens,
            :source_provider,
            :source_provider_product_id,
            :source_fetched_at,
            :data_quality_completeness,
            :price,
            :category_level_1,
            :category_level_2,
            :category_level_3,
            :category_level_4
        )
        ON CONFLICT (barcode)
        DO UPDATE SET
            product_id = EXCLUDED.product_id,
            name = EXCLUDED.name,
            brand = EXCLUDED.brand,
            nutrition_basis = EXCLUDED.nutrition_basis,
            serving_size = EXCLUDED.serving_size,
            energy_kcal = EXCLUDED.energy_kcal,
            protein_g = EXCLUDED.protein_g,
            carbohydrates_g = EXCLUDED.carbohydrates_g,
            fat_g = EXCLUDED.fat_g,
            sugars_g = EXCLUDED.sugars_g,
            fiber_g = EXCLUDED.fiber_g,
            sodium_mg = EXCLUDED.sodium_mg,
            salt_g = EXCLUDED.salt_g,
            ingredients = EXCLUDED.ingredients,
            allergens = EXCLUDED.allergens,
            source_provider = EXCLUDED.source_provider,
            source_provider_product_id = EXCLUDED.source_provider_product_id,
            source_fetched_at = EXCLUDED.source_fetched_at,
            data_quality_completeness = EXCLUDED.data_quality_completeness,
            price = EXCLUDED.price,
            category_level_1 = EXCLUDED.category_level_1,
            category_level_2 = EXCLUDED.category_level_2,
            category_level_3 = EXCLUDED.category_level_3,
            category_level_4 = EXCLUDED.category_level_4
        """
    )

    count = 0
    buffer: list[dict[str, Any]] = []

    def flush(current_batch: list[dict[str, Any]]) -> None:
        nonlocal count
        if not current_batch:
            return
        with engine.begin() as conn:
            conn.execute(sql, current_batch)
        count += len(current_batch)

    for row in rows:
        payload: dict[str, Any] = {}
        for field in CSV_FIELDS:
            payload[field] = _as_db_value(
                row.get(field, None),
                numeric=field in DB_NUMERIC_FIELDS,
            )
        buffer.append(payload)
        if len(buffer) >= batch_size:
            flush(buffer)
            buffer = []

    flush(buffer)
    engine.dispose()
    return count


def category_url(category_id: str, page: int, page_size: int, sort_by: str) -> str:
    params = {
        "currentPage": page,
        "pageSize": page_size,
        "sortBy": sort_by,
    }
    return f"{BASE_URL}{STORE_PREFIX}/c/{category_id}?{urlencode(params)}"


def extract_next_stream(html: str) -> str:
    chunks: list[str] = []
    for script_body in SCRIPT_RE.findall(html):
        match = NEXT_PUSH_RE.match(script_body)
        if not match:
            continue

        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        if (
            isinstance(payload, list)
            and len(payload) >= 2
            and payload[0] == 1
            and isinstance(payload[1], str)
        ):
            chunks.append(payload[1])

    if not chunks:
        raise ValueError("Could not find Next.js streamed page data")
    return "".join(chunks)


def find_balanced_json(text: str, start: int) -> tuple[str, int]:
    opener = text[start]
    closer = {"[": "]", "{": "}"}.get(opener)
    if closer is None:
        raise ValueError(f"Expected JSON array/object at position {start}")

    depth = 0
    in_string = False
    escaped = False

    for pos in range(start, len(text)):
        char = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : pos + 1], pos + 1

    raise ValueError("JSON value did not terminate")


def extract_json_key(stream: str, key: str, start: int = 0) -> tuple[Any, int]:
    token = f'"{key}":'
    key_index = stream.find(token, start)
    if key_index == -1:
        raise KeyError(f"Key not found in page stream: {key}")

    value_start = key_index + len(token)
    while value_start < len(stream) and stream[value_start].isspace():
        value_start += 1

    if stream[value_start] in "[{":
        raw_value, value_end = find_balanced_json(stream, value_start)
        return json.loads(raw_value), value_end

    value_end = value_start
    while value_end < len(stream) and stream[value_end] not in ",}]":
        value_end += 1
    return json.loads(stream[value_start:value_end]), value_end


def extract_int_key(stream: str, key: str, start: int = 0) -> int | None:
    match = re.search(rf'"{re.escape(key)}":(\d+)', stream[start:])
    if not match:
        match = re.search(rf'"{re.escape(key)}":(\d+)', stream)
    return int(match.group(1)) if match else None


def parse_category_page(
    html: str,
    category_id: str,
    category_name: str,
    page_index: int,
    url: str,
) -> CategoryPage:
    stream = extract_next_stream(html)
    products, products_end = extract_json_key(stream, "products")

    if not isinstance(products, list):
        raise ValueError("The products payload was not a list")

    return CategoryPage(
        category_id=category_id,
        category_name=category_name,
        current_page=extract_int_key(stream, "currentPage", products_end) or page_index,
        total_pages=extract_int_key(stream, "totalPages", products_end),
        total_products=extract_int_key(stream, "totalProducts", products_end),
        products=products,
        url=url,
    )


def nested_get(data: dict[str, Any], path: Iterable[str], default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def product_url(product: dict[str, Any]) -> str:
    href = nested_get(product, ["links", "productUrl", "href"], "")
    return urljoin(BASE_URL, str(href)) if href else ""


def category_levels(product: dict[str, Any]) -> list[str]:
    path = product.get("productCategoriesHearchi") or ""
    if isinstance(path, str) and path:
        return [part.strip() for part in path.split("/") if part.strip()]

    categories = product.get("category") or []
    if isinstance(categories, list):
        return [
            str(category.get("name", "")).strip()
            for category in categories
            if isinstance(category, dict) and category.get("name")
        ]
    return []


def split_ingredients(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0

    for char in text:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1

        if char == "," and depth == 0:
            ingredient = clean_text("".join(current))
            if ingredient:
                parts.append(ingredient)
            current = []
        else:
            current.append(char)

    ingredient = clean_text("".join(current))
    if ingredient:
        parts.append(ingredient)
    return parts


def normalize_text(value: str) -> str:
    return clean_text(value).lower()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return unescape(" ".join(str(value).replace("\xa0", " ").split()))


def allergen_names_from_text(text: str) -> list[str]:
    cleaned = clean_text(text)
    cleaned = re.sub(r"(?i)\ballergy advice\b", "", cleaned)
    cleaned = re.sub(r"(?i)\bmay contain\b", "", cleaned)
    cleaned = re.sub(r"(?i)\bcontains?\b", "", cleaned)
    cleaned = cleaned.strip(" :.-")
    if not cleaned:
        return []

    names = []
    for part in re.split(r",|;|/|&|\band\b", cleaned, flags=re.IGNORECASE):
        name = normalize_text(part).strip(" :.-")
        if name and name not in names:
            names.append(name)
    return names


def build_ingredient_json(ingredient_text: str, allergen_names: list[str]) -> str:
    rows = []
    allergen_tokens = {token for name in allergen_names for token in name.split()}
    allergen_tokens.update(ALLERGEN_TERMS)

    for ingredient in split_ingredients(ingredient_text):
        normalized = normalize_text(ingredient)
        rows.append(
            {
                "text": ingredient,
                "normalized_text": normalized,
                "is_allergen": any(term in normalized for term in allergen_tokens),
            }
        )

    return json.dumps(rows, ensure_ascii=False)


def build_allergen_json(allergen_text: str) -> tuple[str, list[str]]:
    allergen_text = clean_text(allergen_text)
    if not allergen_text:
        return "[]", []

    lower = allergen_text.lower()
    if "may contain" in lower:
        severity = "may_contain"
    elif "contain" in lower:
        severity = "contains"
    else:
        severity = "unknown"

    names = allergen_names_from_text(allergen_text)
    rows = [
        {"name": name, "severity": severity, "source_text": allergen_text}
        for name in names
    ]
    return json.dumps(rows, ensure_ascii=False), names


def parse_number(value: Any) -> float | str:
    match = NUMBER_RE.search(str(value or ""))
    if not match:
        return ""
    return float(match.group(0).replace(",", "."))


def value_unit(value: Any) -> str:
    text = str(value or "").lower()
    if "mg" in text:
        return "mg"
    if "kg" in text:
        return "kg"
    if "g" in text:
        return "g"
    if "ml" in text:
        return "ml"
    if "l" in text:
        return "l"
    if "kj" in text:
        return "kj"
    if "kcal" in text:
        return "kcal"
    return ""


def grams_value(value: Any) -> float | str:
    number = parse_number(value)
    if number == "":
        return ""
    unit = value_unit(value)
    if unit == "mg":
        return round(float(number) / 1000, 6)
    if unit == "kg":
        return float(number) * 1000
    return number


def milligrams_value(value: Any) -> float | str:
    number = parse_number(value)
    if number == "":
        return ""
    unit = value_unit(value)
    if unit == "g":
        return float(number) * 1000
    if unit == "kg":
        return float(number) * 1_000_000
    return number


def nutrition_basis(serving_size: str, feature_keys: list[str]) -> str:
    serving_size_lower = serving_size.lower()
    if re.search(r"\b100\s*ml\b", serving_size_lower):
        return "per_100ml"
    if re.search(r"\b100\s*g\b", serving_size_lower):
        return "per_100g"
    if not serving_size and any(key.lower().startswith("per100") for key in feature_keys):
        return "per_100g"
    return "per_serving"


def map_nutrition(features: list[dict[str, Any]]) -> dict[str, Any]:
    mapped: dict[str, Any] = {
        "serving_size": "",
        "energy_kcal": "",
        "protein_g": "",
        "carbohydrates_g": "",
        "fat_g": "",
        "sugars_g": "",
        "fiber_g": "",
        "sodium_mg": "",
        "salt_g": "",
    }
    feature_keys: list[str] = []

    for feature in features:
        if not isinstance(feature, dict):
            continue

        key = str(feature.get("featureKey") or "")
        value = feature.get("featureValue")
        if not key:
            for candidate_key, candidate_value in feature.items():
                if candidate_key not in {"featureKey", "featureValue"}:
                    key = str(candidate_key)
                    value = candidate_value
                    break
        if not key:
            continue

        feature_keys.append(key)
        normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())

        if "portiontype" in normalized_key or "servingsize" in normalized_key:
            mapped["serving_size"] = clean_text(value)
        elif "energyinkcal" in normalized_key or (
            "energy" in normalized_key and "kcal" in str(value).lower()
        ):
            mapped["energy_kcal"] = parse_number(value)
        elif "energyinkj" in normalized_key and mapped["energy_kcal"] == "":
            energy_kj = parse_number(value)
            mapped["energy_kcal"] = round(float(energy_kj) / 4.184, 2) if energy_kj != "" else ""
        elif "protein" in normalized_key:
            mapped["protein_g"] = grams_value(value)
        elif "carbohydrate" in normalized_key or "carbs" in normalized_key:
            mapped["carbohydrates_g"] = grams_value(value)
        elif "sugar" in normalized_key:
            mapped["sugars_g"] = grams_value(value)
        elif "fiber" in normalized_key or "fibre" in normalized_key:
            mapped["fiber_g"] = grams_value(value)
        elif "sodium" in normalized_key:
            mapped["sodium_mg"] = milligrams_value(value)
        elif "salt" in normalized_key:
            mapped["salt_g"] = grams_value(value)
        elif "fat" in normalized_key and "satur" not in normalized_key and "trans" not in normalized_key:
            mapped["fat_g"] = grams_value(value)

    mapped["nutrition_basis"] = nutrition_basis(str(mapped["serving_size"]), feature_keys)
    return mapped


def flatten_nutrition_features(nutrition_facts: dict[str, Any]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    groups = nutrition_facts.get("features") if isinstance(nutrition_facts, dict) else None
    if not isinstance(groups, list):
        return features

    for group in groups:
        group_features = group.get("features") if isinstance(group, dict) else None
        if isinstance(group_features, list):
            features.extend(item for item in group_features if isinstance(item, dict))
    return features


def parse_product_details_html(html: str) -> ProductDetails:
    try:
        stream = extract_next_stream(html)
        accordion, _ = extract_json_key(stream, "accordion")
    except Exception:
        return ProductDetails()

    if not isinstance(accordion, dict):
        return ProductDetails()

    ingredient_text = clean_text(nested_get(accordion, ["ingredient", "ingredientText"], ""))
    info_map = nested_get(accordion, ["information", "infoMap"], {})
    allergen_text = ""
    if isinstance(info_map, dict):
        allergen_text = clean_text(
            info_map.get("Allergy Advice")
            or info_map.get("Allergen Advice")
            or info_map.get("Allergens")
            or ""
        )

    allergens, allergen_names = build_allergen_json(allergen_text)
    nutrition = map_nutrition(
        flatten_nutrition_features(accordion.get("nutritionFacts", {}))
    )

    return ProductDetails(
        nutrition_basis=nutrition.get("nutrition_basis", "per_serving"),
        serving_size=nutrition.get("serving_size", ""),
        energy_kcal=nutrition.get("energy_kcal", ""),
        protein_g=nutrition.get("protein_g", ""),
        carbohydrates_g=nutrition.get("carbohydrates_g", ""),
        fat_g=nutrition.get("fat_g", ""),
        sugars_g=nutrition.get("sugars_g", ""),
        fiber_g=nutrition.get("fiber_g", ""),
        sodium_mg=nutrition.get("sodium_mg", ""),
        salt_g=nutrition.get("salt_g", ""),
        ingredients=build_ingredient_json(ingredient_text, allergen_names),
        allergens=allergens,
    )


def fetch_product_details(
    url: str,
    impersonate: str,
    timeout: float,
    retries: int,
) -> ProductDetails:
    if not url:
        return ProductDetails()

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = Fetcher.get(url, impersonate=impersonate, timeout=timeout)
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            html = response.body.decode("utf-8", errors="ignore")
            return parse_product_details_html(html)
        except Exception as exc:  # noqa: BLE001 - detail pages should not kill the crawl.
            last_error = exc
            if attempt < retries:
                time.sleep(min(2**attempt, 10))

    logging.debug("Failed to fetch detail page %s: %s", url, last_error)
    return ProductDetails()


def fetch_detail_batch(
    products: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, ProductDetails]:
    if not args.fetch_details or not products:
        return {}

    details: dict[str, ProductDetails] = {}
    futures = {}
    with ThreadPoolExecutor(max_workers=args.detail_concurrency) as executor:
        for product in products:
            key = str(product.get("id") or product.get("ean") or "")
            future = executor.submit(
                fetch_product_details,
                product_url(product),
                args.impersonate,
                args.detail_timeout,
                args.detail_retries,
            )
            futures[future] = key

        for future in as_completed(futures):
            details[futures[future]] = future.result()

    return details


def normalize_product(
    product: dict[str, Any],
    page: CategoryPage,
    scraped_at: str,
    details: ProductDetails | None = None,
) -> dict[str, Any]:
    price = product.get("price") or {}
    discount = price.get("discount") or {}
    brand = product.get("brand") or {}
    levels = category_levels(product)
    barcode = str(product.get("ean") or "").strip()
    details = details or ProductDetails()

    original_price = price.get("price")
    discount_price = discount.get("price")
    current_price = discount_price if discount_price is not None else original_price

    row = {
        "barcode": barcode,
        "product_id": f"carrefour:{barcode}",
        "name": product.get("name", ""),
        "brand": brand.get("name", "") if isinstance(brand, dict) else "",
        "nutrition_basis": details.nutrition_basis,
        "serving_size": details.serving_size,
        "energy_kcal": details.energy_kcal,
        "protein_g": details.protein_g,
        "carbohydrates_g": details.carbohydrates_g,
        "fat_g": details.fat_g,
        "sugars_g": details.sugars_g,
        "fiber_g": details.fiber_g,
        "sodium_mg": details.sodium_mg,
        "salt_g": details.salt_g,
        "ingredients": details.ingredients,
        "allergens": details.allergens,
        "source_provider": "carrefour_egypt",
        "source_provider_product_id": barcode,
        "source_fetched_at": scraped_at,
        "data_quality_completeness": data_completeness(details),
        "price": current_price,
        "category_level_1": levels[0] if len(levels) > 0 else "",
        "category_level_2": levels[1] if len(levels) > 1 else "",
        "category_level_3": levels[2] if len(levels) > 2 else "",
        "category_level_4": levels[3] if len(levels) > 3 else "",
    }

    return {key: clean_cell(row.get(key, "")) for key in CSV_FIELDS}


def data_completeness(details: ProductDetails) -> str:
    required_nutrition = [
        details.energy_kcal,
        details.protein_g,
        details.carbohydrates_g,
        details.fat_g,
    ]
    if details.ingredients != "[]" and all(value != "" for value in required_nutrition):
        return "complete"
    return "partial"


def clean_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return unescape(" ".join(value.split()))
    return value


def fetch_category_page(
    session: FetcherSession,
    category_id: str,
    category_name: str,
    page_index: int,
    page_size: int,
    sort_by: str,
    retries: int,
) -> CategoryPage:
    url = category_url(category_id, page_index, page_size, sort_by)
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = session.get(url)
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            html = response.body.decode("utf-8", errors="ignore")
            return parse_category_page(html, category_id, category_name, page_index, url)
        except Exception as exc:  # noqa: BLE001 - keep retry logic central here.
            last_error = exc
            if attempt == retries:
                break
            sleep_for = min(2**attempt, 30)
            logging.warning(
                "Retrying %s page %s after %s (%s/%s)",
                category_id,
                page_index,
                exc,
                attempt,
                retries,
            )
            time.sleep(sleep_for)

    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def scrape_products(args: argparse.Namespace) -> Iterator[dict[str, Any]]:
    categories = selected_categories(args.category)
    seen_ids: set[str] = set()
    emitted = 0
    scraped_at = utc_now_iso()

    with FetcherSession(
        impersonate=args.impersonate,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=1,
        follow_redirects=True,
    ) as session:
        for category_id, category_name in categories.items():
            logging.info("Scraping %s (%s)", category_name, category_id)
            page_index = 0
            category_pages_scraped = 0

            while True:
                page = fetch_category_page(
                    session=session,
                    category_id=category_id,
                    category_name=category_name,
                    page_index=page_index,
                    page_size=args.page_size,
                    sort_by=args.sort_by,
                    retries=args.retries,
                )
                category_pages_scraped += 1

                logging.info(
                    "Fetched %s page %s: %s products, total_pages=%s, total_products=%s",
                    category_id,
                    page.current_page,
                    len(page.products),
                    page.total_pages,
                    page.total_products,
                )

                if not page.products:
                    break

                valid_products = []
                for product in page.products:
                    barcode = str(product.get("ean") or "").strip()
                    if not args.include_invalid_barcodes and not BARCODE_RE.fullmatch(barcode):
                        logging.debug(
                            "Skipping product %s with invalid barcode %r",
                            product.get("id", ""),
                            barcode,
                        )
                        continue

                    dedupe_key = barcode or str(product.get("id") or "")
                    if args.dedupe and dedupe_key:
                        if dedupe_key in seen_ids:
                            continue
                        seen_ids.add(dedupe_key)

                    valid_products.append(product)
                    if args.max_products and emitted + len(valid_products) >= args.max_products:
                        break

                details_by_product_id = fetch_detail_batch(valid_products, args)
                if args.fetch_details and valid_products:
                    found = sum(
                        1
                        for product in valid_products
                        if details_by_product_id.get(str(product.get("id") or product.get("ean") or ""))
                        not in (None, ProductDetails())
                    )
                    logging.info("Fetched detail data for %s/%s products", found, len(valid_products))

                for product in valid_products:
                    detail_key = str(product.get("id") or product.get("ean") or "")
                    yield normalize_product(
                        product,
                        page,
                        scraped_at,
                        details_by_product_id.get(detail_key),
                    )
                    emitted += 1
                    if args.max_products and emitted >= args.max_products:
                        return

                if args.max_pages and category_pages_scraped >= args.max_pages:
                    break
                if page.total_pages is not None and page.current_page + 1 >= page.total_pages:
                    break

                page_index += 1
                time.sleep(args.delay + random.uniform(0, args.jitter))


def selected_categories(category_args: list[str] | None) -> "OrderedDict[str, str]":
    if not category_args:
        return DEFAULT_FOOD_CATEGORIES.copy()

    categories: "OrderedDict[str, str]" = OrderedDict()
    for raw in category_args:
        if "=" in raw:
            category_id, category_name = raw.split("=", 1)
            categories[category_id.strip()] = category_name.strip()
        else:
            category_id = raw.strip()
            categories[category_id] = DEFAULT_FOOD_CATEGORIES.get(category_id, category_id)
    return categories


def infer_format(output: Path, explicit_format: str | None) -> str:
    if explicit_format:
        return explicit_format
    suffix = output.suffix.lower()
    if suffix == ".jsonl":
        return "jsonl"
    return "csv"


def write_rows(rows: Iterable[dict[str, Any]], output: Path, output_format: str) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    if output_format == "jsonl":
        with output.open("w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
        return count

    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape Carrefour Egypt food product listings into DB, CSV, or JSONL."
    )
    parser.add_argument(
        "--sink",
        choices=["db", "csv", "jsonl"],
        default="db",
        help="Output sink. Default: db.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/carrefour_barcode_products.csv"),
        help="File output path for csv/jsonl sinks.",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "jsonl"],
        default=None,
        help="File format. Inferred from --output when omitted.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Database URL for db sink. Defaults to DATABASE_URL env var.",
    )
    parser.add_argument(
        "--db-batch-size",
        type=int,
        default=500,
        help="Rows per DB upsert batch.",
    )
    parser.add_argument(
        "--category",
        action="append",
        help="Category id to scrape. Repeatable. Use ID=Name to label custom categories.",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="Print the default food category ids and exit.",
    )
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages per category.")
    parser.add_argument("--max-products", type=int, default=None, help="Max products overall.")
    parser.add_argument("--page-size", type=int, default=100, help="Products requested per page.")
    parser.add_argument("--sort-by", default="relevance", help="Carrefour sort value.")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay between page requests.")
    parser.add_argument("--jitter", type=float, default=0.5, help="Random extra delay.")
    parser.add_argument("--timeout", type=float, default=45, help="Request timeout in seconds.")
    parser.add_argument("--retries", type=int, default=3, help="Retries per page.")
    parser.add_argument(
        "--no-details",
        dest="fetch_details",
        action="store_false",
        help="Skip product detail pages and leave nutrition, ingredients, and allergens empty.",
    )
    parser.add_argument(
        "--detail-concurrency",
        type=int,
        default=6,
        help="Concurrent product detail requests. Default: 6.",
    )
    parser.add_argument(
        "--detail-timeout",
        type=float,
        default=45,
        help="Product detail request timeout in seconds.",
    )
    parser.add_argument(
        "--detail-retries",
        type=int,
        default=2,
        help="Retries per product detail page.",
    )
    parser.add_argument(
        "--impersonate",
        default="chrome124",
        help="Scrapling/curl_cffi browser impersonation profile.",
    )
    parser.add_argument(
        "--no-dedupe",
        dest="dedupe",
        action="store_false",
        help="Keep duplicate product ids across categories.",
    )
    parser.add_argument(
        "--include-invalid-barcodes",
        action="store_true",
        help="Keep products whose EAN does not match the schema barcode pattern.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console log level.",
    )
    parser.set_defaults(dedupe=True, fetch_details=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("scrapling").setLevel(logging.WARNING)

    if args.list_categories:
        for category_id, category_name in DEFAULT_FOOD_CATEGORIES.items():
            print(f"{category_id}\t{category_name}")
        return 0

    rows = scrape_products(args)
    try:
        if args.sink == "db":
            database_url = resolve_database_url(args.database_url)
            init_carrefour_table(database_url)
            count = upsert_rows_db(rows, database_url, batch_size=args.db_batch_size)
            logging.info("Upserted %s products into %s", count, DB_TABLE)
        else:
            output_format = args.sink if args.sink in {"csv", "jsonl"} else infer_format(args.output, args.format)
            count = write_rows(rows, args.output, output_format)
            logging.info("Saved %s products to %s", count, args.output)
    except KeyboardInterrupt:
        logging.error("Interrupted")
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
