from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import groqApi
from app.main import app
from app.schemas.v1.plans import PlansGenerateRequest
from app.services.plan_service import (
    _simple_generated_plan,
    _to_openai_specs,
    _vitamin_d_range_label,
    generate_plan_from_request,
)
from groqApi import (
    DietPlanSpecs,
    OpenAIDietPlanGenerator,
    calculate_daily_calorie_targets,
)


client = TestClient(app)
VITAMIN_D_TERMS = (
    "sardine",
    "salmon",
    "tuna",
    "egg",
    "fortified milk",
    "fortified yogurt",
    "fortified soy milk",
    "mushroom",
)


def _marker(
    canonical_test_key: str = "vitamin_d_25oh_serum",
    *,
    test_name: str = "25(OH) Vitamin D, Serum",
    status: str = "below_range",
) -> dict:
    return {
        "report_id": 42,
        "test_name": test_name,
        "canonical_test_key": canonical_test_key,
        "result_value": 26.9,
        "unit": "ng/mL",
        "reference_interval_raw": "Deficiency <20\nInsufficiency 21-29\nSufficiency 30-100",
        "matched_band": "Insufficiency",
        "confirmed_at": "2026-05-18T10:15:30Z",
        "status": status,
    }


def _payload(
    *markers: dict,
    allergens: list[str] | None = None,
    dietary_exclusions: list[str] | None = None,
    plan_days: int = 1,
) -> dict:
    return {
        "profile": {
            "age_years": 30,
            "sex": "female",
            "height_cm": 170,
            "weight_kg": 70,
            "activity_level": "moderately_active",
            "goal": "improve_general_health",
            "allergens": allergens or [],
            "dietary_exclusions": dietary_exclusions or [],
            "exclusion_flags": [],
        },
        "below_range_lab_markers": list(markers),
        "plan_preferences": {
            "meals_per_day": 3,
            "plan_days": plan_days,
        },
    }


def _force_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingKeyGenerator:
        def __init__(self) -> None:
            raise groqApi.OpenAILLMError("Missing OPENAI_API_KEY")

    monkeypatch.setattr(groqApi, "OpenAIDietPlanGenerator", MissingKeyGenerator)


def _generated_plan_text(response) -> str:
    return json.dumps(response.generated_plan, sort_keys=True).casefold()


def _meal_plan_text(response) -> str:
    return json.dumps(response.generated_plan["plan"], sort_keys=True).casefold()


def _day_text(day: dict) -> str:
    return json.dumps(day, sort_keys=True).casefold()


def _has_vitamin_d_food(value: str) -> bool:
    return any(term in value for term in VITAMIN_D_TERMS)


def _assert_vitamin_d_food_per_day(response) -> None:
    for day in response.generated_plan["plan"]:
        assert _has_vitamin_d_food(_day_text(day)), day


def test_plan_schema_accepts_below_range_lab_markers() -> None:
    request = PlansGenerateRequest.model_validate(_payload(_marker()))

    assert len(request.below_range_lab_markers) == 1
    marker = request.below_range_lab_markers[0]
    assert marker.status == "below_range"
    assert marker.canonical_test_key == "vitamin_d_25oh_serum"


def test_plan_schema_rejects_non_below_range_lab_markers() -> None:
    with pytest.raises(ValidationError):
        PlansGenerateRequest.model_validate(_payload(_marker(status="within_range")))


def test_plan_generation_rejects_unsupported_below_range_lab_marker() -> None:
    response = client.post(
        "/v1/plans/generate",
        json=_payload(
            _marker(
                canonical_test_key="unsupported_marker",
                test_name="Unsupported Marker",
            )
        ),
    )

    assert response.status_code == 400
    assert (
        "Unsupported below-range lab marker"
        in response.json()["error"]["message"]
    )


def test_supported_lab_markers_are_included_in_llm_prompt() -> None:
    request = PlansGenerateRequest.model_validate(
        _payload(
            _marker(),
            _marker(
                canonical_test_key="ferritin_serum",
                test_name="Ferritin, Serum",
            ),
        )
    )

    specs, warnings = _to_openai_specs(request, DietPlanSpecs)
    calorie_targets = calculate_daily_calorie_targets(specs)
    generator = object.__new__(OpenAIDietPlanGenerator)
    prompt = generator.build_prompt(specs, calorie_targets)

    assert "below_range_lab_food_focuses" in prompt
    assert "vitamin D" in prompt
    assert "sardines" in prompt
    assert "iron" in prompt
    assert "Ferritin, Serum" in prompt
    assert any("this plan prioritizes vitamin D food sources" in warning for warning in warnings)


def test_vitamin_d_range_mapping() -> None:
    assert _vitamin_d_range_label(12.0, None) == "deficiency"
    assert _vitamin_d_range_label(26.9, None) == "insufficiency"
    assert _vitamin_d_range_label(40.0, None) == "sufficient"
    assert _vitamin_d_range_label(160.0, None) == "hypervitaminosis"
    assert _vitamin_d_range_label("not numeric", None) == "unclear"
    assert _vitamin_d_range_label(26.9, "Insufficiency") == "insufficiency"


