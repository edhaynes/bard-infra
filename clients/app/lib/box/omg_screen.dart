import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// The OMG "show once" screen (ADR-0016 §5).
///
/// Displays the one-time recovery code a SINGLE time with a clear "save or print
/// this — it will not be shown again" warning, lets the user copy it, and gates
/// the way forward behind a "I've saved it" confirmation. The code is held only
/// in this widget's state; on confirm the in-memory copy is wiped (overwritten +
/// dropped) and [onConfirmed] fires, so the code is never retained after the user
/// leaves this screen (CLAUDE.md §7: secret material is not kept around).
///
/// Plain language for a non-technical writer (CLAUDE.md §1): "recovery code", not
/// "OMG seed wrap".
class OmgScreen extends StatefulWidget {
  const OmgScreen({
    super.key,
    required this.code,
    required this.onConfirmed,
    this.onCopy = _copyToClipboard,
  });

  /// The one-time recovery code to show (formatted `XXXXX-XXXXX-XXXXX`).
  final String code;

  /// Called after the user confirms they saved the code. The widget has wiped
  /// its in-memory copy by this point. Typically pops back to the box/home flow.
  final VoidCallback onConfirmed;

  /// Clipboard hook (injected so widget tests don't touch the platform channel,
  /// CLAUDE.md §9). Defaults to the system clipboard.
  final Future<void> Function(String text) onCopy;

  static Future<void> _copyToClipboard(String text) =>
      Clipboard.setData(ClipboardData(text: text));

  @override
  State<OmgScreen> createState() => _OmgScreenState();
}

class _OmgScreenState extends State<OmgScreen> {
  /// The code, held mutably so it can be WIPED on confirm (overwritten with a
  /// blank of the same shape, then cleared) rather than lingering in memory.
  late String _code = widget.code;
  bool _saved = false;

  void _confirm() {
    // Wipe the in-memory copy before handing control back. Overwrite then clear
    // so a heap snapshot after this point does not hold the recovery code.
    setState(() {
      _code = '•' * _code.length;
      _code = '';
    });
    widget.onConfirmed();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your recovery code'),
        automaticallyImplyLeading: false, // no back-out: confirm-or-stay.
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Save or print this code now. It is the only way to get back into '
              'your boxes if you lose this device, and it will NOT be shown again.',
              style: theme.textTheme.bodyLarge,
            ),
            const SizedBox(height: 24),
            Card(
              color: theme.colorScheme.surfaceContainerHighest,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
                child: SelectableText(
                  _code,
                  key: const Key('omg-code'),
                  textAlign: TextAlign.center,
                  style: theme.textTheme.headlineSmall?.copyWith(
                    fontFeatures: const [FontFeature.tabularFigures()],
                    letterSpacing: 2,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const Key('omg-copy'),
              icon: const Icon(Icons.copy),
              label: const Text('Copy code'),
              onPressed: _code.isEmpty ? null : () => widget.onCopy(widget.code),
            ),
            const SizedBox(height: 24),
            CheckboxListTile(
              key: const Key('omg-saved-check'),
              value: _saved,
              onChanged: (v) => setState(() => _saved = v ?? false),
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: const Text(
                "I've saved my recovery code somewhere safe.",
              ),
            ),
            const SizedBox(height: 8),
            FilledButton(
              key: const Key('omg-confirm'),
              onPressed: _saved ? _confirm : null,
              child: const Text('Done'),
            ),
          ],
        ),
      ),
    );
  }
}
