import 'package:flutter/material.dart';

import 'model_info.dart';

/// Professional model list — name, provider, params, quant, size, status.
/// Deliberately plain (no album art / skins) per the Pro design direction.
class ModelsScreen extends StatelessWidget {
  const ModelsScreen({super.key, required this.models, this.onRefresh});

  final List<ModelInfo> models;
  final Future<void> Function()? onRefresh;

  @override
  Widget build(BuildContext context) {
    final list = ListView.separated(
      itemCount: models.length,
      separatorBuilder: (_, _) => const Divider(height: 1),
      itemBuilder: (context, i) => _ModelTile(model: models[i]),
    );
    return Scaffold(
      appBar: AppBar(title: const Text('Models')),
      body: onRefresh == null ? list : RefreshIndicator(onRefresh: onRefresh!, child: list),
    );
  }
}

class _ModelTile extends StatelessWidget {
  const _ModelTile({required this.model});

  final ModelInfo model;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 6),
      leading: CircleAvatar(
        child: Text(model.params == '—' ? '?' : model.params,
            style: const TextStyle(fontSize: 12)),
      ),
      title: Text(model.name, style: theme.textTheme.titleMedium),
      subtitle: Text(
        '${model.provider} · ${model.quant}'
        '${model.sizeGb > 0 ? ' · ${model.sizeGb.toStringAsFixed(1)} GB' : ''}',
        style: theme.textTheme.bodySmall,
      ),
      trailing: _StatusChip(status: model.status),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (Color fg, Color bg) = switch (status) {
      'ready' => (scheme.onPrimaryContainer, scheme.primaryContainer),
      'loading' => (scheme.onTertiaryContainer, scheme.tertiaryContainer),
      _ => (scheme.onSurfaceVariant, scheme.surfaceContainerHighest),
    };
    return Chip(
      label: Text(status, style: TextStyle(color: fg, fontSize: 12)),
      backgroundColor: bg,
      visualDensity: VisualDensity.compact,
      side: BorderSide.none,
    );
  }
}
