from __future__ import annotations

import os
from datetime import timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.dates import days_ago


REPO_ROOT = os.getenv("QIMA_REPO_ROOT", "/opt/airflow/qima_project")
BACKEND_DIR = f"{REPO_ROOT}/backend"
SCRAPER_PATH = f"{REPO_ROOT}/scrappers/scrape_carrefour_food.py"


with DAG(
    dag_id="carrefour_monthly_scrape",
    description="Monthly Carrefour scrape into Postgres table with upsert deduplication by barcode.",
    start_date=days_ago(1),
    schedule="0 3 1 * *",  # 03:00 on day 1 of every month
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "data-eng",
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["carrefour", "scraping", "monthly"],
) as dag:
    scrape_and_upsert = BashOperator(
        task_id="scrape_carrefour_to_db",
        cwd=BACKEND_DIR,
        bash_command=(
            "python "
            f"{SCRAPER_PATH} "
            "--sink db "
            "--page-size 100 "
            "--sort-by relevance "
            "--delay 1.5 "
            "--jitter 0.5 "
            "--retries 3 "
            "--detail-retries 2 "
            "--detail-concurrency 6"
        ),
        env={
            **os.environ,
            # Uses DATABASE_URL from scheduler/worker env.
            # Scraper writes with ON CONFLICT (barcode) DO UPDATE to prevent duplicates.
            "PYTHONPATH": f"{REPO_ROOT}/backend",
        },
    )

    scrape_and_upsert
