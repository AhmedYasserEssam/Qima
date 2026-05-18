# Qima

Qima is a Flutter + FastAPI nutrition assistant. The mobile app calls the
backend only; provider API keys and model integrations stay server-side.

Current user flows include:

- barcode lookup for packaged foods
- food image recognition and nutrition estimation
- inventory-based recipe suggestions with ingredient quantities
- grounded recipe discussion
- profile setup and authentication
- lab report scanning, saved lab marker history, and latest marker summaries
- lab-informed meal planning that uses supported below-range markers as food
  preferences, not diagnosis or supplement advice

For a command-first setup, see [quickstart.md](quickstart.md).

## Architecture

```text
Qima/
|-- backend/        FastAPI app, services, schemas, tests, DB setup
|-- mobile/         Flutter app for Android, web, and other Flutter targets
|-- contracts/      Versioned API contract examples/schemas
|-- data/           Local food and recipe datasets
|-- scrappers/      Carrefour scraping pipeline
|-- airflow/        Optional monthly Carrefour refresh orchestration
|-- Docs/           Architecture and decision documents
|-- groqApi.py      LLM integration helper used by plan/recipe flows
|-- docker-compose.yml
`-- quickstart.md
```

## Backend

The backend is a FastAPI API under `backend/app`.

Important endpoints include:

- `GET /v1/health`
- `POST /v1/auth/signup`
- `POST /v1/auth/login`
- `GET /v1/profile/me`
- `POST /v1/profile/update`
- `POST /v1/barcode/lookup`
- `POST /v1/vision/identify`
- `POST /v1/nutrition/estimate`
- `POST /v1/recipes/suggest`
- `POST /v1/recipes/discuss`
- `POST /v1/labs/extract-report`
- `POST /v1/labs/reports`
- `POST /v1/plans/generate`

Backend environment is configured through `backend/.env`. Start from
`backend/.env.example`.

Required for normal local development:

- `DATABASE_URL`
- `JWT_SECRET`

Required for provider-backed features:

- `GEMINI_API_KEY` for vision identification
- `GROQ_API_KEY` or `OPENAI_API_KEY` for LLM-backed recipe/plan flows,
  depending on the configured provider

The backend can still return local fallback responses for some flows when an LLM
provider is not configured, but provider-backed endpoints will be limited.

## Mobile

The Flutter app lives in `mobile/`.

The app reads the backend URL from the compile-time define
`QIMA_API_BASE_URL`. Use an explicit value whenever running against a non-default
backend port or a physical device.

Examples:

```powershell
flutter run -d chrome --dart-define=QIMA_API_BASE_URL=http://127.0.0.1:8001
flutter run -d emulator-5554 --dart-define=QIMA_API_BASE_URL=http://10.0.2.2:8001
flutter run -d R5CY82RV2RJ --dart-define=QIMA_API_BASE_URL=http://127.0.0.1:8001
```

For a physical Android phone over USB, use `adb reverse` first:

```powershell
adb -s <device-id> reverse tcp:8001 tcp:8001
```

This lets the phone call `http://127.0.0.1:8001` and have it forward to the
laptop backend.

## Local Data

The backend uses local food and recipe data where available:

- `data/Food/nutrition.xlsx`
- `data/Food/Egyptian Food.csv`
- FoodData Central JSON sources under `data/Food/`
- `data/Recipes/13k-recipes.csv`

Large/generated datasets are ignored by default unless already tracked.

## Database

The included Docker Compose file starts Postgres with pgvector:

```powershell
docker compose up -d db
```

Default local connection from `backend/.env.example`:

```text
postgresql://qima_user:qima_password@127.0.0.1:15432/qima
```

`backend/app/db.py` initializes the app tables on startup.

## Carrefour Pipeline

Carrefour packaged-food data is managed through a DB-first scraper flow.

- scraper: `scrappers/scrape_carrefour_food.py`
- table: `carrefour_barcode_products`
- upsert strategy: `ON CONFLICT (barcode) DO UPDATE`

Optional Airflow orchestration lives under `airflow/`.

## Validation

Backend:

```powershell
$env:PYTHONPATH = "backend"
pytest backend/app/tests
```

Mobile:

```powershell
cd mobile
flutter analyze
flutter test
```

## Design Rules

- Flutter calls FastAPI only.
- Provider keys and provider SDK/API calls stay in the backend.
- API response shapes should remain contract-first and versioned.
- Recipe flows should stay retrieval-grounded when possible.
- Lab-marker-informed guidance must remain food-oriented, supported-marker
  based, and non-diagnostic.
- Abnormal lab markers are displayed and may inform food focus where supported;
  they do not automatically mutate safety screening answers.

## More Docs

- [quickstart.md](quickstart.md)
- `backend/README.md`
- `backend/AUTH_PROFILE_GUIDE.md`
- `mobile/README.md`
- `mobile/ANDROID_TESTING.md`
- `Docs/Architecture_Updated_260422_v14.docx`
- `Docs/Decision_Log_Updated_260422_v14.docx`
