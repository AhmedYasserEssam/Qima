from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import RECIPE_EMBEDDING_DIMENSION, SessionLocal

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional dependency
    SentenceTransformer = None


DEFAULT_RECIPE_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class PgvectorRecipeSemanticProvider:
    def __init__(
        self,
        *,
        model_name: str = DEFAULT_RECIPE_EMBEDDING_MODEL,
        dimension: int = RECIPE_EMBEDDING_DIMENSION,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self._model = model
        self._model_checked = model is not None
        self._last_warning: str | None = None
        self._available = model is not None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def warning(self) -> str | None:
        return self._last_warning

    def build_index(self, entries: list[Any]) -> None:
        del entries

    def query(self, text_value: str, top_n: int) -> dict[str, float]:
        self._last_warning = None
        if not text_value.strip():
            return {}
        if not self._ensure_model():
            return {}

        try:
            embedding = self._encode_query(text_value)
        except Exception:
            self._available = False
            self._last_warning = "recipe semantic index unavailable: query embedding failed"
            return {}

        try:
            with SessionLocal() as session:
                rows = session.execute(
                    text(
                        """
                        SELECT
                            canonical_name,
                            GREATEST(0.0, LEAST(1.0, 1.0 - (embedding <=> CAST(:embedding AS vector)))) AS score
                        FROM recipe_ingredient_embeddings
                        WHERE model_name = :model_name
                        ORDER BY embedding <=> CAST(:embedding AS vector)
                        LIMIT :limit
                        """
                    ),
                    {
                        "embedding": _vector_literal(embedding),
                        "model_name": self.model_name,
                        "limit": max(1, top_n),
                    },
                ).mappings().all()
        except SQLAlchemyError:
            self._available = False
            self._last_warning = "recipe semantic index unavailable"
            return {}

        if not rows:
            self._available = False
            self._last_warning = "recipe semantic index unavailable: no embeddings found"
            return {}

        self._available = True
        return {
            str(row["canonical_name"]): max(0.0, min(1.0, float(row["score"])))
            for row in rows
        }

    def _ensure_model(self) -> bool:
        if self._model_checked:
            return self._model is not None
        self._model_checked = True
        if SentenceTransformer is None:
            self._available = False
            self._last_warning = "recipe semantic index unavailable: sentence-transformers not installed"
            return False
        try:
            self._model = SentenceTransformer(self.model_name)
        except Exception:
            self._model = None
            self._available = False
            self._last_warning = "recipe semantic index unavailable: embedding model failed to load"
            return False
        self._available = True
        return True

    def _encode_query(self, text_value: str) -> list[float]:
        if self._model is None:
            return []
        embedding = self._model.encode(
            [text_value],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        values = [float(value) for value in embedding]
        if len(values) != self.dimension:
            raise ValueError(
                f"Expected {self.dimension} embedding dimensions, got {len(values)}."
            )
        return values


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"
