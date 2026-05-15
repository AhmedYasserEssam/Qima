import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from groq import Groq
from pydantic import BaseModel, Field, ValidationError, model_validator


BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"
DEFAULT_CARREFOUR_PRODUCTS_CSV = (
    BASE_DIR / "data" / "Food" / "carrefour_test.csv"
)
CARREFOUR_PRODUCTS_CSV_ENV = "CARREFOUR_PRODUCTS_CSV"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from backend.scripts.estimate_recipe_prices import (
        estimate_ingredient_cost,
        prepare_products,
    )
except Exception:  # pragma: no cover - keeps non-pricing usage importable.
    estimate_ingredient_cost = None
    prepare_products = None

_CARREFOUR_PRODUCTS_CACHE: dict[Path, Any] = {}

# Load .env from either:
# 1) Qima/.env
# 2) Qima/backend/.env
root_env = BASE_DIR / ".env"
backend_env = BASE_DIR / "backend" / ".env"

if root_env.exists():
    load_dotenv(root_env)
elif backend_env.exists():
    load_dotenv(backend_env)
else:
    load_dotenv()


class GroqLLMError(Exception):
    """Raised when the Groq LLM call fails."""


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
    plan_days: int = Field(..., ge=1, le=7)

    disliked_foods: list[str] = Field(default_factory=list)
    preferred_foods: list[str] = Field(default_factory=list)

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


def calculate_bmr_mifflin_st_jeor(specs: DietPlanSpecs) -> float:
    base = (
        (10 * specs.weight_kg)
        + (6.25 * specs.height_cm)
        - (5 * specs.age)
    )

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

    calories_per_meal = target_calories / specs.meals_per_day

    return {
        "bmr_kcal": round(bmr),
        "activity_factor": activity_factor,
        "tdee_kcal": round(tdee),
        "goal_adjustment_kcal": goal_adjustment,
        "target_daily_calories_kcal": round(target_calories),
        "estimated_calories_per_meal_kcal": round(calories_per_meal),
        "method": "Mifflin-St Jeor BMR × activity factor + goal adjustment",
    }


def validate_meal_calories(plan: dict[str, Any], target_daily_calories: int) -> dict[str, Any]:
    total = 0

    for day in plan.get("plan", []):
        for meal in day.get("meals", []):
            calories = meal.get("estimated_calories_kcal", 0)
            if isinstance(calories, (int, float)):
                total += calories

    difference = total - target_daily_calories

    plan["backend_meal_calorie_check"] = {
        "sum_of_meal_calories_kcal": round(total),
        "target_daily_calories_kcal": target_daily_calories,
        "difference_kcal": round(difference),
        "within_100_kcal": abs(difference) <= 100,
    }

    return plan


def resolve_carrefour_products_csv(products_csv: str | Path | None = None) -> Path:
    raw_path = products_csv or os.getenv(CARREFOUR_PRODUCTS_CSV_ENV)
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else BASE_DIR / path

    return DEFAULT_CARREFOUR_PRODUCTS_CSV


def _load_carrefour_products(products_csv: str | Path | None = None) -> Any:
    products_path = resolve_carrefour_products_csv(products_csv)

    if prepare_products is None:
        raise GroqLLMError(
            "Price estimation dependencies are unavailable. Install backend requirements."
        )
    if not products_path.exists():
        raise GroqLLMError(f"Carrefour products CSV not found: {products_path}")
    if products_path not in _CARREFOUR_PRODUCTS_CACHE:
        _CARREFOUR_PRODUCTS_CACHE[products_path] = prepare_products(products_path)
    return _CARREFOUR_PRODUCTS_CACHE[products_path]


