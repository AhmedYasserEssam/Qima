from __future__ import annotations

import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.v1.plans import (
    BudgetTier,
    DataQuality,
    EstimatedCost,
    EstimatedNutrition,
    ExclusionFlag,
    MealCandidate,
    MealScore,
    MealSource,
    NutritionTargets,
    PlansGenerateRequest,
    PlansGenerateSuccess,
    Source,
    SupportStatus,
)
from app.services.exceptions import BadRequestError, UpstreamUnavailableError


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


ACTIVITY_TO_INTERNAL = {
    "sedentary": "sedentary",
    "lightly_active": "light",
    "moderately_active": "moderate",
    "very_active": "active",
    "athlete": "very_active",
}

GOAL_TO_INTERNAL = {
    "lose_weight": "weight_loss",
    "gain_muscle": "muscle_gain",
    "maintain_weight": "weight_maintenance",
    "improve_general_health": "healthy_eating",
}

ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

GOAL_ADJUSTMENTS = {
    "weight_loss": -500,
    "weight_maintenance": 0,
    "muscle_gain": 300,
    "healthy_eating": 0,
}

PROTEIN_CALORIE_SHARE = 0.30
CARBOHYDRATE_CALORIE_SHARE = 0.50
FAT_CALORIE_SHARE = 0.20

VITAMIN_D_PREFERRED_FOODS = [
    "sardines",
    "salmon",
    "tuna",
    "egg yolks",
    "whole eggs",
    "fortified milk",
    "fortified yogurt",
    "fortified soy milk",
    "mushrooms",
]
VITAMIN_D_FOOD_TERMS = (
    "sardine",
    "salmon",
    "tuna",
    "egg",
    "fortified milk",
    "fortified yogurt",
    "fortified soy milk",
    "mushroom",
)
PORK_REPLACEMENTS = {
    "pork tenderloin": "chicken breast",
    "pork chop": "chicken breast",
    "pork chops": "chicken breast",
    "pork loin": "chicken breast",
    "pork": "chicken",
    "bacon": "smoked turkey",
    "ham": "grilled chicken",
    "prosciutto": "grilled chicken",
}

LAB_FOOD_FOCUS_BY_MARKER: dict[str, dict[str, Any]] = {
    "vitamin_d_25oh_serum": {
        "nutrient_key": "vitamin_d",
        "nutrient": "vitamin D",
        "food_examples": VITAMIN_D_PREFERRED_FOODS,
    },
    "vitamin_b12_serum": {
        "nutrient": "vitamin B12",
        "food_examples": [
            "fish",
            "eggs",
            "dairy",
            "lean meat",
            "fortified cereals",
        ],
    },
    "folic_acid_serum": {
        "nutrient": "folate",
        "food_examples": [
            "lentils",
            "beans",
            "spinach",
            "leafy greens",
            "citrus",
        ],
    },
    "ferritin_serum": {
        "nutrient": "iron",
        "food_examples": [
            "lean beef",
            "lentils",
            "beans",
            "spinach",
            "fortified cereals",
        ],
    },
    "iron_serum": {
        "nutrient": "iron",
        "food_examples": [
            "lean beef",
            "lentils",
            "beans",
            "spinach",
            "fortified cereals",
        ],
    },
    "iron_total_serum": {
        "nutrient": "iron",
        "food_examples": [
            "lean beef",
            "lentils",
            "beans",
            "spinach",
            "fortified cereals",
        ],
    },
    "serum_iron": {
        "nutrient": "iron",
        "food_examples": [
            "lean beef",
            "lentils",
            "beans",
            "spinach",
            "fortified cereals",
        ],
    },
    "magnesium_serum": {
        "nutrient": "magnesium",
        "food_examples": [
            "nuts",
            "seeds",
            "legumes",
            "whole grains",
            "dark leafy greens",
        ],
    },
    "zinc_serum": {
        "nutrient": "zinc",
        "food_examples": [
            "beef",
            "seafood",
            "beans",
            "chickpeas",
            "pumpkin seeds",
        ],
    },
    "calcium_total_serum": {
        "nutrient": "calcium",
        "food_examples": [
            "milk",
            "yogurt",
            "cheese",
            "sardines with bones",
            "fortified soy milk",
        ],
    },
    "phosphorus_serum": {
        "nutrient": "phosphorus",
        "food_examples": [
            "fish",
            "poultry",
            "dairy",
            "lentils",
            "beans",
        ],
    },
}


def generate_plan_from_request(payload: PlansGenerateRequest) -> PlansGenerateSuccess:
    _lab_food_focuses(payload)

    if _has_exclusion(payload):
        return _fallback_response(
            payload,
            supported=False,
            reason="One or more safety checks require clinician-guided nutrition support.",
            warnings=[
                "Clinical safety check triggered. Please consult a qualified clinician.",
            ],
        )

    try:
        from groqApi import DietPlanSpecs, OpenAIDietPlanGenerator, OpenAILLMError
    except ImportError as exc:
        generated_plan, mapping_warnings = _simple_generated_plan(payload)
        mapping_warnings.append(
            f"LLM diet-plan integration is unavailable, so a local fallback was used: {exc}"
        )
        return _generated_plan_to_response(
            payload,
            generated_plan=generated_plan,
            mapping_warnings=mapping_warnings,
        )

    try:
        specs, mapping_warnings = _to_openai_specs(payload, DietPlanSpecs)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except ValidationError as exc:
        raise BadRequestError(str(exc)) from exc

    try:
        generator = OpenAIDietPlanGenerator()
        generated_plan = generator.generate_plan(specs, include_costs=False)
        generated_plan = _prepare_generated_plan(payload, generated_plan)
    except ValidationError as exc:
        raise BadRequestError(str(exc)) from exc
    except OpenAILLMError as exc:
        message = str(exc)
        if "Missing OPENAI_API_KEY" in message:
            generated_plan, fallback_warnings = _simple_generated_plan(payload)
            return _generated_plan_to_response(
                payload,
                generated_plan=generated_plan,
                mapping_warnings=[
                    *mapping_warnings,
                    *fallback_warnings,
                    "OPENAI_API_KEY is not configured, so Qima returned a local fallback plan.",
                ],
            )
        raise UpstreamUnavailableError(message) from exc

    incomplete_reason = _generated_plan_incomplete_reason(payload, generated_plan)
    if incomplete_reason is not None:
        generated_plan, fallback_warnings = _simple_generated_plan(payload)
        return _generated_plan_to_response(
            payload,
            generated_plan=generated_plan,
            mapping_warnings=[
                *mapping_warnings,
                *fallback_warnings,
                f"{incomplete_reason} Qima returned a local fallback plan.",
            ],
        )

    return _generated_plan_to_response(
        payload,
        generated_plan=generated_plan,
        mapping_warnings=mapping_warnings,
    )


