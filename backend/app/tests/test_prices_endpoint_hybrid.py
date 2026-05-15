from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_prices_estimate_endpoint_returns_hybrid_match_metadata() -> None:
    response = client.post(
        "/v1/prices/estimate",
        json={
            "ingredients": [
                {"name": "rice", "quantity": 100, "unit": "g"},
                {"name": "chicken breast", "quantity": 200, "unit": "g"},
            ],
            "currency": "EGP",
            "geography": "Egypt",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currency"] == "EGP"
    assert "total_cost" in body
    assert "estimate_quality" in body
    assert "unmatched_ingredients" in body
    assert "source_metadata" in body
    assert len(body["item_costs"]) == 2

    first = body["item_costs"][0]
    assert "match" in first
    assert first["match"]["method"] == "hybrid"
    assert "confidence" in first["match"]
    assert "lexical_score" in first["match"]
    assert "embedding_score" in first["match"]
