from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.v1.lab_report import (
    LabReportBand,
    LabReportReferenceInterval,
    LabReportReferenceType,
    LabReportSection,
    LabReportStatus,
    LabReportTest,
)


SUPPORTED_UNITS = (
    "mg/dL",
    "µg/dL",
    "μg/dL",
    "ľg/dL",
    "ug/dL",
    "ng/mL",
    "pg/mL",
    "nmol/L",
    "pmol/L",
    "mIU/L",
    "IU/L",
    "U/L",
    "%",
)

_UNIT_PATTERN = "|".join(
    re.escape(unit) for unit in sorted(SUPPORTED_UNITS, key=len, reverse=True)
)
_ROW_RE = re.compile(
    rf"^(?P<name>.+?)\s+(?P<unit>{_UNIT_PATTERN})\s+"
    r"(?P<result>[<>]=?\s*-?\d+(?:\.\d+)?|-?\d+(?:\.\d+)?|[A-Za-z][^\s]*)"
    r"(?:\s+(?P<reference>.+))?$",
    re.IGNORECASE,
)
_ROW_RESULT_UNIT_RE = re.compile(
    rf"^(?P<name>.+?)\s+"
    r"(?P<result>[<>]=?\s*-?\d+(?:\.\d+)?|-?\d+(?:\.\d+)?|[A-Za-z][^\s]*)"
    rf"\s+(?P<unit>{_UNIT_PATTERN})"
    r"(?:\s+(?P<reference>.+))?$",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(r"^(?P<low>-?\d+(?:\.\d+)?)\s*[-–]\s*(?P<high>-?\d+(?:\.\d+)?)$")
_BOUND_RE = re.compile(r"^(?P<operator>[<>]=?)\s*(?P<value>-?\d+(?:\.\d+)?)$")
_BAND_RE = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z\s()/.-]*?)\s+"
    r"(?P<expression>(?:[<>]=?\s*-?\d+(?:\.\d+)?)|(?:-?\d+(?:\.\d+)?\s*[-–]\s*-?\d+(?:\.\d+)?))$"
)
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_HEADER_LINES = {
    "result",
    "unit",
    "reference interval",
    "test name",
    "result unit reference interval test name",
}

_ALIASES = {
    "calcium total serum": "calcium_total_serum",
    "calcium serum": "calcium_total_serum",
    "phosphorus serum": "phosphorus_serum",
    "phosphorous serum": "phosphorus_serum",
    "magnesium serum": "magnesium_serum",
    "zinc serum": "zinc_serum",
    "25 oh vitamin d serum": "vitamin_d_25oh_serum",
    "25oh vitamin d serum": "vitamin_d_25oh_serum",
    "25 hydroxy vitamin d": "vitamin_d_25oh_serum",
    "folic acid serum": "folic_acid_serum",
    "folate serum": "folic_acid_serum",
    "vitamin b12 cyanocobalamin": "vitamin_b12_serum",
    "vitamin b12 serum": "vitamin_b12_serum",
    "ferritin serum": "ferritin_serum",
}
_DISPLAY_TEST_ALIASES = {
    "Calcium (Total), Serum": "calcium_total_serum",
    "Calcium, Serum": "calcium_total_serum",
    "Phosphorus, Serum": "phosphorus_serum",
    "Phosphorous, Serum": "phosphorus_serum",
    "Magnesium, Serum": "magnesium_serum",
    "Zinc, Serum": "zinc_serum",
    "25(OH) Vitamin D, Serum": "vitamin_d_25oh_serum",
    "25-hydroxy vitamin d": "vitamin_d_25oh_serum",
    "Folic Acid, Serum": "folic_acid_serum",
    "Folate, Serum": "folic_acid_serum",
    "Vitamin B12 (cyanocobalamin)": "vitamin_b12_serum",
    "Vitamin B12, Serum": "vitamin_b12_serum",
    "Ferritin, Serum": "ferritin_serum",
}
_VITAMIN_D_CATEGORICAL_STATUS_BY_BAND = {
    "deficiency": LabReportStatus.BELOW_RANGE,
    "insufficiency": LabReportStatus.BELOW_RANGE,
    "sufficiency": LabReportStatus.WITHIN_RANGE,
    "hypervitaminosis": LabReportStatus.ABOVE_RANGE,
}


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


