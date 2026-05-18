from __future__ import annotations

import json
from typing import Any
import httpx
from pydantic import BaseModel, Field, ValidationError

from app.services.exceptions import UpstreamUnavailableError
from app.services.recipe_discussion.base import RecipeDiscussionClient
from app.services.recipe_discussion.openai_client import (
    RECIPE_DISCUSSION_INSTRUCTIONS,
    RECIPE_DISCUSSION_OUTPUT_SCHEMA,
)


class RecipeDiscussionAnswer(BaseModel):
    answer: str = Field(..., min_length=1)


class GroqRecipeDiscussionClient(RecipeDiscussionClient):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "llama-3.1-8b-instant",
        timeout_seconds: float = 20.0,
        temperature: float = 0.2,
        max_tokens: int = 700,
        max_retries: int = 2,
        base_url: str = "https://api.groq.com/openai/v1/chat/completions",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = model.strip() or "llama-3.1-8b-instant"
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._base_url = base_url
        self._transport = transport

    async def generate_answer(
        self,
        *,
        question: str,
        recipe_context: dict,
        match_context: dict,
        safety_context: dict | None = None,
    ) -> str:
        if not self._api_key:
            raise UpstreamUnavailableError(
                "Recipe discussion service is not configured."
            )

        prompt_data = {
            "recipe": recipe_context,
            "selected_candidate_context": match_context.get("selected_candidate_context"),
            "recent_conversation": match_context.get("recent_conversation", []),
            "current_question": question.strip(),
        }
        prompt = (
            "Use this JSON context to answer the current question. Prefer the "
            "recipe's listed ingredients and directions. When suggesting "
            "substitutions, explain the cooking impact briefly and avoid claiming "
            "that an allergen substitution is safe unless the provided context "
            "supports it. Keep the answer concise and directly useful.\n\n"
            + json.dumps(prompt_data, indent=2, ensure_ascii=False)
        )

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        RECIPE_DISCUSSION_INSTRUCTIONS
                        + "\n\nYou must respond with a JSON object conforming exactly to this JSON schema:\n"
                        + json.dumps(RECIPE_DISCUSSION_OUTPUT_SCHEMA, indent=2)
                        + "\n\nOnly return a valid JSON object matching this schema. Do not include any other text or explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }

        response = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        self._base_url,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self._max_retries:
                        continue
                    raise UpstreamUnavailableError(
                        "Recipe discussion service is currently unavailable or rate limited."
                    )
                elif response.status_code in {401, 403}:
                    raise UpstreamUnavailableError(
                        "Recipe discussion service authentication failed due to misconfiguration."
                    )
                elif response.status_code >= 400:
                    raise UpstreamUnavailableError(
                        f"Recipe discussion service returned error status {response.status_code}."
                    )
                break
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    continue
                raise UpstreamUnavailableError(
                    "Recipe discussion service timed out."
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < self._max_retries:
                    continue
                raise UpstreamUnavailableError(
                    "Recipe discussion service is currently unavailable."
                ) from exc

        if response is None:
            raise UpstreamUnavailableError(
                "Recipe discussion service returned no response."
            )

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise UpstreamUnavailableError(
                "Recipe discussion service returned invalid JSON."
            ) from exc

        if response_payload.get("error"):
            raise UpstreamUnavailableError(
                "Recipe discussion service is currently unavailable."
            )

        try:
            choices = response_payload.get("choices")
            if not isinstance(choices, list) or not choices:
                raise UpstreamUnavailableError(
                    "Recipe discussion service returned an empty response."
                )
            content = choices[0].get("message", {}).get("content", "").strip()
        except Exception as exc:
            raise UpstreamUnavailableError(
                "Recipe discussion service returned an invalid response structure."
            ) from exc

        # Strip markdown backticks if returned by the LLM
        clean_content = content.strip()
        if clean_content.startswith("```"):
            lines = clean_content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_content = "\n".join(lines).strip()

        try:
            parsed = json.loads(clean_content)
        except json.JSONDecodeError as exc:
            raise UpstreamUnavailableError(
                "Recipe discussion service returned an invalid structured response."
            ) from exc

        # Explicitly reject {"text": "..."} format, expect {"answer": "..."}
        if isinstance(parsed, dict) and "text" in parsed and "answer" not in parsed:
            raise UpstreamUnavailableError(
                "Recipe discussion service returned format key 'text' instead of 'answer'."
            )

        try:
            validated = RecipeDiscussionAnswer.model_validate(parsed)
        except ValidationError as exc:
            raise UpstreamUnavailableError(
                "Recipe discussion service answer did not match required schema."
            ) from exc

        return validated.answer
