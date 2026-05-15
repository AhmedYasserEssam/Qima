from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models.user import User
from app.schemas.v1.barcode import BarcodeLookupSuccess

client = TestClient(app)


def _email() -> str:
    return f"inventory-test-{uuid4().hex[:10]}@example.com"


def _signup_payload(email: str) -> dict[str, str]:
    return {
        "email": email,
        "password": "StrongPass123!",
        "name": "Inventory User",
    }


def _cleanup_user(email: str) -> None:
    normalized = email.strip().lower()
    init_db()
    with SessionLocal.begin() as session:
        user = session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()
        if user is not None:
            session.execute(delete(User).where(User.id == user.id))


def _auth_headers(email: str) -> dict[str, str]:
    signup = client.post("/v1/auth/signup", json=_signup_payload(email))
    assert signup.status_code == 201
    login = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "StrongPass123!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_inventory_endpoints_require_authentication() -> None:
    response_get = client.get("/v1/inventory/items")
    response_manual = client.post(
        "/v1/inventory/items/manual",
        json={"items": ["rice"]},
    )
    response_image = client.post(
        "/v1/inventory/items/from-image",
        json={
            "image_id": "img_001",
            "recognized_ingredients": ["rice", "onion"],
            "selected_ingredients": ["rice"],
        },
    )
    response_barcode = client.post(
        "/v1/inventory/items/from-barcode",
        json={"barcode": "5449000000996"},
    )
    response_delete = client.delete("/v1/inventory/items/1")

    assert response_get.status_code == 401
    assert response_manual.status_code == 401
    assert response_image.status_code == 401
    assert response_barcode.status_code == 401
    assert response_delete.status_code == 401


def test_inventory_manual_add_and_list_happy_path() -> None:
    email = _email()
    try:
        headers = _auth_headers(email)
        add_response = client.post(
            "/v1/inventory/items/manual",
            json={"items": ["Rice", "Onion"]},
            headers=headers,
        )
        assert add_response.status_code == 200
        added = add_response.json()["items"]
        assert len(added) == 2
        assert {item["normalized_name"] for item in added} == {"rice", "onion"}
        assert {item["source_method"] for item in added} == {"manual"}

        list_response = client.get("/v1/inventory/items", headers=headers)
        assert list_response.status_code == 200
        listed = list_response.json()["items"]
        assert len(listed) == 2
        assert [item["name"] for item in listed] == ["Rice", "Onion"]
    finally:
        _cleanup_user(email)


def test_inventory_duplicate_add_rejected() -> None:
    email = _email()
    try:
        headers = _auth_headers(email)
        first = client.post(
            "/v1/inventory/items/manual",
            json={"items": ["Rice"]},
            headers=headers,
        )
        assert first.status_code == 200

        duplicate_existing = client.post(
            "/v1/inventory/items/manual",
            json={"items": ["RICE"]},
            headers=headers,
        )
        assert duplicate_existing.status_code == 400
        assert "already contains" in duplicate_existing.json()["error"]["message"]

        duplicate_request = client.post(
            "/v1/inventory/items/manual",
            json={"items": ["Milk", "milk"]},
            headers=headers,
        )
        assert duplicate_request.status_code == 400
        assert "Duplicate inventory items" in duplicate_request.json()["error"]["message"]
    finally:
        _cleanup_user(email)


def test_inventory_from_image_subset_validation() -> None:
    email = _email()
    try:
        headers = _auth_headers(email)
        valid = client.post(
            "/v1/inventory/items/from-image",
            json={
                "image_id": "img_valid_001",
                "recognized_ingredients": ["rice", "onion", "tomato"],
                "selected_ingredients": ["rice", "tomato"],
            },
            headers=headers,
        )
        assert valid.status_code == 200
        valid_items = valid.json()["items"]
        assert len(valid_items) == 2
        assert {item["source_method"] for item in valid_items} == {"image"}
        assert {item["source_ref"] for item in valid_items} == {"img_valid_001"}

        invalid = client.post(
            "/v1/inventory/items/from-image",
            json={
                "image_id": "img_invalid_001",
                "recognized_ingredients": ["rice", "onion"],
                "selected_ingredients": ["rice", "garlic"],
            },
            headers=headers,
        )
        assert invalid.status_code == 400
        assert "subset of recognized_ingredients" in invalid.json()["error"]["message"]
    finally:
        _cleanup_user(email)