def _to_openai_specs(
    payload: PlansGenerateRequest,
    diet_plan_specs_type: type[Any],
) -> tuple[Any, list[str]]:
    if payload.profile is None:
        raise ValueError("Inline profile is required for LLM plan generation.")

    profile = payload.profile
    warnings: list[str] = []
    sex = _enum_value(profile.sex)
    if sex not in {"male", "female"}:
        sex = "female"
        warnings.append(
            "Profile sex was not male/female; calorie calculation used the more conservative female Mifflin-St Jeor branch."
        )

    dietary_restrictions = [
        _enum_value(item) for item in profile.dietary_exclusions
    ]
    dietary_restrictions.extend(_enum_value(item) for item in payload.dietary_filters)
    dietary_restrictions = sorted({item for item in dietary_restrictions if item})
    lab_food_focuses = _lab_food_focuses(payload)
    warnings.extend(_lab_food_focus_notes(lab_food_focuses))

    return (
        diet_plan_specs_type(
            age=profile.age_years,
            sex=sex,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity_level=ACTIVITY_TO_INTERNAL[_enum_value(profile.activity_level)],
            nutrition_goal=GOAL_TO_INTERNAL[_enum_value(profile.goal)],
            dietary_restrictions=dietary_restrictions,
            allergens=[_enum_value(item) for item in profile.allergens],
            meals_per_day=_requested_meals_per_day(payload),
            plan_days=_requested_plan_days(payload),
            disliked_foods=payload.disliked_foods,
            preferred_foods=[item.name for item in payload.pantry or []],
            lab_food_focuses=lab_food_focuses,
            budget=_budget_level(payload),
            pregnant_or_breastfeeding=False,
            eating_disorder_history=False,
            underweight=False,
            diabetes=False,
            kidney_disease=False,
            heart_disease=False,
            requires_clinical_diet=False,
        ),
        warnings,
    )


def _simple_generated_plan(
    payload: PlansGenerateRequest,
) -> tuple[dict[str, Any], list[str]]:
    if payload.profile is None:
        raise ValueError("Inline profile is required for plan generation.")

    profile = payload.profile
    warnings: list[str] = []
    sex = _enum_value(profile.sex)
    if sex not in {"male", "female"}:
        sex = "female"
        warnings.append(
            "Profile sex was not male/female; calorie calculation used the more conservative female Mifflin-St Jeor branch."
        )

    plan_days = _requested_plan_days(payload)
    meals_per_day = _requested_meals_per_day(payload)
    target_calories = _estimate_target_calories(payload)
    meal_calories = _meal_calorie_allocations(round(target_calories), meals_per_day)
    macros = _macro_targets(target_calories)
    lab_food_focuses = _lab_food_focuses(payload)
    lab_notes = _lab_food_focus_notes(lab_food_focuses)
    shopping_totals: dict[tuple[str, str], float] = {}
    days: list[dict[str, Any]] = []

    for day_number in range(1, plan_days + 1):
        meals: list[dict[str, Any]] = []
        focus_meal_index = 1 if len(meal_calories) > 1 else 0
        for meal_index, calories in enumerate(meal_calories):
            meal = _simple_meal(
                payload,
                meal_index,
                calories,
                day_number=day_number,
                use_lab_focus=_has_vitamin_d_focus(lab_food_focuses)
                and meal_index == focus_meal_index,
            )
            meals.append(meal)
            for ingredient in meal["ingredients"]:
                key = (ingredient["item"], ingredient["unit"])
                shopping_totals[key] = shopping_totals.get(key, 0.0) + float(
                    ingredient["amount"]
                )
        days.append({"day": day_number, "meals": meals})

    calorie_check = [
        {
            "day": day["day"],
            "sum_of_meal_calories_kcal": sum(
                meal["estimated_calories_kcal"] for meal in day["meals"]
            ),
            "target_daily_calories_kcal": round(target_calories),
            "difference_kcal": 0,
            "within_100_kcal": True,
        }
        for day in days
    ]

    return (
        {
            "support_status": "supported",
            "safety_flags": [],
            "assumptions": [
                "Generated locally for speed using simple balanced meal templates."
            ],
            "calorie_target": {
                "target_daily_calories_kcal": round(target_calories),
                "estimated_calories_per_meal_kcal": round(
                    target_calories / meals_per_day
                ),
                **macros,
                "method": "Mifflin-St Jeor BMR x activity factor + goal adjustment",
            },
            "backend_calorie_targets": {
                "target_daily_calories_kcal": round(target_calories),
                "estimated_calories_per_meal_kcal": round(
                    target_calories / meals_per_day
                ),
                **macros,
            },
            "daily_summary": {
                "goal": _enum_value(profile.goal),
                "strategy": "Backend-guided plan with simple portions, safety boundaries, and lab-informed food rules where provided.",
                "estimated_budget_level": _budget_level(payload),
                "estimated_total_daily_calories_kcal": round(target_calories),
            },
            "plan": days,
            "days": days,
            "shopping_list": [
                {
                    "item": item,
                    "total_amount": round(amount, 1),
                    "unit": unit,
                    "category": _ingredient_category(item),
                    "priority": "must_have",
                }
                for (item, unit), amount in sorted(shopping_totals.items())
            ],
            "backend_meal_calorie_check": {
                "target_daily_calories_kcal": round(target_calories),
                "daily_checks": calorie_check,
                "all_days_within_100_kcal": True,
            },
            "notes": [
                "This is general food guidance only, not diagnosis or clinical diet therapy.",
                *lab_notes,
            ],
        },
        warnings,
    )