def enrich_plan_with_carrefour_costs(plan: dict[str, Any]) -> dict[str, Any]:
    """Attach ingredient and meal cost estimates using Carrefour product prices."""
    if estimate_ingredient_cost is None:
        raise GroqLLMError(
            "Price estimation dependencies are unavailable. Install backend requirements."
        )

    products = _load_carrefour_products()
    plan_total = 0.0
    priced_total = 0
    unpriced_total = 0

    for day in plan.get("plan", []):
        day_total = 0.0
        day_priced = 0
        day_unpriced = 0

        for meal in day.get("meals", []):
            meal_total = 0.0
            meal_priced = 0
            meal_unpriced = 0

            for ingredient in meal.get("ingredients", []):
                if not isinstance(ingredient, dict):
                    continue

                detail = estimate_ingredient_cost(ingredient, products)
                ingredient["carrefour_price_match"] = {
                    "matched_product": detail["matched_product"],
                    "matched_brand": detail["matched_brand"],
                    "matched_category_level_1": detail["matched_category_level_1"],
                    "product_price_egp": detail["product_price_egp"],
                    "product_package_quantity": detail["product_package_quantity"],
                    "product_package_unit_type": detail["product_package_unit_type"],
                    "estimated_used_cost_egp": detail["estimated_used_cost_egp"],
                    "match_score": detail["match_score"],
                    "match_confidence": detail["match_confidence"],
                    "pricing_method": detail["pricing_method"],
                }

                cost = detail["estimated_used_cost_egp"]
                if cost is None:
                    meal_unpriced += 1
                else:
                    meal_priced += 1
                    meal_total += float(cost)

            meal["cost_estimate"] = {
                "currency": "EGP",
                "estimated_total_cost_egp": round(meal_total, 2),
                "priced_ingredient_count": meal_priced,
                "unpriced_ingredient_count": meal_unpriced,
                "source_provider": "carrefour_egypt",
            }
            day_total += meal_total
            day_priced += meal_priced
            day_unpriced += meal_unpriced

        day["cost_estimate"] = {
            "currency": "EGP",
            "estimated_total_cost_egp": round(day_total, 2),
            "priced_ingredient_count": day_priced,
            "unpriced_ingredient_count": day_unpriced,
            "source_provider": "carrefour_egypt",
        }
        plan_total += day_total
        priced_total += day_priced
        unpriced_total += day_unpriced

    plan["backend_cost_estimate"] = {
        "currency": "EGP",
        "estimated_total_plan_cost_egp": round(plan_total, 2),
        "priced_ingredient_count": priced_total,
        "unpriced_ingredient_count": unpriced_total,
        "source_provider": "carrefour_egypt",
        "products_csv": str(resolve_carrefour_products_csv()),
        "method": "ingredient_cost = product_price * used_quantity / package_quantity when package size is available",
    }

    return plan


