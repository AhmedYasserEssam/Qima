from __future__ import annotations

import asyncio
import httpx
import pytest

from app.core.config import Settings
from app.schemas.v1.recipes import CandidateContext, ConversationTurn
from app.services.exceptions import NotFoundError, UpstreamUnavailableError
from app.services.recipe_service import RecipeService
from app.services.recipe_discussion.openai_client import OpenAIRecipeDiscussionClient
from app.services.recipe_discussion.groq_client import GroqRecipeDiscussionClient
from app.services.recipe_discussion.factory import get_recipe_discussion_client


# ==========================================
# OpenAI Recipe Discussion Client Tests
# ==========================================

def test_openai_recipe_discussion_client_returns_structured_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        payload = request.content.decode("utf-8")
        assert "recipe_discussion_answer" in payload
        assert "json_schema" in payload
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"answer":"Cook the lentils until tender."}',
                            }
                        ],
                    }
                ]
            },
        )

    client = OpenAIRecipeDiscussionClient(
        api_key="test-key",
        model="gpt-test",
        transport=httpx.MockTransport(handler),
    )

    answer = asyncio.run(
        client.generate_answer(
            question="Recipe prompt",
            recipe_context={"title": "tomato lentil skillet"},
            match_context={},
        )
    )

    assert answer == "Cook the lentils until tender."


def test_openai_recipe_discussion_client_requires_api_key() -> None:
    client = OpenAIRecipeDiscussionClient(api_key="")

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_openai_recipe_discussion_client_maps_timeout_to_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.TimeoutException("timeout")

    client = OpenAIRecipeDiscussionClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_openai_recipe_discussion_client_maps_http_failure_to_upstream_error() -> None:
    client = OpenAIRecipeDiscussionClient(
        api_key="test-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        max_retries=0,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_openai_recipe_discussion_client_rejects_invalid_json_response() -> None:
    client = OpenAIRecipeDiscussionClient(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not-json")
        ),
        max_retries=0,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_openai_recipe_discussion_client_rejects_invalid_structured_output() -> None:
    client = OpenAIRecipeDiscussionClient(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "not-json",
                                }
                            ],
                        }
                    ]
                },
            )
        ),
        max_retries=0,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


# ==========================================
# Groq Recipe Discussion Client Tests
# ==========================================

def test_groq_recipe_discussion_client_returns_structured_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer groq-key"
        payload = request.content.decode("utf-8")
        assert "response_format" in payload
        assert "json_object" in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"answer": "Simmer for twenty minutes."}',
                        }
                    }
                ]
            },
        )

    client = GroqRecipeDiscussionClient(
        api_key="groq-key",
        model="llama-test",
        transport=httpx.MockTransport(handler),
    )

    answer = asyncio.run(
        client.generate_answer(
            question="How long should I simmer?",
            recipe_context={"title": "lentil skillet"},
            match_context={},
        )
    )

    assert answer == "Simmer for twenty minutes."


def test_groq_recipe_discussion_client_requires_api_key() -> None:
    client = GroqRecipeDiscussionClient(api_key="")

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_groq_recipe_discussion_client_maps_timeout_to_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.TimeoutException("timeout")

    client = GroqRecipeDiscussionClient(
        api_key="groq-key",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_groq_recipe_discussion_client_maps_http_failure_to_upstream_error() -> None:
    client = GroqRecipeDiscussionClient(
        api_key="groq-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        max_retries=0,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_groq_recipe_discussion_client_rejects_invalid_json_response() -> None:
    client = GroqRecipeDiscussionClient(
        api_key="groq-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not-json")
        ),
        max_retries=0,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_groq_recipe_discussion_client_rejects_incorrect_keys_in_json() -> None:
    # Key 'text' used instead of expected 'answer'
    client = GroqRecipeDiscussionClient(
        api_key="groq-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"text": "Should fail validation."}',
                            }
                        }
                    ]
                },
            )
        ),
        max_retries=0,
    )

    with pytest.raises(UpstreamUnavailableError):
        asyncio.run(
            client.generate_answer(
                question="Recipe prompt",
                recipe_context={},
                match_context={},
            )
        )


def test_groq_recipe_discussion_client_retry_handling() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429)  # Rate limited
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"answer": "Simmer for ten minutes."}',
                        }
                    }
                ]
            },
        )

    client = GroqRecipeDiscussionClient(
        api_key="groq-key",
        transport=httpx.MockTransport(handler),
        max_retries=2,
    )

    answer = asyncio.run(
        client.generate_answer(
            question="Recipe prompt",
            recipe_context={},
            match_context={},
        )
    )

    assert answer == "Simmer for ten minutes."
    assert attempts == 2


# ==========================================
# Factory & Settings Mapping Tests
# ==========================================

def test_recipe_discussion_client_factory_creates_groq_by_default() -> None:
    settings = Settings(
        RECIPE_DISCUSSION_PROVIDER="groq",
        RECIPE_DISCUSSION_MODEL="llama-3.1-8b-instant",
        GROQ_API_KEY="groq-test-key",
    )
    client = get_recipe_discussion_client(settings)
    assert isinstance(client, GroqRecipeDiscussionClient)
    assert client._api_key == "groq-test-key"
    assert client._model == "llama-3.1-8b-instant"


def test_recipe_discussion_client_factory_creates_openai() -> None:
    settings = Settings(
        RECIPE_DISCUSSION_PROVIDER="openai",
        RECIPE_DISCUSSION_MODEL="gpt-test-model",
        OPENAI_API_KEY="openai-test-key",
    )
    client = get_recipe_discussion_client(settings)
    assert isinstance(client, OpenAIRecipeDiscussionClient)
    assert client._api_key == "openai-test-key"
    assert client._model == "gpt-test-model"