_COMPACT_DISPLAY_ALIASES = sorted(
    (
        (_compact_text(test_name), test_name, canonical_key)
        for test_name, canonical_key in _DISPLAY_TEST_ALIASES.items()
    ),
    key=lambda item: len(item[0]),
    reverse=True,
)


@dataclass(frozen=True)
class LabReportParseResult:
    tests: list[LabReportTest]
    sections_found: list[LabReportSection]
    warnings: list[str]


def parse_lab_report_text(text: str) -> LabReportParseResult:
    lines = _clean_lines(text)
    tests: list[LabReportTest] = []
    sections_found: list[LabReportSection] = []
    consumed: set[int] = set()
    current_section = LabReportSection.UNKNOWN

    index = 0
    while index < len(lines):
        line = lines[index]
        section = _section_from_line(line)
        if section is not None:
            current_section = section
            if section not in sections_found:
                sections_found.append(section)
            index += 1
            continue

        if _is_header(line):
            index += 1
            continue

        row_match = _ROW_RE.match(line) or _ROW_RESULT_UNIT_RE.match(line)
        if row_match:
            row_index = index
            test = _test_from_row(row_match, line, current_section)
            if test is not None:
                band_lines, next_index = _collect_following_band_lines(lines, index + 1)
                if band_lines and _looks_like_band(test.reference_interval.raw):
                    test = _with_categorical_bands(
                        test, [test.reference_interval.raw or "", *band_lines]
                    )
                    consumed.update(range(index + 1, next_index))
                    index = next_index
                else:
                    index += 1
                tests.append(test)
                consumed.add(row_index)
                continue

        compact_test = _test_from_compact_row(line, current_section)
        if compact_test is not None:
            tests.append(compact_test)
            consumed.add(index)
            index += 1
            continue

        index += 1

    for index, line in enumerate(lines):
        if (
            index in consumed
            or _is_header(line)
            or _section_from_line(line) is not None
        ):
            continue
        canonical_key = canonical_test_key(line)
        if canonical_key is None:
            continue
        broken = _test_from_line_broken(
            lines, index, current_section_for_line(lines, index)
        )
        if broken is not None and all(
            test.canonical_test_key != broken.canonical_test_key for test in tests
        ):
            tests.append(broken)

    warnings = build_lab_report_warnings(text, tests)
    return LabReportParseResult(
        tests=tests, sections_found=sections_found, warnings=warnings
    )


def build_lab_report_warnings(text: str, tests: list[LabReportTest]) -> list[str]:
    warnings: list[str] = []
    if not tests:
        warnings.append("No lab tests were parsed from the extracted text.")
    for test in tests:
        if not test.unit:
            warnings.append(f"Parsed test '{test.test_name}' is missing a unit.")
        if not test.reference_interval.raw:
            warnings.append(
                f"Parsed test '{test.test_name}' is missing a reference interval."
            )
    if _looks_table_like(text) and not tests:
        warnings.append(
            "Extracted text appears table-like, but no lab rows were parsed."
        )
    return warnings


def canonical_test_key(test_name: str) -> str | None:
    return _ALIASES.get(_normalize_alias(test_name))


def normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    cleaned = unit.strip()
    return (
        cleaned.replace("ug/", "µg/")
        .replace("UG/", "µg/")
        .replace("μg/", "µg/")
        .replace("ľg/", "µg/")
    )


def parse_reference_interval(raw: str | None) -> LabReportReferenceInterval:
    raw = (raw or "").strip() or None
    if raw is None:
        return LabReportReferenceInterval(raw=None, type=LabReportReferenceType.UNKNOWN)

    band = parse_reference_band(raw)
    if band is not None:
        return LabReportReferenceInterval(
            raw=raw,
            type=LabReportReferenceType.CATEGORICAL_BANDS,
            bands=[band],
        )

    range_match = _RANGE_RE.match(raw)
    if range_match:
        return LabReportReferenceInterval(
            raw=raw,
            type=LabReportReferenceType.NUMERIC_RANGE,
            low=float(range_match.group("low")),
            high=float(range_match.group("high")),
        )

    bound_match = _BOUND_RE.match(raw)
    if bound_match:
        operator = bound_match.group("operator")
        value = float(bound_match.group("value"))
        if operator.startswith(">"):
            return LabReportReferenceInterval(
                raw=raw,
                type=LabReportReferenceType.LOWER_BOUND,
                low=value,
                operator=operator,
            )
        return LabReportReferenceInterval(
            raw=raw,
            type=LabReportReferenceType.UPPER_BOUND,
            high=value,
            operator=operator,
        )

    return LabReportReferenceInterval(raw=raw, type=LabReportReferenceType.TEXT)


