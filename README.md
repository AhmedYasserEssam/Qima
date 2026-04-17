# NutriAI / Qima

NutriAI is an AI-powered nutrition assistant focused on two main user journeys:

- packaged-food understanding through barcode lookup
- non-barcode food understanding through image-based recognition

The current project baseline also includes a recipe-assistance layer that operates in a retrieval-first manner after ingredient or dish recognition.

## Project Goal

The system is intended to help users:

- scan packaged foods and retrieve normalized nutrition, ingredient, and allergen information
- upload meal images and receive recognized dish candidates plus estimated nutrients
- compare foods or meals using grounded nutrition data
- get recipe suggestions and follow-up recipe assistance based on recognized ingredients or pantry items

## Architecture Overview

The current architecture described in `Docs/Architecture_Updated_260417_v13.docx` is:

- `Flutter` mobile client
  - camera, barcode scan, UI, session state, API calls
- `Python + FastAPI` backend
  - orchestration, normalization, caching, persistence, provider integration
- `Open Food Facts API`
  - packaged-food barcode lookup
- `Google Gemini 2.5 Flash`
  - no-barcode food and meal image understanding
- `Groq llama-3.1-8b-instant`
  - grounded explanations, comparisons, recipe summary, and light adaptation
- nutrition data layer
  - primary, localized, and fallback nutrition sources
- recipe corpus
  - retrieval-first recipe suggestions and grounded recipe discussion

## Nutrition Data Sources

The backend nutrition source hierarchy is currently:

1. `data/Food/nutrition.xlsx`
   Primary generic food nutrient dataset
2. `data/Food/Egyptian Food.csv`
   Egyptian food and localized dish coverage
3. `data/Food/FoodData_Central_foundation_food_json_2025-12-18.json`
   Fallback source
4. `data/Food/FoodData_Central_sr_legacy_food_json_2018-04.json`
   Fallback source

In practice:

- `nutrition.xlsx` is the first lookup for general foods
- `Egyptian Food.csv` is used for Egyptian foods and localized meal grounding
- FoodData Central Foundation and SR Legacy are used when the primary sources do not provide a usable match

## Planned Request Flows

### 1. Barcode Product Lookup

- User scans a barcode in Flutter
- Flutter sends the barcode to FastAPI
- FastAPI queries Open Food Facts
- Backend normalizes nutrition, ingredients, and allergens
- Normalized response is returned to the client

### 2. No-Barcode Meal Recognition

- User uploads an image in Flutter
- FastAPI sends the image to Gemini 2.5 Flash
- Backend extracts structured dish candidates, ingredients, and confidence
- Backend maps recognized foods through the nutrition source hierarchy
- Backend returns nutrient estimates plus confidence and source metadata

### 3. Nutrition Estimation

Planned backend contract includes:

- `/nutrition/estimate`

Expected output shape includes:

- matched dish or food
- serving assumptions
- nutrients
- confidence
- source metadata

### 4. Recipe Assistance

The recipe layer is not a free-form generation system by default.

It is designed as:

- retrieval-first recipe suggestion
- grounded recipe summary and explanation
- light adaptation of retrieved candidates

## Repository Structure

```text
Qima/
├── data/
│   ├── Food/
│   │   ├── nutrition.xlsx
│   │   ├── Egyptian Food.csv
│   │   ├── FoodData_Central_foundation_food_json_2025-12-18.json
│   │   └── FoodData_Central_sr_legacy_food_json_2018-04.json
│   └── Recipes/
│       └── 13k-recipes.csv
├── Docs/
│   ├── Architecture_Updated_260417_v13.docx
│   └── Decision_Log_Updated_260417_v13.docx
├── .gitignore
└── LICENSE
```

## Design Rules

The current architecture baseline establishes these constraints:

- Flutter should call backend endpoints only
- provider integrations stay in the backend
- barcode and non-barcode flows remain separate upstream
- all nutrition responses should be normalized into one backend-owned schema
- recipe outputs should remain grounded in retrieved recipe data

## Current Status

At the moment, this repository primarily contains:

- architecture and decision documentation
- food and recipe datasets
- project-level Git configuration

The README should be updated as implementation files for the mobile client, backend API, schemas, and matching logic are added.

## Reference Documents

- `Docs/Architecture_Updated_260417_v13.docx`
- `Docs/Decision_Log_Updated_260417_v13.docx`

