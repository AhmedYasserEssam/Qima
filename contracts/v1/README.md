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

### Important

These files are **full API contracts**, not raw HTTP body schemas.

For backend validation:
- validate request bodies against the relevant `$defs` schema
- example: `#/$defs/PlansGenerateRequest`

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
| `prices_estimate.json` | `/v1/prices/estimate` | POST |
| `labs_interpret.json` | `/v1/labs/interpret` | POST |
| `profile_update.json` | `/v1/profile/update` | POST |
| `plans_generate.json` | `/v1/plans/generate` | POST |
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
- extending enums (if safely ignorable)
- improving documentation

---

## Deprecation Policy

Rules:
- A new version (`/v2`) must be introduced **before** breaking `/v1`
- `/v1` and `/v2` must run **in parallel**
- `/v1` must not be removed without a defined migration window

### Operational guarantees
- `/v1` remains supported until all clients migrate
- Breaking existing clients is not allowed
- Backend must continue supporting old versions if clients cannot upgrade

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

---

## Profile Handling Rules

The backend is the **source of truth** for user profile data.

### `/v1/plans/generate`

Exactly one of the following must be provided:
- `profile_id` (saved profile)
- `profile` (inline profile)

Rules:
- both must NOT be sent together
- inline profile is request-scoped only
- stored profile is resolved server-side

---

## Profile Update Behavior

`/v1/profile/update` is an **upsert endpoint**.

Behavior:
- missing `profile_id` → create new profile
- invalid/stale `profile_id` → create new profile
- provided fields → **replace existing values**, not merge

Array behavior:
- deduplicated
- treated as **replacement**, not append

---

## Price Estimation Policy

`/v1/prices/estimate` returns **estimated prices only**.

Rules:
- not real-time prices
- may vary by:
  - geography
  - store
  - brand
- must include:
  - estimate quality
  - currency
  - source metadata

---

## Lab Interpretation Safety Policy

`/v1/labs/interpret` is **strictly constrained**.

Allowed:
- food-based guidance only

Not allowed:
- diagnosis
- treatment
- supplements prescription

Rules:
- whitelist-based markers
- must rely on provided reference ranges
- must return safety flags

---

## Meal Plan Generation Rules

`/v1/plans/generate` is:

- retrieval-first
- bounded
- non-clinical

### Budget behavior

- `budget.max_total_cost` → **hard constraint**
- `dietary_filters: ["budget_friendly"]` → **soft ranking preference**

### Scoring Convention

All scores follow:

- `1.0 = best`
- `0.0 = worst`

Includes:
- `target_fit`
- `cost_fit`
- `ingredient_match`
- `safety_score` (higher = safer)

---

## Source Metadata Policy

Some endpoints include a `source` object.

Rules:
- use stable identifiers
- do not expose raw implementation details

### Important distinction

- `/vision/identify` exposes model/provider identity
- `/chat/query` hides model details

This difference is intentional.

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
## HTTP Status Mapping

| HTTP Status | error.code           |
|------------|----------------------|
| 400        | BAD_REQUEST          |
| 401        | UNAUTHORIZED         |
| 403        | FORBIDDEN            |
| 404        | NOT_FOUND            |
| 422        | VALIDATION_ERROR     |
| 429        | RATE_LIMITED         |
| 500        | INTERNAL_ERROR       |
| 503        | UPSTREAM_UNAVAILABLE |

---

## Retryable Behavior

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

---

## Notes

- `retryable` is advisory only  
- `error.message` is human-readable and must not be parsed  
- `error.details` is not guaranteed unless explicitly documented  
- retries for `INTERNAL_ERROR` must use backoff  