def parse_reference_band(raw: str | None) -> LabReportBand | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    match = _BAND_RE.match(raw)
    if not match:
        return None

    label = " ".join(match.group("label").split())
    expression = match.group("expression").strip()
    range_match = _RANGE_RE.match(expression)
    if range_match:
        return LabReportBand(
            label=label,
            low=float(range_match.group("low")),
            high=float(range_match.group("high")),
            raw=raw,
        )

    bound_match = _BOUND_RE.match(expression)
    if bound_match:
        operator = bound_match.group("operator")
        value = float(bound_match.group("value"))
        if operator.startswith(">"):
            return LabReportBand(label=label, operator=operator, low=value, raw=raw)
        return LabReportBand(label=label, operator=operator, high=value, raw=raw)

    return None


def classify_result(
    result_value: float | str | None,
    reference_interval: LabReportReferenceInterval,
) -> LabReportStatus:
    if not isinstance(result_value, int | float):
        return LabReportStatus.INDETERMINATE

    if reference_interval.type == LabReportReferenceType.NUMERIC_RANGE:
        if reference_interval.low is None or reference_interval.high is None:
            return LabReportStatus.INDETERMINATE
        if result_value < reference_interval.low:
            return LabReportStatus.BELOW_RANGE
        if result_value > reference_interval.high:
            return LabReportStatus.ABOVE_RANGE
        return LabReportStatus.WITHIN_RANGE

    if reference_interval.type == LabReportReferenceType.LOWER_BOUND:
        if reference_interval.low is None:
            return LabReportStatus.INDETERMINATE
        if (
            reference_interval.operator == ">"
            and result_value <= reference_interval.low
        ):
            return LabReportStatus.BELOW_RANGE
        if (
            reference_interval.operator == ">="
            and result_value < reference_interval.low
        ):
            return LabReportStatus.BELOW_RANGE
        return LabReportStatus.WITHIN_RANGE

    if reference_interval.type == LabReportReferenceType.UPPER_BOUND:
        if reference_interval.high is None:
            return LabReportStatus.INDETERMINATE
        if (
            reference_interval.operator == "<"
            and result_value >= reference_interval.high
        ):
            return LabReportStatus.ABOVE_RANGE
        if (
            reference_interval.operator == "<="
            and result_value > reference_interval.high
        ):
            return LabReportStatus.ABOVE_RANGE
        return LabReportStatus.WITHIN_RANGE

    return LabReportStatus.INDETERMINATE


def match_categorical_band(
    result_value: float | str | None,
    bands: list[LabReportBand],
) -> str | None:
    if not isinstance(result_value, int | float):
        return None
    for band in bands:
        if _value_matches_band(float(result_value), band):
            return band.label
    return None


def classify_categorical_band_status(
    *,
    canonical_test_key: str,
    matched_band: str | None,
) -> LabReportStatus | None:
    if canonical_test_key != "vitamin_d_25oh_serum" or matched_band is None:
        return None
    normalized_band = " ".join(matched_band.casefold().split())
    return _VITAMIN_D_CATEGORICAL_STATUS_BY_BAND.get(normalized_band)


def classify_categorical_result(
    *,
    canonical_test_key: str,
    result_value: float | str | None,
    bands: list[LabReportBand],
) -> tuple[LabReportStatus, str | None]:
    matched_band = match_categorical_band(result_value, bands)
    status = classify_categorical_band_status(
        canonical_test_key=canonical_test_key,
        matched_band=matched_band,
    )
    return status or LabReportStatus.INDETERMINATE, matched_band


def _test_from_row(
    row_match: re.Match[str],
    raw_text: str,
    section: LabReportSection,
) -> LabReportTest | None:
    test_name = row_match.group("name").strip()
    canonical_key = canonical_test_key(test_name)
    if canonical_key is None:
        return None
    result_value = _parse_result_value(row_match.group("result"))
    reference_interval = parse_reference_interval(row_match.group("reference"))
    matched_band = None
    status = classify_result(result_value, reference_interval)
    if reference_interval.type == LabReportReferenceType.CATEGORICAL_BANDS:
        status, matched_band = classify_categorical_result(
            canonical_test_key=canonical_key,
            result_value=result_value,
            bands=reference_interval.bands,
        )
    return LabReportTest(
        section=section,
        test_name=test_name,
        canonical_test_key=canonical_key,
        result_value=result_value,
        unit=normalize_unit(row_match.group("unit")),
        reference_interval=reference_interval,
        status=status,
        matched_band=matched_band,
        raw_text=raw_text,
        confidence=0.9,
    )


