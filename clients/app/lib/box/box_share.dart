import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

/// Share/clipboard helpers for the box screens, shared by [CreateBoxScreen] and
/// [BoxScreen] so the iPad popover anchoring + error handling live in one place.
///
/// **iPad popover anchor (bug #share-noop).** On iPad, the OS share sheet is a
/// popover and `Share.share` REQUIRES a `sharePositionOrigin` rectangle (the
/// global bounds of the control that triggered it). Without it the share button
/// "depresses but doesn't fire" — the popover has no anchor and the call no-ops
/// or throws `PlatformException`. [shareInvite] derives the origin from the
/// triggering widget's [BuildContext] so the sheet anchors correctly on iPad and
/// is harmless on iPhone (which ignores the origin).

/// The signature the box screens pass to share an invite. [context] is the
/// triggering widget's context (used to anchor the iPad popover). Injected in
/// widget tests so no native channel is hit (CLAUDE.md §9).
typedef ShareInvite = Future<void> Function(
  BuildContext context,
  String text, {
  String? subject,
});

/// The global bounds of [context]'s render box, used as the iPad share-sheet
/// popover anchor. Falls back to a small rect at the screen centre when the
/// render box is unavailable (e.g. the widget was detached) so the sheet still
/// has a valid, on-screen anchor rather than a null/empty one.
Rect sharePositionFromContext(BuildContext context) {
  final box = context.findRenderObject();
  if (box is RenderBox && box.hasSize) {
    final topLeft = box.localToGlobal(Offset.zero);
    return topLeft & box.size;
  }
  final size = MediaQuery.maybeOf(context)?.size ?? const Size(400, 800);
  return Rect.fromCenter(
    center: Offset(size.width / 2, size.height / 2),
    width: 1,
    height: 1,
  );
}

/// Raise the OS share sheet for [text], anchored to [context] (iPad popover).
/// Any platform failure is swallowed to a returned [bool] rather than thrown so
/// a caller in a tap handler never crashes the UI; the caller surfaces a hint.
/// Returns true when the sheet was presented, false on a platform error.
Future<bool> shareInvite(
  BuildContext context,
  String text, {
  String? subject,
}) async {
  try {
    await Share.share(
      text,
      subject: subject,
      sharePositionOrigin: sharePositionFromContext(context),
    );
    return true;
  } on PlatformException {
    // The share sheet could not be presented (e.g. no anchor, no handler). The
    // copy fallback in the UI keeps the link reachable.
    return false;
  }
}

/// Copy [text] to the system clipboard and confirm via a SnackBar so the tap has
/// visible feedback (the "Copy" affordance the box screens expose alongside
/// Share — bug #copy-unresponsive). Guards on `context.mounted` since the copy
/// is awaited.
Future<void> copyInvite(BuildContext context, String text) async {
  await Clipboard.setData(ClipboardData(text: text));
  if (!context.mounted) return;
  ScaffoldMessenger.of(context)
    ..clearSnackBars()
    ..showSnackBar(
      const SnackBar(
        key: Key('invite-copied'),
        content: Text('Invite link copied'),
        duration: Duration(seconds: 2),
      ),
    );
}
