from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.schemas.v1.nutrition import (
    DataCompleteness,
    DataQuality,
    MatchType,
    MatchedDish,
    Nutrients,
    NutritionDataset,
    NutritionEstimateInputType,
    NutritionEstimateRequest,
    NutritionEstimateSuccess,
    NutritionSourceType,
    ServingAssumptions,
    Source,
)
from app.services.exceptions import NotFoundError, UpstreamUnavailableError

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "Food"

NUTRITION_XLSX = "nutrition.xlsx"
EGYPTIAN_FOOD_CSV = "Egyptian Food.csv"
FDC_FOUNDATION_JSON = "FoodData_Central_foundation_food_json_2025-12-18.json"
FDC_SR_LEGACY_JSON = "FoodData_Central_sr_legacy_food_json_2018-04.json"
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin1")

CORE_NUTRIENTS = ("calories_kcal", "protein_g", "carbohydrates_g", "fat_g")
FDC_NUTRIENT_MAP = {
    1008: "calories_kcal",
    1003: "protein_g",
    1005: "carbohydrates_g",
    1004: "fat_g",
    1079: "fiber_g",
    2000: "sugar_g",
    1093: "sodium_mg",
}
FDC_NUTRIENT_NAME_MAP = {
    "energy": "calories_kcal",
    "protein": "protein_g",
    "carbohydrate, by difference": "carbohydrates_g",
    "total lipid (fat)": "fat_g",
    "fiber, total dietary": "fiber_g",
    "total sugars": "sugar_g",
    "sugars, total": "sugar_g",
    "sugars, total including nlea": "sugar_g",
    "sodium, na": "sodium_mg",
}


@dataclass(frozen=True)
class NutritionValues:
    calories_kcal: float | None
    protein_g: float | None
    carbohydrates_g: float | None
    fat_g: float | None
    fiber_g: float | None = None
    sugar_g: float | None = None
    sodium_mg: float | None = None

    def as_schema(self) -> Nutrients:
        return Nutrients(
            calories_kcal=self.calories_kcal,
            protein_g=self.protein_g,
            carbohydrates_g=self.carbohydrates_g,
            fat_g=self.fat_g,
            fiber_g=self.fiber_g,
            sugar_g=self.sugar_g,
            sodium_mg=self.sodium_mg,
        )

    def has_core_nutrients(self) -> bool:
        return all(getattr(self, key) is not None for key in CORE_NUTRIENTS)


@dataclass(frozen=True)
class NutritionRecord:
    name: str
    normalized_name: str
    normalized_primary_name: str
    normalized_aliases: set[str]
    tokens: set[str]
    serving_size: str | None
    nutrients: NutritionValues
    dataset: NutritionDataset
    source_type: NutritionSourceType
    match_id: str


@dataclass(frozen=True)
class MatchResult:
    record: NutritionRecord
    confidence: float
    match_kind: str


