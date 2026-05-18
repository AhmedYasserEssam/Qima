import json
import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator


BASE_DIR = Path(__file__).resolve().parent

root_env = BASE_DIR / ".env"
backend_env = BASE_DIR / "backend" / ".env"

if root_env.exists():
    load_dotenv(root_env)
elif backend_env.exists():
    load_dotenv(backend_env)
else:
    load_dotenv()


class OpenAILLMError(Exception):
    """Raised when the OpenAI LLM call or JSON parsing fails."""


# Backward-compatible alias in case other files still import GroqLLMError.
GroqLLMError = OpenAILLMError


class DietPlanSpecs(BaseModel):
    # Let backend safety logic catch under-18 instead of Pydantic blocking it first.
    age: int = Field(..., ge=1, le=100)

    sex: Literal["male", "female"]
    height_cm: float = Field(..., ge=120, le=230)
    weight_kg: float = Field(..., ge=20, le=250)

    activity_level: Literal[
        "sedentary",
        "light",
        "moderate",
        "active",
        "very_active",
    ]

    nutrition_goal: Literal[
        "weight_loss",
        "weight_maintenance",
        "muscle_gain",
        "healthy_eating",
    ]

    dietary_restrictions: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)

    meals_per_day: int = Field(..., ge=1, le=6)
    plan_days: int = Field(..., ge=1, le=14)

    disliked_foods: list[str] = Field(default_factory=list)
    preferred_foods: list[str] = Field(default_factory=list)
    lab_food_focuses: list[dict[str, Any]] = Field(default_factory=list)

    budget: Literal["low", "mid", "expensive"]

    pregnant_or_breastfeeding: bool = False
    eating_disorder_history: bool = False
    underweight: bool = False
    diabetes: bool = False
    kidney_disease: bool = False
    heart_disease: bool = False
    requires_clinical_diet: bool = False

    @model_validator(mode="after")
    def check_safety_exclusions(self) -> "DietPlanSpecs":
        exclusion_flags = {
            "under_18": self.age < 18,
            "pregnant_or_breastfeeding": self.pregnant_or_breastfeeding,
            "eating_disorder_history": self.eating_disorder_history,
            "underweight": self.underweight,
            "diabetes": self.diabetes,
            "kidney_disease": self.kidney_disease,
            "heart_disease": self.heart_disease,
            "requires_clinical_diet": self.requires_clinical_diet,
        }
        active_exclusions = [
            name for name, is_active in exclusion_flags.items() if is_active
        ]

        if active_exclusions:
            raise ValueError(
                "This profile is outside Qima's non-clinical diet-plan scope. "
                f"Active exclusion flags: {active_exclusions}"
            )

        return self


ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


GOAL_ADJUSTMENTS: dict[str, int] = {
    "weight_loss": -500,
    "weight_maintenance": 0,
    "muscle_gain": 300,
    "healthy_eating": 0,
}

PROTEIN_CALORIE_SHARE = 0.30
CARBOHYDRATE_CALORIE_SHARE = 0.50
FAT_CALORIE_SHARE = 0.20
PROTEIN_CALORIES_PER_GRAM = 4
CARBOHYDRATE_CALORIES_PER_GRAM = 4
FAT_CALORIES_PER_GRAM = 9


def calculate_bmr_mifflin_st_jeor(specs: DietPlanSpecs) -> float:
    base = 10 * specs.weight_kg + 6.25 * specs.height_cm - 5 * specs.age

    if specs.sex == "male":
        return base + 5

    return base - 161


def calculate_daily_calorie_targets(specs: DietPlanSpecs) -> dict[str, Any]:
    bmr = calculate_bmr_mifflin_st_jeor(specs)
    activity_factor = ACTIVITY_FACTORS[specs.activity_level]
    tdee = bmr * activity_factor
    goal_adjustment = GOAL_ADJUSTMENTS[specs.nutrition_goal]
    target_calories = tdee + goal_adjustment
    minimum_calories = 1500 if specs.sex == "male" else 1200
    target_calories = max(target_calories, minimum_calories)
    macros = calculate_macronutrient_targets(target_calories)

    return {
        "bmr_kcal": round(bmr),
        "activity_factor": activity_factor,
        "tdee_kcal": round(tdee),
        "goal_adjustment_kcal": goal_adjustment,
        "target_daily_calories_kcal": round(target_calories),
        "estimated_calories_per_meal_kcal": round(
            target_calories / specs.meals_per_day
        ),
        **macros,
        "method": "Mifflin-St Jeor BMR x activity factor + goal adjustment",
        "macronutrient_method": (
            "protein_g = target_daily_calories_kcal x 30% / 4; "
            "carbohydrates_g = target_daily_calories_kcal x 50% / 4; "
            "fat_g = target_daily_calories_kcal x 20% / 9"
        ),
    }


