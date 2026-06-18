import 'package:flutter/material.dart';

import '../deep_link.dart';
import 'box_controller.dart';
import 'box_models.dart';

/// "Join box?" screen: the destination of an invite deep link (or a pasted
/// link). Shows a device-name field, redeems the invite, and confirms the join.
///
/// Accepts EITHER a raw [token] (already parsed from a deep link) or a [link]
/// (a pasted `bard://…?invite=…` URL) — when [link] is given the token is parsed
/// with [DeepLinkService.parseInviteToken], so the same screen serves the
/// pasted-link path. A link with no token renders an inert error state.
class RedeemScreen extends StatefulWidget {
  const RedeemScreen({
    super.key,
    required this.controller,
    this.token,
    this.link,
    this.defaultDeviceName = 'My device',
  }) : assert(token != null || link != null, 'one of token or link is required');

  final BoxController controller;

  /// A pre-parsed invite token (e.g. from [DeepLinkService]).
  final String? token;

  /// A full invite URL to parse the token from (pasted-link path).
  final String? link;

  /// Pre-filled device name (writer-facing label, CLAUDE.md §1 plain language).
  final String defaultDeviceName;

  @override
  State<RedeemScreen> createState() => _RedeemScreenState();
}

class _RedeemScreenState extends State<RedeemScreen> {
  late final TextEditingController _nameController =
      TextEditingController(text: widget.defaultDeviceName);
  RedeemResult? _joined;

  /// Resolve the invite token from whichever input the widget was given.
  String? get _token {
    if (widget.token != null && widget.token!.trim().isNotEmpty) {
      return widget.token!.trim();
    }
    final link = widget.link;
    if (link == null) return null;
    final uri = Uri.tryParse(link);
    if (uri == null) return null;
    return DeepLinkService.parseInviteToken(uri);
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  Future<void> _join() async {
    final token = _token;
    final name = _nameController.text.trim();
    if (token == null || name.isEmpty) return;
    // The device joins under its SINGLE identity (ADR-0016) — the deviceId comes
    // from the device key, not the typed name. The name is just the display
    // label for this device in the box.
    final result = await widget.controller.redeem(token, label: name);
    if (!mounted) return;
    if (result != null) {
      setState(() => _joined = result);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final token = _token;
        if (token == null) {
          return Scaffold(
            appBar: AppBar(title: const Text('Join box')),
            body: const Padding(
              padding: EdgeInsets.all(20),
              child: Text(
                key: Key('redeem-no-token'),
                'This invite link is missing its code. Ask whoever sent it for a '
                'fresh link — each link works only once.',
              ),
            ),
          );
        }
        if (_joined != null) {
          return _SuccessView(joined: _joined!);
        }
        return _JoinForm(
          controller: widget.controller,
          nameController: _nameController,
          onJoin: _join,
        );
      },
    );
  }
}

class _JoinForm extends StatelessWidget {
  const _JoinForm({
    required this.controller,
    required this.nameController,
    required this.onJoin,
  });

  final BoxController controller;
  final TextEditingController nameController;
  final Future<void> Function() onJoin;

  @override
  Widget build(BuildContext context) {
    final error = controller.error;
    return Scaffold(
      appBar: AppBar(title: const Text('Join box?')),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text("You've been invited to a box. Name this device, then join."),
            const SizedBox(height: 16),
            TextField(
              key: const Key('device-name-field'),
              controller: nameController,
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => controller.busy ? null : onJoin(),
              decoration: const InputDecoration(
                labelText: 'Device name',
                hintText: 'e.g. My iPhone',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 20),
            FilledButton(
              key: const Key('join-button'),
              onPressed: controller.busy ? null : onJoin,
              child: Text(controller.busy ? 'Joining…' : 'Join box'),
            ),
            if (error != null) ...[
              const SizedBox(height: 16),
              Text(
                error,
                key: const Key('redeem-error'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SuccessView extends StatelessWidget {
  const _SuccessView({required this.joined});

  final RedeemResult joined;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Joined')),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            const SizedBox(height: 12),
            Icon(Icons.check_circle, size: 64, color: Theme.of(context).colorScheme.primary),
            const SizedBox(height: 12),
            Text(
              key: const Key('redeem-success'),
              "You're in",
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              'This device joined the box and is ready to use.',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 24),
            Card(
              child: ListTile(
                leading: const Icon(Icons.devices),
                title: const Text('Device id'),
                subtitle: Text(joined.deviceId),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
