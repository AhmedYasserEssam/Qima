from __future__ import annotations

import runpy
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRAPER_PATH = REPO_ROOT / "scrappers" / "scrape_allrecipes_food.py"
SCRAPER = runpy.run_path(str(SCRAPER_PATH))
BUILD_RECORD = SCRAPER["build_record"]
BUILD_NORMALIZATION_WARNINGS = SCRAPER["build_normalization_warnings"]
COMPUTE_NORMALIZATION_QUALITY_SCORE = SCRAPER["compute_normalization_quality_score"]


def _build(url: str, recipe: dict) -> dict:
    return BUILD_RECORD(url, recipe)


def test_internal_food_temperature_is_not_taken_from_smoker_temperature() -> None:
    recipe = {
        "name": "Smoked Pork Internal Temp Check",
        "recipeYield": ["8"],
        "recipeIngredient": ["7 pounds fresh pork butt roast"],
        "recipeInstructions": [
            {
                "@type": "HowToStep",
                "text": "Smoke at 200 to 225 degrees F (95 to 110 degrees C) for 6 to 18 hours, or until internal pork temperature reaches 145 degrees F (63 degrees C).",
            }
        ],
        "nutrition": {"sodiumContent": "100 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/999002/smoked-pork-internal-temp-check", recipe)
    step = record["directions_json"][0]
    note_text = " ".join(step["food_safety_notes"])
    assert "145 degrees F" in note_text
    assert "225 degrees F" not in note_text
    assert "145 degrees F" in step["action_summary"]
    assert "225 degrees F internal temperature" not in step["action_summary"]


def test_name_cleanup_preserves_connector_and_removes_prep_descriptors() -> None:
    recipe = {
        "name": "Name Cleanup Recipe",
        "recipeYield": ["4"],
        "recipeIngredient": [
            "salt and black pepper to taste",
            "salt and freshly ground black pepper to taste",
            "0.5 cup finely chopped green onions",
            "0.5 cup finely chopped cabbage",
            "0.5 cup finely chopped carrot",
            "2 pounds beef tenderloin, trimmed",
            "1 (1 inch) piece ginger, coarsely chopped",
        ],
        "recipeInstructions": [{"@type": "HowToStep", "text": "Combine ingredients in a bowl and cook briefly."}],
        "nutrition": {"sodiumContent": "300 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/999003/name-cleanup-recipe", recipe)

    salt_pepper = next(i for i in record["ingredients"] if i["raw"] == "salt and black pepper to taste")
    fresh_salt_pepper = next(i for i in record["ingredients"] if i["raw"] == "salt and freshly ground black pepper to taste")
    green_onions = next(i for i in record["ingredients"] if "green onions" in i["raw"])
    cabbage = next(i for i in record["ingredients"] if "chopped cabbage" in i["raw"])
    carrot = next(i for i in record["ingredients"] if "chopped carrot" in i["raw"])
    tenderloin = next(i for i in record["ingredients"] if "beef tenderloin" in i["raw"])
    ginger = next(i for i in record["ingredients"] if "piece ginger" in i["raw"])

    assert salt_pepper["name_normalized"] == "salt and black pepper"
    assert fresh_salt_pepper["name_normalized"] == "salt and freshly ground black pepper"
    assert green_onions["name_normalized"] == "green onions"
    assert cabbage["name_normalized"] == "cabbage"
    assert carrot["name_normalized"] == "carrot"
    assert tenderloin["name_normalized"] == "beef tenderloin"
    assert tenderloin["notes"] == "trimmed"
    assert ginger["name_normalized"] == "ginger"
    assert ginger["package_size"] == {"quantity": 1, "unit": "inch"}


def test_role_fixes_for_edge_ingredients() -> None:
    recipe = {
        "name": "Role Fixes Recipe",
        "recipeYield": ["6"],
        "recipeIngredient": [
            "1 teaspoon garlic powder",
            "1 teaspoon onion powder",
            "2 teaspoons rice wine vinegar",
            "1 tablespoon distilled white vinegar",
            "1 (12 ounce) jar buttermilk ranch dressing",
            "1 (10.75 ounce) can tomato soup",
            "1 tablespoon toasted sesame seeds",
            "1 cup quick-cooking grits",
            "1 teaspoon vanilla extract",
            "1 cup whipped cream",
            "1 teaspoon dried thyme",
            "1 teaspoon dried oregano",
            "1 teaspoon dried basil",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Simmer ingredients in a saucepan, then sprinkle sesame seeds and whipped cream on top."}
        ],
        "nutrition": {"sodiumContent": "500 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/999004/role-fixes-recipe", recipe)
    by_raw = {item["raw"]: item for item in record["ingredients"]}

    assert by_raw["1 teaspoon garlic powder"]["ingredient_role"] == "seasoning"
    assert by_raw["1 teaspoon onion powder"]["ingredient_role"] == "seasoning"
    assert by_raw["2 teaspoons rice wine vinegar"]["ingredient_role"] == "seasoning"
    assert by_raw["1 tablespoon distilled white vinegar"]["ingredient_role"] == "seasoning"
    assert by_raw["1 (12 ounce) jar buttermilk ranch dressing"]["ingredient_role"] == "sauce"
    assert by_raw["1 (10.75 ounce) can tomato soup"]["ingredient_role"] in {"sauce", "liquid"}
    assert by_raw["1 tablespoon toasted sesame seeds"]["ingredient_role"] in {"seasoning", "garnish"}
    assert by_raw["1 cup quick-cooking grits"]["ingredient_role"] in {"main", "base"}
    assert by_raw["1 teaspoon vanilla extract"]["ingredient_role"] == "seasoning"
    assert by_raw["1 cup whipped cream"]["ingredient_role"] == "garnish"
    assert by_raw["1 teaspoon dried thyme"]["ingredient_role"] == "seasoning"
    assert by_raw["1 teaspoon dried oregano"]["ingredient_role"] == "seasoning"
    assert by_raw["1 teaspoon dried basil"]["ingredient_role"] == "seasoning"


def test_packaged_allergen_confidence_is_possible_without_explicit_label_evidence() -> None:
    recipe = {
        "name": "Packaged Allergen Confidence Recipe",
        "recipeYield": ["8"],
        "recipeIngredient": [
            "1 tablespoon Worcestershire sauce",
            "1 (1 ounce) envelope instant hot chocolate mix",
            "1 (18.25 ounce) box yellow cake mix",
            "1 (8 ounce) can refrigerated crescent dinner rolls",
            "0.5 cup mini chocolate chips",
        ],
        "recipeInstructions": [{"@type": "HowToStep", "text": "Combine all ingredients and bake until set."}],
        "nutrition": {"sodiumContent": "450 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/999005/packaged-allergen-confidence-recipe", recipe)

    assert "fish" not in record["allergen_flags"]
    assert "fish" in record["possible_allergen_flags"]
    assert record["allergen_confidence"]["fish"] == "possible"
    assert record["allergen_confidence"].get("milk") != "high"
    assert record["allergen_confidence"].get("soy") != "high"
    assert len(record["packaged_ingredient_warnings"]) >= 3


def test_normalization_score_penalizes_new_edge_case_warnings() -> None:
    record = {
        "dietary_flags": {"vegetarian": False, "contains_meat": True, "contains_poultry": False, "contains_fish_or_shellfish": False},
        "ingredients": [
            {
                "raw": "0.5 cup finely chopped green onions",
                "name_normalized": "finely green onions",
                "canonical_ingredient_id": "finely_green_onions",
                "ingredient_role": "main",
                "requires_label_check": False,
                "possible_allergens": [],
            },
            {
                "raw": "1 teaspoon garlic powder",
                "name_normalized": "garlic powder",
                "canonical_ingredient_id": "garlic_powder",
                "ingredient_role": "aromatic",
                "requires_label_check": False,
                "possible_allergens": [],
            },
            {
                "raw": "1 tablespoon Worcestershire sauce",
                "name_normalized": "worcestershire sauce",
                "canonical_ingredient_id": "worcestershire_sauce",
                "ingredient_role": "sauce",
                "requires_label_check": True,
                "possible_allergens": ["fish"],
            },
        ],
        "cooking_methods": ["smoking"],
        "directions_json": [
            {
                "raw_text": "Smoke at 200 to 225 degrees F (95 to 110 degrees C) until internal pork temperature reaches 145 degrees F (63 degrees C).",
                "equipment": ["smoker"],
                "temperature": ["200 to 225 degrees F (95 to 110 degrees C)", "145 degrees F (63 degrees C)"],
                "duration": [],
                "action_summary": "Smoke pork at low temperature until it reaches 225 degrees F internal temperature.",
                "food_safety_notes": ["Cook pork until internal temperature reaches 225 degrees F."],
            }
        ],
        "allergen_flags": ["fish"],
        "allergen_confidence": {"fish": "high"},
    }

    warnings = BUILD_NORMALIZATION_WARNINGS(record)
    assert "internal_temp_confused_with_cooking_temp" in warnings
    assert "malformed_ingredient_name" in warnings
    assert "obvious_wrong_ingredient_role" in warnings
    assert "packaged_allergen_overconfidence" in warnings

    score = COMPUTE_NORMALIZATION_QUALITY_SCORE(record)
    assert score < 1.0


def test_meat_poultry_seafood_detection_terms() -> None:
    recipe = {
        "name": "Protein Sampler",
        "recipeYield": ["6"],
        "recipeIngredient": [
            "1 pound ground sausage",
            "2 pounds skinless, boneless chicken breast meat",
            "2 pounds lean ground turkey",
            "1.5 pounds raw shrimp, peeled and deveined",
            "1.5 pounds cubed leg of lamb meat",
            "1 pound ground beef",
        ],
        "recipeInstructions": [{"@type": "HowToStep", "text": "Cook all proteins in a skillet until done."}],
        "nutrition": {"sodiumContent": "700 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/999001/protein-sampler", recipe)
    assert record["dietary_flags"]["contains_meat"] is True
    assert record["dietary_flags"]["contains_poultry"] is True
    assert record["dietary_flags"]["contains_fish_or_shellfish"] is True
    assert record["dietary_flags"]["vegetarian"] is False
    assert record["dietary_flags"]["vegan"] is False


def test_case_a_sausage_and_rice_stuffed_peppers() -> None:
    recipe = {
        "name": "Sausage and Rice Stuffed Peppers",
        "recipeYield": ["6"],
        "prepTime": "PT30M",
        "cookTime": "PT60M",
        "totalTime": "PT90M",
        "recipeIngredient": [
            "6 large green bell peppers",
            "1 pound ground sausage",
            "1 large onion, chopped",
            "2 (10.75 ounce) cans tomato soup",
            "3 cups uncooked instant rice",
            "1 pound Cheddar cheese, shredded, divided",
            "1 tablespoon chili powder",
            "1 tablespoon garlic powder",
            "salt and pepper to taste",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Cook sausage and onions in a large deep skillet over medium-high heat until browned."},
            {"@type": "HowToStep", "text": "Spoon rice mixture into peppers and bake until hot."},
        ],
        "nutrition": {"sodiumContent": "1142 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/23517/sausage-and-rice-stuffed-peppers", recipe)

    sausage = next(i for i in record["ingredients"] if "sausage" in i["raw"].lower())
    peppers = next(i for i in record["ingredients"] if "bell peppers" in i["raw"].lower())
    cheddar = next(i for i in record["ingredients"] if "cheddar cheese" in i["raw"].lower())
    rice = next(i for i in record["ingredients"] if "instant rice" in i["raw"].lower())

    assert sausage["ingredient_role"] == "main"
    assert peppers["ingredient_role"] == "main"
    assert cheddar["ingredient_role"] == "filling"
    assert rice["ingredient_role"] == "main"
    assert record["dietary_flags"]["vegetarian"] is False
    assert record["dietary_flags"]["contains_meat"] is True
    assert "milk" in record["allergen_flags"]
    assert record["allergen_confidence"]["milk"] == "high"


def test_case_b_indian_chicken_tikka_masala() -> None:
    recipe = {
        "name": "Indian Chicken Tikka Masala",
        "recipeYield": ["4"],
        "recipeIngredient": [
            "1 (14.5 ounce) can chopped tomatoes",
            "4 tablespoons plain yogurt",
            "2 cloves garlic, roughly chopped",
            "1 (1 inch) piece ginger, coarsely chopped",
            "4 skinless, boneless chicken breasts, cut into 1-inch pieces",
            "1 tablespoon all-purpose flour",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Combine tomatoes, yogurt, garlic, and ginger in a blender and process until smooth."},
            {"@type": "HowToStep", "text": "Heat oil in a large frying pan over medium heat. Add onion and fry until soft."},
            {"@type": "HowToStep", "text": "Stir flour slurry into sauce and simmer until thickened."},
        ],
        "nutrition": {"sodiumContent": "399 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/262622/indian-chicken-tikka-masala", recipe)

    chicken = next(i for i in record["ingredients"] if "chicken breasts" in i["raw"].lower())
    assert chicken["name_normalized"] == "chicken breasts"
    assert chicken["canonical_ingredient_id"] == "chicken_breasts"
    assert "skinless" in chicken["modifiers"]
    assert "boneless" in chicken["modifiers"]
    assert record["dietary_flags"]["contains_poultry"] is True
    assert record["dietary_flags"]["vegetarian"] is False
    assert record["dietary_flags"]["vegan"] is False
    assert "blender" in record["equipment"]
    assert "frying pan" in record["equipment"]
    assert "milk" in record["allergen_flags"]
    assert "wheat_gluten" in record["allergen_flags"]


def test_case_c_chocolate_filled_crescents_packaging_uncertainty() -> None:
    recipe = {
        "name": "Chocolate-Filled Crescents",
        "recipeYield": ["8"],
        "recipeIngredient": [
            "1 (8 ounce) can refrigerated crescent dinner rolls",
            "0.5 cup mini chocolate chips",
            "1 teaspoon powdered sugar",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Heat oven to 350 degrees F. Roll dough and fill with chocolate chips."},
            {"@type": "HowToStep", "text": "Bake until golden."},
        ],
        "nutrition": {"sodiumContent": "224 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/218900/chocolate-filled-crescents", recipe)

    crescent = next(i for i in record["ingredients"] if "crescent" in i["raw"].lower())
    chips = next(i for i in record["ingredients"] if "chocolate chips" in i["raw"].lower())
    assert crescent["ingredient_role"] == "base"
    assert crescent["requires_label_check"] is True
    assert chips["requires_label_check"] is True
    assert "wheat_gluten" in crescent["possible_allergens"]
    assert "milk" in chips["possible_allergens"]
    assert "soy" in chips["possible_allergens"]
    assert record["dietary_flags"]["vegan"] is not True
    assert "refrigerated crescent dinner rolls" in " ".join(record["packaged_ingredient_warnings"]).lower()


def test_case_d_peach_dump_cake_packaged_mix() -> None:
    recipe = {
        "name": "Peach Dump Cake",
        "recipeYield": ["12"],
        "recipeIngredient": [
            "1 (29 ounce) can sliced peaches in heavy syrup, undrained",
            "1 (18.25 ounce) box yellow cake mix",
            "0.75 cup butter",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Pour peaches into baking dish and top with cake mix."},
            {"@type": "HowToStep", "text": "Bake in oven until golden."},
        ],
        "nutrition": {"sodiumContent": "368 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/229004/peach-dump-cake", recipe)

    cake_mix = next(i for i in record["ingredients"] if "cake mix" in i["raw"].lower())
    butter = next(i for i in record["ingredients"] if i["canonical_ingredient_id"] == "butter")
    assert cake_mix["ingredient_role"] == "base"
    assert cake_mix["requires_label_check"] is True
    assert {"wheat_gluten", "milk", "egg", "soy"}.issubset(set(cake_mix["possible_allergens"]))
    assert "milk" in record["allergen_flags"]
    assert "butter" in " ".join(record["allergen_basis"]["milk"]).lower()
    assert record["dietary_flags"]["vegan"] is False


def test_case_e_turkey_chili_no_false_smoking() -> None:
    recipe = {
        "name": "Smokin Scovilles Turkey Chili",
        "recipeYield": ["8"],
        "recipeIngredient": [
            "2 pounds lean ground turkey",
            "1 teaspoon liquid smoke flavoring",
            "2 tablespoons chili powder",
            "1 (15 ounce) can kidney beans",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Cook turkey in a large saucepan over medium heat until no longer pink."},
            {"@type": "HowToStep", "text": "Stir in liquid smoke flavoring and simmer for 50 minutes."},
        ],
        "nutrition": {"sodiumContent": "1100 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/84760/smokin-scovilles-turkey-chili", recipe)
    assert "smoking" not in record["cooking_methods"]
    assert record["dietary_flags"]["contains_poultry"] is True
    assert record["dietary_flags"]["vegetarian"] is False
    assert record["dietary_flags"]["high_sodium"] is True


def test_case_f_lancashire_hot_pot_duration_and_poultry_ambiguity() -> None:
    recipe = {
        "name": "Lancashire Hot Pot",
        "recipeYield": ["6"],
        "recipeIngredient": [
            "1.5 pounds cubed leg of lamb meat",
            "2 cups chicken or lamb stock",
            "2.5 pounds potatoes, peeled and thinly sliced",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Brown lamb in a skillet."},
            {"@type": "HowToStep", "text": "Bake in the preheated oven for 1 1/2 to 2 hours."},
        ],
        "nutrition": {"sodiumContent": "302 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/24805/lancashire-hot-pot", recipe)
    durations = [d for step in record["directions_json"] for d in step["duration"]]
    assert "1 1/2 to 2 hours" in [d.lower() for d in durations]
    lamb = next(i for i in record["ingredients"] if "lamb" in i["raw"].lower())
    assert lamb["ingredient_role"] == "main"
    assert record["dietary_flags"]["contains_meat"] is True
    assert record["dietary_flags"]["contains_poultry"] == "unknown"


def test_case_g_zucchini_jelly_name_and_equipment_and_vegan_uncertainty() -> None:
    recipe = {
        "name": "Zucchini Jelly",
        "recipeYield": ["192"],
        "recipeIngredient": [
            "6 cups peeled, seeded, and shredded zucchini",
            "1 (6 ounce) package strawberry flavored Jell-O mix",
            "0.5 cup lemon juice",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Combine ingredients in a large stockpot and boil."},
            {"@type": "HowToStep", "text": "Pack jelly into jars. Top with lids and screw rings on tightly. Lower jars into boiling water using a jar holder."},
        ],
        "nutrition": {"sodiumContent": "3 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/146995/zucchini-jelly", recipe)
    zucchini = next(i for i in record["ingredients"] if "zucchini" in i["raw"].lower())
    assert zucchini["name_normalized"] == "zucchini"
    assert {"peeled", "seeded", "shredded"}.issubset(set(zucchini["modifiers"]))
    assert "stockpot" in record["equipment"]
    assert "jars" in record["equipment"]
    assert "lids" in record["equipment"]
    assert "rings" in record["equipment"]
    assert record["dietary_flags"]["vegan"] is not True


def test_case_h_lentil_loaf_no_fake_temperatures_and_equipment() -> None:
    recipe = {
        "name": "Delicious Lentil Loaf",
        "recipeYield": ["6"],
        "recipeIngredient": [
            "1 cup brown lentils",
            "0.5 cup all-purpose flour",
            "2 tablespoons mustard",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Combine 2 1/2 cups water and lentils in a saucepan; simmer."},
            {"@type": "HowToStep", "text": "Transfer lentils to a food processor and pulse. Press into loaf pan."},
            {"@type": "HowToStep", "text": "Bake at 350 degrees F (175 degrees C)."},
        ],
        "nutrition": {"sodiumContent": "643 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/246344/delicious-lentil-loaf", recipe)
    all_temps = [temp.lower() for step in record["directions_json"] for temp in step["temperature"]]
    assert "2 c" not in all_temps
    assert "3 c" not in all_temps
    assert "4 c" not in all_temps
    assert "8 c" not in all_temps
    assert "food processor" in record["equipment"]
    assert "loaf pan" in record["equipment"]
    assert "wheat_gluten" in record["allergen_flags"]
    assert "mustard" in record["allergen_flags"]
    assert record["dietary_flags"]["high_sodium"] is True


def test_case_i_strawberry_cheesecake_french_toast_roles_and_allergens() -> None:
    recipe = {
        "name": "Strawberry Cheesecake French Toast",
        "recipeYield": ["8"],
        "recipeIngredient": [
            "1 cup milk",
            "6 eggs",
            "1 (8 ounce) package cream cheese, softened",
            "8 slices bread, cut in half diagonally",
            "2 tablespoons cornstarch",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Whisk milk and eggs in a bowl."},
            {"@type": "HowToStep", "text": "Spread cream cheese on bread to make sandwiches."},
            {"@type": "HowToStep", "text": "Cook in skillet over medium heat until golden."},
        ],
        "nutrition": {"sodiumContent": "329 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/220107/strawberry-cheesecake-french-toast", recipe)
    all_temps = [temp.lower() for step in record["directions_json"] for temp in step["temperature"]]
    assert "2 c" not in all_temps
    assert "4 c" not in all_temps
    eggs = next(i for i in record["ingredients"] if i["canonical_ingredient_id"] == "eggs")
    cream_cheese = next(i for i in record["ingredients"] if "cream cheese" in i["raw"].lower())
    bread = next(i for i in record["ingredients"] if "bread" in i["raw"].lower())
    assert eggs["ingredient_role"] == "binder"
    assert cream_cheese["ingredient_role"] == "filling"
    assert bread["ingredient_role"] in {"base", "wrapper"}
    assert {"milk", "egg", "wheat_gluten"}.issubset(set(record["allergen_flags"]))


def test_case_j_sheet_pan_shrimp_fajitas_methods_equipment_and_safety() -> None:
    recipe = {
        "name": "Sheet Pan Shrimp Fajitas",
        "recipeYield": ["8"],
        "recipeIngredient": [
            "1.5 pounds raw shrimp, peeled and deveined",
            "1 tablespoon olive oil",
            "1 (1 ounce) package fajita seasoning",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Lay shrimp on a baking sheet with peppers."},
            {"@type": "HowToStep", "text": "Roast until shrimp are opaque, 8 to 10 minutes."},
            {"@type": "HowToStep", "text": "Broil pepper mixture for 2 to 3 minutes."},
        ],
        "nutrition": {"sodiumContent": "398 mg"},
    }
    record = _build("https://www.allrecipes.com/recipe/258572/sheet-pan-shrimp-fajitas", recipe)
    assert "baking sheet" in record["equipment"]
    assert "roasting" in record["cooking_methods"]
    assert "broiling" in record["cooking_methods"]
    assert "crustacean_shellfish" in record["allergen_flags"]
    assert record["dietary_flags"]["contains_fish_or_shellfish"] is True
    safety_notes = " ".join(note for step in record["directions_json"] for note in step["food_safety_notes"]).lower()
    assert "opaque" in safety_notes
