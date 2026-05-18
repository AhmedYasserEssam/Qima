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
    finally:
        _cleanup_user(email)