def _simple_meal(
    payload: PlansGenerateRequest,
    meal_index: int,
    calories: int,
    *,
    day_number: int,
    use_lab_focus: bool = False,
) -> dict[str, Any]:
    restrictions = {
        _enum_value(item)
        for item in [
            *(payload.profile.dietary_exclusions if payload.profile else []),
            *payload.dietary_filters,
        ]
    }
    allergens = {
        _enum_value(item)
        for item in (payload.profile.allergens if payload.profile else [])
    }
    disliked = {item.strip().lower() for item in payload.disliked_foods}
    vegetarian = bool(restrictions & {"vegetarian", "vegan", "meat", "poultry"})
    vegan = "vegan" in restrictions
    no_dairy = vegan or "dairy" in restrictions or "milk" in allergens

    meal_type = _meal_type_for_index(meal_index)
    if use_lab_focus:
        return _vitamin_d_template_meal(
            payload=payload,
            meal_type=meal_type,
            calories=calories,
            day_number=day_number,
        )

    if meal_type == "breakfast":
        if no_dairy and "soy" in allergens:
            milk = "water"
        elif no_dairy:
            milk = "soy milk"
        else:
            milk = "milk"
        meal_name = "Oats with Banana"
        ingredients = [
            {"item": "oats", "amount": 80, "unit": "g"},
            {"item": "banana", "amount": 1, "unit": "piece"},
            {"item": milk, "amount": 200, "unit": "ml"},
        ]
    elif meal_type == "lunch":
        protein = "lentils" if vegetarian else "chicken breast"
        meal_name = "Lentil Rice Bowl" if vegetarian else "Chicken Rice Bowl"
        ingredients = [
            {"item": protein, "amount": 150, "unit": "g"},
            {"item": "rice", "amount": 120, "unit": "g"},
            {"item": "mixed vegetables", "amount": 150, "unit": "g"},
            {"item": "olive oil", "amount": 10, "unit": "g"},
        ]
    elif meal_type == "dinner":
        meal_name = "Lentil Vegetable Stew"
        ingredients = [
            {"item": "lentils", "amount": 120, "unit": "g"},
            {"item": "potatoes", "amount": 200, "unit": "g"},
            {"item": "carrots", "amount": 100, "unit": "g"},
            {"item": "olive oil", "amount": 10, "unit": "g"},
        ]
    else:
        snack = "apple" if no_dairy else "yogurt"
        meal_name = "Apple Oat Snack" if no_dairy else "Yogurt Oat Snack"
        ingredients = [
            {
                "item": snack,
                "amount": 1 if no_dairy else 170,
                "unit": "piece" if no_dairy else "g",
            },
            {"item": "oats", "amount": 30, "unit": "g"},
        ]

    for ingredient in ingredients:
        if ingredient["item"].lower() in disliked:
            ingredient["item"] = "seasonal vegetables"

    return {
        "meal_type": meal_type,
        "meal_name": meal_name,
        "estimated_calories_kcal": calories,
        "ingredients": ingredients,
        "preparation_steps": [
            "Cook staple ingredients until tender.",
            "Combine with vegetables and protein.",
            "Season simply while avoiding listed allergens and disliked foods.",
        ],
        "why_it_fits": "Simple balanced meal with carbohydrates, protein, vegetables, and moderate fat.",
        "allergen_check": "Avoids listed allergens using simple substitutions where possible.",
        "budget_fit": f"Uses common ingredients suitable for a {_budget_level(payload)} budget.",
    }


def _vitamin_d_template_meal(
    *,
    payload: PlansGenerateRequest,
    meal_type: str,
    calories: int,
    day_number: int,
) -> dict[str, Any]:
    flags = _food_restriction_flags(payload)
    if meal_type == "breakfast":
        if not flags["no_eggs"]:
            milk = _fortified_drink_or_side(flags)
            ingredients = [
                {"item": "whole eggs", "amount": 2, "unit": "piece"},
                {"item": "whole-grain bread", "amount": 2, "unit": "piece"},
                {"item": "mushrooms", "amount": 80, "unit": "g"},
            ]
            if milk is not None:
                ingredients.append(milk)
            return _meal_payload(
                meal_type=meal_type,
                meal_name="Eggs with Mushrooms and Whole-Grain Bread",
                calories=calories,
                ingredients=ingredients,
                why_it_fits="Includes whole eggs and mushrooms as food sources that support the vitamin D focus.",
                payload=payload,
            )

        if not flags["no_dairy"]:
            return _meal_payload(
                meal_type=meal_type,
                meal_name="Fortified Yogurt Oats with Mushrooms",
                calories=calories,
                ingredients=[
                    {"item": "fortified yogurt", "amount": 200, "unit": "g"},
                    {"item": "oats", "amount": 60, "unit": "g"},
                    {"item": "mushrooms", "amount": 80, "unit": "g"},
                ],
                why_it_fits="Uses fortified yogurt and mushrooms as food sources that support the vitamin D focus.",
                payload=payload,
            )

        return _meal_payload(
            meal_type=meal_type,
            meal_name="Mushroom Breakfast Bowl",
            calories=calories,
            ingredients=[
                {"item": "mushrooms", "amount": 140, "unit": "g"},
                {"item": "oats", "amount": 70, "unit": "g"},
                {"item": "banana", "amount": 1, "unit": "piece"},
            ],
            why_it_fits="Uses mushrooms as a food-based vitamin D focus while avoiding restricted dairy and eggs.",
            payload=payload,
        )

    if not flags["no_fish"]:
        fish = _vitamin_d_fish_choice(payload, day_number)
        staple = "rice" if meal_type != "dinner" else "potatoes"
        return _meal_payload(
            meal_type=meal_type,
            meal_name=f"{fish.title()} {'Rice Bowl' if staple == 'rice' else 'Dinner Plate'}",
            calories=calories,
            ingredients=[
                {"item": fish, "amount": 130, "unit": "g"},
                {"item": staple, "amount": 150, "unit": "g"},
                {"item": "mixed vegetables", "amount": 180, "unit": "g"},
                {"item": "olive oil", "amount": 10, "unit": "g"},
            ],
            why_it_fits=f"Includes {fish} as a vitamin-D-focused food source while keeping the meal food-oriented.",
            payload=payload,
        )

    if not flags["no_eggs"]:
        return _meal_payload(
            meal_type=meal_type,
            meal_name="Egg and Mushroom Rice Bowl",
            calories=calories,
            ingredients=[
                {"item": "whole eggs", "amount": 2, "unit": "piece"},
                {"item": "mushrooms", "amount": 120, "unit": "g"},
                {"item": "rice", "amount": 130, "unit": "g"},
                {"item": "mixed vegetables", "amount": 150, "unit": "g"},
            ],
            why_it_fits="Uses whole eggs and mushrooms as food sources that support the vitamin D focus without fish.",
            payload=payload,
        )

    if not flags["no_dairy"]:
        return _meal_payload(
            meal_type=meal_type,
            meal_name="Fortified Yogurt Lentil Bowl",
            calories=calories,
            ingredients=[
                {"item": "fortified yogurt", "amount": 200, "unit": "g"},
                {"item": "lentils", "amount": 140, "unit": "g"},
                {"item": "rice", "amount": 100, "unit": "g"},
                {"item": "mushrooms", "amount": 100, "unit": "g"},
            ],
            why_it_fits="Uses fortified yogurt and mushrooms as food sources that support the vitamin D focus without fish or eggs.",
            payload=payload,
        )

    dairy_alternative = (
        [{"item": "fortified soy milk", "amount": 250, "unit": "ml"}]
        if not flags["no_soy"]
        else []
    )
    return _meal_payload(
        meal_type=meal_type,
        meal_name="Mushroom Lentil Bowl",
        calories=calories,
        ingredients=[
            {"item": "mushrooms", "amount": 160, "unit": "g"},
            {"item": "lentils", "amount": 140, "unit": "g"},
            {"item": "rice", "amount": 120, "unit": "g"},
            *dairy_alternative,
        ],
        why_it_fits="Uses mushrooms and compatible fortified dairy alternatives where possible for food-based vitamin D support.",
        payload=payload,
    )