def calculate_macronutrient_targets(target_calories: float) -> dict[str, float]:
    return {
        "protein_g": round(
            target_calories * PROTEIN_CALORIE_SHARE / PROTEIN_CALORIES_PER_GRAM,
            1,
        ),
        "carbohydrates_g": round(
            target_calories
            * CARBOHYDRATE_CALORIE_SHARE
            / CARBOHYDRATE_CALORIES_PER_GRAM,
            1,
        ),
        "fat_g": round(
            target_calories * FAT_CALORIE_SHARE / FAT_CALORIES_PER_GRAM,
            1,
        ),
    }


def format_diet_plan_message(plan: dict[str, Any]) -> str:
    """Build a short readable message from the structured diet-plan JSON."""
    lines: list[str] = []
    summary = plan.get("daily_summary") if isinstance(plan, dict) else {}
    calorie_target = plan.get("calorie_target") if isinstance(plan, dict) else {}

    goal = _clean_text(summary.get("goal") if isinstance(summary, dict) else None)
    strategy = _clean_text(
        summary.get("strategy") if isinstance(summary, dict) else None
    )
    target_calories = (
        calorie_target.get("target_daily_calories_kcal")
        if isinstance(calorie_target, dict)
        else None
    )

    header = "Qima nutrition plan"
    lines.append(f"{header} - {goal}" if goal else header)

    if target_calories is not None:
        lines.append(f"Daily target: {_format_number(target_calories)} kcal")

    macros = _format_macronutrient_targets(calorie_target)
    if macros:
        lines.append(f"Macro targets: {macros}")

    if strategy:
        lines.append(f"Strategy: {strategy}")

    plan_days = plan.get("plan") or plan.get("days") or []
    for day in plan_days:
        if not isinstance(day, dict):
            continue

        lines.append("")
        lines.append(f"Day {day.get('day', '?')}")

        for meal in day.get("meals") or []:
            if not isinstance(meal, dict):
                continue

            meal_type = _clean_text(meal.get("meal_type")).title() or "Meal"
            meal_name = _clean_text(meal.get("meal_name")) or "Generated meal"
            calories = meal.get("estimated_calories_kcal")
            calorie_text = (
                f" ({_format_number(calories)} kcal)"
                if calories is not None
                else ""
            )
            lines.append(f"{meal_type}: {meal_name}{calorie_text}")

            ingredients = [
                _format_ingredient(ingredient)
                for ingredient in meal.get("ingredients") or []
                if isinstance(ingredient, dict)
            ]
            ingredients = [item for item in ingredients if item]

            if ingredients:
                lines.append(f"Ingredients: {', '.join(ingredients)}")

    return "\n".join(lines).strip()


def _format_ingredient(ingredient: dict[str, Any]) -> str:
    item = _clean_text(ingredient.get("item"))
    amount = ingredient.get("amount")
    unit = _clean_text(ingredient.get("unit"))

    if not item:
        return ""
    if amount is None:
        return item

    return f"{_format_number(amount)} {unit} {item}".strip()


