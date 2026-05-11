import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:qima/main.dart';

void main() {
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
}

Widget _wrap(Widget child) {
  return ProviderScope(
    child: MaterialApp(
      home: Scaffold(body: SingleChildScrollView(child: child)),
    ),
  );
}