def test_inventory_from_barcode_uses_lookup_result(monkeypatch) -> None:
    async def fake_lookup_barcode(barcode: str) -> BarcodeLookupSuccess:
        assert barcode == "12345678"
        return BarcodeLookupSuccess.model_validate(
            {
                "product_id": "mock:12345678",
                "name": "Greek Yogurt",
                "brand": "Mock Brand",
                "nutrition": {
                    "basis": "per_100g",
                    "serving_size": "100 g",
                    "values": {
                        "energy_kcal": 60,
                        "protein_g": 10,
                        "carbohydrates_g": 4,
                        "fat_g": 2,
                        "sugars_g": None,
                        "fiber_g": None,
                        "sodium_mg": None,
                        "salt_g": None,
                    },
                },
                "ingredients": [],
                "allergens": [],
                "source": {
                    "provider": "open_food_facts",
                    "provider_product_id": "12345678",
                    "fetched_at": datetime.now(UTC).isoformat(),
                },
                "data_quality": {"completeness": "partial"},
            }
        )

    monkeypatch.setattr("app.services.inventory_service.lookup_barcode", fake_lookup_barcode)

    email = _email()
    try:
        headers = _auth_headers(email)
        response = client.post(
            "/v1/inventory/items/from-barcode",
            json={"barcode": "12345678"},
            headers=headers,
        )
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["name"] == "Greek Yogurt"
        assert item["source_method"] == "barcode"
        assert item["source_ref"] == "12345678"
        assert item["source_product_id"] == "mock:12345678"
    finally:
        _cleanup_user(email)


def test_inventory_delete_item_and_missing_item() -> None:
    email = _email()
    try:
        headers = _auth_headers(email)
        add_response = client.post(
            "/v1/inventory/items/manual",
            json={"items": ["lentils"]},
            headers=headers,
        )
        assert add_response.status_code == 200
        item_id = add_response.json()["items"][0]["id"]

        delete_response = client.delete(f"/v1/inventory/items/{item_id}", headers=headers)
        assert delete_response.status_code == 200
        assert delete_response.json()["deleted_item_id"] == item_id

        list_response = client.get("/v1/inventory/items", headers=headers)
        assert list_response.status_code == 200
        assert list_response.json()["items"] == []

        missing_response = client.delete(f"/v1/inventory/items/{item_id}", headers=headers)
        assert missing_response.status_code == 404
    finally:
        _cleanup_user(email)


def test_recipes_suggest_uses_inventory_item_ids() -> None:
    email = _email()
    try:
        headers = _auth_headers(email)
        add_response = client.post(
            "/v1/inventory/items/manual",
            json={"items": ["Rice", "Lentils"]},
            headers=headers,
        )
        assert add_response.status_code == 200
        item_id = add_response.json()["items"][0]["id"]

        suggest = client.post(
            "/v1/recipes/suggest",
            json={"inventory_item_ids": [item_id]},
            headers=headers,
        )
        assert suggest.status_code == 200
        matched = suggest.json()["recipes"][0]["matched_ingredients"]
        assert matched == ["Rice"]
    finally:
        _cleanup_user(email)


def test_recipes_suggest_requires_auth_when_using_inventory_item_ids() -> None:
    response = client.post(
        "/v1/recipes/suggest",
        json={"inventory_item_ids": [999]},
    )
    assert response.status_code == 401


def test_recipes_suggest_rejects_unowned_inventory_item_ids() -> None:
    owner_email = _email()
    other_email = _email()
    try:
        owner_headers = _auth_headers(owner_email)
        other_headers = _auth_headers(other_email)

        add_response = client.post(
            "/v1/inventory/items/manual",
            json={"items": ["Chicken"]},
            headers=owner_headers,
        )
        assert add_response.status_code == 200
        owner_item_id = add_response.json()["items"][0]["id"]

        suggest = client.post(
            "/v1/recipes/suggest",
            json={"inventory_item_ids": [owner_item_id]},
            headers=other_headers,
        )
        assert suggest.status_code == 400
        assert "do not exist or are not owned" in suggest.json()["error"]["message"]
    finally:
        _cleanup_user(owner_email)
        _cleanup_user(other_email)


def test_recipes_suggest_accepts_budget_level_with_inventory_item_ids() -> None:
    email = _email()
    try:
        headers = _auth_headers(email)
        add_response = client.post(
            "/v1/inventory/items/manual",
            json={"items": ["Rice"]},
            headers=headers,
        )
        assert add_response.status_code == 200
        item_id = add_response.json()["items"][0]["id"]

        suggest = client.post(
            "/v1/recipes/suggest",
            json={
                "inventory_item_ids": [item_id],
                "budget_level": "low",
            },
            headers=headers,
        )
        assert suggest.status_code == 200
        candidate = suggest.json()["recipes"][0]
        assert "budget_friendly" in candidate["exclusions"]
    finally:
        _cleanup_user(email)
