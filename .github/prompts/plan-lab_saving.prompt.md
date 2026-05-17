## Plan: Lab Report Save + Review Flow

Add a persisted lab report flow that keeps extraction and saving separate. The backend will first extract structured lab-report data for user review, then persist the confirmed payload only after the user presses **Confirm & Save** in Flutter. This adds backend schemas, SQLAlchemy models, `init_db` table creation, a persistence service, authenticated save/list/detail endpoints, Flutter confirm-save UI, and tests.

Extraction remains preview-only. Persistence happens only through the confirmed save endpoint. The saved report must be linked to the authenticated user through a foreign key. Flutter must not send `user_id`; the backend must derive it from the authenticated user. Lab report handling remains non-diagnostic and must not call `/v1/labs/interpret` in this task.

This follows the Qima backend-owned boundary: Flutter calls FastAPI only, while backend handles normalization, persistence, authentication, and safety boundaries. :contentReference[oaicite:0]{index=0} It also keeps lab-marker behavior separate from diagnosis/treatment advice. :contentReference[oaicite:1]{index=1}

---

## Steps

1. **Update backend schemas and extraction source enum**
   - Update `backend/app/schemas/v1/lab_report.py`.
   - Rename image `extraction_method` to `paddleocr` everywhere.
   - Add save request/response schemas.
   - Keep the extraction response intact where possible.
   - Allow `raw_text_preview` to be nullable in the save request, while keeping it required in the extraction response if currently required.
   - Add/confirm schema support for:
     - `sections_found`
     - `warnings`
     - `source.extraction_method`
     - `pages_processed`
     - `images_processed`
     - `tests`
     - reference interval bands

2. **Add SQLAlchemy models and DB table creation**
   - Add `backend/app/models/lab_report.py`.
   - Add two models:
     - `LabReport`
     - `LabReportTest`
   - Add relationships:
     - `User -> LabReport`
     - `LabReport -> LabReportTest`
   - `lab_reports` must include:
     - `id`
     - `user_id` foreign key to `users.id`
     - `input_type`
     - `report_type`
     - `sections_found`
     - `source_extraction_method`
     - `pages_processed`
     - `images_processed`
     - `warnings`
     - `raw_text_preview`
     - `extracted_at`
     - `confirmed_at`
     - `created_at`
     - `updated_at`
   - `lab_report_tests` must include:
     - `id`
     - `lab_report_id` foreign key to `lab_reports.id`
     - `section`
     - `test_name`
     - `canonical_test_key`
     - `result_value_numeric`
     - `result_value_text`
     - `unit`
     - `reference_interval_raw`
     - `reference_interval_type`
     - `reference_low`
     - `reference_high`
     - `reference_operator`
     - `reference_bands`
     - `status`
     - `matched_band`
     - `raw_text`
     - `confidence`
     - `created_at`
   - Use dialect-safe JSON fields:
     - PostgreSQL: JSONB
     - SQLite/test fallback: JSON
   - Extend `init_db` with `CREATE TABLE`, indexes, and cascade delete logic.
   - No Alembic.

   *Depends on step 1.*

3. **Implement `lab_report_persistence_service`**
   - Add `backend/app/services/lab_report_persistence_service.py`.
   - Validate the save payload.
   - Do **not** re-run PDF/image extraction.
   - Do **not** re-parse `raw_text`.
   - Persist only the already-extracted structured payload.
   - Recompute only `status` from `result_value + reference_interval` if existing parser helpers already support it safely.
   - For categorical intervals, use `match_categorical_band` where applicable.
   - Split `result_value` into:
     - `result_value_numeric` if numeric
     - `result_value_text` if non-numeric
   - Persist `lab_reports` and child `lab_report_tests` in one transaction.
   - Roll back cleanly on failure.
   - Do not leak raw DB errors to API responses.

   *Depends on step 2.*

4. **Add authenticated backend endpoints**
   - Add `backend/app/api/v1/endpoints/lab_reports.py`.
   - Add routes:
     - `POST /v1/labs/reports`
     - `GET /v1/labs/reports`
     - `GET /v1/labs/reports/{id}`
   - Use `get_current_user`.
   - Do not accept `user_id` from request body.
   - Set `user_id` from the authenticated backend user.
   - All read queries must filter by both:
     - report id
     - current user id
   - Return 404 if the report does not exist or does not belong to the current user.
   - Map service errors to `HTTPException`.
   - Do not expose raw DB errors.

   *Depends on step 3.*

5. **Update Flutter API client**
   - Update `mobile/lib/features/labs/data/lab_report_api_client.dart`.
   - Reuse the existing authenticated API client/Dio instance if available.
   - Ensure auth headers are included.
   - Add:
     - `saveExtractedReport(...)`
   - The method should send the extracted JSON to:

     ```text
     POST /v1/labs/reports
     ```

   - Do not send `user_id`.
   - Add `toJson()` to existing response models or create request models that serialize the extraction payload correctly.

   *Parallel with step 4 once schema shape is locked.*

