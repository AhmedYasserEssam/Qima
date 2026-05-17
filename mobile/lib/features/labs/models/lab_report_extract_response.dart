class LabReportExtractResponse {
  const LabReportExtractResponse({
    this.inputType,
    this.reportType,
    this.tests = const [],
    this.sectionsFound = const [],
    this.source,
    this.warnings = const [],
    this.rawTextPreview,
  });

  factory LabReportExtractResponse.fromJson(Map<String, dynamic> json) {
    return LabReportExtractResponse(
      inputType: _string(json['input_type']),
      reportType: _string(json['report_type']),
      tests: _listOfMaps(json['tests']).map(LabTestResult.fromJson).toList(),
      sectionsFound: _stringList(json['sections_found']),
      source: json['source'] is Map
          ? ExtractionSource.fromJson(
              Map<String, dynamic>.from(json['source'] as Map),
            )
          : null,
      warnings: _stringList(json['warnings']),
      rawTextPreview: _string(json['raw_text_preview']),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'input_type': inputType,
      'report_type': reportType ?? 'lab_report',
      'tests': tests.map((test) => test.toJson()).toList(),
      'sections_found': sectionsFound,
      'source': source?.toJson(),
      'warnings': warnings,
      'raw_text_preview': rawTextPreview,
    };
  }

  final String? inputType;
  final String? reportType;
  final List<LabTestResult> tests;
  final List<String> sectionsFound;
  final ExtractionSource? source;
  final List<String> warnings;
  final String? rawTextPreview;
}

class LabReportSaveResponse {
  const LabReportSaveResponse({this.report});

  factory LabReportSaveResponse.fromJson(Map<String, dynamic> json) {
    return LabReportSaveResponse(
      report: json['report'] is Map
          ? SavedLabReport.fromJson(
              Map<String, dynamic>.from(json['report'] as Map),
            )
          : null,
    );
  }

  final SavedLabReport? report;
}

class SavedLabReport extends LabReportExtractResponse {
  const SavedLabReport({
    this.id,
    super.inputType,
    super.reportType,
    super.tests,
    super.sectionsFound,
    super.source,
    super.warnings,
    super.rawTextPreview,
    this.extractedAt,
    this.confirmedAt,
    this.createdAt,
    this.updatedAt,
  });

  factory SavedLabReport.fromJson(Map<String, dynamic> json) {
    final extracted = LabReportExtractResponse.fromJson(json);
    return SavedLabReport(
      id: _int(json['id']),
      inputType: extracted.inputType,
      reportType: extracted.reportType,
      tests: extracted.tests,
      sectionsFound: extracted.sectionsFound,
      source: extracted.source,
      warnings: extracted.warnings,
      rawTextPreview: extracted.rawTextPreview,
      extractedAt: _string(json['extracted_at']),
      confirmedAt: _string(json['confirmed_at']),
      createdAt: _string(json['created_at']),
      updatedAt: _string(json['updated_at']),
    );
  }

  final int? id;
  final String? extractedAt;
  final String? confirmedAt;
  final String? createdAt;
  final String? updatedAt;
}

class LabTestResult {
  const LabTestResult({
    this.section,
    this.testName,
    this.canonicalTestKey,
    this.resultValue,
    this.unit,
    this.referenceInterval,
    this.status,
    this.matchedBand,
    this.rawText,
    this.confidence,
  });

  factory LabTestResult.fromJson(Map<String, dynamic> json) {
    return LabTestResult(
      section: _string(json['section']),
      testName: _string(json['test_name']),
      canonicalTestKey: _string(json['canonical_test_key']),
      resultValue: json['result_value'],
      unit: _string(json['unit']),
      referenceInterval: json['reference_interval'] is Map
          ? ReferenceInterval.fromJson(
              Map<String, dynamic>.from(json['reference_interval'] as Map),
            )
          : null,
      status: _string(json['status']),
      matchedBand: _string(json['matched_band']),
      rawText: _string(json['raw_text']),
      confidence: _number(json['confidence']),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'section': section,
      'test_name': testName,
      'canonical_test_key': canonicalTestKey,
      'result_value': resultValue,
      'unit': unit,
      'reference_interval': referenceInterval?.toJson(),
      'status': status,
      'matched_band': matchedBand,
      'raw_text': rawText,
      'confidence': confidence,
    };
  }

  final String? section;
  final String? testName;
  final String? canonicalTestKey;
  final Object? resultValue;
  final String? unit;
  final ReferenceInterval? referenceInterval;
  final String? status;
  final String? matchedBand;
  final String? rawText;
  final double? confidence;
}

class ReferenceInterval {
  const ReferenceInterval({
    this.raw,
    this.type,
    this.low,
    this.high,
    this.operator,
    this.bands = const [],
  });

  factory ReferenceInterval.fromJson(Map<String, dynamic> json) {
    return ReferenceInterval(
      raw: _string(json['raw']),
      type: _string(json['type']),
      low: _number(json['low']),
      high: _number(json['high']),
      operator: _string(json['operator']),
      bands: _listOfMaps(json['bands']).map(ReferenceBand.fromJson).toList(),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'raw': raw,
      'type': type,
      'low': low,
      'high': high,
      'operator': operator,
      'bands': bands.map((band) => band.toJson()).toList(),
    };
  }

  final String? raw;
  final String? type;
  final double? low;
  final double? high;
  final String? operator;
  final List<ReferenceBand> bands;
}

class ReferenceBand {
  const ReferenceBand({
    this.label,
    this.operator,
    this.low,
    this.high,
    this.raw,
  });

  factory ReferenceBand.fromJson(Map<String, dynamic> json) {
    return ReferenceBand(
      label: _string(json['label']),
      operator: _string(json['operator']),
      low: _number(json['low']),
      high: _number(json['high']),
      raw: _string(json['raw']),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'label': label,
      'operator': operator,
      'low': low,
      'high': high,
      'raw': raw,
    };
  }

  final String? label;
  final String? operator;
  final double? low;
  final double? high;
  final String? raw;
}

class ExtractionSource {
  const ExtractionSource({
    this.extractionMethod,
    this.pagesProcessed,
    this.imagesProcessed,
  });

  factory ExtractionSource.fromJson(Map<String, dynamic> json) {
    return ExtractionSource(
      extractionMethod: _string(json['extraction_method']),
      pagesProcessed: _int(json['pages_processed']),
      imagesProcessed: _int(json['images_processed']),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'extraction_method': extractionMethod,
      'pages_processed': pagesProcessed,
      'images_processed': imagesProcessed,
    };
  }

  final String? extractionMethod;
  final int? pagesProcessed;
  final int? imagesProcessed;
}

List<Map<String, dynamic>> _listOfMaps(Object? value) {
  if (value is! List) {
    return const [];
  }
  return [
    for (final item in value)
      if (item is Map) Map<String, dynamic>.from(item),
  ];
}

List<String> _stringList(Object? value) {
  if (value is! List) {
    return const [];
  }
  return [
    for (final item in value)
      if (item != null && item.toString().trim().isNotEmpty)
        item.toString().trim(),
  ];
}

double? _number(Object? value) {
  if (value is num) {
    return value.toDouble();
  }
  if (value is String) {
    return double.tryParse(value);
  }
  return null;
}

int? _int(Object? value) {
  if (value is int) {
    return value;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is String) {
    return int.tryParse(value);
  }
  return null;
}

String? _string(Object? value) {
  if (value == null) {
    return null;
  }
  return value.toString();
}