def _meal_payload(
    *,
    meal_type: str,
    meal_name: str,
    calories: int,
    ingredients: list[dict[str, Any]],
    why_it_fits: str,
    payload: PlansGenerateRequest,
) -> dict[str, Any]:
    return {
        "meal_type": meal_type,
        "meal_name": meal_name,
        "estimated_calories_kcal": calories,
        "ingredients": ingredients,
        "preparation_steps": [
            "Cook staple ingredients until tender.",
            "Prepare protein or vitamin-D-focused foods safely.",
            "Combine with vegetables while avoiding listed allergens and restrictions.",
        ],
        "why_it_fits": why_it_fits,
        "allergen_check": "Avoids listed allergens using simple substitutions where possible.",
        "budget_fit": f"Uses common ingredients suitable for a {_budget_level(payload)} budget.",
    }


def _vitamin_d_fish_choice(payload: PlansGenerateRequest, day_number: int) -> str:
    budget = _budget_level(payload)
    if budget == "low":
        options = ["sardines", "tuna"]
    elif budget == "expensive":
        options = ["salmon", "sardines", "tuna"]
    else:
        options = ["sardines", "tuna", "salmon"]
    return options[(day_number - 1) % len(options)]


def _fortified_drink_or_side(flags: dict[str, bool]) -> dict[str, Any] | None:
    if not flags["no_dairy"]:
        return {"item": "fortified milk", "amount": 250, "unit": "ml"}
    if not flags["no_soy"]:
        return {"item": "fortified soy milk", "amount": 250, "unit": "ml"}
    return None


def _food_restriction_flags(payload: PlansGenerateRequest) -> dict[str, bool]:
    restrictions = {
        _enum_value(item)
        for item in [
            *(payload.profile.dietary_exclusions if payload.profile else []),
            *payload.dietary_filters,
        ]
    }
    allergens = {
        _enum_value(item)
        for item in (payload.profile.allergens if payload.profile else [])
    }
    vegan = "vegan" in restrictions
    vegetarian = bool(restrictions & {"vegetarian", "vegan"})
    return {
        "no_fish": vegan
        or vegetarian
        or "fish" in restrictions
        or "fish" in allergens,
        "no_eggs": vegan
        or "eggs" in restrictions
        or "egg" in allergens,
        "no_dairy": vegan
        or "dairy" in restrictions
        or "milk" in allergens,
        "no_soy": "soy" in restrictions or "soy" in allergens,
    }


def _lab_food_focuses(payload: PlansGenerateRequest) -> list[dict[str, Any]]:
    focuses: list[dict[str, Any]] = []
    unsupported: list[str] = []

    for marker in payload.below_range_lab_markers:
        canonical_key = marker.canonical_test_key.strip()
        focus = LAB_FOOD_FOCUS_BY_MARKER.get(canonical_key)
        if focus is None:
            unsupported.append(f"{marker.test_name} ({canonical_key})")
            continue

        range_label = (
            _vitamin_d_range_label(marker.result_value, marker.matched_band)
            if canonical_key == "vitamin_d_25oh_serum"
            else "below_range"
        )
        preferred_foods = list(focus["food_examples"])
        nutrient_label = str(focus["nutrient"])
        nutrient_key = str(focus.get("nutrient_key") or nutrient_label.lower())
        if canonical_key == "vitamin_d_25oh_serum":
            reason = _vitamin_d_focus_reason(range_label)
        else:
            reason = f"{marker.test_name} is below range."

        focuses.append(
            {
                "test_name": marker.test_name,
                "canonical_test_key": canonical_key,
                "status": marker.status,
                "range": range_label,
                "result": _format_lab_result(marker.result_value, marker.unit),
                "matched_band": marker.matched_band,
                "reference_interval_raw": marker.reference_interval_raw,
                "confirmed_at": marker.confirmed_at.isoformat()
                if marker.confirmed_at is not None
                else None,
                "nutrient_focus": nutrient_key,
                "nutrient_label": nutrient_label,
                "preferred_foods": preferred_foods,
                "food_examples": preferred_foods,
                "avoid_overclaiming": True,
                "reason": reason,
            }
        )

    if unsupported:
        raise BadRequestError(
            "Unsupported below-range lab marker(s) for dietary planning: "
            + "; ".join(unsupported)
        )

    return focuses