def _test_from_compact_row(
    line: str, section: LabReportSection
) -> LabReportTest | None:
    compact_line = _compact_text(line)
    if not compact_line:
        return None

    for compact_alias, test_name, canonical_key in _COMPACT_DISPLAY_ALIASES:
        if not compact_line.casefold().startswith(compact_alias.casefold()):
            continue
        compact_rest = compact_line[len(compact_alias) :]
        parsed = _parse_compact_measurement(compact_rest)
        if parsed is None:
            continue
        result_value, unit, reference_interval = parsed
        matched_band = None
        status = classify_result(result_value, reference_interval)
        if reference_interval.type == LabReportReferenceType.CATEGORICAL_BANDS:
            status, matched_band = classify_categorical_result(
                canonical_test_key=canonical_key,
                result_value=result_value,
                bands=reference_interval.bands,
            )
        return LabReportTest(
            section=section,
            test_name=test_name,
            canonical_test_key=canonical_key,
            result_value=result_value,
            unit=unit,
            reference_interval=reference_interval,
            status=status,
            matched_band=matched_band,
            raw_text=line,
            confidence=0.8,
        )

    return None


def _parse_compact_measurement(
    compact_rest: str,
) -> tuple[float | str | None, str | None, LabReportReferenceInterval] | None:
    compact_unit_pattern = "|".join(
        re.escape(_compact_text(unit))
        for unit in sorted(SUPPORTED_UNITS, key=len, reverse=True)
    )
    result_pattern = r"(?P<result>[<>]=?-?\d+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    result_unit_match = re.match(
        rf"^{result_pattern}(?P<unit>{compact_unit_pattern})(?P<reference>.*)$",
        compact_rest,
        re.IGNORECASE,
    )
    unit_result_match = re.match(
        rf"^(?P<unit>{compact_unit_pattern}){result_pattern}(?P<reference>.*)$",
        compact_rest,
        re.IGNORECASE,
    )
    match = result_unit_match or unit_result_match
    if match is None:
        return None

    result_value = _parse_result_value(match.group("result"))
    unit = normalize_unit(match.group("unit"))
    reference_raw = match.group("reference").strip() or None
    categorical = _parse_compact_categorical_reference(reference_raw)
    reference_interval = categorical or parse_reference_interval(reference_raw)
    return result_value, unit, reference_interval


def _parse_compact_categorical_reference(
    raw: str | None,
) -> LabReportReferenceInterval | None:
    if not raw:
        return None
    band_matches = list(
        re.finditer(
            r"(?P<label>[A-Za-z][A-Za-z()/-]*?)(?P<expression>[<>]=?-?\d+(?:\.\d+)?|-?\d+(?:\.\d+)?[-–]-?\d+(?:\.\d+)?)",
            raw,
        )
    )
    if not band_matches:
        return None
    bands = [
        band
        for match in band_matches
        if (
            band := parse_reference_band(
                f"{match.group('label')} {match.group('expression')}"
            )
        )
        is not None
    ]
    if not bands:
        return None
    return LabReportReferenceInterval(
        raw="\n".join(band.raw for band in bands),
        type=LabReportReferenceType.CATEGORICAL_BANDS,
        bands=bands,
    )


def _test_from_line_broken(
    lines: list[str],
    index: int,
    section: LabReportSection,
) -> LabReportTest | None:
    test_name = lines[index].strip()
    canonical_key = canonical_test_key(test_name)
    if canonical_key is None:
        return None

    values: list[str] = []
    cursor = index + 1
    while cursor < len(lines) and len(values) < 4:
        line = lines[cursor].strip()
        if _section_from_line(line) is not None or canonical_test_key(line) is not None:
            break
        if not _is_header(line):
            values.append(line)
        cursor += 1

    result_value: float | str | None = None
    unit: str | None = None
    reference_raw: str | None = None
    for value in values:
        if result_value is None and _NUMBER_RE.match(value):
            result_value = _parse_result_value(value)
            continue
        if unit is None and _is_supported_unit(value):
            unit = normalize_unit(value)
            continue
        if reference_raw is None and (
            parse_reference_band(value) is not None
            or _RANGE_RE.match(value)
            or _BOUND_RE.match(value)
        ):
            reference_raw = value

    reference_interval = parse_reference_interval(reference_raw)
    return LabReportTest(
        section=section,
        test_name=test_name,
        canonical_test_key=canonical_key,
        result_value=result_value,
        unit=unit,
        reference_interval=reference_interval,
        status=classify_result(result_value, reference_interval),
        raw_text="\n".join(lines[index:cursor]),
        confidence=0.75,
    )


