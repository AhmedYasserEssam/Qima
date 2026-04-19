# API Contracts — v1

This directory defines the **public, client-facing API contracts** for the Qima backend.
It is the single source of truth for:
- request and response schemas
- error handling structure
- versioning rules
- behavioral guarantees and constraints

Clients (Flutter) must rely **only** on what is defined here.
The backend may change internally (providers, models, data sources, logic), but **these contracts must remain stable within a version**.

---

## Contract Scope

All contracts in this directory follow a consistent structure:
- `endpoint` (path)
- `method`
- `request`
- `responses`

Each contract fully defines:
- valid inputs
- successful responses
- error responses

No behavior outside these definitions should be assumed by clients.

---

## Contracts Index

| File | Endpoint | Method |
|------|----------|--------|
| `chat_query.json` | `/v1/chat/query` | POST |
| `barcode_lookup.json` | `/v1/barcode/lookup` | POST |
| `nutrition_estimate.json` | `/v1/nutrition/estimate` | POST |
| `recipes_suggest.json` | `/v1/recipes/suggest` | POST |
| `recipes_discuss.json` | `/v1/recipes/discuss` | POST |
| `vision_identify.json` | `/v1/vision/identify` | POST |
| `error_response.json` | shared error schema | — |

---

## Versioning

All public endpoints are versioned via path:
- `/v1/...` — current stable version
- `/v2/...` — next version with breaking changes

### Breaking changes (require new version)
- removing fields
- adding required fields
- changing field meaning
- changing enum semantics
- changing response structure
- tightening validation in a way that breaks existing clients

### Non-breaking changes (allowed within version)
- adding optional fields
- extending enums (only if clients can safely ignore new values)
- improving descriptions or documentation

---

## Deprecation Policy

Rules:
- A new version (`/v2`) must be introduced **before** breaking `/v1`
- `/v1` and `/v2` must run **in parallel** during migration
- `/v1` must not be removed without a defined migration window

### Operational guarantees
- `/v1` remains supported until all known clients migrate
- Deprecation must be communicated clearly (release notes, API docs, app updates)
- Breaking existing clients is not allowed

If clients cannot upgrade immediately, **the backend must continue supporting the old version**.

---

## Stability Principle

The backend **owns normalization and abstraction**.

This means:
- providers may change
- datasets may change
- models may change

But:
- **public contract fields must remain stable**
- **clients must not depend on backend implementation details**

When a field is exposed publicly, it becomes part of the contract and must be treated as stable.

---

## Profile Resolution Rules

The backend is the **source of truth** for user profile data.

Resolution order:
1. Stored backend profile (default)
2. `profile_overrides` in the request (request-scoped only)
3. System defaults (if no profile exists)

Notes:
- `profile_overrides` apply only to the current request
- Overrides are **not persisted**
- Profile resolution details are internal metadata and are not returned in API responses

---

## Source Metadata Policy

Some endpoints include a `source` object describing where data originated.

Rules:
- Use **stable identifiers**, not raw file names or vendor strings
- Represent logical sources, not implementation details

### Important distinction

- `/vision/identify` exposes provider and model identity — vision output is **model-shaped** and results depend on model behavior
- `/chat/query` hides model identity — output is **fully normalized** and does not require model awareness

This difference is intentional and must remain consistent across versions.
Clients must not assume all endpoints expose the same level of source detail.

---

## Error Contract

All non-200 responses must follow:

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "retryable": true,
    "request_id": "...",
    "details": {}
  }
}
```

### HTTP status to error.code

| HTTP Status | error.code           |
|-------------|----------------------|
| 400         | BAD_REQUEST          |
| 401         | UNAUTHORIZED         |
| 403         | FORBIDDEN            |
| 404         | NOT_FOUND            |
| 422         | VALIDATION_ERROR     |
| 429         | RATE_LIMITED         |
| 500         | INTERNAL_ERROR       |
| 503         | UPSTREAM_UNAVAILABLE |

### Expected retryable values

| error.code           | retryable |
|----------------------|-----------|
| BAD_REQUEST          | false     |
| VALIDATION_ERROR     | false     |
| UNAUTHORIZED         | false     |
| FORBIDDEN            | false     |
| NOT_FOUND            | false     |
| RATE_LIMITED         | true      |
| UPSTREAM_UNAVAILABLE | true      |
| INTERNAL_ERROR       | true      |

### Notes
- `retryable` is advisory backend guidance, not a guarantee
- `INTERNAL_ERROR` retries must use backoff — do not retry immediately
- `error.details` structure is non-contractual unless separately documented in a specific endpoint contract
- `error.message` is human-readable only — clients must not parse or depend on its content
- Breaking changes to error semantics require a new API version