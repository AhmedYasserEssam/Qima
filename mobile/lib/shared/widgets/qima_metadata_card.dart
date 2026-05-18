import 'package:flutter/material.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_text_styles.dart';
import 'qima_card.dart';

class QimaMetadataCard extends StatelessWidget {
  const QimaMetadataCard({
    super.key,
    required this.title,
    required this.lines,
    this.icon = Icons.source_outlined,
  });

  final String title;
  final List<String> lines;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    if (lines.isEmpty) {
      return const SizedBox.shrink();
    }

    final colors = Theme.of(context).colorScheme;
    return QimaCard(
      backgroundColor: colors.surfaceContainer,
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
                Text(lines.join('\n'), style: AppTextStyles.metadata(context)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
