import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/labs/data/lab_report_api_client.dart';
import 'package:mobile/features/labs/models/lab_report_extract_response.dart';
import 'package:mobile/features/labs/screens/lab_report_extract_test_screen.dart';

void main() {
  testWidgets('lab report extraction test screen renders initial state', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: LabReportExtractTestScreen(baseUrl: 'http://127.0.0.1:8000'),
        ),
      ),
    );

    expect(find.text('Scan Lab Report'), findsOneWidget);
    expect(find.text('Pick PDF Report'), findsOneWidget);
    expect(find.text('Pick Lab Report Images'), findsOneWidget);
    expect(find.byKey(const Key('selected-files-preview')), findsOneWidget);
    expect(find.text('No files selected.'), findsOneWidget);

    final uploadButton = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Upload'),
    );
    expect(uploadButton.onPressed, isNull);
    expect(find.text('Confirm & Save'), findsNothing);
  });

  testWidgets('extracted tests render after extraction', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LabReportExtractTestScreen(
            baseUrl: 'http://127.0.0.1:8000',
            initialResponse: _sampleResponse(),
          ),
        ),
      ),
    );

    expect(find.text('Calcium (Total), Serum'), findsOneWidget);
    expect(find.text('Confirm & Save'), findsOneWidget);
  });

  testWidgets('confirm save calls reports endpoint and shows success', (
    WidgetTester tester,
  ) async {
    var saveCalled = false;
    final apiClient = _FakeLabReportApiClient(
      onSave: (report) async {
        saveCalled = true;
        return const LabReportSaveResponse(report: SavedLabReport(id: 42));
      },
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LabReportExtractTestScreen(
            baseUrl: 'http://127.0.0.1:8000',
            apiClient: apiClient,
            initialResponse: _sampleResponse(),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Confirm & Save'));
    await tester.pumpAndSettle();

    expect(saveCalled, isTrue);
    expect(
      find.text('Lab results saved to profile. Report ID: 42'),
      findsOneWidget,
    );
  });

  testWidgets('confirm save shows backend error', (WidgetTester tester) async {
    final apiClient = _FakeLabReportApiClient(
      onSave: (report) async {
        throw const LabReportUploadException('Save failed.');
      },
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LabReportExtractTestScreen(
            baseUrl: 'http://127.0.0.1:8000',
            apiClient: apiClient,
            initialResponse: _sampleResponse(),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Confirm & Save'));
    await tester.pumpAndSettle();

    expect(find.text('Save failed.'), findsOneWidget);
  });
}

LabReportExtractResponse _sampleResponse() {
  return const LabReportExtractResponse(
    inputType: 'images',
    reportType: 'lab_report',
    sectionsFound: ['chemistry'],
    source: ExtractionSource(extractionMethod: 'paddleocr', imagesProcessed: 1),
    tests: [
      LabTestResult(
        section: 'chemistry',
        testName: 'Calcium (Total), Serum',
        canonicalTestKey: 'calcium_total_serum',
        resultValue: 9.6,
        unit: 'mg/dL',
        referenceInterval: ReferenceInterval(
          raw: '8.8 - 10.6',
          type: 'numeric_range',
          low: 8.8,
          high: 10.6,
        ),
        status: 'within_range',
        rawText: 'Calcium (Total), Serum mg/dL 9.6 8.8 - 10.6',
      ),
    ],
  );
}

class _FakeLabReportApiClient extends LabReportApiClient {
  _FakeLabReportApiClient({required this.onSave})
    : super(baseUrl: 'http://127.0.0.1:8000');

  final Future<LabReportSaveResponse> Function(LabReportExtractResponse report)
  onSave;

  @override
  Future<LabReportSaveResponse> saveExtractedReport(
    LabReportExtractResponse report,
  ) {
    return onSave(report);
  }
}
