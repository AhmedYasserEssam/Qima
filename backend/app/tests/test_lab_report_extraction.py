from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.parsers.lab_report_parser import parse_lab_report_text
from app.services.pdf_text_extraction_service import PdfTextExtractionService


client = TestClient(app)


def _only_test(text: str):
    result = parse_lab_report_text(text)
    assert len(result.tests) == 1
    return result.tests[0]


def test_parse_chemistry_row() -> None:
    test = _only_test("Calcium (Total), Serum mg/dL 9.6 8.8 - 10.6")

    assert test.test_name == "Calcium (Total), Serum"
    assert test.canonical_test_key == "calcium_total_serum"
    assert test.result_value == 9.6
    assert test.unit == "mg/dL"
    assert test.reference_interval.low == 8.8
    assert test.reference_interval.high == 10.6
    assert test.status == "within_range"


def test_parse_phosphorus_row() -> None:
    test = _only_test("Phosphorus, Serum mg/dL 3.5 2.4 - 5.1")

    assert test.canonical_test_key == "phosphorus_serum"
    assert test.result_value == 3.5
    assert test.reference_interval.low == 2.4
    assert test.reference_interval.high == 5.1


def test_parse_zinc_with_microgram_unit() -> None:
    test = _only_test("Zinc, Serum µg/dL 83 50 - 120")

    assert test.canonical_test_key == "zinc_serum"
    assert test.unit == "µg/dL"
    assert test.result_value == 83.0


def test_parse_vitamin_d_categorical_bands() -> None:
    result = parse_lab_report_text(
        "\n".join(
            [
                "HORMONE UNIT",
                "25(OH) Vitamin D, Serum ng/mL 26.9 Deficiency <20",
                "Insufficiency 21-29",
                "Sufficiency 30-100",
                "Hypervitaminosis >150",
            ]
        )
    )

    test = result.tests[0]
    assert test.canonical_test_key == "vitamin_d_25oh_serum"
    assert test.result_value == 26.9
    assert test.unit == "ng/mL"
    assert test.reference_interval.type == "categorical_bands"
    assert [band.label for band in test.reference_interval.bands] == [
        "Deficiency",
        "Insufficiency",
        "Sufficiency",
        "Hypervitaminosis",
    ]
    assert test.reference_interval.bands[0].high == 20
    assert test.reference_interval.bands[1].low == 21
    assert test.reference_interval.bands[1].high == 29
    assert test.reference_interval.bands[3].low == 150
    assert test.matched_band == "Insufficiency"


def test_parse_folic_acid_lower_bound_reference() -> None:
    test = _only_test("Folic Acid, Serum ng/mL 4.72 >3.5")

    assert test.canonical_test_key == "folic_acid_serum"
    assert test.reference_interval.type == "lower_bound"
    assert test.reference_interval.low == 3.5
    assert test.status == "within_range"


def test_parse_b12() -> None:
    test = _only_test("Vitamin B12 (cyanocobalamin) pg/mL 390 222 - 1439")

    assert test.canonical_test_key == "vitamin_b12_serum"
    assert test.result_value == 390.0
    assert test.unit == "pg/mL"
    assert test.reference_interval.low == 222
    assert test.reference_interval.high == 1439


def test_parse_ferritin_line_broken_layout() -> None:
    test = _only_test(
        "\n".join(
            [
                "IMMUNOLOGY UNIT",
                "Test Name",
                "Result",
                "Unit",
                "Ferritin, Serum",
                "163.0",
                "Reference Interval",
                "ng/mL",
            ]
        )
    )

    assert test.canonical_test_key == "ferritin_serum"
    assert test.result_value == 163.0
    assert test.unit == "ng/mL"
    assert test.reference_interval.raw is None
    assert test.status == "indeterminate"


def test_parse_opendataloader_character_spaced_markdown_layout() -> None:
    result = parse_lab_report_text(
        "\n".join(
            [
                "|C H E M I S T R Y U N I T|",
                "|---|",
                "|C a l c i u m ( T o t a l ) , S e r u m 9 . 6 m g / d L 8 . 8 - 1 0 . 6|",
                "|Z i n c , S e r u m 8 3 ľ g / d L 5 0 - 1 2 0|",
                "|H O R M O N E U N I T|",
                "|2 5 ( O H ) V i t a m i n D , S e r u m 2 6 . 9 n g / m L D e f i c i e n c y < 2 0 I n s u f f i c i e n c y 2 1 - 2 9 S u f f i c i e n c y 3 0 - 1 0 0 H y p e r v i t a m i n o s i s > 1 5 0|",
            ]
        )
    )

    by_key = {test.canonical_test_key: test for test in result.tests}
    assert by_key["calcium_total_serum"].result_value == 9.6
    assert by_key["calcium_total_serum"].unit == "mg/dL"
    assert by_key["calcium_total_serum"].status == "within_range"
    assert by_key["zinc_serum"].unit == "µg/dL"
    assert by_key["zinc_serum"].reference_interval.low == 50
    assert by_key["vitamin_d_25oh_serum"].matched_band == "Insufficiency"


