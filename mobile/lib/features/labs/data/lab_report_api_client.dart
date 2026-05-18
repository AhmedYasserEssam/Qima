import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:file_picker/file_picker.dart';

import '../models/lab_report_extract_response.dart';

class LabReportApiClient {
  LabReportApiClient({
    required String baseUrl,
    Dio? dio,
    String? Function()? authTokenReader,
  }) : _authTokenReader = authTokenReader,
       _dio =
           dio ??
           Dio(
             BaseOptions(
               baseUrl: baseUrl,
               connectTimeout: _requestTimeout,
               receiveTimeout: _uploadTimeout,
               sendTimeout: _uploadTimeout,
               validateStatus: (status) => status != null,
             ),
           );

  static const _requestTimeout = Duration(seconds: 12);
  static const _uploadTimeout = Duration(seconds: 90);

  final Dio _dio;
  final String? Function()? _authTokenReader;

  Future<LabReportExtractResponse> extractFromPdf(
    PlatformFile file, {
    ProgressCallback? onSendProgress,
  }) async {
    final formData = FormData()
      ..fields.add(const MapEntry('input_type', 'pdf'))
      ..files.add(MapEntry('file', await _multipartFile(file)));

    final response = await _postMultipart(
      '/v1/labs/extract-report',
      formData,
      onSendProgress: onSendProgress,
    );
    return LabReportExtractResponse.fromJson(response);
  }

  Future<LabReportExtractResponse> extractFromImages(
    List<PlatformFile> files, {
    ProgressCallback? onSendProgress,
  }) async {
    final formData = FormData()
      ..fields.add(const MapEntry('input_type', 'images'));
    for (final file in files) {
      formData.files.add(MapEntry('files', await _multipartFile(file)));
    }

    final response = await _postMultipart(
      '/v1/labs/extract-report',
      formData,
      onSendProgress: onSendProgress,
    );
    return LabReportExtractResponse.fromJson(response);
  }

  Future<LabReportSaveResponse> saveExtractedReport(
    LabReportExtractResponse report,
  ) async {
    try {
      final response = await _dio.post<Object?>(
        '/v1/labs/reports',
        data: report.toJson(),
        options: Options(
          headers: _headers(),
          contentType: Headers.jsonContentType,
          receiveTimeout: _requestTimeout,
          sendTimeout: _requestTimeout,
        ),
      );
      final decoded = _validatedResponse(response);
      return LabReportSaveResponse.fromJson(decoded);
    } on LabReportUploadException {
      rethrow;
    } on DioException catch (error) {
      throw LabReportUploadException(_dioMessage(error));
    }
  }

  Future<Map<String, dynamic>> _postMultipart(
    String path,
    FormData data, {
    ProgressCallback? onSendProgress,
  }) async {
    try {
      final response = await _dio.post<Object?>(
        path,
        data: data,
        options: Options(headers: _headers()),
        onSendProgress: onSendProgress,
      );
      return _validatedResponse(response);
    } on LabReportUploadException {
      rethrow;
    } on DioException catch (error) {
      throw LabReportUploadException(_dioMessage(error));
    }
  }

  Map<String, String> _headers() {
    final token = _authTokenReader?.call();
    if (token == null || token.isEmpty) {
      return const {};
    }
    return {'authorization': 'Bearer $token'};
  }

  Future<MultipartFile> _multipartFile(PlatformFile file) {
    final bytes = file.bytes;
    if (bytes != null) {
      return Future.value(MultipartFile.fromBytes(bytes, filename: file.name));
    }
    final path = file.path;
    if (path != null && path.isNotEmpty) {
      return MultipartFile.fromFile(path, filename: file.name);
    }
    throw LabReportUploadException(
      'The selected file cannot be uploaded from this platform.',
    );
  }

  Map<String, dynamic> _validatedResponse(Response<Object?> response) {
    final decoded = _decodeObject(response.data);
    final statusCode = response.statusCode ?? 0;
    if (statusCode < 200 || statusCode >= 300) {
      throw LabReportUploadException(_errorMessage(statusCode, decoded));
    }
    return decoded;
  }

  Map<String, dynamic> _decodeObject(Object? data) {
    if (data is Map<String, dynamic>) {
      return data;
    }
    if (data is Map) {
      return Map<String, dynamic>.from(data);
    }
    if (data is String) {
      try {
        final decoded = jsonDecode(data);
        if (decoded is Map) {
          return Map<String, dynamic>.from(decoded);
        }
      } on FormatException {
        return {'body': data};
      }
    }
    return {'value': data};
  }

  String _errorMessage(int statusCode, Map<String, dynamic> decoded) {
    final error = decoded['error'];
    if (error is Map) {
      final message = error['message']?.toString().trim();
      if (message != null && message.isNotEmpty) {
        return message;
      }
    }
    final detail = decoded['detail'];
    if (detail is String && detail.trim().isNotEmpty) {
      return detail.trim();
    }
    if (detail is List && detail.isNotEmpty) {
      final first = detail.first;
      if (first is Map) {
        final message = first['msg']?.toString().trim();
        if (message != null && message.isNotEmpty) {
          return message;
        }
      }
    }
    return 'Request failed with HTTP $statusCode.';
  }

  String _dioMessage(DioException error) {
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return 'The FastAPI backend took too long to respond. It may still be warming up.';
      case DioExceptionType.connectionError:
      case DioExceptionType.unknown:
        return 'Could not reach the FastAPI backend.';
      case DioExceptionType.badResponse:
        final response = error.response;
        if (response == null) {
          return 'Request failed.';
        }
        return _errorMessage(
          response.statusCode ?? 0,
          _decodeObject(response.data),
        );
      case DioExceptionType.cancel:
        return 'The upload was cancelled.';
      case DioExceptionType.badCertificate:
        return 'The backend TLS certificate could not be verified.';
    }
  }
}

class LabReportUploadException implements Exception {
  const LabReportUploadException(this.message);

  final String message;

  @override
  String toString() => message;
}
