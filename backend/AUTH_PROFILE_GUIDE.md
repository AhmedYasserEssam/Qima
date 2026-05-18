# Qima Auth + Profile Guide

## Update (No Email Verification)

Email verification has been removed from the current app flow.

- Signup creates the user immediately.
- Login works directly after signup.
- No `/v1/auth/verify-email` endpoint.
- No `/v1/auth/resend-verification` endpoint.
- SMTP setup is optional and not required for auth now.

This guide explains:

1. what changed in the backend
2. how to run the feature locally
3. how to test with real input end-to-end

## What Was Implemented

The backend now supports immediate-login user accounts and editable nutrition profiles.

### New auth endpoints

- `POST /v1/auth/signup`
- `POST /v1/auth/login`

### Profile endpoints (authenticated users)

- `POST /v1/profile/update`
- `GET /v1/profile/me`

### Database entities added

- `users`
- `nutrition_profiles`

### Important behavior guarantees

- Users can log in immediately after signup.
- First-time users must create a profile before `GET /v1/profile/me` will succeed.
- Profile is one-to-one per user and updates replace existing values.

## Key Files Added/Updated

- `backend/app/api/v1/endpoints/auth.py`
- `backend/app/api/v1/endpoints/profile.py`
- `backend/app/api/deps/auth.py`
- `backend/app/services/auth_service.py`
- `backend/app/services/profile_service.py`
- `backend/app/services/email_service.py`
- `backend/app/core/security.py`
- `backend/app/core/config.py`
- `backend/app/models/`
- `backend/app/schemas/v1/auth.py`
- `backend/app/schemas/v1/profile.py`
- `backend/app/db.py`
- `backend/app/tests/test_auth_profile.py`

## Prerequisites

- Python environment created and dependencies installed.
- PostgreSQL running (recommended via repository `docker-compose.yml`).
- `backend/.env` created from `backend/.env.example`.

## Environment Configuration

Copy env file:

```powershell
Copy-Item ".\backend\.env.example" ".\backend\.env"
```

### Required auth settings

Set these in `backend/.env`:

- `JWT_SECRET` (strong secret)
- `JWT_ACCESS_TOKEN_EXP_MINUTES`

Legacy verification-related env vars may still exist in `backend/.env.example`, but they are not required for the current signup/login flow.

## Start the Services

### 1) Start PostgreSQL (and optional pgAdmin)

From repo root:

```powershell
docker compose up -d db pgadmin
```

### 2) Install dependencies

```powershell
py -m pip install -r backend/requirements-dev.txt
```

### 3) Start FastAPI

From repo root:

```powershell
uvicorn app.main:app --reload --app-dir backend
```

API docs: `http://127.0.0.1:8000/docs`

## Real End-to-End Test (PowerShell)

### Variables

```powershell
$base = "http://127.0.0.1:8000"
$email = "your-email@example.com"
$password = "StrongPass123!"
```

### 1) Signup

```powershell
Invoke-RestMethod -Method POST -Uri "$base/v1/auth/signup" -ContentType "application/json" -Body (@{
  email = $email
  password = $password
} | ConvertTo-Json)
```

Expected: `201` signup success message.

### 2) Login

```powershell
$login = Invoke-RestMethod -Method POST -Uri "$base/v1/auth/login" -ContentType "application/json" -Body (@{
  email = $email
  password = $password
} | ConvertTo-Json)

$accessToken = $login.access_token
$headers = @{ Authorization = "Bearer $accessToken" }
```

Expected: `200` with `access_token`.

### 3) Create/update profile with real input

```powershell
Invoke-RestMethod -Method POST -Uri "$base/v1/profile/update" -Headers $headers -ContentType "application/json" -Body (@{
  age = 30
  sex = "male"
  height_cm = 178.5
  weight_kg = 82.3
  activity_level = "moderately_active"
  goal = "reduce_sugar"
  allergens = @("Milk", "milk", "peanut")
  dietary_restrictions = @("halal", " low_sodium ")
  safety_screening = @{
    pregnant = $false
    breastfeeding = $false
    eating_disorder_history = $false
    under_18 = $false
    medical_condition_affects_diet = $false
    abnormal_labs_or_health_concerns = $false
    none_of_above = $true
  }
  agreement_accepted = $true
} | ConvertTo-Json)
```

Expected:

- `200`
- deduplicated normalized lists (for example `["milk","peanut"]`).

### 4) Read profile

```powershell
Invoke-RestMethod -Method GET -Uri "$base/v1/profile/me" -Headers $headers
```

Expected: `200` with your stored profile.

If you call this endpoint before creating a profile, expect `404` with guidance to complete onboarding via `POST /v1/profile/update` first.

## Validation Rules Enforced

- Email must be valid.
- Password length is enforced.
- `age`, `height_cm`, `weight_kg` must be realistic positive values.
- `allergens` and `dietary_restrictions` are trimmed, lowercased, deduplicated.
- `sex` allowed values: `male`, `female`.
- Safety screening is required: either select at least one safety option or `none_of_above`.
- `none_of_above` cannot be combined with any safety option.
- The Qima AI Nutrition Disclaimer & User Agreement must be accepted before profile creation/update.

## Run Automated Tests

From repo root:

```powershell
$env:PYTHONPATH = "backend"
py -m pytest backend/app/tests
```

Focus auth/profile tests only:

```powershell
$env:PYTHONPATH = "backend"
py -m pytest backend/app/tests/test_auth_profile.py -q
```

## Example JSON Payloads

Examples below are for API contract illustration.

### Signup request

```json
{
  "email": "user@example.com",
  "password": "StrongPass123!"
}
```

### Profile update request

```json
{
  "age": 30,
  "sex": "male",
  "height_cm": 178.5,
  "weight_kg": 82.3,
  "activity_level": "moderately_active",
  "goal": "reduce_sugar",
  "allergens": ["Milk", "milk", "peanut"],
  "dietary_restrictions": ["halal", " low_sodium "],
  "safety_screening": {
    "pregnant": false,
    "breastfeeding": false,
    "eating_disorder_history": false,
    "under_18": false,
    "medical_condition_affects_diet": false,
    "abnormal_labs_or_health_concerns": false,
    "none_of_above": true
  },
  "agreement_accepted": true
}
```

### Login response

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

## Out of Scope (Intentional)

- Password reset endpoints are not part of this feature and should be tracked as a follow-up issue:
  - `POST /v1/auth/forgot-password`
  - `POST /v1/auth/reset-password`
