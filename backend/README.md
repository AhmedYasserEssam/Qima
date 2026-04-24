# Qima Backend

FastAPI backend for the Qima v1 API.

## Run locally

From the repository root:

```bash
uvicorn app.main:app --reload --app-dir backend
```

## API docs

Open:

http://127.0.0.1:8000/docs

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