def _vitamin_d_range_label(
    result_value: Any,
    matched_band: str | None,
) -> str:
    normalized_band = " ".join(str(matched_band or "").casefold().split())
    if normalized_band in {
        "deficiency",
        "insufficiency",
        "sufficiency",
        "hypervitaminosis",
    }:
        return "sufficient" if normalized_band == "sufficiency" else normalized_band

    value = _numeric_lab_value(result_value)
    if value is None:
        return "unclear"
    if value < 20:
        return "deficiency"
    if 21 <= value <= 29:
        return "insufficiency"
    if 30 <= value <= 100:
        return "sufficient"
    if value > 150:
        return "hypervitaminosis"
    return "unclear"


def _numeric_lab_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if raw.startswith(("<", ">", "=")):
        raw = raw.lstrip("<>=").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _vitamin_d_focus_reason(range_label: str) -> str:
    if range_label == "deficiency":
        return "25(OH) Vitamin D is in the deficiency range."
    if range_label == "insufficiency":
        return "25(OH) Vitamin D is in the insufficiency range."
    if range_label == "sufficient":
        return "25(OH) Vitamin D is in the sufficiency range."
    if range_label == "hypervitaminosis":
        return "25(OH) Vitamin D is in the hypervitaminosis range."
    return "25(OH) Vitamin D is below range, but the exact categorical band is unclear."


def _format_lab_result(value: Any, unit: str | None) -> str:
    display = "unavailable" if value is None else str(value).strip()
    unit_label = str(unit or "").strip()
    if not unit_label:
        return display
    return f"{display} {unit_label}"