6. **Update Flutter confirm-save UI**
   - Update `mobile/lib/features/labs/screens/lab_report_extract_test_screen.dart`.
   - After extraction succeeds:
     - Show extracted tests.
     - Show warnings.
     - Show source metadata.
     - Show **Confirm & Save** button.
   - Button behavior:
     - Hidden or disabled before extraction succeeds.
     - Disabled while saving.
     - Sends extracted payload to `POST /v1/labs/reports`.
     - Shows success message after save.
     - Shows backend error message on failure.
   - Do not add medical interpretation or recommendations.

   *Depends on step 5.*

7. **Add tests**
   - Backend tests in `backend/app/tests/test_lab_reports.py`.
   - Flutter widget tests in `mobile/test/lab_report_extract_test_screen_test.dart`.

   Backend tests should cover:
   - Creating a lab report creates one `lab_reports` row.
   - Creating a lab report creates child `lab_report_tests` rows.
   - Saved `lab_report.user_id` equals current authenticated user id.
   - Request body `user_id` is ignored or rejected.
   - Empty tests list returns validation error.
   - List endpoint returns only current user reports.
   - Detail endpoint denies reports owned by another user.
   - JSON/JSONB fields persist `warnings`, `sections_found`, and `reference_bands`.
   - Image extraction method is stored as `paddleocr`.

   Flutter tests should cover:
   - Confirm & Save button is disabled before extraction.
   - Extracted tests render after extraction.
   - Confirm & Save calls `/v1/labs/reports`.
   - Success message appears after save.
   - Backend error message appears on save failure.

   *Depends on steps 2–6.*

---

## Relevant Files

- `backend/app/schemas/v1/lab_report.py` — add save schemas and update `extraction_method` enum.
- `backend/app/services/lab_report_extraction_service.py` — rename image `extraction_method` to `paddleocr`.
- `backend/app/models/lab_report.py` — new SQLAlchemy models and relationships.
- `backend/app/models/user.py` — add relationship to lab reports.
- `backend/app/models/__init__.py` — export new models.
- `backend/app/db.py` — extend `init_db` with lab report tables, indexes, and cascade delete rules.
- `backend/app/services/lab_report_persistence_service.py` — new persistence logic.
- `backend/app/api/v1/endpoints/lab_reports.py` — new save/list/detail endpoints.
- `backend/app/api/v1/router.py` — include lab reports router.
- `backend/app/parsers/lab_report_parser.py` — reuse `classify_result` and `match_categorical_band` only for already-parsed values.
- `backend/app/tests/test_lab_reports.py` — new backend tests.
- `mobile/lib/features/labs/data/lab_report_api_client.dart` — add auth + save method.
- `mobile/lib/features/labs/models/lab_report_extract_response.dart` — add `toJson` + save response model.
- `mobile/lib/features/labs/screens/lab_report_extract_test_screen.dart` — confirm/save UI flow.
- `mobile/test/lab_report_extract_test_screen_test.dart` — widget tests for confirm/save.

---

## Verification

1. **Backend tests**
   - Run focused pytest for new lab report tests.
   - Confirm create/list/detail obey user scoping.
   - Confirm validation errors return expected 400/404/422 responses.
   - Confirm JSON/JSONB fields persist correctly.

2. **Manual backend test**
   - Extract a lab report through:

     ```text
     POST /v1/labs/extract-report
     ```

   - Copy the extracted payload.
   - Send it with a valid auth token to:

     ```text
     POST /v1/labs/reports
     ```

   - Confirm rows are created in:
     - `lab_reports`
     - `lab_report_tests`
   - Confirm `lab_reports.user_id` matches the authenticated user.

3. **Flutter test**
   - Run widget tests.
   - Manually test:

     ```text
     extract report -> review tests -> Confirm & Save -> success message
     ```

   - Confirm the button is disabled while saving.
   - Confirm no `user_id` is sent from Flutter.

---

## Decisions

- Use `init_db` with `CREATE TABLE` statements.
- Do not use Alembic for this task.
- Rename image `extraction_method` to `paddleocr` everywhere.
- Save/list/detail endpoints require authentication.
- Extraction does not save automatically.
- Save happens only after Flutter confirmation.
- `user_id` comes only from backend authentication.
- Use dialect-safe JSON:
  - PostgreSQL JSONB in production.
  - JSON fallback for SQLite/tests.
- Keep lab-report persistence separate from `/v1/labs/interpret`.
- Do not add medical recommendations in this task.

---

## Further Considerations

1. Allow `raw_text_preview` to be nullable in the save request, while keeping extraction response stricter if needed.
2. Add `DELETE /v1/labs/reports/{id}` later if the app needs report deletion.
3. Add history UI later using `GET /v1/labs/reports`.
4. Add interpretation later as a separate explicit flow, not as part of saving.