def test_vitamin_d_insufficiency_changes_generated_meals_for_one_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_local_fallback(monkeypatch)
    request = PlansGenerateRequest.model_validate(_payload(_marker()))

    response = generate_plan_from_request(request)
    warnings = "\n".join(response.warnings or [])
    plan_text = _meal_plan_text(response)

    assert _has_vitamin_d_food(plan_text)
    assert any(meal.score.overall > 0.8 for meal in response.meals)
    assert "Because the submitted 25(OH) Vitamin D" in warnings
    assert "vitamin D" in warnings
    assert "supplement" not in plan_text


def test_vitamin_d_insufficiency_includes_food_source_each_requested_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_local_fallback(monkeypatch)
    request = PlansGenerateRequest.model_validate(
        _payload(_marker(), plan_days=3)
    )

    response = generate_plan_from_request(request)

    assert len(response.generated_plan["plan"]) == 3
    assert len(response.generated_plan["days"]) == 3
    _assert_vitamin_d_food_per_day(response)


def test_dairy_restriction_uses_non_dairy_vitamin_d_foods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_local_fallback(monkeypatch)
    request = PlansGenerateRequest.model_validate(
        _payload(_marker(), dietary_exclusions=["dairy"], plan_days=1)
    )

    response = generate_plan_from_request(request)
    plan_text = _meal_plan_text(response)

    assert "fortified yogurt" not in plan_text
    assert "fortified milk" not in plan_text
    assert _has_vitamin_d_food(plan_text)


def test_egg_allergy_avoids_eggs_for_vitamin_d_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_local_fallback(monkeypatch)
    request = PlansGenerateRequest.model_validate(
        _payload(_marker(), allergens=["egg"], plan_days=1)
    )

    response = generate_plan_from_request(request)
    plan_text = _meal_plan_text(response)

    assert "egg" not in plan_text
    assert _has_vitamin_d_food(plan_text)


def test_fish_allergy_avoids_fish_for_vitamin_d_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_local_fallback(monkeypatch)
    request = PlansGenerateRequest.model_validate(
        _payload(_marker(), allergens=["fish"], plan_days=1)
    )

    response = generate_plan_from_request(request)
    plan_text = _meal_plan_text(response)

    assert "sardine" not in plan_text
    assert "salmon" not in plan_text
    assert "tuna" not in plan_text
    assert _has_vitamin_d_food(plan_text)


def test_plan_generation_without_lab_markers_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_local_fallback(monkeypatch)
    request = PlansGenerateRequest.model_validate(_payload())

    response = generate_plan_from_request(request)
    warnings = "\n".join(response.warnings or [])

    assert response.meals
    assert "Lab-informed food focus" not in warnings


def test_default_plan_contains_no_pork(monkeypatch: pytest.MonkeyPatch) -> None:
    class PorkPlanGenerator:
        def generate_plan(self, specs, *, include_costs: bool = False):
            return {
                "support_status": "supported",
                "assumptions": [],
                "daily_summary": {"strategy": "LLM draft."},
                "plan": [
                    {
                        "day": 1,
                        "meals": [
                            {
                                "meal_type": "breakfast",
                                "meal_name": "Oats",
                                "estimated_calories_kcal": 500,
                                "ingredients": [
                                    {"item": "oats", "amount": 80, "unit": "g"}
                                ],
                            },
                            {
                                "meal_type": "lunch",
                                "meal_name": "Pork Tenderloin Rice Bowl",
                                "estimated_calories_kcal": 700,
                                "ingredients": [
                                    {
                                        "item": "pork tenderloin",
                                        "amount": 120,
                                        "unit": "g",
                                    },
                                    {"item": "rice", "amount": 120, "unit": "g"},
                                ],
                            },
                            {
                                "meal_type": "dinner",
                                "meal_name": "Vegetable Lentils",
                                "estimated_calories_kcal": 600,
                                "ingredients": [
                                    {"item": "lentils", "amount": 140, "unit": "g"}
                                ],
                            },
                        ],
                    }
                ],
                "notes": ["Avoid supplements."],
            }

    monkeypatch.setattr(groqApi, "OpenAIDietPlanGenerator", PorkPlanGenerator)
    request = PlansGenerateRequest.model_validate(_payload())

    response = generate_plan_from_request(request)
    plan_text = _meal_plan_text(response)

    assert "pork" not in plan_text
    assert "chicken" in plan_text
    assert "supplement" not in json.dumps(response.generated_plan["notes"]).casefold()


