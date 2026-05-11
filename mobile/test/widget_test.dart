import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:qima/main.dart';

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
    expect(find.text('Iceberg lettuce 99%'), findsOneWidget);
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
}

Widget _wrap(Widget child) {
  return ProviderScope(
    child: MaterialApp(
      home: Scaffold(body: SingleChildScrollView(child: child)),
    ),
  );
}