class NutritionService:
    def __init__(self, *, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or DEFAULT_DATA_DIR
        self._records_by_dataset: dict[NutritionDataset, list[NutritionRecord]] | None = None

    def estimate(self, payload: NutritionEstimateRequest) -> NutritionEstimateSuccess:
        if payload.input_type == NutritionEstimateInputType.RECOGNIZED_DISH:
            return self._estimate_recognized_dish(payload)
        return self._estimate_ingredient_set(
            ingredients=payload.ingredients or [],
            serving_hint=payload.serving_hint,
            fallback_warning=None,
        )

    def _estimate_recognized_dish(
        self, payload: NutritionEstimateRequest
    ) -> NutritionEstimateSuccess:
        dish_name = payload.recognized_dish or ""
        match = self._find_best_match(dish_name)
        if match is not None:
            warnings = _match_warnings(dish_name, match)
            return _single_match_response(
                match=match,
                query=dish_name,
                match_type=MatchType.DISH,
                serving_hint=payload.serving_hint,
                warnings=warnings,
            )

        if payload.ingredients:
            return self._estimate_ingredient_set(
                ingredients=payload.ingredients,
                serving_hint=payload.serving_hint,
                fallback_warning=(
                    f"No direct nutrition match found for '{dish_name}'. "
                    "Estimated from recognized ingredients instead."
                ),
            )

        raise NotFoundError("No matching dish or ingredient data found.")

    def _estimate_ingredient_set(
        self,
        *,
        ingredients: list[str],
        serving_hint: str | None,
        fallback_warning: str | None,
    ) -> NutritionEstimateSuccess:
        matched: list[tuple[str, MatchResult]] = []
        missing: list[str] = []
        warnings: list[str] = []
        if fallback_warning:
            warnings.append(fallback_warning)

        for ingredient in _distinct_text(ingredients):
            match = self._find_best_match(ingredient)
            if match is None:
                missing.append(ingredient)
                continue
            matched.append((ingredient, match))
            warnings.extend(_match_warnings(ingredient, match))

        if not matched:
            raise NotFoundError("No matching dish or ingredient data found.")

        nutrients = _average_nutrients([match.record.nutrients for _, match in matched])
        completeness = (
            DataCompleteness.COMPLETE
            if not missing and nutrients.has_core_nutrients()
            else DataCompleteness.PARTIAL
        )
        if missing:
            warnings.append(
                "No nutrition match found for: " + ", ".join(missing) + "."
            )
        if not nutrients.has_core_nutrients():
            warnings.append("One or more core nutrient values are unavailable.")

        source = _source_for_matches([match for _, match in matched], warnings)
        confidence = _ingredient_set_confidence(
            matched_count=len(matched),
            requested_count=len(_distinct_text(ingredients)),
            matches=[match for _, match in matched],
        )
        matched_names = [match.record.name for _, match in matched]

        return NutritionEstimateSuccess(
            matched_dish=MatchedDish(
                name=", ".join(matched_names),
                match_type=MatchType.INGREDIENT_SET,
                match_id=None,
            ),
            serving_assumptions=ServingAssumptions(
                basis=serving_hint or "100 g composite serving",
                note="Estimated as an equal-weight composite of matched ingredients.",
            ),
            nutrients=nutrients.as_schema(),
            confidence=confidence,
            source=source,
            data_quality=DataQuality(completeness=completeness),
            warnings=_unique_warnings(warnings),
        )

    def _find_best_match(self, query: str) -> MatchResult | None:
        query_normalized = _normalize_name(query)
        query_tokens = _tokens(query_normalized)
        if not query_normalized or not query_tokens:
            return None

        for dataset in (
            NutritionDataset.NUTRITION_XLSX,
            NutritionDataset.EGYPTIAN_FOOD_CSV,
            NutritionDataset.FDC_FOUNDATION,
            NutritionDataset.FDC_SR_LEGACY,
        ):
            best: MatchResult | None = None
            for record in self._records_by_dataset_loaded().get(dataset, []):
                candidate = _score_match(
                    query_normalized=query_normalized,
                    query_tokens=query_tokens,
                    record=record,
                )
                if candidate is None:
                    continue
                if best is None or candidate.confidence > best.confidence:
                    best = candidate
            if best is not None:
                return best

        return None

    def _records_by_dataset_loaded(self) -> dict[NutritionDataset, list[NutritionRecord]]:
        if self._records_by_dataset is not None:
            return self._records_by_dataset

        try:
            records_by_dataset = {
                NutritionDataset.NUTRITION_XLSX: self._load_nutrition_xlsx(),
                NutritionDataset.EGYPTIAN_FOOD_CSV: self._load_egyptian_food_csv(),
                NutritionDataset.FDC_FOUNDATION: self._load_fdc_json(
                    filename=FDC_FOUNDATION_JSON,
                    root_key="FoundationFoods",
                    dataset=NutritionDataset.FDC_FOUNDATION,
                ),
                NutritionDataset.FDC_SR_LEGACY: self._load_fdc_json(
                    filename=FDC_SR_LEGACY_JSON,
                    root_key="SRLegacyFoods",
                    dataset=NutritionDataset.FDC_SR_LEGACY,
                ),
            }
        except UpstreamUnavailableError:
            raise
        except Exception as exc:
            raise UpstreamUnavailableError(
                "Nutrition data sources are currently unavailable."
            ) from exc

        if not records_by_dataset[NutritionDataset.NUTRITION_XLSX]:
            raise UpstreamUnavailableError("nutrition.xlsx contains no usable foods.")

        self._records_by_dataset = records_by_dataset
        return records_by_dataset

    def _load_nutrition_xlsx(self) -> list[NutritionRecord]:
        path = self._data_dir / NUTRITION_XLSX
        if not path.exists():
            raise UpstreamUnavailableError("nutrition.xlsx is not available.")

        try:
            frame = pd.read_excel(path)
        except Exception as exc:
            raise UpstreamUnavailableError("nutrition.xlsx could not be read.") from exc

        records: list[NutritionRecord] = []
        for index, row in frame.iterrows():
            name = _text(row.get("name"))
            if not name:
                continue
            records.append(
                _record(
                    name=name,
                    serving_size=_text(row.get("serving_size")) or None,
                    nutrients=NutritionValues(
                        calories_kcal=_number(row.get("calories")),
                        protein_g=_number(row.get("protein")),
                        carbohydrates_g=_number(row.get("carbohydrate")),
                        fat_g=_number(row.get("fat")),
                        fiber_g=_number(row.get("fiber")),
                        sugar_g=_number(row.get("sugars")),
                        sodium_mg=_number(row.get("sodium")),
                    ),
                    dataset=NutritionDataset.NUTRITION_XLSX,
                    source_type=NutritionSourceType.NUTRITION_DATASET,
                    match_id=f"nutrition_xlsx:{index}",
                )
            )
        return records

    def _load_egyptian_food_csv(self) -> list[NutritionRecord]:
        path = self._data_dir / EGYPTIAN_FOOD_CSV
        if not path.exists():
            return []

        try:
            frame = _read_csv_with_encoding_fallback(path)
        except Exception as exc:
            raise UpstreamUnavailableError("Egyptian Food.csv could not be read.") from exc
        frame = frame.drop(
            columns=[
                column
                for column in frame.columns
                if str(column).strip().lower().startswith("unnamed:")
            ],
            errors="ignore",
        )

        records: list[NutritionRecord] = []
        for index, row in frame.iterrows():
            name = _first_text(row, ["FOOD", "name", "dish", "food", "food_name"])
            if not name:
                continue
            records.append(
                _record(
                    name=name,
                    serving_size="100 g",
                    nutrients=NutritionValues(
                        calories_kcal=_first_number(
                            row, ["ENERGY (Kcal)", "calories_kcal", "calories", "energy_kcal"]
                        ),
                        protein_g=_first_number(row, ["PROTEIN (g)", "protein_g", "protein"]),
                        carbohydrates_g=_first_number(
                            row,
                            [
                                "CARBOHYDRATE  (g)",
                                "CARBOHYDRATE (g)",
                                "carbohydrates_g",
                                "carbohydrate",
                                "carbs_g",
                                "carbs",
                            ],
                        ),
                        fat_g=_first_number(row, ["FAT (g)", "fat_g", "fat", "total_fat"]),
                        fiber_g=_first_number(row, ["FIBER (g)", "fiber_g", "fiber"]),
                        sugar_g=_first_number(row, ["sugar_g", "sugars_g", "sugars"]),
                        sodium_mg=_first_number(row, ["SODIUM (mg)", "sodium_mg", "sodium"]),
                    ),
                    dataset=NutritionDataset.EGYPTIAN_FOOD_CSV,
                    source_type=NutritionSourceType.EGYPTIAN_FOOD_DATASET,
                    match_id=f"egyptian_food_csv:{index}",
                )
            )
        return records

    def _load_fdc_json(
        self,
        *,
        filename: str,
        root_key: str,
        dataset: NutritionDataset,
    ) -> list[NutritionRecord]:
        path = self._data_dir / filename
        if not path.exists():
            return []

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise UpstreamUnavailableError(f"{filename} could not be read.") from exc

        foods = payload.get(root_key)
        if not isinstance(foods, list):
            return []

        records: list[NutritionRecord] = []
        for food in foods:
            if not isinstance(food, dict):
                continue
            name = _text(food.get("description"))
            if not name:
                continue
            nutrients = _fdc_nutrients(food.get("foodNutrients"))
            records.append(
                _record(
                    name=name,
                    serving_size="100 g",
                    nutrients=nutrients,
                    dataset=dataset,
                    source_type=NutritionSourceType.FOODDATA_CENTRAL,
                    match_id=f"fdc:{food.get('fdcId') or food.get('ndbNumber') or len(records)}",
                )
            )
        return records


def _single_match_response(
    *,
    match: MatchResult,
    query: str,
    match_type: MatchType,
    serving_hint: str | None,
    warnings: list[str],
) -> NutritionEstimateSuccess:
    nutrients = match.record.nutrients
    completeness = (
        DataCompleteness.COMPLETE
        if nutrients.has_core_nutrients()
        else DataCompleteness.PARTIAL
    )
    if not nutrients.has_core_nutrients():
        warnings.append("One or more core nutrient values are unavailable.")

    return NutritionEstimateSuccess(
        matched_dish=MatchedDish(
            name=match.record.name,
            match_type=match_type,
            match_id=match.record.match_id,
        ),
        serving_assumptions=ServingAssumptions(
            basis=serving_hint or match.record.serving_size or "100 g",
            note=(
                f"Matched '{query}' to nutrition source row '{match.record.name}'. "
                "Values are estimated from the matched data source."
            ),
        ),
        nutrients=nutrients.as_schema(),
        confidence=match.confidence,
        source=Source(
            dataset=match.record.dataset,
            source_type=match.record.source_type,
        ),
        data_quality=DataQuality(completeness=completeness),
        warnings=_unique_warnings(warnings),
    )


def _record(
    *,
    name: str,
    serving_size: str | None,
    nutrients: NutritionValues,
    dataset: NutritionDataset,
    source_type: NutritionSourceType,
    match_id: str,
) -> NutritionRecord:
    normalized = _normalize_name(name)
    normalized_primary = _normalize_name(_primary_name(name))
    normalized_aliases = {
        normalized_alias
        for alias in _parenthetical_aliases(name)
        if (normalized_alias := _normalize_name(alias))
    }
    return NutritionRecord(
        name=name,
        normalized_name=normalized,
        normalized_primary_name=normalized_primary,
        normalized_aliases=normalized_aliases,
        tokens=_tokens(normalized),
        serving_size=serving_size,
        nutrients=nutrients,
        dataset=dataset,
        source_type=source_type,
        match_id=match_id,
    )


def _score_match(
    *,
    query_normalized: str,
    query_tokens: set[str],
    record: NutritionRecord,
) -> MatchResult | None:
    if query_normalized == record.normalized_name:
        return MatchResult(record=record, confidence=0.95, match_kind="exact")

    if query_normalized == record.normalized_primary_name:
        return MatchResult(record=record, confidence=0.86, match_kind="fuzzy")

    if query_normalized in record.normalized_aliases:
        return MatchResult(record=record, confidence=0.84, match_kind="fuzzy")

    if len(query_tokens) == 1:
        return None

    if query_tokens.issubset(record.tokens):
        return MatchResult(record=record, confidence=0.78, match_kind="fuzzy")

    overlap = len(query_tokens & record.tokens) / max(len(query_tokens), 1)
    if overlap >= 0.75:
        return MatchResult(record=record, confidence=0.68, match_kind="fuzzy")

    return None


def _match_warnings(query: str, match: MatchResult) -> list[str]:
    if match.match_kind == "exact":
        return []
    return [f"Matched '{query}' to '{match.record.name}' using fuzzy matching."]


def _average_nutrients(values: list[NutritionValues]) -> NutritionValues:
    def average(key: str) -> float | None:
        present = [getattr(item, key) for item in values if getattr(item, key) is not None]
        if not present:
            return None
        return round(sum(present) / len(present), 3)

    return NutritionValues(
        calories_kcal=average("calories_kcal"),
        protein_g=average("protein_g"),
        carbohydrates_g=average("carbohydrates_g"),
        fat_g=average("fat_g"),
        fiber_g=average("fiber_g"),
        sugar_g=average("sugar_g"),
        sodium_mg=average("sodium_mg"),
    )


def _source_for_matches(matches: list[MatchResult], warnings: list[str]) -> Source:
    priority = {
        NutritionDataset.NUTRITION_XLSX: 0,
        NutritionDataset.EGYPTIAN_FOOD_CSV: 1,
        NutritionDataset.FDC_FOUNDATION: 2,
        NutritionDataset.FDC_SR_LEGACY: 3,
    }
    datasets = {match.record.dataset for match in matches}
    selected = min(datasets, key=lambda dataset: priority[dataset])
    selected_source_type = {
        NutritionDataset.NUTRITION_XLSX: NutritionSourceType.NUTRITION_DATASET,
        NutritionDataset.EGYPTIAN_FOOD_CSV: NutritionSourceType.EGYPTIAN_FOOD_DATASET,
        NutritionDataset.FDC_FOUNDATION: NutritionSourceType.FOODDATA_CENTRAL,
        NutritionDataset.FDC_SR_LEGACY: NutritionSourceType.FOODDATA_CENTRAL,
    }[selected]
    if len(datasets) > 1:
        warnings.append("Multiple nutrition data sources were used for this estimate.")
    return Source(dataset=selected, source_type=selected_source_type)


def _ingredient_set_confidence(
    *,
    matched_count: int,
    requested_count: int,
    matches: list[MatchResult],
) -> float:
    if requested_count <= 0 or not matches:
        return 0.0
    coverage = matched_count / requested_count
    average_match = sum(match.confidence for match in matches) / len(matches)
    return round(max(0.0, min(0.9, coverage * average_match)), 3)


def _fdc_nutrients(raw_nutrients: Any) -> NutritionValues:
    values: dict[str, float] = {}
    if isinstance(raw_nutrients, list):
        for item in raw_nutrients:
            if not isinstance(item, dict):
                continue
            nutrient = item.get("nutrient")
            if not isinstance(nutrient, dict):
                continue
            key = FDC_NUTRIENT_MAP.get(nutrient.get("id"))
            if key is None:
                nutrient_name = _normalize_nutrient_name(nutrient.get("name"))
                key = FDC_NUTRIENT_NAME_MAP.get(nutrient_name)
            if key is None:
                continue
            if key == "calories_kcal" and _text(nutrient.get("unitName")).lower() != "kcal":
                continue
            amount = _number(item.get("amount"))
            if amount is not None:
                values[key] = amount

    return NutritionValues(
        calories_kcal=values.get("calories_kcal"),
        protein_g=values.get("protein_g"),
        carbohydrates_g=values.get("carbohydrates_g"),
        fat_g=values.get("fat_g"),
        fiber_g=values.get("fiber_g"),
        sugar_g=values.get("sugar_g"),
        sodium_mg=values.get("sodium_mg"),
    )


def _first_text(row: Any, keys: list[str]) -> str:
    for key in keys:
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _first_number(row: Any, keys: list[str]) -> float | None:
    for key in keys:
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _read_csv_with_encoding_fallback(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", "").strip()
    if not cleaned:
        return None
    match = re.search(r"[-+]?\d*\.?\d+", cleaned)
    if match is None:
        return None
    return float(match.group(0))


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _normalize_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _primary_name(value: str) -> str:
    without_parentheticals = re.sub(r"\([^)]*\)", " ", value)
    return re.split(r"[,;/]", without_parentheticals, maxsplit=1)[0].strip()


def _parenthetical_aliases(value: str) -> list[str]:
    return re.findall(r"\(([^)]*)\)", value)


def _normalize_nutrient_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _tokens(normalized: str) -> set[str]:
    tokens: set[str] = set()
    for token in normalized.split():
        if not token:
            continue
        tokens.add(token)
        if len(token) > 3 and token.endswith("s"):
            tokens.add(token[:-1])
    return tokens


def _distinct_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    distinct: list[str] = []
    for value in values:
        cleaned = _text(value)
        key = _normalize_name(cleaned)
        if not cleaned or not key or key in seen:
            continue
        seen.add(key)
        distinct.append(cleaned)
    return distinct


def _unique_warnings(warnings: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for warning in warnings:
        cleaned = warning.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique


nutrition_service = NutritionService()


def estimate_nutrition(payload: NutritionEstimateRequest) -> NutritionEstimateSuccess:
    return nutrition_service.estimate(payload)
