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
    final body = buildInventoryManualAddBody([
      ' rice ',
      'onion',
      '',
      '  ',
    ]);
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

  test('recipe suggest body includes inventory ids pantry and budget level', () {
    final body = buildRecipeSuggestRequestBody(
      budgetLevel: 'mid',
      inventoryItemIds: [7, 7, 3],
      pantryItems: [' rice ', 'lentils', 'Rice'],
    );

    expect(body['budget_level'], 'mid');
    expect(body['inventory_item_ids'], [7, 3]);
    expect(body['pantry_items'], ['rice', 'lentils']);
  });
}

Widget _wrap(Widget child) {
  return ProviderScope(
    child: MaterialApp(
      home: Scaffold(body: SingleChildScrollView(child: child)),
    ),
  );
}
