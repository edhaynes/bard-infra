import 'dart:async';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import 'box_controller.dart';
import 'box_link.dart';
import 'create_box.dart';
import 'redeem.dart';

/// Share-sheet entry point used by the owner's "Add people" action. Injected so
/// widget tests drive the add-people flow without raising the native share sheet
/// (CLAUDE.md §9). Mirrors [CreateBoxScreen]'s `onShare` seam.
typedef ShareCallback = Future<void> Function(String text, {String? subject});

Future<void> _shareViaOs(String text, {String? subject}) async {
  await Share.share(text, subject: subject);
}

/// The "Box" tab: the entry point to box onboarding.
///
/// - No box joined yet → offers "Create a box" (share an invite) and "Join with
///   a link" (paste an invite URL).
/// - A box joined this session → shows the box + its members ([_MembersView])
///   and a **Ping** button.
///
/// Stateful so it can subscribe to [BoxController.pings] while mounted and raise
/// a lightweight in-app SnackBar (`Ping from <from>`) for each received ping
/// (S6 — no OS push for the MVP). A deep-link redemption (lib/deep_link.dart)
/// pushes [RedeemScreen] directly; this tab is the manual surface.
class BoxScreen extends StatefulWidget {
  const BoxScreen({
    super.key,
    required this.controller,
    this.onShare = _shareViaOs,
  });

  final BoxController controller;

  /// Share-sheet hook for the owner's "Add people" invite. Defaults to the OS
  /// share sheet; tests override it.
  final ShareCallback onShare;

  @override
  State<BoxScreen> createState() => _BoxScreenState();
}

class _BoxScreenState extends State<BoxScreen> {
  StreamSubscription<BoxPing>? _pingSub;

  @override
  void initState() {
    super.initState();
    _pingSub = widget.controller.pings.listen(_showPing);
  }

  /// Raise the in-app ping banner. Guarded on `mounted` since the stream may
  /// emit after the tab is torn down.
  void _showPing(BoxPing ping) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(
          key: const Key('ping-received'),
          content: Text('Ping from ${ping.from}'),
          duration: const Duration(seconds: 3),
        ),
      );
  }

  @override
  void dispose() {
    _pingSub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final box = widget.controller.joinedBox;
        return Scaffold(
          appBar: AppBar(title: const Text('Box')),
          body: box == null
              ? _OnboardingActions(controller: widget.controller)
              : _MembersView(controller: widget.controller, onShare: widget.onShare),
        );
      },
    );
  }
}

class _OnboardingActions extends StatelessWidget {
  const _OnboardingActions({required this.controller});

  final BoxController controller;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'A box is a private group your devices share. Create one and send '
            'the link, or join one someone sent you.',
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            key: const Key('open-create-box'),
            icon: const Icon(Icons.add_box_outlined),
            label: const Text('Create a box'),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => CreateBoxScreen(controller: controller),
              ),
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            key: const Key('open-join-box'),
            icon: const Icon(Icons.link),
            label: const Text('Join with a link'),
            onPressed: () => _promptForLink(context),
          ),
        ],
      ),
    );
  }

  Future<void> _promptForLink(BuildContext context) async {
    final linkController = TextEditingController();
    final link = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Paste invite link'),
        content: TextField(
          key: const Key('paste-link-field'),
          controller: linkController,
          autofocus: true,
          decoration: const InputDecoration(hintText: 'bard://invite?invite=…'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(linkController.text.trim()),
            child: const Text('Continue'),
          ),
        ],
      ),
    );
    if (link == null || link.isEmpty || !context.mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => RedeemScreen(controller: controller, link: link),
      ),
    );
  }
}

/// Shows the joined box and its current members. Pull-to-refresh and an explicit
/// refresh button re-fetch `GET /channels/{id}/members`.
///
/// When the controller reports [BoxController.isOwner], each member row gains a
/// Remove action and the screen offers "Add people" (mint + share a fresh
/// invite) plus a disabled "Suspend" affordance (semantics pending — not yet
/// wired to any backend). Ordinary members see none of these.
class _MembersView extends StatelessWidget {
  const _MembersView({required this.controller, required this.onShare});

  final BoxController controller;
  final ShareCallback onShare;

  bool get _isOwner => controller.isOwner;

