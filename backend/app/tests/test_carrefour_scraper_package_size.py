import json

from scrappers.scrape_carrefour_food import (
    CategoryPage,
    ProductDetails,
    normalize_product,
    parse_product_details_html,
    parse_package_size_from_text,
    product_from_section,
)


def _page(category_name: str = "Food Cupboard") -> CategoryPage:
    return CategoryPage(
        category_id="FEGY1700000",
        category_name=category_name,
        current_page=0,
        total_pages=1,
        total_products=1,
        products=[],
        url="https://www.carrefouregypt.com/test",
    )


def test_package_size_is_separate_from_nutrition_serving_size() -> None:
    row = normalize_product(
        {
            "ean": "12345678",
            "id": "12345678",
            "name": "Sample Rice - 1 Kg",
            "brand": {"name": "Qima Test"},
            "price": {"price": 100},
            "productCategoriesHearchi": "Food Cupboard/Rice, Pasta & Pulses/Rice",
        },
        _page(),
        "2026-04-29T00:00:00+00:00",
        ProductDetails(
            nutrition_basis="per_serving",
            serving_size="Average Nutritional Value As Per 30g",
        ),
    )

    assert row["serving_size"] == "Average Nutritional Value As Per 30g"
    assert row["package_size_quantity"] == 1000
    assert row["package_size_unit"] == "g"
    assert row["package_size_raw"] == "1 Kg"


def test_nutrition_serving_size_is_not_used_as_package_size() -> None:
    row = normalize_product(
        {
            "ean": "12345679",
            "id": "12345679",
            "name": "Sample Cereal",
            "brand": {"name": "Qima Test"},
            "price": {"price": 80},
            "productCategoriesHearchi": "Food Cupboard/Breakfast Cereals",
        },
        _page(),
        "2026-04-29T00:00:00+00:00",
        ProductDetails(
            nutrition_basis="per_serving",
            serving_size="Average Nutritional Value As Per 30g",
        ),
    )

    assert row["serving_size"] == "Average Nutritional Value As Per 30g"
    assert row["package_size_quantity"] == ""
    assert row["package_size_unit"] == ""
    assert row["package_size_raw"] == ""


def test_package_size_parser_normalizes_common_units() -> None:
    assert parse_package_size_from_text("Oil - 1 L").quantity == 1000
    assert parse_package_size_from_text("Sauce - 150ml").unit == "ml"
    assert parse_package_size_from_text("Beans - 15 ounce").unit == "g"


def test_current_carrefour_section_card_maps_to_product() -> None:
    product = product_from_section(
        {
            "uid": "master-product-card",
            "componentDTO": {
                "additionalAttributes": {
                    "productId": "509555",
                    "productName": "Almarai Full Fat Milk - 1.5 Liters",
                    "sellingPrice": 67,
                    "markedPrice": 77.99,
                    "productCategory": ["Fresh Food"],
                    "productUrl": "/mafegy/en/full-cream-milk/almarai-full-fat-milk-1-5l/p/509555",
                },
                "analytics": {"brandName": "food_almarai"},
            },
        },
        "Fresh Food",
    )

    assert product is not None
    assert product["id"] == "509555"
    assert product["ean"] == ""
    assert product["brand"]["name"] == "almarai"
    assert product["price"]["discount"]["price"] == 67
    assert product["productCategoriesHearchi"] == "Fresh Food"


def test_detail_page_barcode_is_used_when_listing_has_no_ean() -> None:
    accordion = json.dumps(
        {
            "ingredient": {"ingredientText": ""},
            "information": {"infoMap": {}},
            "nutritionFacts": {"features": []},
        },
        separators=(",", ":"),
    )
    stream = (
        '{"accordion":"$8f","isMarketPlaceProduct":false,'
        f'"barcode":"6223001878018","componentDTO":{{"accordion":{accordion}}}}}'
    )
    html = f"<script>self.__next_f.push({json.dumps([1, stream])})</script>"

    details = parse_product_details_html(html)
    row = normalize_product(
        {
            "id": "509555",
            "ean": "",
            "name": "Almarai Full Fat Milk - 1.5 Liters",
            "brand": {"name": "almarai"},
            "price": {"discount": {"price": 67}},
            "productCategoriesHearchi": "Fresh Food",
        },
        _page("Fresh Food"),
        "2026-04-29T00:00:00+00:00",
        details,
    )

    assert row["barcode"] == "6223001878018"
    assert row["product_id"] == "carrefour:6223001878018"
    assert row["source_provider_product_id"] == "509555"
