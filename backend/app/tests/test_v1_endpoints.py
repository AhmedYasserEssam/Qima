from fastapi.testclient import TestClient

from app.main import app
from app.services.exceptions import NotFoundError, UpstreamUnavailableError


client = TestClient(app)


def test_health() -> None:
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_v1_post_endpoints_return_mock_responses() -> None:
    requests = [
        (
            "post",
            "/v1/nutrition/estimate",
            {"input_type": "recognized_dish", "recognized_dish": "Eggplant, raw"},
        ),
        ("post", "/v1/recipes/suggest", {"pantry_items": ["rice", "lentils"]}),
        (
            "post",
            "/v1/recipes/discuss",
            {"recipe_id": "recipe_stub_001", "question": "How do I prepare it?"},
        ),
        (
            "post",
            "/v1/chat/query",
            {"context_id": "ctx_stub_001", "question": "Is this meal balanced?"},
        ),
        (
            "post",
            "/v1/prices/estimate",
            {
                "estimate_type": "ingredient_list",
                "ingredients": [{"name": "rice", "quantity": 500, "unit": "g"}],
            },
        ),
        (
            "post",
            "/v1/labs/interpret",
            {
                "marker_name": "ferritin",
                "value": 60,
                "unit": "ng/ml",
                "reference_range": {"low": 30, "high": 300, "unit": "ng/ml"},
            },
        ),
        (
            "post",
            "/v1/plans/generate",
            {
                "profile": {
                    "age_years": 30,
                    "sex": "prefer_not_to_say",
                    "height_cm": 170,
                    "weight_kg": 70,
                    "activity_level": "moderately_active",
                    "goal": "improve_general_health",
                }
            },
        ),
    ]

    for method, path, json in requests:
        response = getattr(client, method)(path, json=json)

        assert response.status_code == 200, (path, response.text)
        assert response.json()


def test_vision_identify_returns_structured_response(monkeypatch) -> None:
    async def fake_identify_uploaded_food_image(
        *,
        image_bytes: bytes,
        filename: str | None,
        content_type: str | None,
        locale: str | None,
    ) -> dict:
        assert image_bytes == b"mock-image"
        assert filename == "food.jpg"
        assert content_type == "image/jpeg"
        assert locale == "en"
        return {
            "image_id": "img_test_001",
            "dish_candidates": [{"name": "koshari", "confidence": 0.88}],
            "ingredients": [{"name": "rice", "confidence": 0.92}],
            "confidence": 0.86,
            "source": {
                "provider": "gemini",
                "model": "gemini_2_5_flash",
                "source_type": "vision_model",
            },
            "data_quality": {"completeness": "complete"},
            "warnings": [],
            "latency_ms": 12,
        }

    monkeypatch.setattr(
        "app.api.v1.endpoints.vision.identify_uploaded_food_image",
        fake_identify_uploaded_food_image,
    )

    response = client.post(
        "/v1/vision/identify",
        files={"image": ("food.jpg", b"mock-image", "image/jpeg")},
        data={"locale": "en"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["image_id"] == "img_test_001"
    assert body["dish_candidates"][0]["name"] == "koshari"
    assert body["source"]["provider"] == "gemini"


def test_nutrition_estimate_returns_real_xlsx_response() -> None:
    response = client.post(
        "/v1/nutrition/estimate",
        json={"input_type": "recognized_dish", "recognized_dish": "Eggplant, raw"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched_dish"]["name"] == "Eggplant, raw"
    assert body["source"] == {
        "dataset": "nutrition_xlsx",
        "source_type": "nutrition_dataset",
    }
    assert body["nutrients"]["calories_kcal"] == 25


def test_nutrition_estimate_returns_404_for_no_match(monkeypatch) -> None:
    def fake_estimate_nutrition_with_data(payload) -> None:
        del payload
        raise NotFoundError("not found")

    monkeypatch.setattr(
        "app.api.v1.endpoints.nutrition.estimate_nutrition_with_data",
        fake_estimate_nutrition_with_data,
    )

    response = client.post(
        "/v1/nutrition/estimate",
        json={"input_type": "recognized_dish", "recognized_dish": "missing food"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_nutrition_estimate_returns_503_for_unavailable_source(monkeypatch) -> None:
    def fake_estimate_nutrition_with_data(payload) -> None:
        del payload
        raise UpstreamUnavailableError("unavailable")

    monkeypatch.setattr(
        "app.api.v1.endpoints.nutrition.estimate_nutrition_with_data",
        fake_estimate_nutrition_with_data,
    )

    response = client.post(
        "/v1/nutrition/estimate",
        json={"input_type": "recognized_dish", "recognized_dish": "eggplant"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_v1_get_endpoints_return_mock_responses() -> None:
    for path, expected_id_field in [
        ("/v1/recipes/recipe_stub_001", "recipe_id"),
        ("/v1/plans/plan_stub_001", "plan_id"),
    ]:
        response = client.get(path)

        assert response.status_code == 200, (path, response.text)
        assert expected_id_field in response.json()


def test_profile_endpoints_require_authentication() -> None:
    response_update = client.post(
        "/v1/profile/update",
        json={
            "age": 30,
            "sex": "male",
            "height_cm": 175,
            "weight_kg": 80,
            "activity_level": "moderately_active",
            "goal": "improve_general_health",
            "allergens": [],
            "dietary_restrictions": [],
            "safety_screening": {
                "pregnant": False,
                "breastfeeding": False,
                "eating_disorder_history": False,
                "under_18": False,
                "medical_condition_affects_diet": False,
                "abnormal_labs_or_health_concerns": False,
                "none_of_above": True,
            },
            "agreement_accepted": True,
        },
    )
    response_get = client.get("/v1/profile/me")

    assert response_update.status_code == 401
    assert response_get.status_code == 401
