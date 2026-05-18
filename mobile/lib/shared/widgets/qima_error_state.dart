import 'package:flutter/material.dart';

import '../../core/theme/app_spacing.dart';
import 'qima_warning_card.dart';

class QimaErrorState extends StatelessWidget {
  const QimaErrorState({
    super.key,
    required this.title,
    required this.message,
    this.statusCode,
    this.retryable = false,
    this.onRetry,
  });

  final String title;
  final String message;
  final int? statusCode;
  final bool retryable;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return QimaWarningCard(
      icon: Icons.error_outline,
      title: title,
      message: [message, if (statusCode != null) 'HTTP $statusCode'].join('\n'),
      tone: QimaMessageTone.error,
    ).withRetryButton(retryable && onRetry != null ? onRetry : null);
  }
}

extension _RetryableQimaError on Widget {
  Widget withRetryButton(VoidCallback? onRetry) {
    if (onRetry == null) {
      return this;
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        this,
        const SizedBox(height: AppSpacing.sm),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ),
      ],
    );
  }
}
