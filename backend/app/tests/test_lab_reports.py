from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models.lab_report import LabReport, LabReportTest
from app.models.user import User


client = TestClient(app)


def _email() -> str:
    return f"lab-report-{uuid4().hex[:10]}@example.com"


def _auth_headers(email: str | None = None) -> tuple[dict[str, str], int, str]:
    user_email = email or _email()
    signup = client.post(
        "/v1/auth/signup",
        json={
            "email": user_email,
            "password": "StrongPass123!",
            "name": "Lab Report User",
        },
    )
    assert signup.status_code == 201
    login = client.post(
        "/v1/auth/login",
        json={"email": user_email, "password": "StrongPass123!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, signup.json()["user"]["id"], user_email


def _cleanup_user(email: str) -> None:
    init_db()
    with SessionLocal.begin() as session:
        user = session.execute(
            select(User).where(User.email == email.lower())
        ).scalar_one_or_none()
        if user is not None:
            session.execute(delete(User).where(User.id == user.id))


def _save_payload() -> dict:
    return {
        "input_type": "images",
        "report_type": "lab_report",
        "sections_found": ["chemistry", "hormone"],
        "source": {
            "extraction_method": "paddleocr",
            "pages_processed": None,
            "images_processed": 2,
        },
        "warnings": ["Reference interval missing for Ferritin, Serum."],
        "raw_text_preview": "CHEMISTRY UNIT\nCalcium (Total), Serum mg/dL 9.6 8.8 - 10.6",
        "tests": [
            {
                "section": "chemistry",
                "test_name": "Calcium (Total), Serum",
                "canonical_test_key": "calcium_total_serum",
                "result_value": 9.6,
                "unit": "mg/dL",
                "reference_interval": {
                    "raw": "8.8 - 10.6",
                    "type": "numeric_range",
                    "low": 8.8,
                    "high": 10.6,
                    "operator": None,
                    "bands": [],
                },
                "status": "above_range",
                "matched_band": None,
                "raw_text": "Calcium (Total), Serum mg/dL 9.6 8.8 - 10.6",
                "confidence": None,
            },
            {
                "section": "hormone",
                "test_name": "25(OH) Vitamin D, Serum",
                "canonical_test_key": "vitamin_d_25oh_serum",
                "result_value": 26.9,
                "unit": "ng/mL",
                "reference_interval": {
                    "raw": "Deficiency <20\nInsufficiency 21-29\nSufficiency 30-100\nHypervitaminosis >150",
                    "type": "categorical_bands",
                    "low": None,
                    "high": None,
                    "operator": None,
                    "bands": [
                        {
                            "label": "Deficiency",
                            "operator": "<",
                            "low": None,
                            "high": 20,
                            "raw": "Deficiency <20",
                        },
                        {
                            "label": "Insufficiency",
                            "operator": None,
                            "low": 21,
                            "high": 29,
                            "raw": "Insufficiency 21-29",
                        },
                    ],
                },
                "status": "within_range",
                "matched_band": None,
                "raw_text": "25(OH) Vitamin D, Serum ng/mL 26.9 Deficiency <20",
                "confidence": 0.91,
            },
        ],
    }


def _profile_payload() -> dict:
    return {
        "age": 34,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 82,
        "activity_level": "moderately_active",
        "goal": "improve_general_health",
        "allergens": [],
        "dietary_restrictions": [],
        "safety_screening": {
            "pregnant": False,
            "breastfeeding": False,
            "eating_disorder_history": False,
            "under_18": False,
            "medical_condition_affects_diet": False,
            "abnormal_labs_or_health_concerns": False,
            "none_of_above": True,
        },
        "agreement_accepted": True,
    }


def _single_calcium_payload(*, value: float) -> dict:
    payload = _save_payload()
    calcium = dict(payload["tests"][0])
    calcium["result_value"] = value
    calcium["raw_text"] = f"Calcium (Total), Serum mg/dL {value} 8.8 - 10.6"
    return {
        **payload,
        "sections_found": ["chemistry"],
        "raw_text_preview": calcium["raw_text"],
        "tests": [calcium],
    }


def _other_categorical_payload() -> dict:
    payload = _save_payload()
    return {
        **payload,
        "sections_found": ["unknown"],
        "raw_text_preview": "Other Marker units 12 Low <10 Normal 10-20",
        "tests": [
            {
                "section": "unknown",
                "test_name": "Other Marker",
                "canonical_test_key": "other_categorical_marker",
                "result_value": 12,
                "unit": "units",
                "reference_interval": {
                    "raw": "Low <10\nNormal 10-20",
                    "type": "categorical_bands",
                    "low": None,
                    "high": None,
                    "operator": None,
                    "bands": [
                        {
                            "label": "Low",
                            "operator": "<",
                            "low": None,
                            "high": 10,
                            "raw": "Low <10",
                        },
                        {
                            "label": "Normal",
                            "operator": None,
                            "low": 10,
                            "high": 20,
                            "raw": "Normal 10-20",
                        },
                    ],
                },
                "status": "within_range",
                "matched_band": None,
                "raw_text": "Other Marker units 12 Low <10 Normal 10-20",
                "confidence": 0.8,
            }
        ],
    }


def test_create_lab_report_creates_report_and_tests() -> None:
    headers, user_id, email = _auth_headers()
    try:
        response = client.post(
            "/v1/labs/reports", json=_save_payload(), headers=headers
        )

        assert response.status_code == 201
        report_id = response.json()["report"]["id"]
        assert response.json()["report"]["source"]["extraction_method"] == "paddleocr"
        assert response.json()["report"]["tests"][0]["status"] == "within_range"
        assert response.json()["report"]["tests"][1]["status"] == "below_range"
        assert response.json()["report"]["tests"][1]["matched_band"] == "Insufficiency"

        with SessionLocal() as session:
            report = session.execute(
                select(LabReport).where(LabReport.id == report_id)
            ).scalar_one()
            test_count = session.execute(
                select(func.count())
                .select_from(LabReportTest)
                .where(LabReportTest.lab_report_id == report_id)
            ).scalar_one()

        assert report.user_id == user_id
        assert report.source_extraction_method == "paddleocr"
        assert test_count == 2
    finally:
        _cleanup_user(email)


def test_request_body_user_id_is_rejected() -> None:
    headers, _, email = _auth_headers()
    try:
        payload = {**_save_payload(), "user_id": 999999}
        response = client.post("/v1/labs/reports", json=payload, headers=headers)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        _cleanup_user(email)


def test_empty_tests_list_returns_validation_error() -> None:
    headers, _, email = _auth_headers()
    try:
        payload = {**_save_payload(), "tests": []}
        response = client.post("/v1/labs/reports", json=payload, headers=headers)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        _cleanup_user(email)


def test_list_endpoint_returns_only_current_user_reports() -> None:
    first_headers, _, first_email = _auth_headers()
    second_headers, _, second_email = _auth_headers()
    try:
        first = client.post(
            "/v1/labs/reports", json=_save_payload(), headers=first_headers
        )
        second = client.post(
            "/v1/labs/reports", json=_save_payload(), headers=second_headers
        )
        assert first.status_code == 201
        assert second.status_code == 201

        listed = client.get("/v1/labs/reports", headers=first_headers)

        assert listed.status_code == 200
        ids = [report["id"] for report in listed.json()["reports"]]
        assert first.json()["report"]["id"] in ids
        assert second.json()["report"]["id"] not in ids
    finally:
        _cleanup_user(first_email)
        _cleanup_user(second_email)


def test_profile_includes_latest_saved_lab_results() -> None:
    headers, _, email = _auth_headers()
    try:
        profile = client.post(
            "/v1/profile/update", json=_profile_payload(), headers=headers
        )
        assert profile.status_code == 200

        saved = client.post("/v1/labs/reports", json=_save_payload(), headers=headers)
        assert saved.status_code == 201
        report_id = saved.json()["report"]["id"]

        response = client.get("/v1/profile/me", headers=headers)

        assert response.status_code == 200
        lab_results = response.json()["lab_results"]
        assert len(lab_results) == 2
        calcium = next(
            result
            for result in lab_results
            if result["canonical_test_key"] == "calcium_total_serum"
        )
        assert calcium["report_id"] == report_id
        assert calcium["test_name"] == "Calcium (Total), Serum"
        assert calcium["result_value"] == 9.6
        assert calcium["unit"] == "mg/dL"
        assert calcium["status"] == "within_range"
        assert calcium["reference_interval"]["raw"] == "8.8 - 10.6"
        assert calcium["confirmed_at"]
        vitamin_d = next(
            result
            for result in lab_results
            if result["canonical_test_key"] == "vitamin_d_25oh_serum"
        )
        assert vitamin_d["status"] == "below_range"
        assert vitamin_d["matched_band"] == "Insufficiency"
    finally:
        _cleanup_user(email)


def test_profile_lab_results_use_newest_report_per_marker_and_keep_history() -> None:
    headers, _, email = _auth_headers()
    try:
        profile = client.post(
            "/v1/profile/update", json=_profile_payload(), headers=headers
        )
        assert profile.status_code == 200

        first = client.post(
            "/v1/labs/reports",
            json=_single_calcium_payload(value=9.6),
            headers=headers,
        )
        second = client.post(
            "/v1/labs/reports",
            json=_single_calcium_payload(value=11.2),
            headers=headers,
        )
        assert first.status_code == 201
        assert second.status_code == 201

        response = client.get("/v1/profile/me", headers=headers)
        listed = client.get("/v1/labs/reports", headers=headers)

        assert response.status_code == 200
        lab_results = response.json()["lab_results"]
        assert len(lab_results) == 1
        assert lab_results[0]["canonical_test_key"] == "calcium_total_serum"
        assert lab_results[0]["report_id"] == second.json()["report"]["id"]
        assert lab_results[0]["result_value"] == 11.2
        assert lab_results[0]["status"] == "above_range"

        assert listed.status_code == 200
        assert len(listed.json()["reports"]) == 2
    finally:
        _cleanup_user(email)


def test_profile_lab_results_are_scoped_to_current_user() -> None:
    owner_headers, _, owner_email = _auth_headers()
    other_headers, _, other_email = _auth_headers()
    try:
        assert (
            client.post(
                "/v1/profile/update",
                json=_profile_payload(),
                headers=owner_headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/v1/profile/update",
                json=_profile_payload(),
                headers=other_headers,
            ).status_code
            == 200
        )
        created = client.post(
            "/v1/labs/reports", json=_save_payload(), headers=owner_headers
        )
        assert created.status_code == 201

        other_profile = client.get("/v1/profile/me", headers=other_headers)

        assert other_profile.status_code == 200
        assert other_profile.json()["lab_results"] == []
    finally:
        _cleanup_user(owner_email)
        _cleanup_user(other_email)


def test_detail_endpoint_denies_reports_owned_by_another_user() -> None:
    owner_headers, _, owner_email = _auth_headers()
    other_headers, _, other_email = _auth_headers()
    try:
        created = client.post(
            "/v1/labs/reports", json=_save_payload(), headers=owner_headers
        )
        assert created.status_code == 201
        report_id = created.json()["report"]["id"]

        response = client.get(f"/v1/labs/reports/{report_id}", headers=other_headers)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        _cleanup_user(owner_email)
        _cleanup_user(other_email)


def test_json_fields_persist_sections_warnings_and_reference_bands() -> None:
    headers, _, email = _auth_headers()
    try:
        created = client.post("/v1/labs/reports", json=_save_payload(), headers=headers)
        assert created.status_code == 201
        report_id = created.json()["report"]["id"]

        with SessionLocal() as session:
            report = session.execute(
                select(LabReport).where(LabReport.id == report_id)
            ).scalar_one()
            vitamin_d = session.execute(
                select(LabReportTest).where(
                    LabReportTest.lab_report_id == report_id,
                    LabReportTest.canonical_test_key == "vitamin_d_25oh_serum",
                )
            ).scalar_one()

        assert report.sections_found == ["chemistry", "hormone"]
        assert report.warnings == ["Reference interval missing for Ferritin, Serum."]
        assert vitamin_d.reference_bands[1]["label"] == "Insufficiency"
        assert vitamin_d.matched_band == "Insufficiency"
        assert vitamin_d.status == "below_range"
    finally:
        _cleanup_user(email)


def test_non_vitamin_d_categorical_status_remains_indeterminate() -> None:
    headers, _, email = _auth_headers()
    try:
        created = client.post(
            "/v1/labs/reports", json=_other_categorical_payload(), headers=headers
        )

        assert created.status_code == 201
        test = created.json()["report"]["tests"][0]
        assert test["matched_band"] == "Normal"
        assert test["status"] == "indeterminate"
    finally:
        _cleanup_user(email)


def test_init_db_backfills_existing_vitamin_d_categorical_status() -> None:
    headers, _, email = _auth_headers()
    try:
        created = client.post("/v1/labs/reports", json=_save_payload(), headers=headers)
        assert created.status_code == 201
        report_id = created.json()["report"]["id"]

        with SessionLocal.begin() as session:
            vitamin_d = session.execute(
                select(LabReportTest).where(
                    LabReportTest.lab_report_id == report_id,
                    LabReportTest.canonical_test_key == "vitamin_d_25oh_serum",
                )
            ).scalar_one()
            vitamin_d.status = "indeterminate"

        init_db()

        with SessionLocal() as session:
            vitamin_d = session.execute(
                select(LabReportTest).where(
                    LabReportTest.lab_report_id == report_id,
                    LabReportTest.canonical_test_key == "vitamin_d_25oh_serum",
                )
            ).scalar_one()

        assert vitamin_d.status == "below_range"
    finally:
        _cleanup_user(email)
