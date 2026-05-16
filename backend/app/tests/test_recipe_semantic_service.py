from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.services import recipe_semantic_service as semantic_module
from app.services.recipe_semantic_service import PgvectorRecipeSemanticProvider


class FakeEmbeddingModel:
    def encode(
        self,
        values: list[str],
        *,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> list[list[float]]:
        assert values == ["burger bun"]
        assert normalize_embeddings is True
        assert show_progress_bar is False
        return [[1.0] + [0.0] * 383]


class FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


def test_pgvector_recipe_provider_returns_ranked_candidates(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: dict[str, object]) -> FakeResult:
            del statement
            captured.update(params)
            return FakeResult(
                [
                    {"canonical_name": "hamburger bun", "score": 0.91},
                    {"canonical_name": "bread roll", "score": 0.72},
                ]
            )

    monkeypatch.setattr(semantic_module, "SessionLocal", lambda: FakeSession())

    provider = PgvectorRecipeSemanticProvider(model=FakeEmbeddingModel())
    result = provider.query("burger bun", top_n=2)

    assert list(result) == ["hamburger bun", "bread roll"]
    assert result["hamburger bun"] == 0.91
    assert captured["model_name"] == provider.model_name
    assert captured["limit"] == 2
    assert str(captured["embedding"]).startswith("[1.00000000,0.00000000")


def test_pgvector_recipe_provider_falls_back_when_index_unavailable(monkeypatch) -> None:
    class BrokenSession:
        def __enter__(self) -> "BrokenSession":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: dict[str, object]) -> FakeResult:
            del statement, params
            raise SQLAlchemyError("missing vector table")

    monkeypatch.setattr(semantic_module, "SessionLocal", lambda: BrokenSession())

    provider = PgvectorRecipeSemanticProvider(model=FakeEmbeddingModel())

    assert provider.query("burger bun", top_n=2) == {}
    assert provider.available is False
    assert provider.warning == "recipe semantic index unavailable"
