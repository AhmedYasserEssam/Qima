import 'package:flutter/material.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_text_styles.dart';
import 'qima_card.dart';

enum QimaMessageTone { info, warning, error, success }

class QimaWarningCard extends StatelessWidget {
  const QimaWarningCard({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
    this.tone = QimaMessageTone.warning,
  });

  final IconData icon;
  final String title;
  final String message;
  final QimaMessageTone tone;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final (background, foreground, border) = switch (tone) {
      QimaMessageTone.error => (
        colors.errorContainer,
        colors.onErrorContainer,
        colors.error,
      ),
      QimaMessageTone.success => (
        colors.primaryContainer,
        colors.onPrimaryContainer,
        colors.primary,
      ),
      QimaMessageTone.info => (
        colors.secondaryContainer,
        colors.onSecondaryContainer,
        colors.secondary,
      ),
      QimaMessageTone.warning => (
        colors.tertiaryContainer,
        colors.onTertiaryContainer,
        colors.tertiary,
      ),
    };

    return QimaCard(
      backgroundColor: background,
      borderColor: border.withValues(alpha: 0.35),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: foreground),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: AppTextStyles.sectionTitle(
                    context,
                  )?.copyWith(color: foreground),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(message, style: TextStyle(color: foreground)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
