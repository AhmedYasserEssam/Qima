from __future__ import annotations

from dataclasses import dataclass

from scripts import seed_recipe_ingredient_embeddings as seed_embeddings


@dataclass(frozen=True)
class FakeVocabularyEntry:
    canonical_name: str
    observed_names: tuple[str, ...]
    frequency: int


class FakeSentenceTransformer:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def encode(
        self,
        names: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> list[list[float]]:
        assert names == ["hamburger bun", "cheddar cheese"]
        assert batch_size == 2
        assert normalize_embeddings is True
        assert show_progress_bar is True
        return [
            [1.0] + [0.0] * 383,
            [0.0, 1.0] + [0.0] * 382,
        ]


def test_build_embedding_rows_uses_vocabulary_without_writing(monkeypatch) -> None:
    monkeypatch.setattr(seed_embeddings, "SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr(
        seed_embeddings.ingredient_vocabulary_service,
        "get_entries",
        lambda: [
            FakeVocabularyEntry("hamburger bun", ("Hamburger bun",), 4),
            FakeVocabularyEntry("cheddar cheese", ("Cheddar cheese",), 2),
        ],
    )

    rows = seed_embeddings.build_embedding_rows(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        batch_size=2,
    )

    assert [row["canonical_name"] for row in rows] == [
        "hamburger bun",
        "cheddar cheese",
    ]
    assert rows[0]["display_name"] == "Hamburger bun"
    assert rows[0]["frequency"] == 4
    assert str(rows[0]["embedding"]).startswith("[1.00000000,0.00000000")


def test_upsert_embedding_rows_uses_conflict_update(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, rows: list[dict[str, object]]) -> None:
            captured["statement"] = str(statement)
            captured["rows"] = rows

    class FakeSessionLocal:
        def begin(self) -> FakeSession:
            return FakeSession()

    monkeypatch.setattr(seed_embeddings, "SessionLocal", FakeSessionLocal())
    rows = [
        {
            "canonical_name": "hamburger bun",
            "display_name": "Hamburger bun",
            "frequency": 4,
            "model_name": "model",
            "embedding": "[1.0,0.0]",
            "updated_at": None,
        }
    ]

    assert seed_embeddings.upsert_embedding_rows(rows) == 1
    assert "ON CONFLICT (canonical_name)" in str(captured["statement"])
    assert captured["rows"] == rows