def _with_categorical_bands(
    test: LabReportTest, raw_band_lines: list[str]
) -> LabReportTest:
    bands = [
        band
        for raw in raw_band_lines
        if (band := parse_reference_band(raw)) is not None
    ]
    if not bands:
        return test
    raw = "\n".join(band.raw for band in bands)
    reference_interval = LabReportReferenceInterval(
        raw=raw,
        type=LabReportReferenceType.CATEGORICAL_BANDS,
        bands=bands,
    )
    status, matched_band = classify_categorical_result(
        canonical_test_key=test.canonical_test_key,
        result_value=test.result_value,
        bands=bands,
    )
    return test.model_copy(
        update={
            "reference_interval": reference_interval,
            "status": status,
            "matched_band": matched_band,
            "raw_text": "\n".join([test.raw_text, *raw_band_lines]),
        }
    )


def _collect_following_band_lines(
    lines: list[str], index: int
) -> tuple[list[str], int]:
    band_lines: list[str] = []
    cursor = index
    while cursor < len(lines):
        line = lines[cursor]
        if (
            _section_from_line(line) is not None
            or _ROW_RE.match(line)
            or _is_header(line)
        ):
            break
        if parse_reference_band(line) is None:
            break
        band_lines.append(line)
        cursor += 1
    return band_lines, cursor


def current_section_for_line(lines: list[str], index: int) -> LabReportSection:
    section = LabReportSection.UNKNOWN
    for line in lines[: index + 1]:
        parsed = _section_from_line(line)
        if parsed is not None:
            section = parsed
    return section


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.replace("<br>", " ").replace("|", " ").strip()
        if not line or set(line) <= {"-"}:
            continue
        line = re.sub(r"\s+", " ", line).strip()
        if _looks_character_spaced(line):
            line = _collapse_character_spaced_line(line)
        if line:
            lines.append(line)
    return lines


def _section_from_line(line: str) -> LabReportSection | None:
    normalized = line.strip().casefold()
    if "chemistry" in normalized:
        return LabReportSection.CHEMISTRY
    if "hormone" in normalized:
        return LabReportSection.HORMONE
    if "immunology" in normalized:
        return LabReportSection.IMMUNOLOGY
    return None


def _is_header(line: str) -> bool:
    return line.strip().casefold() in _HEADER_LINES


def _normalize_alias(value: str) -> str:
    normalized = value.casefold().replace("µ", "u")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _looks_character_spaced(line: str) -> bool:
    tokens = line.split()
    if len(tokens) < 8:
        return False
    single_character_tokens = sum(1 for token in tokens if len(token) == 1)
    return single_character_tokens / len(tokens) > 0.65


def _collapse_character_spaced_line(line: str) -> str:
    return _compact_text(line)


def _parse_result_value(value: str | None) -> float | str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if _NUMBER_RE.match(cleaned):
        return float(cleaned)
    return cleaned or None


def _looks_like_band(raw: str | None) -> bool:
    return parse_reference_band(raw) is not None


def _is_supported_unit(value: str) -> bool:
    normalized = normalize_unit(value)
    return normalized in {normalize_unit(unit) for unit in SUPPORTED_UNITS}


def _value_matches_band(value: float, band: LabReportBand) -> bool:
    if band.low is not None and band.high is not None:
        return band.low <= value <= band.high
    if band.low is not None:
        if band.operator == ">":
            return value > band.low
        if band.operator == ">=":
            return value >= band.low
    if band.high is not None:
        if band.operator == "<":
            return value < band.high
        if band.operator == "<=":
            return value <= band.high
    return False


def _looks_table_like(text: str) -> bool:
    normalized = text.casefold()
    return "result" in normalized and "unit" in normalized and "reference" in normalized