class GroqDietPlanGenerator:
    def __init__(self, model: str = "llama-3.1-8b-instant") -> None:
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            checked_paths = [str(root_env), str(backend_env)]
            raise GroqLLMError(
                "Missing GROQ_API_KEY. Add it to .env. "
                f"Checked paths: {checked_paths}"
            )

        self.client = Groq(api_key=api_key)
        self.model = os.getenv("GROQ_MODEL", model)

    def build_prompt(
        self,
        specs: DietPlanSpecs,
        calorie_targets: dict[str, Any],
    ) -> str:
        user_specs_json = specs.model_dump_json(indent=2)
        calorie_targets_json = json.dumps(
            calorie_targets,
            indent=2,
            ensure_ascii=False,
        )

        return f"""
You are Qima's diet-plan generation assistant.

Your task:
Generate a practical diet plan using the user specs and the calculated calorie target.

Critical rules:
1. Return valid JSON only.
2. Do not include markdown.
3. Do not diagnose disease.
4. Do not claim to treat medical conditions.
5. Do not prescribe supplements.
6. Respect allergens strictly.
7. Respect dietary restrictions strictly.
8. Avoid disliked foods.
9. Prefer preferred foods when reasonable.
10. Make the plan realistic for the budget level.
11. Use simple meals suitable for normal home cooking.
12. Use the calculated calorie target as the main planning constraint.
13. The sum of estimated_calories_kcal across all meals must be within ±100 kcal of target_daily_calories_kcal.
14. Do not set estimated_total_daily_calories_kcal equal to the target unless the meal calories actually sum to that value.
15. For weight loss, use moderate portions and high-protein, high-fiber meals.
16. The answer must be food guidance only, not medical advice.
17. For every meal ingredient, specify the required amount.
18. Use grams as the standard unit for solid foods. For liquids, use milliliters only if grams would be more confusing.
19. Ingredient quantities must be realistic for one person unless plan_days or meals imply otherwise.
20. This plan is only for generally healthy adults.

Budget meaning:
- "low": cheap, common ingredients, minimal expensive proteins
- "mid": balanced cost, normal ingredients
- "expensive": allows premium ingredients

User specs:
{user_specs_json}

Calculated calorie targets:
{calorie_targets_json}

Required JSON output shape:
{{
  "support_status": "supported",
  "safety_flags": [],
  "assumptions": [
    "string"
  ],
  "calorie_target": {{
    "target_daily_calories_kcal": number,
    "estimated_calories_per_meal_kcal": number,
    "method": "string"
  }},
  "daily_summary": {{
    "goal": "string",
    "strategy": "string",
    "estimated_budget_level": "low | mid | expensive",
    "estimated_total_daily_calories_kcal": number
  }},
  "meal_calorie_check": {{
    "sum_of_meal_calories_kcal": number,
    "target_daily_calories_kcal": number,
    "difference_kcal": number,
    "within_target_range": true
  }},
  "plan": [
    {{
      "day": 1,
      "meals": [
        {{
          "meal_type": "breakfast | lunch | dinner | snack",
          "meal_name": "string",
          "estimated_calories_kcal": number,
          "ingredients": [
            {{
              "item": "string",
              "amount": number,
              "unit": "g | ml | piece | tsp | tbsp",
              "notes": "string"
            }}
          ],
          "preparation_steps": [
            "string"
          ],
          "why_it_fits": "string",
          "allergen_check": "string",
          "budget_fit": "string"
        }}
      ]
    }}
  ],
  "shopping_list": [
    {{
      "item": "string",
      "total_amount": number,
      "unit": "g | ml | piece | tsp | tbsp",
      "category": "protein | carbohydrate | vegetable | fruit | dairy | fat | spice | other",
      "priority": "must_have | optional"
    }}
  ],
  "notes": [
    "string"
  ]
}}
""".strip()

    def generate_plan(self, specs: DietPlanSpecs) -> dict[str, Any]:
        calorie_targets = calculate_daily_calorie_targets(specs)
        prompt = self.build_prompt(specs, calorie_targets)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict JSON diet-plan generator for a nutrition app. "
                            "Return JSON only. Follow safety, calorie, allergy, and dietary constraints exactly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.7,
                max_tokens=3000,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content

            if not content:
                raise GroqLLMError("Groq returned an empty response.")

            plan = json.loads(content)

            plan = validate_meal_calories(
                plan,
                calorie_targets["target_daily_calories_kcal"],
            )

            plan["backend_calorie_targets"] = calorie_targets
            plan = enrich_plan_with_carrefour_costs(plan)

            return plan

        except json.JSONDecodeError as exc:
            raise GroqLLMError(f"Model did not return valid JSON: {exc}") from exc

        except Exception as exc:
            raise GroqLLMError(f"Groq API call failed: {exc}") from exc


if __name__ == "__main__":
    raw_specs = {
        "age": 22,
        "sex": "male",
        "height_cm": 175,
        "weight_kg": 78,
        "activity_level": "moderate",
        "nutrition_goal": "weight_loss",
        "dietary_restrictions": ["halal"],
        "allergens": ["peanuts"],
        "meals_per_day": 3,
        "plan_days": 1,
        "disliked_foods": ["tuna", "eggplant"],
        "preferred_foods": ["chicken", "rice", "yogurt"],
        "budget": "low",
        "pregnant_or_breastfeeding": False,
        "eating_disorder_history": False,
        "underweight": False,
        "diabetes": False,
        "kidney_disease": False,
        "heart_disease": False,
        "requires_clinical_diet": False,
    }

    try:
        specs = DietPlanSpecs(**raw_specs)

        calorie_targets = calculate_daily_calorie_targets(specs)
        print("Backend-calculated calorie targets:")
        print(json.dumps(calorie_targets, indent=2, ensure_ascii=False))
        print()

        generator = GroqDietPlanGenerator()
        plan = generator.generate_plan(specs)

        print("Generated diet plan:")
        print(json.dumps(plan, indent=2, ensure_ascii=False))

    except ValidationError as exc:
        print("Invalid user specs:")
        print(exc)

    except GroqLLMError as exc:
        print("LLM error:")
        print(exc)
