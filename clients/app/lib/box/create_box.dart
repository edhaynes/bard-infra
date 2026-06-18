import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import 'box_controller.dart';
import 'box_models.dart';

/// "Create a box" screen: name a box, mint a shareable invite, and hand the
/// link to the OS share sheet (SMS / AirDrop / email) so a peer can join.
///
/// The share action is injected ([onShare]) so widget tests drive the flow
/// without invoking the native share sheet (CLAUDE.md §9). Production uses
/// `Share.share`, which raises the platform share UI.
class CreateBoxScreen extends StatefulWidget {
  const CreateBoxScreen({
    super.key,
    required this.controller,
    this.onShare = _shareViaOs,
  });

  final BoxController controller;

  /// Share-sheet entry point; defaults to the OS share sheet.
  final Future<void> Function(String text, {String? subject}) onShare;

  static Future<void> _shareViaOs(String text, {String? subject}) async {
    await Share.share(text, subject: subject);
  }

  @override
  State<CreateBoxScreen> createState() => _CreateBoxScreenState();
}

class _CreateBoxScreenState extends State<CreateBoxScreen> {
  final _nameController = TextEditingController();
  InviteResult? _lastInvite;

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  bool get _canCreate =>
      !widget.controller.busy && _nameController.text.trim().isNotEmpty;

  Future<void> _create() async {
    final name = _nameController.text.trim();
    if (name.isEmpty) return;
    final invite = await widget.controller.createBox(name, label: name);
    if (!mounted) return;
    if (invite != null) {
      setState(() => _lastInvite = invite);
      await widget.onShare(
        invite.inviteUrl,
        subject: 'Join my "$name" box on Bard',
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final error = widget.controller.error;
        return Scaffold(
          appBar: AppBar(title: const Text('Create a box')),
          body: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Give your box a name, then send the invite link. Whoever '
                  'opens it joins your box.',
                ),
                const SizedBox(height: 16),
                TextField(
                  key: const Key('box-name-field'),
                  controller: _nameController,
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => setState(() {}),
                  onSubmitted: (_) => _canCreate ? _create() : null,
                  decoration: const InputDecoration(
                    labelText: 'Box name',
                    hintText: 'e.g. North site crew',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 20),
                FilledButton.icon(
                  key: const Key('create-and-share-button'),
                  onPressed: _canCreate ? _create : null,
                  icon: widget.controller.busy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.ios_share),
                  label: Text(widget.controller.busy ? 'Creating…' : 'Create & share invite'),
                ),
                if (error != null) ...[
                  const SizedBox(height: 16),
                  Text(
                    error,
                    key: const Key('create-box-error'),
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ],
                if (_lastInvite != null) ...[
                  const SizedBox(height: 24),
                  Card(
                    child: ListTile(
                      key: const Key('invite-link-tile'),
                      leading: const Icon(Icons.link),
                      title: const Text('Invite link ready'),
                      subtitle: Text(_lastInvite!.inviteUrl),
                      trailing: IconButton(
                        icon: const Icon(Icons.ios_share),
                        tooltip: 'Share again',
                        onPressed: () => widget.onShare(_lastInvite!.inviteUrl),
                      ),
                    ),
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
