from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_v1_post_endpoints_return_mock_responses() -> None:
    requests = [
        ("post", "/v1/barcode/lookup", {"barcode": "5449000000996"}),
        (
            "post",
            "/v1/nutrition/estimate",
            {"input_type": "recognized_dish", "recognized_dish": "koshari"},
        ),
        (
            "post",
            "/v1/recipes/suggest",
            {
                "pantry_items": ["rice", "lentils"],
                "user_preferences": ["budget_friendly"],
                "price_preferences": {
                    "price_aware": True,
                    "ranking_mode": "budget_friendly",
                    "include_item_costs": True,
                    "use_pantry_as_owned": True,
                },
            },
        ),
        (
            "post",
            "/v1/recipes/discuss",
            {
                "recipe_id": "recipe_stub_001",
                "question": "How do I make it cheaper?",
                "conversation_intent": "reduce_cost",
            },
        ),
        (
            "post",
            "/v1/chat/query",
            {
                "context_id": "ctx_stub_001",
                "question": "Can you make this cheaper?",
                "active_context_type": "recipe_suggestions",
                "food_context": {
                    "selected_recipe_id": "recipe_stub_001",
                    "recipes": [
                        {
                            "recipe_id": "recipe_stub_001",
                            "title": "Simple Lentil Rice Bowl",
                            "matched_ingredients": ["rice", "lentils"],
                            "missing_ingredients": ["onion", "tomato sauce"],
                            "applied_filters": ["budget_friendly"],
                            "estimated_cost": {
                                "total_cost": 24.5,
                                "currency": "EGP",
                                "coverage": "partial",
                                "confidence": 0.72,
                            },
                        }
                    ],
                    "budget": {
                        "max_total_cost": 60,
                        "currency": "EGP",
                        "geography": "Cairo",
                    },
                },
            },
        ),
        (
            "post",
            "/v1/prices/estimate",
            {
                "price_basis": "ingredient_list",
                "ingredients": [
                    {
                        "id": "ing_001",
                        "name": "rice",
                        "quantity": 500,
                        "unit": "g",
                    }
                ],
                "budget": {
                    "currency": "EGP",
                    "geography": "Cairo",
                },
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
            "/v1/profile/update",
            {
                "age_years": 30,
                "sex": "prefer_not_to_say",
                "height_cm": 170,
                "weight_kg": 70,
                "activity_level": "moderately_active",
                "goal": "improve_general_health",
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
                },
                "pantry": [
                    {
                        "id": "ing_001",
                        "name": "rice",
                        "quantity": 500,
                        "unit": "g",
                    },
                    {
                        "id": "ing_002",
                        "name": "lentils",
                        "quantity": 250,
                        "unit": "g",
                    },
                ],
                "budget": {
                    "currency": "EGP",
                    "geography": "Cairo",
                },
                "dietary_filters": ["budget_friendly"],
            },
        ),
    ]

    for method, path, json in requests:
        response = getattr(client, method)(path, json=json)

        assert response.status_code == 200, (path, response.text)
        assert response.json()


def test_vision_identify_returns_mock_response() -> None:
    response = client.post(
        "/v1/vision/identify",
        files={"image": ("food.jpg", b"mock-image", "image/jpeg")},
        data={"locale": "en"},
    )

    assert response.status_code == 200
    assert response.json()["image_id"] == "img_stub_001"


def test_v1_get_endpoints_return_mock_responses() -> None:
    for path, expected_id_field in [
        ("/v1/profile/profile_stub_001", "profile_id"),
        ("/v1/recipes/recipe_stub_001", "recipe_id"),
        ("/v1/plans/plan_stub_001", "plan_id"),
    ]:
        response = client.get(path)

        assert response.status_code == 200, (path, response.text)
        assert expected_id_field in response.json()