import 'package:flutter/material.dart';

class QimaChip extends StatelessWidget {
  const QimaChip({
    super.key,
    required this.label,
    this.icon,
    this.tone = QimaChipTone.neutral,
  });

  final String label;
  final IconData? icon;
  final QimaChipTone tone;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final (background, foreground) = switch (tone) {
      QimaChipTone.error => (colors.errorContainer, colors.onErrorContainer),
      QimaChipTone.success => (
        colors.primaryContainer,
        colors.onPrimaryContainer,
      ),
      QimaChipTone.neutral => (
        colors.secondaryContainer,
        colors.onSecondaryContainer,
      ),
    };

    return Chip(
      avatar: icon == null ? null : Icon(icon, size: 16, color: foreground),
      label: Text(label),
      visualDensity: VisualDensity.compact,
      backgroundColor: background,
      labelStyle: TextStyle(color: foreground, fontWeight: FontWeight.w700),
      side: BorderSide(color: foreground.withValues(alpha: 0.18)),
    );
  }
}

enum QimaChipTone { neutral, success, error }
