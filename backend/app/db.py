import os
from importlib.util import find_spec
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
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

RECIPE_EMBEDDING_DIMENSION = 384


def _sql_json_type() -> str:
    return "JSONB" if engine.dialect.name == "postgresql" else "JSON"


def _sql_id_type() -> str:
    return "BIGSERIAL" if engine.dialect.name == "postgresql" else "INTEGER"


def _sql_json_default(value: str) -> str:
    if engine.dialect.name == "postgresql":
        return f"'{value}'::jsonb"
    return f"'{value}'"


def _try_init_pgvector_extension() -> bool:
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        return True
    except SQLAlchemyError:
        return False


def _create_recipe_embedding_schema(conn) -> None:
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS recipe_ingredient_embeddings (
                canonical_name TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                frequency INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                embedding vector({RECIPE_EMBEDDING_DIMENSION}) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    )


def _create_lab_report_schema(conn) -> None:
    id_type = _sql_id_type()
    json_type = _sql_json_type()
    empty_array = _sql_json_default("[]")
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS lab_reports (
                id {id_type} PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                input_type TEXT NOT NULL,
                report_type TEXT NOT NULL,
                sections_found {json_type} NOT NULL DEFAULT {empty_array},
                source_extraction_method TEXT NOT NULL,
                pages_processed INTEGER,
                images_processed INTEGER,
                warnings {json_type} NOT NULL DEFAULT {empty_array},
                raw_text_preview TEXT,
                extracted_at TIMESTAMP NOT NULL,
                confirmed_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            );
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_lab_reports_user_id
            ON lab_reports(user_id);
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_lab_reports_user_created_at
            ON lab_reports(user_id, created_at);
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS lab_report_tests (
                id {id_type} PRIMARY KEY,
                lab_report_id BIGINT NOT NULL REFERENCES lab_reports(id) ON DELETE CASCADE,
                section TEXT NOT NULL,
                test_name TEXT NOT NULL,
                canonical_test_key TEXT NOT NULL,
                result_value_numeric DOUBLE PRECISION,
                result_value_text TEXT,
                unit TEXT,
                reference_interval_raw TEXT,
                reference_interval_type TEXT NOT NULL,
                reference_low DOUBLE PRECISION,
                reference_high DOUBLE PRECISION,
                reference_operator TEXT,
                reference_bands {json_type} NOT NULL DEFAULT {empty_array},
                status TEXT NOT NULL,
                matched_band TEXT,
                raw_text TEXT NOT NULL,
                confidence DOUBLE PRECISION,
                created_at TIMESTAMP NOT NULL
            );
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_lab_report_tests_lab_report_id
            ON lab_report_tests(lab_report_id);
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_lab_report_tests_canonical_test_key
            ON lab_report_tests(canonical_test_key);
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_recipe_ingredient_embeddings_model_name
            ON recipe_ingredient_embeddings(model_name);
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_recipe_ingredient_embeddings_hnsw
            ON recipe_ingredient_embeddings
            USING hnsw (embedding vector_cosine_ops);
            """
        )
    )


def _backfill_vitamin_d_categorical_status(conn) -> None:
    conn.execute(
        text(
            """
            UPDATE lab_report_tests
            SET status = CASE lower(matched_band)
                WHEN 'deficiency' THEN 'below_range'
                WHEN 'insufficiency' THEN 'below_range'
                WHEN 'sufficiency' THEN 'within_range'
                WHEN 'hypervitaminosis' THEN 'above_range'
                ELSE status
            END
            WHERE canonical_test_key = 'vitamin_d_25oh_serum'
              AND reference_interval_type = 'categorical_bands'
              AND lower(COALESCE(matched_band, '')) IN (
                  'deficiency',
                  'insufficiency',
                  'sufficiency',
                  'hypervitaminosis'
              )
              AND status <> CASE lower(matched_band)
                WHEN 'deficiency' THEN 'below_range'
                WHEN 'insufficiency' THEN 'below_range'
                WHEN 'sufficiency' THEN 'within_range'
                WHEN 'hypervitaminosis' THEN 'above_range'
                ELSE status
              END;
            """
        )
    )


def init_db() -> None:
    pgvector_enabled = _try_init_pgvector_extension()
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
                    package_size_quantity DOUBLE PRECISION,
                    package_size_unit TEXT,
                    package_size_raw TEXT,
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
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS allrecipes_recipes (
                    source_url TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    recipe_id TEXT,
                    stable_slug TEXT,
                    title TEXT NOT NULL,
                    cuisine TEXT,
                    category TEXT,
                    meal_type TEXT,
                    author_name TEXT,
                    servings DOUBLE PRECISION,
                    prep_minutes INTEGER,
                    cook_minutes INTEGER,
                    total_minutes INTEGER,
                    calories_kcal DOUBLE PRECISION,
                    protein_g DOUBLE PRECISION,
                    carbohydrates_g DOUBLE PRECISION,
                    fat_g DOUBLE PRECISION,
                    fiber_g DOUBLE PRECISION,
                    sugar_g DOUBLE PRECISION,
                    sodium_mg DOUBLE PRECISION,
                    rating DOUBLE PRECISION,
                    review_count INTEGER,
                    date_published TEXT,
                    date_modified TEXT,
                    ingredients JSONB NOT NULL DEFAULT '[]'::jsonb,
                    directions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    cooking_methods JSONB NOT NULL DEFAULT '[]'::jsonb,
                    equipment JSONB NOT NULL DEFAULT '[]'::jsonb,
                    nutrition_facts_raw JSONB,
                    nutrition_quality JSONB NOT NULL DEFAULT '{}'::jsonb,
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    dietary_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
                    allergen_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    possible_allergen_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    packaged_ingredient_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
                    allergen_basis JSONB NOT NULL DEFAULT '{}'::jsonb,
                    allergen_confidence JSONB NOT NULL DEFAULT '{}'::jsonb,
                    difficulty TEXT,
                    data_quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    completeness_score DOUBLE PRECISION,
                    normalization_quality_score DOUBLE PRECISION,
                    recipe_quality_score DOUBLE PRECISION,
                    attribution JSONB
                );
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS directions_json JSONB NOT NULL DEFAULT '[]'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS cooking_methods JSONB NOT NULL DEFAULT '[]'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS equipment JSONB NOT NULL DEFAULT '[]'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS nutrition_quality JSONB NOT NULL DEFAULT '{}'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS possible_allergen_flags JSONB NOT NULL DEFAULT '[]'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS packaged_ingredient_warnings JSONB NOT NULL DEFAULT '[]'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS allergen_basis JSONB NOT NULL DEFAULT '{}'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS allergen_confidence JSONB NOT NULL DEFAULT '{}'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS difficulty TEXT;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS data_quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS recipe_quality_score DOUBLE PRECISION;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS completeness_score DOUBLE PRECISION;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE allrecipes_recipes
                ADD COLUMN IF NOT EXISTS normalization_quality_score DOUBLE PRECISION;
                """
            )
        )
        if pgvector_enabled:
            _create_recipe_embedding_schema(conn)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_email_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    last_login_at TIMESTAMP NULL
                );
                """
            )
        )
        _create_lab_report_schema(conn)
        _backfill_vitamin_d_categorical_status(conn)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    source_method TEXT NOT NULL,
                    source_ref TEXT,
                    source_product_id TEXT,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventory_items_user_id
                ON inventory_items(user_id);
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_items_user_normalized_name
                ON inventory_items(user_id, normalized_name);
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS name TEXT;
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE users
                SET name = split_part(email, '@', 1)
                WHERE name IS NULL OR btrim(name) = '';
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE users
                ALTER COLUMN name SET NOT NULL;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS email_verification_tokens (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP NULL,
                    invalidated_at TIMESTAMP NULL,
                    created_at TIMESTAMP NOT NULL
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_user_id
                ON email_verification_tokens(user_id);
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_expires_at
                ON email_verification_tokens(expires_at);
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_email_verification_tokens_active_per_user
                ON email_verification_tokens(user_id)
                WHERE used_at IS NULL AND invalidated_at IS NULL;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS nutrition_profiles (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    age INTEGER NOT NULL,
                    sex TEXT NOT NULL,
                    height_cm DOUBLE PRECISION NOT NULL,
                    weight_kg DOUBLE PRECISION NOT NULL,
                    activity_level TEXT NOT NULL,
                    nutrition_goal TEXT NOT NULL,
                    allergens JSONB NOT NULL DEFAULT '[]'::jsonb,
                    dietary_restrictions JSONB NOT NULL DEFAULT '[]'::jsonb,
                    safety_screening JSONB NOT NULL DEFAULT '{"pregnant": false, "breastfeeding": false, "eating_disorder_history": false, "under_18": false, "medical_condition_affects_diet": false, "abnormal_labs_or_health_concerns": false, "none_of_above": true}'::jsonb,
                    agreement_accepted BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE carrefour_barcode_products
                ADD COLUMN IF NOT EXISTS package_size_quantity DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS package_size_unit TEXT,
                ADD COLUMN IF NOT EXISTS package_size_raw TEXT;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE nutrition_profiles
                DROP COLUMN IF EXISTS budget_limit_egp;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE nutrition_profiles
                ADD COLUMN IF NOT EXISTS safety_screening JSONB NOT NULL DEFAULT '{"pregnant": false, "breastfeeding": false, "eating_disorder_history": false, "under_18": false, "medical_condition_affects_diet": false, "abnormal_labs_or_health_concerns": false, "none_of_above": true}'::jsonb;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE nutrition_profiles
                ADD COLUMN IF NOT EXISTS agreement_accepted BOOLEAN NOT NULL DEFAULT FALSE;
                """
            )
        )
