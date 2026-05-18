from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.normalizers.ingredient_normalizer import normalize_name

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency at runtime.
    np = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional dependency at runtime.
    SentenceTransformer = None


@dataclass(frozen=True)
class EmbeddingCandidate:
    item_id: str
    score: float


class PriceEmbeddingService:
    """Vector retrieval service with a swappable provider."""

    def __init__(
        self,
        *,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        cache_path: str | Path | None = None,
        dimension: int = 384,
    ) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self.cache_path = Path(cache_path) if cache_path else None
        self.provider = "token_hash"
        self._model: Any = None
        self._items: list[dict[str, Any]] = []
        self._dense_matrix: Any = None
        self._item_vectors: dict[str, dict[int, float]] = {}
        self._item_norms: dict[str, float] = {}

        if SentenceTransformer is not None and np is not None:
            try:
                self._model = SentenceTransformer(model_name)
                self.provider = "sentence_transformers"
            except Exception:
                self._model = None
                self.provider = "token_hash"

    def build_index(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        if self.provider == "sentence_transformers":
            self._build_sentence_index(items)
            return
        self._build_token_hash_index(items)

    def query(self, text: str, top_n: int = 8) -> list[EmbeddingCandidate]:
        if not self._items:
            return []

        normalized = normalize_name(text)
        if not normalized:
            return []

        if self.provider == "sentence_transformers":
            return self._query_sentence(normalized, top_n=top_n)
        return self._query_token_hash(normalized, top_n=top_n)

    def _build_sentence_index(self, items: list[dict[str, Any]]) -> None:
        names = [normalize_name(item.get("name", "")) for item in items]
        if not names or self._model is None or np is None:
            self.provider = "token_hash"
            self._build_token_hash_index(items)
            return

        embeddings = self._model.encode(
            names,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        self._dense_matrix = embeddings

    def _query_sentence(self, normalized: str, top_n: int) -> list[EmbeddingCandidate]:
        if self._dense_matrix is None or self._model is None or np is None:
            return []

        query_vector = self._model.encode(
            [normalized],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        scores = np.dot(self._dense_matrix, query_vector)
        if len(scores) == 0:
            return []

        top_indexes = np.argsort(scores)[::-1][:top_n]
        result: list[EmbeddingCandidate] = []
        for idx in top_indexes:
            score = float(scores[idx])
            item_id = str(self._items[int(idx)]["id"])
            result.append(EmbeddingCandidate(item_id=item_id, score=max(0.0, min(1.0, score))))
        return result

    def _signature(self, items: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for item in items:
            digest.update(str(item.get("id", "")).encode("utf-8"))
            digest.update(b"|")
            digest.update(str(item.get("name", "")).encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _build_token_hash_index(self, items: list[dict[str, Any]]) -> None:
        self._item_vectors = {}
        self._item_norms = {}
        signature = self._signature(items)

        if self.cache_path and self._load_cache(signature):
            return

        for item in items:
            item_id = str(item["id"])
            text = normalize_name(item.get("name", ""))
            vector = self._hash_vector(text)
            self._item_vectors[item_id] = vector
            self._item_norms[item_id] = self._vector_norm(vector)

        if self.cache_path:
            self._save_cache(signature)

    def _hash_vector(self, text: str) -> dict[int, float]:
        vector: dict[int, float] = {}
        for token in text.split():
            self._add_to_vector(vector, token, 1.0)
            padded = f"#{token}#"
            for idx in range(max(0, len(padded) - 2)):
                ngram = padded[idx : idx + 3]
                self._add_to_vector(vector, ngram, 0.5)
        return vector

    def _add_to_vector(self, vector: dict[int, float], value: str, weight: float) -> None:
        index = hash(value) % self.dimension
        vector[index] = vector.get(index, 0.0) + weight

    def _vector_norm(self, vector: dict[int, float]) -> float:
        return math.sqrt(sum(component * component for component in vector.values()))

    def _cosine_sparse(
        self,
        left: dict[int, float],
        right: dict[int, float],
        left_norm: float,
        right_norm: float,
    ) -> float:
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
            left_norm, right_norm = right_norm, left_norm

        dot = 0.0
        for key, value in left.items():
            dot += value * right.get(key, 0.0)
        return dot / (left_norm * right_norm)

    def _query_token_hash(self, normalized: str, top_n: int) -> list[EmbeddingCandidate]:
        query_vector = self._hash_vector(normalized)
        query_norm = self._vector_norm(query_vector)
        if query_norm <= 0:
            return []

        scores: list[EmbeddingCandidate] = []
        for item in self._items:
            item_id = str(item["id"])
            item_vector = self._item_vectors.get(item_id)
            item_norm = self._item_norms.get(item_id, 0.0)
            if not item_vector:
                continue
            score = self._cosine_sparse(query_vector, item_vector, query_norm, item_norm)
            scores.append(EmbeddingCandidate(item_id=item_id, score=max(0.0, min(1.0, score))))

        scores.sort(key=lambda candidate: candidate.score, reverse=True)
        return scores[:top_n]

    def _load_cache(self, signature: str) -> bool:
        if not self.cache_path:
            return False
        if not self.cache_path.exists():
            return False
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if payload.get("signature") != signature:
            return False
        if payload.get("dimension") != self.dimension:
            return False

        vectors = payload.get("vectors")
        if not isinstance(vectors, dict):
            return False

        self._item_vectors = {}
        self._item_norms = {}
        for item_id, entries in vectors.items():
            if not isinstance(entries, list):
                continue
            vector: dict[int, float] = {}
            for pair in entries:
                if not isinstance(pair, list) or len(pair) != 2:
                    continue
                vector[int(pair[0])] = float(pair[1])
            self._item_vectors[str(item_id)] = vector
            self._item_norms[str(item_id)] = self._vector_norm(vector)
        return True

    def _save_cache(self, signature: str) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            vectors = {
                item_id: [[index, value] for index, value in vector.items()]
                for item_id, vector in self._item_vectors.items()
            }
            payload = {
                "signature": signature,
                "dimension": self.dimension,
                "vectors": vectors,
            }
            self.cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            return
