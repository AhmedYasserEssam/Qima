import asyncio
import base64
import json
from typing import Any

import httpx
import pytest

from app.schemas.v1.vision import VisionIdentifyResponse
from app.services.exceptions import BadRequestError, UpstreamUnavailableError
from app.services.vision_service import (
    GeminiVisionClient,
    GeminiVisionRecognition,
    VisionService,
)


def _gemini_response_text() -> str:
    return json.dumps(
        {
            "dish_candidates": [
                {"name": "koshari", "confidence": 0.88},
                {"name": "lentil rice bowl", "confidence": 0.61},
            ],
            "ingredients": [
                {"name": "rice", "confidence": 0.92},
                {"name": "lentils", "confidence": 0.89},
            ],
            "confidence": 0.86,
            "data_quality": {"completeness": "complete"},
            "warnings": [],
        }
    )


def test_gemini_client_sends_inline_image_and_parses_structured_output() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-goog-api-key")
        payload = json.loads(request.content.decode("utf-8"))
        captured["payload"] = payload
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": _gemini_response_text()}]}}
                ]
            },
        )

    client = GeminiVisionClient(
        api_key="test-secret-key",
        base_url="https://gemini.test/v1beta",
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(
        client.recognize_food_image(
            image_bytes=b"fake-image",
            mime_type="image/jpeg",
            locale="en",
        )
    )

    assert captured["url"] == (
        "https://gemini.test/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert captured["api_key"] == "test-secret-key"
    assert "test-secret-key" not in json.dumps(captured["payload"])
    inline_data = captured["payload"]["contents"][0]["parts"][0]["inline_data"]
    assert inline_data == {
        "mime_type": "image/jpeg",
        "data": base64.b64encode(b"fake-image").decode("ascii"),
    }
    prompt = captured["payload"]["contents"][0]["parts"][1]["text"]
    assert "Prioritize Egyptian dishes" in prompt
    assert "prefer 'macaroni bechamel' over 'pastitsio'" in prompt
    assert "Use the simplest accurate food name" in prompt
    assert "use 'walnuts' instead of 'glazed walnuts'" in prompt
    assert "cashews' instead of 'seasoned cashews'" in prompt
    generation_config = captured["payload"]["generationConfig"]
    assert generation_config["responseMimeType"] == "application/json"
    assert generation_config["responseJsonSchema"]["required"] == [
        "dish_candidates",
        "ingredients",
        "confidence",
        "data_quality",
        "warnings",
    ]
    assert result.dish_candidates[0].name == "koshari"
    assert result.confidence == 0.86


def test_gemini_client_requires_api_key() -> None:
    client = GeminiVisionClient(api_key="")

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.recognize_food_image(
                image_bytes=b"fake-image",
                mime_type="image/jpeg",
                locale=None,
            )
        )


def test_vision_service_maps_gemini_result_to_public_contract() -> None:
    class FakeGeminiClient:
        async def recognize_food_image(
            self,
            *,
            image_bytes: bytes,
            mime_type: str,
            locale: str | None,
        ) -> GeminiVisionRecognition:
            assert image_bytes == b"fake-image"
            assert mime_type == "image/png"
            assert locale == "ar-EG"
            return GeminiVisionRecognition.model_validate_json(_gemini_response_text())

    service = VisionService(client=FakeGeminiClient(), max_image_bytes=100)

    result = asyncio.run(
        service.identify_food_image(
            image_bytes=b"fake-image",
            filename="meal.png",
            content_type="application/octet-stream",
            locale="ar-EG",
        )
    )

    assert isinstance(result, VisionIdentifyResponse)
    assert result.image_id.startswith("img_")
    assert result.source.provider == "gemini"
    assert result.source.model == "gemini_2_5_flash"
    assert result.source.source_type == "vision_model"
    assert result.dish_candidates[0].name == "koshari"
    assert result.ingredients[0].name == "rice"
    assert result.data_quality.completeness == "complete"


def test_vision_service_rejects_unsupported_image_type() -> None:
    service = VisionService(
        client=GeminiVisionClient(api_key="unused"),
        max_image_bytes=100,
    )

    with pytest.raises(BadRequestError):
        asyncio.run(
            service.identify_food_image(
                image_bytes=b"not-an-image",
                filename="notes.txt",
                content_type="text/plain",
                locale=None,
            )
        )


def test_vision_service_rejects_large_inline_image() -> None:
    service = VisionService(
        client=GeminiVisionClient(api_key="unused"),
        max_image_bytes=3,
    )

    with pytest.raises(BadRequestError):
        asyncio.run(
            service.identify_food_image(
                image_bytes=b"too-large",
                filename="meal.jpg",
                content_type="image/jpeg",
                locale=None,
            )
        )