# ==========================================
# Grounding, Safety & Recipe Service Integration Tests
# ==========================================

def test_recipe_service_uses_discussion_answer_with_grounded_references(monkeypatch) -> None:
    fake_client = _FakeDiscussionClient("Use olive oil and simmer until tender.")
    service = RecipeService(discussion_client=fake_client)
    monkeypatch.setattr(service, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(
        service,
        "_resolve_recipe_row",
        lambda **kwargs: _recipe_row(),
    )

    response = asyncio.run(
        service.discuss_recipe(
            recipe_id="recipe_001",
            candidate_context=CandidateContext(
                title="Tomato Lentil Skillet",
                matched_ingredients=["lentils", "tomato"],
                missing_ingredients=["butter"],
            ),
            question="Can I replace butter?",
            conversation_history=[
                ConversationTurn(role="user", content="How do I start?")
            ],
        )
    )

    assert response.answer == "Use olive oil and simmer until tender."
    assert response.grounded_references[0].recipe_id == "recipe_001"
    assert response.safety_flags.allergen_risk is True
    assert response.warnings == [
        "Selected candidate context listed missing ingredients: butter"
    ]
    assert fake_client.question == "Can I replace butter?"
    assert fake_client.recipe_context["title"] == "Tomato Lentil Skillet"
    assert fake_client.match_context["selected_candidate_context"]["title"] == "Tomato Lentil Skillet"
    assert len(fake_client.match_context["recent_conversation"]) == 1


def test_recipe_discussion_prompt_includes_retrieved_recipe_context(monkeypatch) -> None:
    fake_client = _FakeDiscussionClient("Mocked answer")
    service = RecipeService(discussion_client=fake_client)
    monkeypatch.setattr(service, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(
        service,
        "_resolve_recipe_row",
        lambda **kwargs: _recipe_row(),
    )

    asyncio.run(
        service.discuss_recipe(
            recipe_id="recipe_001",
            candidate_context=None,
            question="Is butter used?",
            conversation_history=[],
        )
    )

    assert fake_client.recipe_context["title"] == "Tomato Lentil Skillet"
    assert fake_client.recipe_context["servings"] == 2
    assert fake_client.recipe_context["total_minutes"] == 30.0
    assert fake_client.recipe_context["ingredients"] == ["lentils", "tomato", "butter"]


def test_recipe_discussion_rejects_missing_recipe_context(monkeypatch) -> None:
    fake_client = _FakeDiscussionClient("unused")
    service = RecipeService(discussion_client=fake_client)
    monkeypatch.setattr(service, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(service, "_resolve_recipe_row", lambda **kwargs: None)

    with pytest.raises(NotFoundError):
        asyncio.run(
            service.discuss_recipe(
                recipe_id="missing",
                candidate_context=None,
                question="How do I cook this?",
                conversation_history=[],
            )
        )


def test_recipe_discussion_does_not_call_llm_when_recipe_context_missing(monkeypatch) -> None:
    fake_client = _FakeDiscussionClient("unused")
    service = RecipeService(discussion_client=fake_client)
    monkeypatch.setattr(service, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(service, "_resolve_recipe_row", lambda **kwargs: None)

    try:
        asyncio.run(
            service.discuss_recipe(
                recipe_id="missing",
                candidate_context=None,
                question="Is there cheese?",
                conversation_history=[],
            )
        )
    except NotFoundError:
        pass

    assert fake_client.question == ""
    assert not fake_client.recipe_context


def test_recipe_discussion_returns_limitation_when_user_asks_for_unrelated_new_recipe(monkeypatch) -> None:
    limitation_answer = "I can only help you cook the selected recipe (Tomato Lentil Skillet). Let me know if you want to cook that instead!"
    fake_client = _FakeDiscussionClient(limitation_answer)
    
    service = RecipeService(discussion_client=fake_client)
    monkeypatch.setattr(service, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(
        service,
        "_resolve_recipe_row",
        lambda **kwargs: _recipe_row(),
    )

    response = asyncio.run(
        service.discuss_recipe(
            recipe_id="recipe_001",
            candidate_context=None,
            question="Can you give me a recipe for cheese pizza?",
            conversation_history=[],
        )
    )

    assert "pizza" in fake_client.question
    assert "only help you cook" in response.answer


# ==========================================
# Helpers & Mocks
# ==========================================

class _FakeDiscussionClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.question = ""
        self.recipe_context = {}
        self.match_context = {}
        self.safety_context = {}

    async def generate_answer(
        self,
        *,
        question: str,
        recipe_context: dict,
        match_context: dict,
        safety_context: dict | None = None,
    ) -> str:
        self.question = question
        self.recipe_context = recipe_context
        self.match_context = match_context
        self.safety_context = safety_context or {}
        return self.answer


def _recipe_row() -> dict:
    return {
        "recipe_id": "recipe_001",
        "stable_slug": "tomato-lentil-skillet",
        "source_url": "https://example.test/recipe_001",
        "title": "Tomato Lentil Skillet",
        "servings": 2,
        "total_minutes": 30,
        "ingredients": [
            {"name_normalized": "lentils"},
            {"name_normalized": "tomato"},
            {"name_normalized": "butter"},
        ],
        "directions_json": [
            {"raw_text": "Melt butter in a skillet."},
            {"raw_text": "Simmer lentils until tender."},
        ],
        "allergen_flags": ["milk"],
    }
