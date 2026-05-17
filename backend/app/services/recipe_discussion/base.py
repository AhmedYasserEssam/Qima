from __future__ import annotations

from abc import ABC, abstractmethod


class RecipeDiscussionClient(ABC):
    @abstractmethod
    async def generate_answer(
        self,
        *,
        question: str,
        recipe_context: dict,
        match_context: dict,
        safety_context: dict | None = None,
    ) -> str:
        """Generates a structured answer response for the recipe discussion flow."""
