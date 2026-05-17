import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../data/lab_report_api_client.dart';
import '../models/lab_report_extract_response.dart';

class LabReportExtractTestScreen extends StatefulWidget {
  const LabReportExtractTestScreen({
    super.key,
    required this.baseUrl,
    this.apiClient,
    this.initialResponse,
  });

  final String baseUrl;
  final LabReportApiClient? apiClient;
  final LabReportExtractResponse? initialResponse;

  @override
  State<LabReportExtractTestScreen> createState() =>
      _LabReportExtractTestScreenState();
}

class _LabReportExtractTestScreenState
    extends State<LabReportExtractTestScreen> {
  PlatformFile? _selectedPdf;
  List<PlatformFile> _selectedImages = const [];
  String? _inputType;
  bool _uploading = false;
  bool _saving = false;
  double? _uploadProgress;
  String? _errorMessage;
  String? _successMessage;
  LabReportExtractResponse? _response;

  late final LabReportApiClient _apiClient =
      widget.apiClient ?? LabReportApiClient(baseUrl: widget.baseUrl);

  @override
  void initState() {
    super.initState();
    _response = widget.initialResponse;
  }

  bool get _canUpload {
    if (_uploading || _saving) {
      return false;
    }
    if (_inputType == 'pdf') {
      return _selectedPdf != null;
    }
    if (_inputType == 'images') {
      return _selectedImages.isNotEmpty;
    }
    return false;
  }

  bool get _canSave {
    final response = _response;
    return response != null &&
        response.tests.isNotEmpty &&
        !_uploading &&
        !_saving;
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Lab Report Extraction Test',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    FilledButton.icon(
                      onPressed: _uploading ? null : _pickPdf,
                      icon: const Icon(Icons.picture_as_pdf_outlined),
                      label: const Text('Pick PDF Report'),
                    ),
                    OutlinedButton.icon(
                      onPressed: _uploading ? null : _pickImages,
                      icon: const Icon(Icons.image_outlined),
                      label: const Text('Pick Lab Report Images'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                _SelectedFilesPreview(
                  selectedPdf: _selectedPdf,
                  selectedImages: _selectedImages,
                ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: _canUpload ? _upload : null,
                  icon: const Icon(Icons.cloud_upload_outlined),
                  label: const Text('Upload'),
                ),
                if (_uploading) ...[
                  const SizedBox(height: 12),
                  LinearProgressIndicator(value: _progressIndicatorValue),
                  const SizedBox(height: 6),
                  Text(_progressLabel),
                ],
              ],
            ),
          ),
        ),
        if (_errorMessage != null) ...[
          const SizedBox(height: 12),
          _ErrorMessage(message: _errorMessage!),
        ],
        if (_successMessage != null) ...[
          const SizedBox(height: 12),
          _SuccessMessage(message: _successMessage!),
        ],
        if (_response != null) ...[
          const SizedBox(height: 12),
          _LabReportResultView(response: _response!),
          const SizedBox(height: 12),
          FilledButton.icon(
            key: const Key('confirm-save-lab-report-button'),
            onPressed: _canSave ? _saveReport : null,
            icon: _saving
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.check_circle_outline),
            label: Text(_saving ? 'Saving...' : 'Confirm & Save'),
          ),
        ],
      ],
    );
  }

  String get _progressLabel {
    final progress = _uploadProgress;
    if (progress == null) {
      return 'Preparing upload...';
    }
    if (progress >= 0.999) {
      return 'Upload complete. Backend is extracting text and parsing the report...';
    }
    return 'Upload progress: ${(progress * 100).clamp(0, 100).toStringAsFixed(0)}%';
  }

  double? get _progressIndicatorValue {
    final progress = _uploadProgress;
    if (progress == null || progress >= 0.999) {
      return null;
    }
    return progress.clamp(0, 1).toDouble();
  }

  Future<void> _pickPdf() async {
    final result = await FilePicker.platform.pickFiles(
      allowMultiple: false,
      type: FileType.custom,
      allowedExtensions: const ['pdf'],
      withData: true,
    );
    final file = result?.files.firstOrNull;
    if (file == null) {
      return;
    }
    setState(() {
      _selectedPdf = file;
      _selectedImages = const [];
      _inputType = 'pdf';
      _errorMessage = null;
      _successMessage = null;
      _response = null;
      _uploadProgress = null;
    });
  }

  Future<void> _pickImages() async {
    final result = await FilePicker.platform.pickFiles(
      allowMultiple: true,
      type: FileType.custom,
      allowedExtensions: const ['jpg', 'jpeg', 'png', 'webp'],
      withData: true,
    );
    final files = result?.files ?? const <PlatformFile>[];
    if (files.isEmpty) {
      return;
    }
    setState(() {
      _selectedPdf = null;
      _selectedImages = files;
      _inputType = 'images';
      _errorMessage = null;
      _successMessage = null;
      _response = null;
      _uploadProgress = null;
    });
  }

  Future<void> _upload() async {
    final inputType = _inputType;
    if (inputType == 'pdf' && !_canUploadPlatformFile(_selectedPdf)) {
      _setError('The selected file cannot be uploaded from this platform.');
      return;
    }
    if (inputType == 'images' &&
        _selectedImages.any((file) => !_canUploadPlatformFile(file))) {
      _setError('The selected file cannot be uploaded from this platform.');
      return;
    }

    setState(() {
      _uploading = true;
      _uploadProgress = null;
      _errorMessage = null;
      _successMessage = null;
      _response = null;
    });

    try {
      final response = inputType == 'pdf'
          ? await _apiClient.extractFromPdf(
              _selectedPdf!,
              onSendProgress: _onSendProgress,
            )
          : await _apiClient.extractFromImages(
              _selectedImages,
              onSendProgress: _onSendProgress,
            );
      if (!mounted) {
        return;
      }
      setState(() {
        _response = response;
        _uploadProgress = 1;
      });
    } on LabReportUploadException catch (error) {
      _setError(error.message);
    } on Object catch (error) {
      _setError(error.toString());
    } finally {
      if (mounted) {
        setState(() => _uploading = false);
      }
    }
  }

  Future<void> _saveReport() async {
    final response = _response;
    if (response == null) {
      return;
    }

    setState(() {
      _saving = true;
      _errorMessage = null;
      _successMessage = null;
    });

    try {
      final saved = await _apiClient.saveExtractedReport(response);
      if (!mounted) {
        return;
      }
      final id = saved.report?.id;
      setState(() {
        _successMessage = id == null
            ? 'Lab report saved.'
            : 'Lab report saved. Report ID: $id';
      });
    } on LabReportUploadException catch (error) {
      _setError(error.message);
    } on Object catch (error) {
      _setError(error.toString());
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  void _onSendProgress(int sent, int total) {
    if (!mounted || total <= 0) {
      return;
    }
    setState(() => _uploadProgress = sent / total);
  }

  void _setError(String message) {
    if (!mounted) {
      return;
    }
    setState(() {
      _errorMessage = message;
      _uploading = false;
      _saving = false;
    });
  }
}

bool _canUploadPlatformFile(PlatformFile? file) {
  if (file == null) {
    return false;
  }
  return file.bytes != null || (file.path != null && file.path!.isNotEmpty);
}

class _SelectedFilesPreview extends StatelessWidget {
  const _SelectedFilesPreview({
    required this.selectedPdf,
    required this.selectedImages,
  });

  final PlatformFile? selectedPdf;
  final List<PlatformFile> selectedImages;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('selected-files-preview'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Selected files', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 6),
        if (selectedPdf != null)
          Text(selectedPdf!.name)
        else if (selectedImages.isNotEmpty)
          for (final image in selectedImages)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text(image.name),
            )
        else
          const Text('No files selected.'),
      ],
    );
  }
}

