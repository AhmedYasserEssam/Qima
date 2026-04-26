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
| `shared_price_context.json` | shared price schemas | — |
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

## Stability Principle

The backend **owns normalization, orchestration, and abstraction**.

This means:
- providers may change
- datasets may change
- models may change
- pricing sources may change

But:
- **public contract fields must remain stable**
- **clients must not depend on backend implementation details**

---

## Recipe Suggestion Rules

`/v1/recipes/suggest` is:

- retrieval-first (no free-form generation)
- ranked by backend logic
- optionally price-aware

### Input Model

- `user_preferences` replaces `dietary_filters`
- `excluded_ingredients` are **hard constraints**
- `budget` is optional
- `price_preferences` controls price-aware ranking

### Ranking Behavior

- retrieval match is primary signal
- price is a **secondary ranking signal**
- backend may ignore price when:
  - coverage is low
  - confidence is insufficient

### Output Model

Each recipe candidate may include:
- `estimated_cost`
- `price_rank`
- `price_explanation`
- `applied_filters` (final constraints used)

---

## Recipe Discussion Rules

`/v1/recipes/discuss` is:

- strictly grounded in recipe context
- optionally enriched with price context

### Constraints

- must include `recipe_id` OR `candidate_context`
- must include at least one `grounded_reference`
- must NOT hallucinate missing recipe facts

### Price-Aware Behavior

If cost is discussed:
- must use `price_context` or existing `estimated_cost`
- must return:
  - `price_references`
  - `suggested_substitutions` (if applicable)
  - `updated_estimated_cost` (if recomputed)

If price cannot be computed:
- must explicitly say so
- must not estimate blindly

---

## Chat Query Rules

`/v1/chat/query` is:

- general-purpose
- multi-context aware
- optionally price-aware

### Context Model

Supports:
- `food_context`
- `active_context_type`

### Price-Aware Behavior

If the user asks about:
- cost
- savings
- budget

Then:
- must use structured price context
- must return `price_references`
- must NOT infer price without data

If price context is missing:
- set `safety_flags.price_context_missing = true`

### Output Additions

May include:
- `recommended_recipe_ids`
- `cost_saving_actions`

---

## Price Estimation Policy

`/v1/prices/estimate` returns **estimated prices only**.

Rules:
- not real-time
- may vary by geography, store, brand
- must include:
  - `coverage`
  - `confidence`
  - `assumptions`
  - `warnings`
  - `source`

### Cost Types

The system distinguishes:

- **usage cost** → cost of ingredients used
- **purchase cost** → cost to buy packages

Both may be present.

---

## Budget Rules

- `budget.max_total_cost` → **hard constraint**
- `user_preferences: ["budget_friendly"]` → **soft preference**

---

## Profile Overrides

`profile_overrides` allows temporary preferences:

- `dietary_preferences`
- `user_preferences`
- `allergens`

These do NOT modify stored profile data.

---

## Source Metadata Policy

Sources must be explicit and structured.

Examples:
- `recipe_corpus`
- `nutrition_dataset`
- `price_context`
- `price_dataset`

Rules:
- no hidden providers
- no implicit sources

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