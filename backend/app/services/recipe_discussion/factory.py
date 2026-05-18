from __future__ import annotations

from app.core.config import Settings
from app.services.recipe_discussion.base import RecipeDiscussionClient
from app.services.recipe_discussion.openai_client import OpenAIRecipeDiscussionClient
from app.services.recipe_discussion.groq_client import GroqRecipeDiscussionClient


def get_recipe_discussion_client(settings: Settings) -> RecipeDiscussionClient:
    provider = settings.recipe_discussion_provider.lower().strip()
    if provider == "groq":
        return GroqRecipeDiscussionClient(
            api_key=settings.groq_api_key,
            model=settings.recipe_discussion_model,
            timeout_seconds=settings.recipe_discussion_timeout_seconds,
            temperature=settings.recipe_discussion_temperature,
            max_tokens=settings.recipe_discussion_max_tokens,
            max_retries=settings.recipe_discussion_max_retries,
        )
    elif provider == "openai":
        return OpenAIRecipeDiscussionClient(
            api_key=settings.openai_api_key,
            model=settings.recipe_discussion_model,
            timeout_seconds=settings.recipe_discussion_timeout_seconds,
            temperature=settings.recipe_discussion_temperature,
            max_tokens=settings.recipe_discussion_max_tokens,
            max_retries=settings.recipe_discussion_max_retries,
        )
    else:
        raise ValueError(f"Unsupported recipe discussion provider: {provider}")
