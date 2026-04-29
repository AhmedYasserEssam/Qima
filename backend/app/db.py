import os
from importlib.util import find_spec
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

def _postgres_driver_prefix() -> str:
    if find_spec("psycopg") is not None:
        return "postgresql+psycopg://"
    if find_spec("psycopg2") is not None:
        return "postgresql+psycopg2://"
    raise RuntimeError(
        "No PostgreSQL DBAPI found. Install `psycopg` or `psycopg2-binary`."
    )


if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", _postgres_driver_prefix(), 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", _postgres_driver_prefix(), 1)
elif DATABASE_URL.startswith("postgresql+psycopg://") and find_spec("psycopg") is None:
    if find_spec("psycopg2") is not None:
        DATABASE_URL = DATABASE_URL.replace(
            "postgresql+psycopg://", "postgresql+psycopg2://", 1
        )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS barcode_cache (
                    barcode TEXT PRIMARY KEY,
                    payload JSONB NOT NULL,
                    status TEXT NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL
                );
                """
            )
        )
        # Ensure legacy payload-style table is replaced with the CSV-shaped schema.
        conn.execute(
            text(
                """
                DO $$
                DECLARE
                    has_payload_column BOOLEAN;
                BEGIN
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'carrefour_barcode_products'
                          AND column_name = 'payload'
                    ) INTO has_payload_column;

                    IF has_payload_column THEN
                        DROP TABLE carrefour_barcode_products;
                    END IF;
                END
                $$;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS carrefour_barcode_products (
                    barcode TEXT PRIMARY KEY,
                    product_id TEXT,
                    name TEXT,
                    brand TEXT,
                    nutrition_basis TEXT,
                    serving_size TEXT,
                    energy_kcal DOUBLE PRECISION,
                    protein_g DOUBLE PRECISION,
                    carbohydrates_g DOUBLE PRECISION,
                    fat_g DOUBLE PRECISION,
                    sugars_g DOUBLE PRECISION,
                    fiber_g DOUBLE PRECISION,
                    sodium_mg DOUBLE PRECISION,
                    salt_g DOUBLE PRECISION,
                    ingredients TEXT,
                    allergens TEXT,
                    source_provider TEXT,
                    source_provider_product_id TEXT,
                    source_fetched_at TEXT,
                    data_quality_completeness TEXT,
                    price TEXT,
                    category_level_1 TEXT,
                    category_level_2 TEXT,
                    category_level_3 TEXT,
                    category_level_4 TEXT
                );
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'carrefour_barcode_products'
                          AND column_name = 'energy_kcal'
                          AND data_type <> 'double precision'
                    ) THEN
                        ALTER TABLE carrefour_barcode_products
                            ALTER COLUMN energy_kcal TYPE DOUBLE PRECISION
                            USING CASE
                                WHEN energy_kcal IS NULL OR trim(energy_kcal::text) = '' THEN NULL
                                WHEN trim(energy_kcal::text) ~ '^[-+]?[0-9]*\\.?[0-9]+$' THEN trim(energy_kcal::text)::DOUBLE PRECISION
                                ELSE NULL
                            END,
                            ALTER COLUMN protein_g TYPE DOUBLE PRECISION
                            USING CASE
                                WHEN protein_g IS NULL OR trim(protein_g::text) = '' THEN NULL
                                WHEN trim(protein_g::text) ~ '^[-+]?[0-9]*\\.?[0-9]+$' THEN trim(protein_g::text)::DOUBLE PRECISION
                                ELSE NULL
                            END,
                            ALTER COLUMN carbohydrates_g TYPE DOUBLE PRECISION
                            USING CASE
                                WHEN carbohydrates_g IS NULL OR trim(carbohydrates_g::text) = '' THEN NULL
                                WHEN trim(carbohydrates_g::text) ~ '^[-+]?[0-9]*\\.?[0-9]+$' THEN trim(carbohydrates_g::text)::DOUBLE PRECISION
                                ELSE NULL
                            END,
                            ALTER COLUMN fat_g TYPE DOUBLE PRECISION
                            USING CASE
                                WHEN fat_g IS NULL OR trim(fat_g::text) = '' THEN NULL
                                WHEN trim(fat_g::text) ~ '^[-+]?[0-9]*\\.?[0-9]+$' THEN trim(fat_g::text)::DOUBLE PRECISION
                                ELSE NULL
                            END,
                            ALTER COLUMN sugars_g TYPE DOUBLE PRECISION
                            USING CASE
                                WHEN sugars_g IS NULL OR trim(sugars_g::text) = '' THEN NULL
                                WHEN trim(sugars_g::text) ~ '^[-+]?[0-9]*\\.?[0-9]+$' THEN trim(sugars_g::text)::DOUBLE PRECISION
                                ELSE NULL
                            END,
                            ALTER COLUMN fiber_g TYPE DOUBLE PRECISION
                            USING CASE
                                WHEN fiber_g IS NULL OR trim(fiber_g::text) = '' THEN NULL
                                WHEN trim(fiber_g::text) ~ '^[-+]?[0-9]*\\.?[0-9]+$' THEN trim(fiber_g::text)::DOUBLE PRECISION
                                ELSE NULL
                            END,
                            ALTER COLUMN sodium_mg TYPE DOUBLE PRECISION
                            USING CASE
                                WHEN sodium_mg IS NULL OR trim(sodium_mg::text) = '' THEN NULL
                                WHEN trim(sodium_mg::text) ~ '^[-+]?[0-9]*\\.?[0-9]+$' THEN trim(sodium_mg::text)::DOUBLE PRECISION
                                ELSE NULL
                            END,
                            ALTER COLUMN salt_g TYPE DOUBLE PRECISION
                            USING CASE
                                WHEN salt_g IS NULL OR trim(salt_g::text) = '' THEN NULL
                                WHEN trim(salt_g::text) ~ '^[-+]?[0-9]*\\.?[0-9]+$' THEN trim(salt_g::text)::DOUBLE PRECISION
                                ELSE NULL
                            END;
                    END IF;
                END
                $$;
                """
            )
        )