def test_llm_days_shape_is_canonicalized_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DaysShapeGenerator:
        def generate_plan(self, specs, *, include_costs: bool = False):
            return {
                "support_status": "supported",
                "assumptions": [],
                "daily_summary": {"strategy": "LLM draft."},
                "days": [
                    {
                        "day": day,
                        "meals": [
                            {
                                "meal_type": "breakfast",
                                "meal_name": "Egg Breakfast",
                                "estimated_calories_kcal": 500,
                                "ingredients": [
                                    {
                                        "item": "whole eggs",
                                        "amount": 2,
                                        "unit": "piece",
                                    }
                                ],
                            },
                            {
                                "meal_type": "lunch",
                                "meal_name": "Sardine Rice Bowl",
                                "estimated_calories_kcal": 700,
                                "ingredients": [
                                    {"item": "sardines", "amount": 130, "unit": "g"}
                                ],
                            },
                            {
                                "meal_type": "dinner",
                                "meal_name": "Lentils",
                                "estimated_calories_kcal": 600,
                                "ingredients": [
                                    {"item": "lentils", "amount": 140, "unit": "g"}
                                ],
                            },
                        ],
                    }
                    for day in range(1, 4)
                ],
            }

    monkeypatch.setattr(groqApi, "OpenAIDietPlanGenerator", DaysShapeGenerator)
    request = PlansGenerateRequest.model_validate(_payload(_marker(), plan_days=3))

    response = generate_plan_from_request(request)
    warnings = "\n".join(response.warnings or [])

    assert len(response.generated_plan["plan"]) == 3
    assert len(response.generated_plan["days"]) == 3
    assert "Generated plan contains 0 day(s)" not in warnings


def test_generic_llm_plan_gets_vitamin_d_food_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class GenericPlanGenerator:
        def generate_plan(self, specs, *, include_costs: bool = False):
            return {
                "support_status": "supported",
                "assumptions": [],
                "daily_summary": {"strategy": "LLM draft."},
                "plan": [
                    {
                        "day": 1,
                        "meals": [
                            {
                                "meal_type": "breakfast",
                                "meal_name": "Oats with Banana",
                                "estimated_calories_kcal": 500,
                                "ingredients": [
                                    {"item": "oats", "amount": 80, "unit": "g"},
                                    {"item": "banana", "amount": 1, "unit": "piece"},
                                ],
                            },
                            {
                                "meal_type": "lunch",
                                "meal_name": "Chicken Rice Bowl",
                                "estimated_calories_kcal": 700,
                                "ingredients": [
                                    {
                                        "item": "chicken breast",
                                        "amount": 140,
                                        "unit": "g",
                                    },
                                    {"item": "rice", "amount": 120, "unit": "g"},
                                ],
                            },
                            {
                                "meal_type": "dinner",
                                "meal_name": "Lentil Stew",
                                "estimated_calories_kcal": 600,
                                "ingredients": [
                                    {"item": "lentils", "amount": 140, "unit": "g"}
                                ],
                            },
                        ],
                    }
                ],
            }

    monkeypatch.setattr(groqApi, "OpenAIDietPlanGenerator", GenericPlanGenerator)
    request = PlansGenerateRequest.model_validate(_payload(_marker()))

    response = generate_plan_from_request(request)

    assert _has_vitamin_d_food(_meal_plan_text(response))
    assert response.support_status.reason.startswith(
        "Generated by Qima's backend-guided meal planner"
    )
    assert any(meal.score.overall > 0.8 for meal in response.meals)


def test_incomplete_llm_plan_falls_back_to_local_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyPlanGenerator:
        def generate_plan(self, specs, *, include_costs: bool = False):
            return {
                "support_status": "supported",
                "assumptions": [],
                "daily_summary": {"strategy": ""},
                "plan": [],
                "formatted_message": "Qima nutrition plan",
            }

    monkeypatch.setattr(groqApi, "OpenAIDietPlanGenerator", EmptyPlanGenerator)
    payload = _payload(_marker())
    payload["plan_preferences"]["plan_days"] = 3
    request = PlansGenerateRequest.model_validate(payload)

    response = generate_plan_from_request(request)
    warnings = "\n".join(response.warnings or [])

    assert len(response.generated_plan["plan"]) == 3
    assert "Day 3" in response.generated_plan["formatted_message"]
    assert response.support_status.reason.startswith(
        "Generated by Qima's backend-guided meal planner"
    )
    assert "LLM diet-plan response contained 0 day(s), but 3 were requested" in warnings
    assert "Generated plan contains 0 day(s)" not in warnings


def test_simple_generated_plan_includes_lab_foods_and_notes() -> None:
    request = PlansGenerateRequest.model_validate(_payload(_marker()))

    generated_plan, warnings = _simple_generated_plan(request)
    notes = "\n".join(generated_plan["notes"])
    plan_ingredients = json.dumps(generated_plan["plan"]).lower()

    assert warnings == []
    assert "this plan prioritizes vitamin D food sources" in notes
    assert _has_vitamin_d_food(plan_ingredients)
    assert "supplement" not in plan_ingredients