class _ErrorMessage extends StatelessWidget {
  const _ErrorMessage({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        message,
        style: TextStyle(color: colorScheme.onErrorContainer),
      ),
    );
  }
}

class _SuccessMessage extends StatelessWidget {
  const _SuccessMessage({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colorScheme.primaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        message,
        style: TextStyle(color: colorScheme.onPrimaryContainer),
      ),
    );
  }
}

class _LabReportResultView extends StatelessWidget {
  const _LabReportResultView({required this.response});

  final LabReportExtractResponse response;

  @override
  Widget build(BuildContext context) {
    final source = response.source;
    final processedCount = source?.pagesProcessed ?? source?.imagesProcessed;
    final processedLabel = source?.pagesProcessed != null
        ? 'Pages processed'
        : 'Images processed';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Parsed result',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            _KeyValueRow(
              label: 'Sections',
              value: response.sectionsFound.isEmpty
                  ? 'None'
                  : response.sectionsFound.join(', '),
            ),
            _KeyValueRow(
              label: 'Extraction method',
              value: source?.extractionMethod ?? 'Unknown',
            ),
            if (processedCount != null)
              _KeyValueRow(label: processedLabel, value: '$processedCount'),
            if (response.warnings.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text('Warnings', style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 4),
              for (final warning in response.warnings) Text('- $warning'),
            ],
            const SizedBox(height: 12),
            Text('Tests', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 6),
            if (response.tests.isEmpty)
              const Text('No tests returned.')
            else
              for (final test in response.tests) _LabTestTile(test: test),
          ],
        ),
      ),
    );
  }
}

class _LabTestTile extends StatelessWidget {
  const _LabTestTile({required this.test});

  final LabTestResult test;

  @override
  Widget build(BuildContext context) {
    final value = _resultValue(test);
    final reference = test.referenceInterval?.raw?.trim();
    final matchedBand = test.matchedBand?.trim();
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(test.testName ?? 'Unnamed test'),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Result: $value'),
          Text(
            'Reference: ${reference == null || reference.isEmpty ? 'Unavailable' : reference}',
          ),
          Text('Status: ${test.status ?? 'indeterminate'}'),
          if (matchedBand != null && matchedBand.isNotEmpty)
            Text('Matched band: $matchedBand'),
        ],
      ),
    );
  }
}

class _KeyValueRow extends StatelessWidget {
  const _KeyValueRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: RichText(
        text: TextSpan(
          style: Theme.of(context).textTheme.bodyMedium,
          children: [
            TextSpan(
              text: '$label: ',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            TextSpan(text: value),
          ],
        ),
      ),
    );
  }
}

String _resultValue(LabTestResult test) {
  final rawValue = test.resultValue;
  final value = rawValue == null ? 'Unavailable' : rawValue.toString();
  final unit = test.unit?.trim();
  if (unit == null || unit.isEmpty) {
    return value;
  }
  return '$value $unit';
}
