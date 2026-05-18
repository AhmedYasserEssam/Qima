from __future__ import annotations

import base64
import json
import mimetypes
import time
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.schemas.v1.vision import (
    DishCandidate,
    IngredientCandidate,
    VisionDataQuality,
    VisionIdentifyResponse,
    VisionSource,
)
from app.services.exceptions import BadRequestError, UpstreamUnavailableError

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_PUBLIC_MODEL_ID = "gemini_2_5_flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

SUPPORTED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

VISION_RECOGNITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "dish_candidates",
        "ingredients",
        "confidence",
        "data_quality",
        "warnings",
    ],
    "properties": {
        "dish_candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "description": "Ordered food or dish candidates visible in the image.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "confidence"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Concise dish or food name.",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
            },
        },
        "ingredients": {
            "type": "array",
            "maxItems": 20,
            "description": "Visible ingredient candidates. Use an empty array if none are reliable.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "confidence"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Concise ingredient name.",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
            },
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Overall confidence in the image recognition result.",
        },
        "data_quality": {
            "type": "object",
            "additionalProperties": False,
            "required": ["completeness"],
            "properties": {
                "completeness": {
                    "type": "string",
                    "enum": ["complete", "partial"],
                },
            },
        },
        "warnings": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string"},
        },
    },
}


class GeminiCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0, le=1)


class GeminiDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completeness: Literal["complete", "partial"]


class GeminiVisionRecognition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dish_candidates: list[GeminiCandidate] = Field(..., min_length=1, max_length=5)
    ingredients: list[GeminiCandidate] = Field(default_factory=list, max_length=20)
    confidence: float = Field(..., ge=0, le=1)
    data_quality: GeminiDataQuality
    warnings: list[str] = Field(default_factory=list, max_length=5)


class GeminiVisionClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = GEMINI_BASE_URL,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def recognize_food_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        locale: str | None,
    ) -> GeminiVisionRecognition:
        if not self._api_key:
            raise UpstreamUnavailableError("Gemini API key is not configured.")

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                        {"text": _build_prompt(locale)},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseJsonSchema": VISION_RECOGNITION_SCHEMA,
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/models/{GEMINI_MODEL}:generateContent",
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self._api_key,
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise UpstreamUnavailableError(
                "Vision identification service timed out."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(
                "Vision identification service is currently unavailable."
            ) from exc

        if response.status_code >= 400:
            raise UpstreamUnavailableError(
                "Vision provider request failed with HTTP "
                f"{response.status_code}: {_response_error_message(response)}"
            )

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise UpstreamUnavailableError(
                "Vision identification service returned invalid JSON."
            ) from exc

        response_text = _extract_response_text(response_payload)
        try:
            return GeminiVisionRecognition.model_validate_json(response_text)
        except ValidationError as exc:
            raise UpstreamUnavailableError(
                "Vision identification service returned an invalid structured response."
            ) from exc


class VisionService:
    def __init__(
        self,
        *,
        client: GeminiVisionClient | None = None,
        max_image_bytes: int | None = None,
    ) -> None:
        settings = get_settings()
        self._client = client or GeminiVisionClient(
            api_key=settings.gemini_api_key,
            timeout_seconds=settings.gemini_request_timeout_seconds,
        )
        self._max_image_bytes = (
            max_image_bytes
            if max_image_bytes is not None
            else settings.gemini_inline_image_max_bytes
        )

    async def identify_food_image(
        self,
        *,
        image_bytes: bytes,
        filename: str | None,
        content_type: str | None,
        locale: str | None = None,
    ) -> VisionIdentifyResponse:
        started_at = time.perf_counter()
        _validate_image_size(image_bytes, self._max_image_bytes)
        mime_type = _resolve_image_mime_type(
            filename=filename,
            content_type=content_type,
        )

        recognition = await self._client.recognize_food_image(
            image_bytes=image_bytes,
            mime_type=mime_type,
            locale=locale,
        )

        return VisionIdentifyResponse(
            image_id=f"img_{uuid4().hex[:12]}",
            dish_candidates=[
                DishCandidate.model_validate(candidate.model_dump())
                for candidate in recognition.dish_candidates
            ],
            ingredients=[
                IngredientCandidate.model_validate(candidate.model_dump())
                for candidate in recognition.ingredients
            ],
            confidence=recognition.confidence,
            source=VisionSource(
                provider="gemini",
                model=GEMINI_PUBLIC_MODEL_ID,
                source_type="vision_model",
            ),
            data_quality=VisionDataQuality(
                completeness=recognition.data_quality.completeness
            ),
            warnings=recognition.warnings,
            latency_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        )


def _build_prompt(locale: str | None) -> str:
    prompt = (
        "Analyze the uploaded food or meal image for Qima. Return only JSON matching "
        "the provided schema. Identify visible dish candidates and visible ingredient "
        "candidates with confidence scores from 0 to 1. Include at least one dish "
        "candidate; if no food is visible, use the name 'unknown food item' with low "
        "confidence and add a warning. Do not estimate nutrients, prices, medical "
        "advice, or recipe instructions. Prioritize Egyptian dishes and foods "
        "commonly available in Egypt when the image evidence supports them. When "
        "a food could be either an Egyptian/local Egyptian dish or a similar "
        "international dish, rank the Egyptian/common-in-Egypt name first; for "
        "example, prefer 'macaroni bechamel' over 'pastitsio' when both fit the "
        "image. Use the simplest accurate food name when the image evidence is "
        "simple. For ingredient candidates, prefer raw/base ingredients over "
        "processed or assembled intermediate food forms when the raw ingredient is "
        "reasonably inferable from the visible dish; for example, for a burger, "
        "list 'ground beef' instead of 'burger patty', and for pizza, list 'flour' "
        "instead of 'dough'. For pasta with sauce, list base ingredients such as "
        "'wheat pasta', 'tomato', or 'cheese' where visually supported, instead of "
        "only naming the assembled dish. For fried chicken, list 'chicken' instead "
        "of 'fried chicken piece' as an ingredient candidate. Do not over-infer "
        "hidden ingredients. Only include raw/base ingredients that are visually "
        "supported or strongly implied by the identified dish. If an ingredient is "
        "not visible and not strongly implied, omit it or assign low confidence. "
        "Do not add preparation, coating, seasoning, or flavor adjectives unless "
        "they are clearly visible; for example, use 'walnuts' instead of "
        "'glazed walnuts' and 'cashews' instead of 'seasoned cashews' when those "
        "extra details are not visually supported."
    )
    if locale:
        prompt += f" User locale: {locale}."
    return prompt


def _extract_response_text(response_payload: dict[str, Any]) -> str:
    candidates = response_payload.get("candidates")
    if not isinstance(candidates, list):
        raise UpstreamUnavailableError(
            "Vision identification service returned an empty response."
        )

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ).strip()
        if text:
            return text

    raise UpstreamUnavailableError(
        "Vision identification service returned no structured content."
    )


def _response_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()[:500] or "empty response body"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:500]
        try:
            return json.dumps(payload, ensure_ascii=True)[:500]
        except TypeError:
            return str(payload)[:500]

    return str(payload)[:500]


def _validate_image_size(image_bytes: bytes, max_image_bytes: int) -> None:
    if not image_bytes:
        raise BadRequestError("Request must include a non-empty image file.")
    if len(image_bytes) > max_image_bytes:
        raise BadRequestError("Image file is too large for inline vision processing.")


def _resolve_image_mime_type(*, filename: str | None, content_type: str | None) -> str:
    mime_type = (content_type or "").split(";")[0].strip().lower()
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"

    if not mime_type or mime_type == "application/octet-stream":
        guessed_type, _ = mimetypes.guess_type(filename or "")
        mime_type = (guessed_type or "").lower()
        if mime_type == "image/jpg":
            mime_type = "image/jpeg"

    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise BadRequestError("Request must include a supported image file.")

    return mime_type


vision_service = VisionService()


async def identify_food_image(
    *,
    image_bytes: bytes,
    filename: str | None,
    content_type: str | None,
    locale: str | None = None,
) -> VisionIdentifyResponse:
    return await vision_service.identify_food_image(
        image_bytes=image_bytes,
        filename=filename,
        content_type=content_type,
        locale=locale,
    )
