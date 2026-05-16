from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import RECIPE_EMBEDDING_DIMENSION, SessionLocal, init_db
from app.services.ingredient_vocabulary_service import ingredient_vocabulary_service
from app.services.recipe_semantic_service import DEFAULT_RECIPE_EMBEDDING_MODEL

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - dependency error is handled in main.
    SentenceTransformer = None


def build_embedding_rows(
    *,
    model_name: str,
    batch_size: int,
) -> list[dict[str, Any]]:
    entries = ingredient_vocabulary_service.get_entries()
    if not entries:
        return []
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is required to seed recipe embeddings.")

    model = SentenceTransformer(model_name)
    names = [entry.canonical_name for entry in entries]
    embeddings = model.encode(
        names,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    rows: list[dict[str, Any]] = []
    now = datetime.now(UTC).replace(tzinfo=None)
    for entry, embedding in zip(entries, embeddings, strict=True):
        values = [float(value) for value in embedding]
        if len(values) != RECIPE_EMBEDDING_DIMENSION:
            raise ValueError(
                f"Expected {RECIPE_EMBEDDING_DIMENSION} dimensions for {entry.canonical_name}, "
                f"got {len(values)}."
            )
        rows.append(
            {
                "canonical_name": entry.canonical_name,
                "display_name": entry.observed_names[0]
                if entry.observed_names
                else entry.canonical_name,
                "frequency": entry.frequency,
                "model_name": model_name,
                "embedding": _vector_literal(values),
                "updated_at": now,
            }
        )
    return rows


def upsert_embedding_rows(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    try:
        with SessionLocal.begin() as session:
            session.execute(
                text(
                    """
                    INSERT INTO recipe_ingredient_embeddings (
                        canonical_name,
                        display_name,
                        frequency,
                        model_name,
                        embedding,
                        updated_at
                    )
                    VALUES (
                        :canonical_name,
                        :display_name,
                        :frequency,
                        :model_name,
                        CAST(:embedding AS vector),
                        :updated_at
                    )
                    ON CONFLICT (canonical_name)
                    DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        frequency = EXCLUDED.frequency,
                        model_name = EXCLUDED.model_name,
                        embedding = EXCLUDED.embedding,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                rows,
            )
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Could not upsert recipe embeddings. Make sure Postgres has pgvector enabled."
        ) from exc
    return len(rows)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Precompute pgvector embeddings for the recipe ingredient vocabulary."
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_RECIPE_EMBEDDING_MODEL,
        help="SentenceTransformer model used for recipe ingredient embeddings.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Embedding batch size.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build embeddings and report row count without writing to Postgres.",
    )
    args = parser.parse_args()

    init_db()
    rows = build_embedding_rows(
        model_name=args.model_name,
        batch_size=max(1, args.batch_size),
    )
    if args.dry_run:
        print(f"Built {len(rows)} recipe ingredient embedding row(s).")
        return 0

    upserted = upsert_embedding_rows(rows)
    print(f"Upserted {upserted} recipe ingredient embedding row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
