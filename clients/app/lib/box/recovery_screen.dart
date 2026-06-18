import 'package:flutter/material.dart';

import 'omg_screen.dart';
import 'recovery_controller.dart';

/// First-run "Set up recovery" screen (ADR-0016 §5).
///
/// Captures the lightweight account handle + an app password, escrows the
/// device seed (wrapped under the password and a generated OMG code), then routes
/// to the [OmgScreen] to show the one-time code ONCE. Plain language for a
/// non-technical writer (CLAUDE.md §1): "account handle" + "password", not
/// "Argon2id secret".
///
/// The share/clipboard and navigation are driven through the injected controller
/// + an [onDone] callback so widget tests exercise the flow without the platform
/// channel (CLAUDE.md §9).
class EscrowSetupScreen extends StatefulWidget {
  const EscrowSetupScreen({
    super.key,
    required this.controller,
    this.onDone,
  });

  final RecoveryController controller;

  /// Called once the user has set up recovery and confirmed they saved the OMG
  /// code. Defaults to popping this screen. Tests inject a spy.
  final VoidCallback? onDone;

  @override
  State<EscrowSetupScreen> createState() => _EscrowSetupScreenState();
}

class _EscrowSetupScreenState extends State<EscrowSetupScreen> {
  final _handleController = TextEditingController();
  final _passwordController = TextEditingController();

  @override
  void dispose() {
    _handleController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  bool get _canSubmit =>
      !widget.controller.busy &&
      _handleController.text.trim().isNotEmpty &&
      _passwordController.text.isNotEmpty;

  Future<void> _submit() async {
    final result = await widget.controller.setUpEscrow(
      handle: _handleController.text,
      password: _passwordController.text,
    );
    if (!mounted || result == null) return;
    // Clear the password field as soon as the wrap is done — no need to keep the
    // plaintext on screen (CLAUDE.md §7).
    _passwordController.clear();
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => OmgScreen(
          code: result.omgCode,
          onConfirmed: () {
            // Pop the OMG screen, then finish the setup flow.
            Navigator.of(context).pop();
            (widget.onDone ?? () => Navigator.of(context).pop())();
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final error = widget.controller.error;
        return Scaffold(
          appBar: AppBar(title: const Text('Set up recovery')),
          body: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Set up recovery so you can get back into your boxes if you lose '
                  'this device. Pick an account name and a password — and keep the '
                  'recovery code we show you next.',
                ),
                const SizedBox(height: 20),
                TextField(
                  key: const Key('handle-field'),
                  controller: _handleController,
                  textInputAction: TextInputAction.next,
                  onChanged: (_) => setState(() {}),
                  decoration: const InputDecoration(
                    labelText: 'Account name',
                    hintText: 'e.g. your email or a username',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  key: const Key('password-field'),
                  controller: _passwordController,
                  obscureText: true,
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => setState(() {}),
                  onSubmitted: (_) => _canSubmit ? _submit() : null,
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 24),
                FilledButton.icon(
                  key: const Key('escrow-submit'),
                  onPressed: _canSubmit ? _submit : null,
                  icon: widget.controller.busy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.shield_outlined),
                  label: Text(widget.controller.busy ? 'Setting up…' : 'Set up recovery'),
                ),
                if (error != null) ...[
                  const SizedBox(height: 16),
                  Text(
                    error,
                    key: const Key('escrow-error'),
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}

/// "Recover this device" screen (ADR-0016 §5) — the fresh-install recovery path.
///
/// Enter the account handle and EITHER the app password OR the one-time OMG code;
/// the controller fetches the escrow, decrypts the matching wrap, rebuilds the
/// identity (same stable deviceId → memberships restored), and self-registers.
/// On success [onRecovered] fires so the shell can route into the box flow.
class RecoverScreen extends StatefulWidget {
  const RecoverScreen({super.key, required this.controller, this.onRecovered});

  final RecoveryController controller;

  /// Fired (optionally) when the identity is successfully restored, so the shell
  /// can route the recovered device into the box flow. The success view stays
  /// shown regardless; this is a notification, not a navigation directive.
  final VoidCallback? onRecovered;

  @override
  State<RecoverScreen> createState() => _RecoverScreenState();
}

class _RecoverScreenState extends State<RecoverScreen> {
  final _handleController = TextEditingController();
  final _secretController = TextEditingController();

  /// Which recovery secret the user is entering: the password (false) or the
  /// one-time OMG code (true). Selects which escrow wrap is decrypted.
  bool _useOmgCode = false;
  bool _done = false;

  @override
  void dispose() {
    _handleController.dispose();
    _secretController.dispose();
    super.dispose();
  }

  bool get _canSubmit =>
      !widget.controller.busy &&
      _handleController.text.trim().isNotEmpty &&
      _secretController.text.trim().isNotEmpty;

  Future<void> _submit() async {
    final restored = await widget.controller.recover(
      handle: _handleController.text,
      secret: _secretController.text,
      usingOmgCode: _useOmgCode,
    );
    if (!mounted || restored == null) return;
    _secretController.clear();
    // Show the success view (the destination of this screen) and notify the
    // shell so it can route the recovered device into the box flow. The success
    // view stays up; we do NOT pop it out from under the user.
    setState(() => _done = true);
    widget.onRecovered?.call();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        if (_done) {
          return Scaffold(
            appBar: AppBar(title: const Text('Recovered')),
            body: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  const SizedBox(height: 12),
                  Icon(Icons.check_circle,
                      size: 64, color: Theme.of(context).colorScheme.primary),
                  const SizedBox(height: 12),
                  Text(
                    key: const Key('recover-success'),
                    'This device is back',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Your identity and your boxes have been restored.',
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          );
        }
        final error = widget.controller.error;
        return Scaffold(
          appBar: AppBar(title: const Text('Recover this device')),
          body: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Enter the account name you set up, then your password — or use '
                  'your one-time recovery code instead.',
                ),
                const SizedBox(height: 20),
                TextField(
                  key: const Key('recover-handle-field'),
                  controller: _handleController,
                  textInputAction: TextInputAction.next,
                  onChanged: (_) => setState(() {}),
                  decoration: const InputDecoration(
                    labelText: 'Account name',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 16),
                SegmentedButton<bool>(
                  key: const Key('recover-mode-toggle'),
                  segments: const [
                    ButtonSegment(value: false, label: Text('Password')),
                    ButtonSegment(value: true, label: Text('Recovery code')),
                  ],
                  selected: {_useOmgCode},
                  onSelectionChanged: (s) => setState(() {
                    _useOmgCode = s.first;
                    _secretController.clear();
                  }),
                ),
                const SizedBox(height: 16),
                TextField(
                  key: const Key('recover-secret-field'),
                  controller: _secretController,
                  obscureText: !_useOmgCode,
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => setState(() {}),
                  onSubmitted: (_) => _canSubmit ? _submit() : null,
                  decoration: InputDecoration(
                    labelText: _useOmgCode ? 'Recovery code' : 'Password',
                    hintText: _useOmgCode ? '7K3P9-R2M4X-WQ8TB' : null,
                    border: const OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 24),
                FilledButton(
                  key: const Key('recover-submit'),
                  onPressed: _canSubmit ? _submit : null,
                  child: Text(widget.controller.busy ? 'Recovering…' : 'Recover'),
                ),
                if (error != null) ...[
                  const SizedBox(height: 16),
                  Text(
                    error,
                    key: const Key('recover-error'),
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}