def _lab_food_focus_notes(focuses: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for focus in focuses:
        foods = ", ".join(str(item) for item in focus["preferred_foods"][:4])
        notes.append(
            f"Because the submitted {focus['test_name']} value falls in the "
            f"{focus['range']} range, this plan prioritizes "
            f"{focus['nutrient_label']} food sources such as {foods} where "
            "compatible with the profile."
        )
    return notes


def _has_vitamin_d_focus(focuses: list[dict[str, Any]]) -> bool:
    return any(focus.get("nutrient_focus") == "vitamin_d" for focus in focuses)


def _requested_plan_days(payload: PlansGenerateRequest) -> int:
    if payload.plan_preferences and payload.plan_preferences.plan_days is not None:
        return payload.plan_preferences.plan_days
    return 1


def _requested_meals_per_day(payload: PlansGenerateRequest) -> int:
    preferences = payload.plan_preferences
    if preferences and preferences.meals_per_day is not None:
        return preferences.meals_per_day
    if preferences and preferences.meal_count is not None:
        return preferences.meal_count
    return 3


def _meal_type_for_index(meal_index: int) -> str:
    meal_types = ["breakfast", "lunch", "dinner"]
    return meal_types[meal_index] if meal_index < len(meal_types) else "snack"


def _meal_calorie_allocations(target: int, meals_per_day: int) -> list[int]:
    patterns = {
        1: [1.0],
        2: [0.4, 0.6],
        3: [0.3, 0.4, 0.3],
        4: [0.25, 0.35, 0.3, 0.1],
        5: [0.22, 0.3, 0.28, 0.1, 0.1],
        6: [0.2, 0.25, 0.25, 0.1, 0.1, 0.1],
    }
    weights = patterns.get(meals_per_day, [1 / meals_per_day] * meals_per_day)
    allocations = [round(target * weight) for weight in weights]
    allocations[-1] += target - sum(allocations)
    return allocations


def _macro_targets(target_calories: float) -> dict[str, float]:
    return {
        "protein_g": round((target_calories * PROTEIN_CALORIE_SHARE) / 4, 1),
        "carbohydrates_g": round((target_calories * CARBOHYDRATE_CALORIE_SHARE) / 4, 1),
        "fat_g": round((target_calories * FAT_CALORIE_SHARE) / 9, 1),
    }


def _ingredient_category(item: str) -> str:
    low = item.lower()
    if any(token in low for token in ["chicken", "lentils", "yogurt"]):
        return "protein"
    if any(token in low for token in ["rice", "oats", "potatoes"]):
        return "carbohydrate"
    if any(token in low for token in ["banana", "apple"]):
        return "fruit"
    if "milk" in low:
        return "dairy"
    if "oil" in low:
        return "fat"
    if any(token in low for token in ["vegetables", "carrots"]):
        return "vegetable"
    return "other"


def _prepare_generated_plan(
    payload: PlansGenerateRequest,
    generated_plan: dict[str, Any],
) -> dict[str, Any]:
    _canonicalize_generated_plan_shape(generated_plan)
    _sanitize_generated_plan_meals(generated_plan)
    _ensure_lab_food_focus_in_generated_plan(payload, generated_plan)
    _canonicalize_generated_plan_shape(generated_plan)
    _refresh_formatted_message(generated_plan)
    return generated_plan


def _canonicalize_generated_plan_shape(generated_plan: dict[str, Any]) -> None:
    plan = generated_plan.get("plan")
    if isinstance(plan, dict):
        nested_days = plan.get("days") or plan.get("plan")
        if isinstance(nested_days, list):
            plan = nested_days

    if not isinstance(plan, list):
        days = generated_plan.get("days")
        if isinstance(days, list):
            plan = days

    if isinstance(plan, list):
        generated_plan["plan"] = plan
        generated_plan["days"] = plan


def _generated_plan_days(generated_plan: dict[str, Any]) -> list[Any]:
    _canonicalize_generated_plan_shape(generated_plan)
    plan = generated_plan.get("plan")
    return plan if isinstance(plan, list) else []


def _ensure_lab_food_focus_in_generated_plan(
    payload: PlansGenerateRequest,
    generated_plan: dict[str, Any],
) -> None:
    lab_food_focuses = _lab_food_focuses(payload)
    if not _has_vitamin_d_focus(lab_food_focuses):
        return

    days = _generated_plan_days(generated_plan)
    if not days:
        return

    changed = False
    for day_index, day in enumerate(days, start=1):
        if not isinstance(day, dict):
            continue
        meals = day.get("meals")
        if not isinstance(meals, list) or not meals:
            continue
        if _meals_include_vitamin_d_food(meals):
            continue

        target_index = 1 if len(meals) > 1 else 0
        current_meal = meals[target_index]
        meal_type = "lunch"
        calories = round(_estimate_target_calories(payload) / max(len(meals), 1))
        if isinstance(current_meal, dict):
            meal_type = str(current_meal.get("meal_type") or meal_type)
            calories = int(_number(current_meal.get("estimated_calories_kcal")) or calories)
        meals[target_index] = _vitamin_d_template_meal(
            payload=payload,
            meal_type=meal_type if meal_type in {"breakfast", "lunch", "dinner", "snack"} else "lunch",
            calories=calories,
            day_number=day_index,
        )
        changed = True

    generated_plan["backend_guidance_applied"] = True
    generated_plan["lab_food_focuses"] = lab_food_focuses
    assumptions = generated_plan.setdefault("assumptions", [])
    if isinstance(assumptions, list):
        assumptions.append(
            "Backend lab-informed food rules "
            + (
                "ensured vitamin-D-focused foods appear in the meal plan."
                if changed
                else "verified vitamin-D-focused foods in the meal plan."
            )
        )
    notes = generated_plan.setdefault("notes", [])
    if isinstance(notes, list):
        for note in _lab_food_focus_notes(lab_food_focuses):
            if note not in notes:
                notes.append(note)


def _meals_include_vitamin_d_food(meals: list[Any]) -> bool:
    return any(
        _text_contains_vitamin_d_food(jsonish)
        for jsonish in meals
        if isinstance(jsonish, dict)
    )


def _text_contains_vitamin_d_food(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.casefold()
        return any(term in lowered for term in VITAMIN_D_FOOD_TERMS)
    if isinstance(value, dict):
        return any(_text_contains_vitamin_d_food(item) for item in value.values())
    if isinstance(value, list):
        return any(_text_contains_vitamin_d_food(item) for item in value)
    return False


def _sanitize_generated_plan_meals(generated_plan: dict[str, Any]) -> None:
    for day in _generated_plan_days(generated_plan):
        if not isinstance(day, dict):
            continue
        meals = day.get("meals")
        if isinstance(meals, list):
            for meal in meals:
                if isinstance(meal, dict):
                    _sanitize_mapping_text(meal)

    shopping_list = generated_plan.get("shopping_list")
    if isinstance(shopping_list, list):
        for item in shopping_list:
            if isinstance(item, dict):
                _sanitize_mapping_text(item)

    notes = generated_plan.get("notes")
    if isinstance(notes, list):
        generated_plan["notes"] = [
            _sanitize_supplement_text(str(note)) for note in notes
        ]


def _sanitize_mapping_text(mapping: dict[str, Any]) -> None:
    for key, value in list(mapping.items()):
        if isinstance(value, str):
            mapping[key] = _sanitize_supplement_text(_replace_pork_text(value))
        elif isinstance(value, dict):
            _sanitize_mapping_text(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _sanitize_mapping_text(item)
            mapping[key] = [
                _sanitize_supplement_text(_replace_pork_text(item))
                if isinstance(item, str)
                else item
                for item in value
            ]


def _replace_pork_text(value: str) -> str:
    result = value
    for pork_term, replacement in PORK_REPLACEMENTS.items():
        result = re.sub(
            rf"\b{re.escape(pork_term)}\b",
            replacement,
            result,
            flags=re.IGNORECASE,
        )
    return result


def _sanitize_supplement_text(value: str) -> str:
    result = re.sub(
        r"\bvitamin\s+d\s+supplements?\b",
        "vitamin-D-rich foods",
        value,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"\bsupplements?\b",
        "food sources",
        result,
        flags=re.IGNORECASE,
    )
    return result


def _refresh_formatted_message(generated_plan: dict[str, Any]) -> None:
    try:
        from groqApi import format_diet_plan_message
    except ImportError:
        generated_plan.pop("formatted_message", None)
        return
    generated_plan["formatted_message"] = format_diet_plan_message(generated_plan)


def _generated_plan_to_response(
    payload: PlansGenerateRequest,
    *,
    generated_plan: dict[str, Any],
    mapping_warnings: list[str],
) -> PlansGenerateSuccess:
    generated_plan = _prepare_generated_plan(payload, generated_plan)
    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    calorie_targets = generated_plan.get("backend_calorie_targets") or {}
    target_calories = _number(
        calorie_targets.get("target_daily_calories_kcal")
        or generated_plan.get("calorie_target", {}).get("target_daily_calories_kcal")
    )
    meals = _meal_candidates_from_generated_plan(plan_id, payload, generated_plan)
    generation_reason = _generation_reason(generated_plan)
    warnings = [
        *mapping_warnings,
        *_generated_plan_quality_warnings(payload, generated_plan),
        *[str(item) for item in generated_plan.get("notes") or []],
    ]
    warnings.extend(str(item) for item in generated_plan.get("warnings") or [])

    return PlansGenerateSuccess(
        plan_id=plan_id,
        support_status=SupportStatus(
            status="supported",
            reason=generation_reason,
        ),
        nutrition_targets=NutritionTargets(
            calories_kcal=target_calories,
            protein_g=_number(calorie_targets.get("protein_g")),
            carbohydrates_g=_number(calorie_targets.get("carbohydrates_g")),
            fat_g=_number(calorie_targets.get("fat_g")),
            target_basis="estimated",
        ),
        meals=meals,
        rationale=_rationale_from_generated_plan(generated_plan),
        safety_flags=[
            "non_diagnostic",
            "no_treatment_advice",
            "no_supplement_prescription",
            "general_information_only",
            "estimated_targets_only",
            "estimated_cost_only",
        ],
        source=Source(
            provider="qima_backend",
            source_type="meal_plan_ranker",
            fetched_at=datetime.now(UTC),
        ),
        data_quality=DataQuality(completeness="partial"),
        warnings=warnings or None,
        generated_plan=generated_plan,
    )


def _meal_candidates_from_generated_plan(
    plan_id: str,
    payload: PlansGenerateRequest,
    generated_plan: dict[str, Any],
) -> list[MealCandidate]:
    pantry_items = {
        item.name.strip().lower()
        for item in payload.pantry or []
        if item.name.strip()
    }
    candidates: list[MealCandidate] = []

    for day in _generated_plan_days(generated_plan):
        day_number = day.get("day", len(candidates) + 1) if isinstance(day, dict) else 1
        for meal in (day.get("meals") or []) if isinstance(day, dict) else []:
            if not isinstance(meal, dict):
                continue

            ingredients = [
                str(ingredient.get("item")).strip()
                for ingredient in meal.get("ingredients") or []
                if isinstance(ingredient, dict) and str(ingredient.get("item", "")).strip()
            ]
            matched = [
                ingredient
                for ingredient in ingredients
                if ingredient.lower() in pantry_items
            ]
            missing = [
                ingredient
                for ingredient in ingredients
                if ingredient.lower() not in pantry_items
            ]
            meal_type = str(meal.get("meal_type") or "unspecified").strip()
            if meal_type not in {"breakfast", "lunch", "dinner", "snack"}:
                meal_type = "unspecified"

            cost_estimate = meal.get("cost_estimate") or {}
            total_cost = _number(cost_estimate.get("estimated_total_cost_egp"))
            estimate_quality = "partial" if total_cost is not None else "unavailable"
            lab_boost = _meal_lab_focus_score_boost(payload, ingredients)
            meal_warnings = [
                value
                for value in [
                    str(meal.get("allergen_check") or "").strip(),
                    str(meal.get("budget_fit") or "").strip(),
                ]
                if value
            ]
            if lab_boost > 0:
                meal_warnings.append(
                    "Includes vitamin-D-focused foods because of the submitted below-range lab marker."
                )

            candidates.append(
                MealCandidate(
                    meal_id=f"{plan_id}_day{day_number}_meal{len(candidates) + 1}",
                    title=str(meal.get("meal_name") or "Generated meal"),
                    meal_type=meal_type,
                    matched_ingredients=matched,
                    missing_ingredients=missing,
                    estimated_nutrition=EstimatedNutrition(
                        calories_kcal=_number(meal.get("estimated_calories_kcal")),
                        protein_g=None,
                        carbohydrates_g=None,
                        fat_g=None,
                    ),
                    estimated_cost=EstimatedCost(
                        total_cost=total_cost,
                        currency="EGP",
                        estimate_quality=estimate_quality,
                    ),
                    score=MealScore(
                        overall=min(1.0, 0.8 + lab_boost),
                        ingredient_match=0.75 if matched else 0.5,
                        target_fit=min(1.0, 0.8 + (lab_boost / 2)),
                        cost_fit=0.75,
                        safety_score=1,
                    ),
                    warnings=meal_warnings,
                    source=MealSource(source_type="mixed_sources"),
                )
            )

    return candidates or _fallback_meals(payload)


def _meal_lab_focus_score_boost(
    payload: PlansGenerateRequest,
    ingredients: list[str],
) -> float:
    if not _has_vitamin_d_focus(_lab_food_focuses(payload)):
        return 0.0
    if _text_contains_vitamin_d_food(ingredients):
        return 0.12
    return 0.0


def _generation_reason(generated_plan: dict[str, Any]) -> str:
    if generated_plan.get("backend_guidance_applied"):
        return (
            "Generated by Qima's backend-guided meal planner using the submitted "
            "profile, lab-informed food rules, and plan preferences."
        )

    assumptions = [
        str(item).lower()
        for item in generated_plan.get("assumptions") or []
    ]
    if any("generated locally" in item for item in assumptions):
        return "Generated locally using the submitted profile and plan preferences."

    return "Generated by the diet-plan LLM using the submitted profile and plan preferences."


def _fallback_response(
    payload: PlansGenerateRequest,
    *,
    supported: bool,
    reason: str,
    warnings: list[str],
) -> PlansGenerateSuccess:
    calories = _estimate_target_calories(payload)
    return PlansGenerateSuccess(
        plan_id=f"plan_{uuid.uuid4().hex[:12]}",
        support_status=SupportStatus(
            status="supported" if supported else "unsupported",
            reason=reason,
        ),
        nutrition_targets=NutritionTargets(
            calories_kcal=calories,
            protein_g=None,
            carbohydrates_g=None,
            fat_g=None,
            target_basis="estimated" if supported else "unavailable",
        ),
        meals=_fallback_meals(payload) if supported else [],
        rationale=(
            "Fallback response returned because a full plan could not be generated."
            if supported
            else "Qima does not generate personalized nutrition plans for profiles that need clinical nutrition support."
        ),
        safety_flags=[
            "non_diagnostic",
            "no_treatment_advice",
            "no_supplement_prescription",
            "general_information_only",
            "estimated_targets_only",
            "estimated_cost_only",
            *(["profile_exclusion_triggered"] if not supported else []),
        ],
        source=Source(
            provider="qima_backend",
            source_type="meal_plan_ranker",
            fetched_at=datetime.now(UTC),
        ),
        data_quality=DataQuality(completeness="partial"),
        warnings=warnings,
        generated_plan=None,
    )


def _fallback_meals(payload: PlansGenerateRequest) -> list[MealCandidate]:
    pantry = [item.name for item in payload.pantry or []]
    return [
        MealCandidate(
            meal_id=f"meal_{uuid.uuid4().hex[:12]}",
            title="Balanced Rice and Protein Bowl",
            meal_type="lunch",
            matched_ingredients=pantry[:3],
            missing_ingredients=["rice", "lean protein", "vegetables"],
            estimated_nutrition=EstimatedNutrition(
                calories_kcal=_estimate_target_calories(payload) / 3,
                protein_g=None,
                carbohydrates_g=None,
                fat_g=None,
            ),
            estimated_cost=EstimatedCost(
                total_cost=None,
                currency="EGP",
                estimate_quality="unavailable",
            ),
            score=MealScore(
                overall=0.5,
                ingredient_match=0.5,
                target_fit=0.5,
                cost_fit=0.5,
                safety_score=1,
            ),
            warnings=["Fallback meal returned because a full plan was unavailable."],
            source=MealSource(source_type="mixed_sources"),
        )
    ]


def _generated_plan_quality_warnings(
    payload: PlansGenerateRequest,
    generated_plan: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    plan = _generated_plan_days(generated_plan)
    expected_days = (
        payload.plan_preferences.plan_days
        if payload.plan_preferences and payload.plan_preferences.plan_days is not None
        else 1
    )
    expected_meals = (
        payload.plan_preferences.meals_per_day
        if payload.plan_preferences and payload.plan_preferences.meals_per_day is not None
        else payload.plan_preferences.meal_count
        if payload.plan_preferences and payload.plan_preferences.meal_count is not None
        else 3
    )

    if len(plan) != expected_days:
        warnings.append(
            f"Generated plan contains {len(plan)} day(s), but {expected_days} were requested."
        )

    for day in plan:
        if not isinstance(day, dict):
            continue
        meals = day.get("meals") or []
        if len(meals) != expected_meals:
            warnings.append(
                f"Day {day.get('day')} contains {len(meals)} meal(s), but {expected_meals} were requested."
            )

    calorie_check = generated_plan.get("backend_meal_calorie_check") or {}
    if calorie_check.get("all_days_within_100_kcal") is False:
        warnings.append(
            "Generated meal calories are outside the requested daily target range for at least one day."
        )

    return warnings


def _generated_plan_incomplete_reason(
    payload: PlansGenerateRequest,
    generated_plan: dict[str, Any],
) -> str | None:
    expected_days = _requested_plan_days(payload)
    expected_meals = _requested_meals_per_day(payload)

    _canonicalize_generated_plan_shape(generated_plan)
    plan = generated_plan.get("plan")
    if not isinstance(plan, list):
        return "LLM diet-plan response did not include a plan list."
    if len(plan) != expected_days:
        return (
            f"LLM diet-plan response contained {len(plan)} day(s), "
            f"but {expected_days} were requested."
        )

    for day_index, day in enumerate(plan, start=1):
        if not isinstance(day, dict):
            return f"LLM diet-plan response day {day_index} was malformed."

        meals = day.get("meals")
        if not isinstance(meals, list):
            return f"LLM diet-plan response day {day.get('day', day_index)} did not include meals."

        usable_meals = [
            meal
            for meal in meals
            if isinstance(meal, dict)
            and str(meal.get("meal_name") or "").strip()
            and isinstance(meal.get("ingredients"), list)
            and len(meal.get("ingredients") or []) > 0
        ]
        if len(usable_meals) != expected_meals:
            return (
                f"LLM diet-plan response day {day.get('day', day_index)} "
                f"contained {len(usable_meals)} usable meal(s), "
                f"but {expected_meals} were requested."
            )

    return None


def _estimate_target_calories(payload: PlansGenerateRequest) -> float:
    profile = payload.profile
    if profile is None:
        return 2200

    sex = _enum_value(profile.sex)
    sex_adjustment = 5 if sex == "male" else -161
    base = (
        (10 * profile.weight_kg)
        + (6.25 * profile.height_cm)
        - (5 * profile.age_years)
        + sex_adjustment
    )
    activity = ACTIVITY_TO_INTERNAL.get(_enum_value(profile.activity_level), "moderate")
    goal = GOAL_TO_INTERNAL.get(_enum_value(profile.goal), "healthy_eating")
    target = (base * ACTIVITY_FACTORS[activity]) + GOAL_ADJUSTMENTS[goal]
    minimum = 1500 if sex == "male" else 1200
    return round(max(target, minimum))


def _has_exclusion(payload: PlansGenerateRequest) -> bool:
    if payload.safety_checks is not None and payload.safety_checks.has_exclusion:
        return True

    flags = {
        _enum_value(flag)
        for flag in payload.profile.exclusion_flags
    } if payload.profile is not None else set()

    return bool(
        flags
        & {
            _enum_value(ExclusionFlag.PREGNANCY),
            _enum_value(ExclusionFlag.ADOLESCENT),
            _enum_value(ExclusionFlag.UNDERWEIGHT),
            _enum_value(ExclusionFlag.EATING_DISORDER_RISK),
            _enum_value(ExclusionFlag.KIDNEY_DISEASE),
            _enum_value(ExclusionFlag.DIABETES),
            _enum_value(ExclusionFlag.OTHER_CLINICAL_CONDITION),
        }
    )


def _budget_level(payload: PlansGenerateRequest) -> str:
    value = payload.budget.max_total_cost if payload.budget is not None else None
    if value is None:
        return "mid"
    if isinstance(value, BudgetTier):
        return "expensive" if value == BudgetTier.HIGH else value.value
    if isinstance(value, (int, float)):
        if value <= 100:
            return "low"
        if value <= 300:
            return "mid"
        return "expensive"

    raw = str(value).strip().lower()
    if raw == "high":
        return "expensive"
    if raw in {"low", "mid", "expensive"}:
        return raw
    return "mid"


def _rationale_from_generated_plan(generated_plan: dict[str, Any]) -> str:
    summary = generated_plan.get("daily_summary") or {}
    if isinstance(summary, dict):
        strategy = str(summary.get("strategy") or "").strip()
        if strategy:
            return strategy

    notes = [str(item).strip() for item in generated_plan.get("notes") or [] if str(item).strip()]
    if notes:
        return " ".join(notes[:2])
    return "Generated meals are based on the submitted profile, preferences, calorie target, and safety boundaries."


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _enum_value(value: Any) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value)
