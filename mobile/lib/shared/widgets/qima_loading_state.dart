import 'package:flutter/material.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_text_styles.dart';
import 'qima_card.dart';

class QimaLoadingState extends StatelessWidget {
  const QimaLoadingState({
    super.key,
    required this.title,
    this.message = 'Calling FastAPI...',
  });

  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return QimaCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox.square(
            dimension: 24,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: AppTextStyles.sectionTitle(context)),
                const SizedBox(height: AppSpacing.xs),
                Text(message, style: AppTextStyles.metadata(context)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
