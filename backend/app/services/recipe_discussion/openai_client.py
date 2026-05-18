from __future__ import annotations

import json
from typing import Any
import httpx

from app.services.exceptions import UpstreamUnavailableError
from app.services.recipe_discussion.base import RecipeDiscussionClient

RECIPE_DISCUSSION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {
        "answer": {
            "type": "string",
            "description": "A practical, grounded answer for the user's recipe question.",
        }
    },
}

RECIPE_DISCUSSION_INSTRUCTIONS = (
    "You are Qima's recipe cooking assistant. Return JSON only, matching the "
    "provided schema. Answer practical questions about the selected recipe using "
    "only the supplied recipe context and conversation history. Help the user "
    "understand how to use the given ingredients, step-by-step preparation, and "
    "reasonable substitutions. If exact context is missing, say what is unknown "
    "and give cautious general cooking guidance. Do not provide medical advice, "
    "diagnose conditions, or claim allergy safety. For allergens or packaged "
    "ingredients, remind the user to check labels and avoid unsafe substitutions."
)


class OpenAIRecipeDiscussionClient(RecipeDiscussionClient):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-5-nano",
        timeout_seconds: float = 20.0,
        temperature: float = 0.2,
        max_tokens: int = 700,
        max_retries: int = 2,
        base_url: str = "https://api.openai.com/v1/responses",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = model.strip() or "gpt-5-nano"
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
            "instructions": RECIPE_DISCUSSION_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "recipe_discussion_answer",
                    "strict": True,
                    "schema": RECIPE_DISCUSSION_OUTPUT_SCHEMA,
                }
            },
            "max_output_tokens": self._max_tokens,
            "store": False,
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

        output_text = _extract_openai_output_text(response_payload)

        # Strip markdown backticks if present
        clean_text = output_text.strip()
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()

        try:
            parsed = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            raise UpstreamUnavailableError(
                "Recipe discussion service returned an invalid structured response."
            ) from exc

        answer = (
            str(parsed.get("answer") or "").strip()
            if isinstance(parsed, dict)
            else ""
        )
        if not answer:
            raise UpstreamUnavailableError(
                "Recipe discussion service returned an empty response."
            )
        return answer


def _extract_openai_output_text(response_payload: dict[str, Any]) -> str:
    direct_text = response_payload.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    output = response_payload.get("output")
    if not isinstance(output, list):
        raise UpstreamUnavailableError(
            "Recipe discussion service returned an empty response."
        )

    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") not in {"output_text", "text"}:
                continue
            text_value = part.get("text")
            if isinstance(text_value, str) and text_value.strip():
                text_parts.append(text_value.strip())

    output_text = "".join(text_parts).strip()
    if not output_text:
        raise UpstreamUnavailableError(
            "Recipe discussion service returned no structured content."
        )
    return output_text
