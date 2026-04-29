# Qima Backend

FastAPI backend for the Qima v1 API.

## Run locally

From the repository root:

```bash
uvicorn app.main:app --reload --app-dir backend
```

## Environment

Required:

- `DATABASE_URL`

Driver behavior:

- prefers `psycopg` when installed
- falls back to `psycopg2` automatically

## API docs

Open:

http://127.0.0.1:8000/docs

## Carrefour Table

The backend uses a dedicated table for Carrefour scraped data:

- table: `carrefour_barcode_products`
- schema: mirrors CSV column names from `data/Food/carrefour_barcode_products.csv`
- nutrition/price numeric columns use `DOUBLE PRECISION`

Lookup order for barcode flow:

1. `carrefour_barcode_products` table
2. Open Food Facts cache (`barcode_cache`)
3. Open Food Facts API fallback

## Seed Carrefour Data

From `backend` directory:

```powershell
py -3 scripts\seed_carrefour_barcode_products.py --truncate
```

Custom CSV path:

```powershell
py -3 scripts\seed_carrefour_barcode_products.py --csv "C:\Work\Qima_project\data\Food\carrefour_barcode_products.csv" --truncate
```

## Direct DB Scrape (No CSV Intermediate)

Carrefour scraper writes directly to DB by default:

```powershell
py -3 ..\scrappers\scrape_carrefour_food.py --sink db
```

Optional explicit DB URL:

```powershell
py -3 ..\scrappers\scrape_carrefour_food.py --sink db --database-url "postgresql://qima_user:qima_password@localhost:15432/qima"
```

## Run tests

### Windows PowerShell

```powershell
$env:PYTHONPATH = "backend"
pytest backend/app/tests
```

### macOS / Linux

```bash
PYTHONPATH=backend pytest backend/app/tests
```
