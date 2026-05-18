import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile/main.dart';

void main() {
  test('vision nutrition request uses a high-confidence dish candidate', () {
    final request = nutritionRequestBodyFromVisionPayload({
      'dish_candidates': [
        {'name': 'Koshari', 'confidence': 0.88},
      ],
      'ingredients': [
        {'name': 'Rice', 'confidence': 0.92},
      ],
    });

    expect(request, {
      'input_type': 'recognized_dish',
      'recognized_dish': 'Koshari',
      'ingredients': ['Rice'],
    });
  });

  test('vision nutrition request falls back to distinct ingredients', () {
    final weakDishRequest = nutritionRequestBodyFromVisionPayload({
      'dish_candidates': [
        {'name': 'Koshari', 'confidence': 0.69},
      ],
      'ingredients': [
        {'name': 'Rice', 'confidence': 0.92},
        {'name': 'rice', 'confidence': 0.81},
        {'name': 'Lentils', 'confidence': 0.89},
      ],
    });
    final unknownDishRequest = nutritionRequestBodyFromVisionPayload({
      'dish_candidates': [
        {'name': 'Unknown food item', 'confidence': 0.98},
      ],
      'ingredients': [
        {'name': 'Tomato', 'confidence': 0.76},
      ],
    });

    expect(weakDishRequest, {
      'input_type': 'ingredient_set',
      'ingredients': ['Rice', 'Lentils'],
    });
    expect(unknownDishRequest, {
      'input_type': 'ingredient_set',
      'ingredients': ['Tomato'],
    });
  });

  test('vision nutrition request returns null for unusable payloads', () {
    final request = nutritionRequestBodyFromVisionPayload({
      'dish_candidates': [
        {'name': 'Unknown', 'confidence': 0.35},
      ],
      'ingredients': [],
    });

    expect(request, isNull);
  });

  testWidgets('vision result card renders normalized candidates', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      _wrap(
        PayloadCard(
          title: 'Scan result',
          payload: ApiPayload(
            raw: {
              'image_id': 'img_test_001',
              'dish_candidates': [
                {'name': 'Iceberg lettuce', 'confidence': 0.98},
                {'name': 'Lettuce leaf', 'confidence': 0.73},
              ],
              'ingredients': [
                {'name': 'Iceberg lettuce', 'confidence': 0.99},
              ],
              'confidence': 0.98,
              'source': {
                'provider': 'gemini',
                'model': 'gemini_2_5_flash',
                'source_type': 'vision_model',
              },
              'data_quality': {'completeness': 'complete'},
              'warnings': ['Low light image'],
              'latency_ms': 3832,
            },
            contractIssues: const [],
            partialReasons: const [],
          ),
        ),
      ),
    );

    expect(find.text('Scan result'), findsOneWidget);
    expect(find.text('Iceberg lettuce'), findsWidgets);
    expect(find.text('Overall confidence: 98%'), findsOneWidget);
    expect(find.text('Dish candidates'), findsOneWidget);
    expect(find.text('Lettuce leaf'), findsOneWidget);
    expect(find.text('Ingredients'), findsOneWidget);
    expect(find.text('Iceberg lettuce'), findsWidgets);
    expect(find.text('99%'), findsWidgets);
    expect(find.text('Warnings'), findsOneWidget);
    expect(find.text('Low light image'), findsOneWidget);
    expect(find.text('Estimate nutrition'), findsNothing);
    expect(find.text('Debug payload'), findsNothing);
    expect(find.textContaining('img_test_001'), findsNothing);
  });

  testWidgets('vision result card explains empty ingredient candidates', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      _wrap(
        PayloadCard(
          title: 'Scan result',
          payload: ApiPayload(
            raw: {
              'image_id': 'img_test_002',
              'dish_candidates': [
                {'name': 'Unknown food item', 'confidence': 0.32},
              ],
              'ingredients': [],
              'confidence': 0.32,
              'source': {
                'provider': 'gemini',
                'model': 'gemini_2_5_flash',
                'source_type': 'vision_model',
              },
              'data_quality': {'completeness': 'partial'},
              'warnings': [],
              'latency_ms': 104,
            },
            contractIssues: const [],
            partialReasons: const ['Confidence is low.'],
          ),
        ),
      ),
    );

    expect(find.text('Unknown food item'), findsWidgets);
    expect(
      find.text('No reliable ingredient candidates returned.'),
      findsOneWidget,
    );
    expect(find.text('Uncertainty'), findsOneWidget);
    expect(find.text('Confidence is low.'), findsOneWidget);
  });

  testWidgets('vision estimate action validates unusable nutrition input', (
    WidgetTester tester,
  ) async {
    var apiCalls = 0;

    await tester.pumpWidget(
      _wrap(
        Builder(
          builder: (context) => PayloadCard(
            title: 'Scan result',
            payload: ApiPayload(
              raw: {
                'image_id': 'img_test_003',
                'dish_candidates': [
                  {'name': 'Unknown food item', 'confidence': 0.32},
                ],
                'ingredients': [],
                'confidence': 0.32,
                'source': {
                  'provider': 'gemini',
                  'model': 'gemini_2_5_flash',
                  'source_type': 'vision_model',
                },
                'data_quality': {'completeness': 'partial'},
                'warnings': [],
                'latency_ms': 104,
              },
              contractIssues: const [],
              partialReasons: const [],
            ),
            onEstimateNutritionFromVision: (raw) {
              final request = nutritionRequestBodyFromVisionPayload(raw);
              if (request == null) {
                showValidation(context, noReliableVisionNutritionInputMessage);
                return;
              }
              apiCalls += 1;
            },
          ),
        ),
      ),
    );

    await tester.tap(find.text('Estimate nutrition'));
    await tester.pump();

    expect(apiCalls, 0);
    expect(find.text(noReliableVisionNutritionInputMessage), findsOneWidget);
  });

  testWidgets('nutrition estimate card renders flat nutrient response', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      _wrap(
        PayloadCard(
          title: 'Nutrition estimate',
          payload: ApiPayload(
            raw: {
              'matched_dish': {
                'name': 'Koshari',
                'match_type': 'dish',
                'match_id': 'egy_koshari_001',
              },
              'serving_assumptions': {
                'basis': '1 bowl',
                'note': 'Estimated from default serving assumption.',
              },
              'nutrients': {
                'calories_kcal': 420,
                'protein_g': 12,
                'carbohydrates_g': 72,
                'fat_g': 9,
                'fiber_g': 8,
                'sugar_g': 6,
                'sodium_mg': 540,
              },
              'confidence': 0.84,
              'source': {
                'dataset': 'egyptian_food_csv',
                'source_type': 'egyptian_food_dataset',
              },
              'data_quality': {'completeness': 'complete'},
              'warnings': ['Mock response. Nutrition values are estimates.'],
            },
            contractIssues: const [],
            partialReasons: const [],
          ),
        ),
      ),
    );

    expect(find.text('Nutrition estimate'), findsOneWidget);
    expect(find.text('Koshari'), findsOneWidget);
    expect(find.text('Match: dish'), findsOneWidget);
    expect(find.text('Estimate confidence: 84%'), findsOneWidget);
    expect(find.text('Serving assumption'), findsOneWidget);
    expect(find.text('1 bowl'), findsOneWidget);
    expect(find.text('Calories'), findsOneWidget);
    expect(find.text('420 kcal'), findsOneWidget);
    expect(find.text('Protein'), findsOneWidget);
    expect(find.text('12 g'), findsOneWidget);
    expect(find.text('Warnings'), findsOneWidget);
    expect(
      find.text('Mock response. Nutrition values are estimates.'),
      findsOneWidget,
    );
  });

  test('inventory items are parsed from payload shape', () {
    final items = inventoryItemsFromPayload({
      'items': [
        {
          'id': 11,
          'name': 'Rice',
          'normalized_name': 'rice',
          'source_method': 'manual',
          'source_ref': null,
          'source_product_id': null,
        },
        {
          'id': 12,
          'name': 'Chicken Breast',
          'normalized_name': 'chicken breast',
          'source_method': 'barcode',
          'source_ref': '6224000000000',
          'source_product_id': 'off:6224000000000',
        },
      ],
    });

    expect(items.length, 2);
    expect(items.first.id, 11);
    expect(items.first.name, 'Rice');
    expect(items.last.sourceMethod, 'barcode');
    expect(items.last.sourceRef, '6224000000000');
  });

  test('manual inventory add body uses items list', () {
    final body = buildInventoryManualAddBody([' rice ', 'onion', '', '  ']);
    expect(body, {
      'items': ['rice', 'onion'],
    });
  });

  test('vision inventory add body includes recognized and selected lists', () {
    final body = buildInventoryImageAddBody(
      const InventoryImageSelection(
        imageId: 'img_123',
        recognizedIngredients: ['rice', 'lentils', 'onion'],
        selectedIngredients: ['rice', 'onion'],
      ),
    );
    expect(body['image_id'], 'img_123');
    expect(body['recognized_ingredients'], ['rice', 'lentils', 'onion']);
    expect(body['selected_ingredients'], ['rice', 'onion']);
  });

  test('barcode is extracted from barcode scan payload', () {
    final barcodeFromOff = inventoryBarcodeFromScanPayload({
      'product_id': 'off:5449000000996',
      'source': {'provider_product_id': '5449000000996'},
    });
    final barcodeFromSource = inventoryBarcodeFromScanPayload({
      'product_id': 'carrefour:abc',
      'source': {'provider_product_id': '6224000000000'},
    });
    final missingBarcode = inventoryBarcodeFromScanPayload({
      'product_id': 'carrefour:abc',
      'source': {'provider_product_id': 'abc'},
    });

    expect(barcodeFromOff, '5449000000996');
    expect(barcodeFromSource, '6224000000000');
    expect(missingBarcode, isNull);
  });

  test(
    'recipe suggest body includes inventory ids pantry and budget level',
    () {
      final body = buildRecipeSuggestRequestBody(
        budgetLevel: 'mid',
        inventoryItemIds: [7, 7, 3],
        pantryItems: [' rice ', 'lentils', 'Rice'],
      );

      expect(body['budget_level'], 'mid');
      expect(body['inventory_item_ids'], [7, 3]);
      expect(body['pantry_items'], ['rice', 'lentils']);
    },
  );

  test('recipe suggestions are parsed into selectable records', () {
    final recipes = recipeSuggestionsFromPayload({
      'recipes': [
        {
          'recipe_id': 'recipe_001',
          'title': 'Tomato Lentil Skillet',
          'match_score': 0.82,
          'matched_ingredients': ['lentils', 'tomato'],
          'missing_ingredients': ['butter'],
          'recipe_ingredients': [
            {
              'name': 'lentils',
              'raw': '1 cup dry lentils',
              'quantity': 1,
              'unit': 'cup',
            },
            {
              'name': 'tomatoes',
              'raw': '1 (14.5 ounce) can diced tomatoes',
              'quantity': 1,
              'unit': 'can',
              'package_size': {'quantity': 14.5, 'unit': 'ounce'},
            },
          ],
        },
      ],
    });

    expect(recipes, hasLength(1));
    expect(recipes.first.recipeId, 'recipe_001');
    expect(recipes.first.title, 'Tomato Lentil Skillet');
    expect(recipes.first.matchedIngredients, ['lentils', 'tomato']);
    expect(recipes.first.missingIngredients, ['butter']);
    expect(recipes.first.summary, contains('Match 82%'));
    expect(recipes.first.recipeIngredients, hasLength(2));
    expect(recipes.first.recipeIngredients.first.displayLabel, '1 cup lentils');
    expect(
      recipes.first.recipeIngredients.last.displayLabel,
      '1 can tomatoes (14.5 ounce package)',
    );
    expect(
      recipes.first.ingredientQuantitySummary,
      '1 cup lentils, 1 can tomatoes (14.5 ounce package)',
    );

    const bread = RecipeIngredientQuantityRecord(
      name: 'bread',
      raw: '3 slices bread',
      quantity: 3,
      unit: 'slice',
    );
    expect(bread.displayLabel, '3 slices bread');
  });

  testWidgets('profile lab results card renders empty state and scan action', (
    WidgetTester tester,
  ) async {
    var scanTapped = false;

    await tester.pumpWidget(
      _wrap(
        ProfileLabResultsCard(
          results: const [],
          onScan: () {
            scanTapped = true;
          },
        ),
      ),
    );

    expect(find.text('Latest lab results'), findsOneWidget);
    expect(find.text('No saved lab results yet.'), findsOneWidget);

    await tester.tap(find.text('Scan lab report'));
    expect(scanTapped, isTrue);
  });

  testWidgets('profile lab results card renders latest marker details', (
    WidgetTester tester,
  ) async {
    final results = profileLabResultsFromPayload([
      {
        'report_id': 42,
        'test_name': 'Calcium (Total), Serum',
        'canonical_test_key': 'calcium_total_serum',
        'section': 'chemistry',
        'result_value': 9.6,
        'unit': 'mg/dL',
        'reference_interval': {'raw': '8.8 - 10.6'},
        'status': 'within_range',
        'matched_band': null,
        'confidence': 0.91,
        'confirmed_at': '2026-05-18T10:15:30Z',
      },
    ]);

    await tester.pumpWidget(
      _wrap(ProfileLabResultsCard(results: results, onScan: () {})),
    );

    expect(results, hasLength(1));
    expect(results.first.resultLabel, 'Result: 9.6 mg/dL');
    expect(find.text('Calcium (Total), Serum'), findsOneWidget);
    expect(find.text('Result: 9.6 mg/dL'), findsOneWidget);
    expect(find.text('Reference: 8.8 - 10.6'), findsOneWidget);
    expect(find.text('within range'), findsOneWidget);
  });

  test(
    'recipe discuss body includes context transcript and valid fields only',
    () {
      final body = buildRecipeDiscussRequestBody(
        recipeId: 'recipe_001',
        selectedRecipe: const RecipeSuggestionRecord(
          recipeId: 'recipe_001',
          title: 'Tomato Lentil Skillet',
          matchScore: 0.82,
          matchedIngredients: ['lentils', 'tomato'],
          missingIngredients: ['butter'],
        ),
        question: ' What can I substitute for butter? ',
        conversationHistory: const [
          RecipeChatTurn(role: 'user', content: 'How do I start?'),
          RecipeChatTurn(role: 'assistant', content: 'Heat the skillet first.'),
        ],
      );

      expect(body['recipe_id'], 'recipe_001');
      expect(body['question'], 'What can I substitute for butter?');
      expect(body['candidate_context'], {
        'title': 'Tomato Lentil Skillet',
        'matched_ingredients': ['lentils', 'tomato'],
        'missing_ingredients': ['butter'],
      });
      expect(body['conversation_history'], [
        {'role': 'user', 'content': 'How do I start?'},
        {'role': 'assistant', 'content': 'Heat the skillet first.'},
      ]);
      expect(body.containsKey('conversation_intent'), isFalse);
      expect(body.containsKey('price_context'), isFalse);
    },
  );

  test('recipe discuss body keeps the latest eight valid transcript turns', () {
    final body = buildRecipeDiscussRequestBody(
      recipeId: 'recipe_001',
      selectedRecipe: null,
      question: 'Continue',
      conversationHistory: [
        for (var index = 0; index < 10; index += 1)
          RecipeChatTurn(
            role: index.isEven ? 'user' : 'assistant',
            content: 'turn $index',
          ),
      ],
    );

    expect(body['conversation_history'], [
      {'role': 'user', 'content': 'turn 2'},
      {'role': 'assistant', 'content': 'turn 3'},
      {'role': 'user', 'content': 'turn 4'},
      {'role': 'assistant', 'content': 'turn 5'},
      {'role': 'user', 'content': 'turn 6'},
      {'role': 'assistant', 'content': 'turn 7'},
      {'role': 'user', 'content': 'turn 8'},
      {'role': 'assistant', 'content': 'turn 9'},
    ]);
  });
}

Widget _wrap(Widget child) {
  return ProviderScope(
    child: MaterialApp(
      home: Scaffold(body: SingleChildScrollView(child: child)),
    ),
  );
}
