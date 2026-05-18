import 'package:flutter/material.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_text_styles.dart';
import 'qima_card.dart';

class QimaEmptyState extends StatelessWidget {
  const QimaEmptyState({
    super.key,
    required this.title,
    this.message = 'No response yet.',
    this.icon = Icons.inbox_outlined,
  });

  final String title;
  final String message;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return QimaCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: colors.onSurfaceVariant),
          const SizedBox(width: AppSpacing.sm),
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