  @override
  Widget build(BuildContext context) {
    final box = controller.joinedBox!;
    final members = controller.members;
    return RefreshIndicator(
      onRefresh: controller.refreshMembers,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: ListTile(
              leading: const Icon(Icons.inbox),
              title: Text(box.label ?? box.channelId),
              subtitle: Text(
                _isOwner
                    ? 'You manage this box (${box.deviceId})'
                    : 'You joined as ${box.deviceId}',
              ),
              trailing: IconButton(
                key: const Key('refresh-members'),
                icon: controller.busy
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.refresh),
                onPressed: controller.busy ? null : controller.refreshMembers,
              ),
            ),
          ),
          const SizedBox(height: 8),
          // The S6 payoff: ping every other connected device in this box. A
          // ping the OTHER members receive over their live link; this device
          // sees their pings as a SnackBar (wired in [_BoxScreenState]).
          FilledButton.icon(
            key: const Key('ping-box'),
            icon: const Icon(Icons.notifications_active_outlined),
            label: const Text('Ping'),
            onPressed: controller.busy ? null : () => _ping(context),
          ),
          if (_isOwner) ...[
            const SizedBox(height: 8),
            _OwnerActions(controller: controller, onShare: onShare),
          ],
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text('Members', style: Theme.of(context).textTheme.titleMedium),
          ),
          if (controller.error != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(
                controller.error!,
                key: const Key('members-error'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          if (members == null)
            const Padding(
              padding: EdgeInsets.all(8),
              child: Text('Pull down to load members.', key: Key('members-empty-hint')),
            )
          else if (members.deviceIds.isEmpty)
            const Padding(
              padding: EdgeInsets.all(8),
              child: Text('No members yet.', key: Key('members-none')),
            )
          else
            ...members.deviceIds.map(
              (id) => ListTile(
                key: Key('member-$id'),
                leading: const Icon(Icons.smartphone),
                title: Text(id),
                trailing: _trailingFor(context, box.deviceId, id),
              ),
            ),
        ],
      ),
    );
  }

  /// Send a ping to every other connected member (`POST /channels/{id}/ping`).
  /// On success shows a brief confirmation with the delivered count; failures
  /// surface via the controller's [BoxController.error] in the members list.
  Future<void> _ping(BuildContext context) async {
    final result = await controller.pingBox();
    if (!context.mounted || result == null) return;
    final n = result.delivered.length;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(
          key: const Key('ping-sent'),
          content: Text(
            n == 0 ? 'No one else is connected right now.' : 'Pinged $n device(s).',
          ),
          duration: const Duration(seconds: 2),
        ),
      );
  }

  /// The trailing affordance for a member row: a "This device" chip for the
  /// current device, a Remove button for any *other* device when this user owns
  /// the box, otherwise nothing. The current device is never removable (an owner
  /// can't evict itself here).
  Widget? _trailingFor(BuildContext context, String selfId, String memberId) {
    if (memberId == selfId) {
      return const Chip(label: Text('This device'));
    }
    if (!_isOwner) return null;
    return IconButton(
      key: Key('remove-member-$memberId'),
      icon: const Icon(Icons.person_remove_outlined),
      tooltip: 'Remove from box',
      color: Theme.of(context).colorScheme.error,
      onPressed: controller.busy ? null : () => _confirmRemove(context, memberId),
    );
  }

  Future<void> _confirmRemove(BuildContext context, String memberId) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Remove this device?'),
        content: Text(
          '$memberId will lose access to this box. You can re-invite it later '
          'with a new link.',
        ),
        actions: [
          TextButton(
            key: const Key('remove-cancel'),
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('remove-confirm'),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await controller.removeMember(memberId);
  }
}

/// Owner-only action bar: "Add people" (mint a fresh invite and share it) and a
/// disabled "Suspend" affordance whose semantics are still pending — it is
/// rendered visibly but wired to nothing on purpose.
class _OwnerActions extends StatelessWidget {
  const _OwnerActions({required this.controller, required this.onShare});

  final BoxController controller;
  final ShareCallback onShare;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: FilledButton.icon(
            key: const Key('add-people'),
            icon: const Icon(Icons.person_add_alt_1),
            label: const Text('Add people'),
            onPressed: controller.busy ? null : () => _addPeople(context),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          // Suspend is intentionally disabled: the backend has no suspend
          // endpoint yet and the semantics are pending Eddie. Rendered as a
          // visible, non-functional affordance with a "coming soon" hint.
          child: Tooltip(
            message: 'Suspend is coming soon',
            child: OutlinedButton.icon(
              key: const Key('suspend-member'),
              icon: const Icon(Icons.pause_circle_outline),
              label: const Text('Suspend'),
              onPressed: null,
            ),
          ),
        ),
      ],
    );
  }

  /// Mint a FRESH invite for THIS existing box (device-token auth) and hand the
  /// link to the OS share sheet — the MVP "add a member" flow (no direct-add
  /// endpoint exists). The new device joins by opening the link (redeem).
  Future<void> _addPeople(BuildContext context) async {
    final box = controller.joinedBox!;
    final invite = await controller.createInvite(label: box.label);
    if (!context.mounted || invite == null) return;
    await onShare(
      invite.inviteUrl,
      subject: 'Join the "${box.label ?? box.channelId}" box on Bard',
    );
  }
}