def test_alias_normalization_maps_phosphorous_to_phosphorus() -> None:
    test = _only_test("Phosphorous, Serum mg/dL 3.5 2.4 - 5.1")

    assert test.canonical_test_key == "phosphorus_serum"


def test_pdf_extraction_service_calls_opendataloader_once_and_reads_markdown(
    tmp_path: Path,
) -> None:
    calls: list[dict] = []
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF")

    def fake_convert(**kwargs) -> None:
        calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        (output_dir / "report.md").write_text(
            "Calcium (Total), Serum mg/dL 9.6 8.8 - 10.6", encoding="utf-8"
        )

    service = PdfTextExtractionService(converter=fake_convert)
    result = service.extract_text(pdf_path)

    assert len(calls) == 1
    assert calls[0]["input_path"] == str(pdf_path)
    assert calls[0]["format"] == "markdown,text"
    assert calls[0]["hybrid"] == "off"
    assert result.text == "Calcium (Total), Serum mg/dL 9.6 8.8 - 10.6"


def test_endpoint_rejects_pdf_mode_without_file() -> None:
    response = client.post("/v1/labs/extract-report", data={"input_type": "pdf"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_endpoint_rejects_image_mode_without_files() -> None:
    response = client.post("/v1/labs/extract-report", data={"input_type": "images"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_endpoint_returns_503_when_image_ocr_is_unavailable(monkeypatch) -> None:
    from app.services.exceptions import UpstreamUnavailableError

    class FakeExtractionService:
        def extract_from_images(self, *, images):
            del images
            raise UpstreamUnavailableError(
                "Local Transformers OCR runtime is unavailable."
            )

    monkeypatch.setattr(
        "app.api.v1.endpoints.lab_report_extraction.lab_report_extraction_service",
        FakeExtractionService(),
    )

    response = client.post(
        "/v1/labs/extract-report",
        data={"input_type": "images"},
        files={"files": ("report.png", b"mock-image", "image/png")},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_image_ocr_service_reuses_loaded_paddleocr(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.image_ocr_service import ImageOcrService

    calls = 0

    class FakeOcr:
        def ocr(self, image_path: str):
            del image_path
            return [{"rec_texts": ["Ferritin, Serum", "163.0", "ng/mL"]}]

    def fake_load_paddleocr():
        nonlocal calls
        calls += 1
        return FakeOcr()

    monkeypatch.setattr(
        "app.services.image_ocr_service._load_paddleocr",
        fake_load_paddleocr,
    )

    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"mock-image")
    service = ImageOcrService()

    first = service.extract_text_from_images([image_path])
    second = service.extract_text_from_images([image_path])

    assert calls == 1
    assert first.text == second.text


def test_image_ocr_service_normalizes_paddleocr_dict_output(tmp_path: Path) -> None:
    from app.services.image_ocr_service import ImageOcrService

    class FakeOcr:
        def ocr(self, image_path: str):
            del image_path
            return [{"rec_texts": ["Calcium (Total), Serum mg/dL 9.6 8.8 - 10.6"]}]

    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"mock-image")

    result = ImageOcrService(ocr=FakeOcr()).extract_text_from_images([image_path])

    assert result.text == "Calcium (Total), Serum mg/dL 9.6 8.8 - 10.6"


def test_image_ocr_service_normalizes_paddleocr_list_output(tmp_path: Path) -> None:
    from app.services.image_ocr_service import ImageOcrService

    class FakeOcr:
        def ocr(self, image_path: str):
            del image_path
            return [
                [
                    [None, ("Folic Acid, Serum", 0.99)],
                    [None, ("ng/mL", 0.99)],
                    [None, ("4.72", 0.99)],
                    [None, (">3.5", 0.99)],
                ]
            ]

    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"mock-image")

    result = ImageOcrService(ocr=FakeOcr()).extract_text_from_images([image_path])

    assert result.text == "Folic Acid, Serum\nng/mL\n4.72\n>3.5"


def test_endpoint_returns_parse_failed_when_text_has_no_lab_tests(monkeypatch) -> None:
    class FakeExtractionService:
        def extract_from_pdf(self, *, filename: str, content: bytes):
            from app.services.lab_report_extraction_service import (
                LabReportParseFailedError,
            )

            del filename, content
            raise LabReportParseFailedError(
                "Extracted text did not contain recognizable lab tests."
            )

    monkeypatch.setattr(
        "app.api.v1.endpoints.lab_report_extraction.lab_report_extraction_service",
        FakeExtractionService(),
    )

    response = client.post(
        "/v1/labs/extract-report",
        data={"input_type": "pdf"},
        files={"file": ("report.pdf", b"%PDF mock", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LAB_REPORT_PARSE_FAILED"