def _format_number(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return _clean_text(value)


def _format_macronutrient_targets(calorie_target: Any) -> str:
    if not isinstance(calorie_target, dict):
        return ""

    protein = calorie_target.get("protein_g")
    carbs = calorie_target.get("carbohydrates_g")
    fat = calorie_target.get("fat_g")

    if protein is None or carbs is None or fat is None:
        return ""

    return (
        f"protein {_format_number(protein)} g, "
        f"carbs {_format_number(carbs)} g, "
        f"fat {_format_number(fat)} g"
    )


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenAILLMError(
            "Model did not return valid JSON. The response may have been cut off "
            f"before completion: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise OpenAILLMError("Model output must be a JSON object.")

    return parsed


def _max_completion_tokens(specs: DietPlanSpecs) -> int:
    meal_count = specs.plan_days * specs.meals_per_day
    needed_tokens = 1600 + (meal_count * 450)
    configured_tokens = int(os.getenv("OPENAI_MAX_COMPLETION_TOKENS", "0") or "0")
    return min(max(configured_tokens, needed_tokens), 16000)


class OpenAIDietPlanGenerator:
    def __init__(self, model: str = "gpt-4o-mini") -> None:
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            checked_paths = [str(root_env), str(backend_env)]
            raise OpenAILLMError(
                "Missing OPENAI_API_KEY. Add it to .env. "
                f"Checked paths: {checked_paths}"
            )

        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv(
            "OPENAI_DIET_PLAN_MODEL",
            os.getenv("OPENAI_MODEL", model),
        )

    def build_prompt(
        self,
        specs: DietPlanSpecs,
        calorie_targets: dict[str, Any],
    ) -> str:
        payload = {
            "user_specifications": {
                "age": specs.age,
                "sex": specs.sex,
                "height_cm": specs.height_cm,
                "weight_kg": specs.weight_kg,
                "activity_level": specs.activity_level,
                "nutrition_goal": specs.nutrition_goal,
                "meals_per_day": specs.meals_per_day,
                "plan_days": specs.plan_days,
                "dietary_restrictions": specs.dietary_restrictions,
                "allergens": specs.allergens,
                "disliked_foods": specs.disliked_foods,
                "preferred_foods": specs.preferred_foods,
                "below_range_lab_food_focuses": specs.lab_food_focuses,
                "budget": specs.budget,
            },
            "calorie_and_macro_targets": {
                "target_daily_calories_kcal": calorie_targets[
                    "target_daily_calories_kcal"
                ],
                "estimated_calories_per_meal_kcal": calorie_targets[
                    "estimated_calories_per_meal_kcal"
                ],
                "protein_g": calorie_targets["protein_g"],
                "carbohydrates_g": calorie_targets["carbohydrates_g"],
                "fat_g": calorie_targets["fat_g"],
                "method": calorie_targets["method"],
                "macronutrient_method": calorie_targets["macronutrient_method"],
                "macro_split": "30% protein, 50% carbohydrates, 20% fat",
            },
            "json_shape": {
                "support_status": "supported",
                "safety_flags": [],
                "assumptions": [],
                "calorie_target": {
                    "target_daily_calories_kcal": 0,
                    "estimated_calories_per_meal_kcal": 0,
                    "protein_g": 0,
                    "carbohydrates_g": 0,
                    "fat_g": 0,
                    "method": "string",
                    "macronutrient_method": "string",
                },
                "daily_summary": {
                    "goal": "string",
                    "strategy": "string",
                    "estimated_budget_level": "low|mid|expensive",
                    "estimated_total_daily_calories_kcal": 0,
                },
                "plan": [
                    {
                        "day": 1,
                        "meals": [
                            {
                                "meal_type": "breakfast|lunch|dinner|snack",
                                "meal_name": "string",
                                "estimated_calories_kcal": 0,
                                "ingredients": [
                                    {
                                        "item": "string",
                                        "amount": 0,
                                        "unit": "g|ml|piece|tsp|tbsp",
                                    }
                                ],
                                "preparation_steps": ["string"],
                                "why_it_fits": "string",
                            }
                        ],
                    }
                ],
                "shopping_list": [
                    {
                        "item": "string",
                        "total_amount": 0,
                        "unit": "g|ml|piece|tsp|tbsp",
                        "category": "protein|carbohydrate|vegetable|fruit|dairy|fat|spice|other",
                    }
                ],
                "notes": [],
            },
        }

        return (
            "Generate a practical non-clinical diet plan for a generally healthy adult. "
            "Return valid JSON only. "
            f"Create exactly {specs.plan_days} day(s), each with exactly "
            f"{specs.meals_per_day} meal(s). "
            "Respect allergens, dietary restrictions, disliked foods, preferred foods, "
            "budget, calories, and macros. Use realistic normal foods and quantities. "
            "When below-range lab food focuses are provided, include ordinary foods "
            "rich in those nutrient focuses where compatible; do not frame this as "
            "diagnosis, treatment, or supplement advice. "
            "Do not use pork by default; use chicken, beef, fish, eggs, dairy, "
            "or legumes instead unless pork is explicitly allowed. "
            "Keep meal names, preparation steps, reasons, and notes concise. "
            "Do not provide diagnosis, disease treatment, supplement prescription, "
            "or clinical medical advice. Use the provided calorie and macro targets exactly. "
            "Macro split is 30% protein, 50% carbohydrates, 20% fat. "
            f"DATA={json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )

    def generate_plan(
        self,
        specs: DietPlanSpecs,
        *,
        include_costs: bool = False,
    ) -> dict[str, Any]:
        del include_costs  # Kept only for existing backend call compatibility.

        calorie_targets = calculate_daily_calorie_targets(specs)
        prompt = self.build_prompt(specs, calorie_targets)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You generate compact JSON diet plans for generally "
                            "healthy adults. Return JSON only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_completion_tokens=_max_completion_tokens(specs),
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content

            if not content:
                raise OpenAILLMError("OpenAI returned an empty response.")

            plan = _parse_json_object(content)
            plan["backend_calorie_targets"] = calorie_targets
            plan["formatted_message"] = format_diet_plan_message(plan)
            return plan

        except OpenAILLMError:
            raise
        except Exception as exc:
            raise OpenAILLMError(f"OpenAI API call failed: {exc}") from exc


# Backward-compatible alias in case other files still import GroqDietPlanGenerator.
GroqDietPlanGenerator = OpenAIDietPlanGenerator
