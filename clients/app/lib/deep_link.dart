import 'dart:async';

import 'package:app_links/app_links.dart';

/// Receives box invite deep links (`bard://invite?invite=<token>`) at launch and
/// while the app is running, and turns them into an invite token for the redeem
/// flow.
///
/// The parsing ([parseInviteToken]) is a pure, plugin-free static — unit-tested
/// without any native channel (CLAUDE.md §9: no platform calls in unit tests).
/// The [AppLinks] stream wiring is isolated in [start] so the rest of the app
/// (and its tests) never touch the plugin.
///
/// Wire format: the registry builds the invite URL as
/// `<base>?invite=<urlencoded-token>` (registry/channel_store.py
/// `_INVITE_QUERY_PARAM = "invite"`); the same token also rides the web join
/// server's `?invite=` link. We accept the `invite` query key (authoritative)
/// and fall back to `token` so a hand-built `bard://invite?token=…` link — the
/// shape named in the onboarding brief — also resolves.
class DeepLinkService {
  DeepLinkService({AppLinks? appLinks}) : _appLinks = appLinks ?? AppLinks();

  /// Query keys that may carry the invite token, in precedence order.
  static const inviteTokenKeys = ['invite', 'token'];

  final AppLinks _appLinks;
  StreamSubscription<Uri>? _sub;

  /// Extract the invite token from a deep-link [uri], or null when the URI does
  /// not carry one. Tolerant of either query key and of an empty/whitespace
  /// value (treated as absent). Pure — safe to unit-test.
  static String? parseInviteToken(Uri uri) {
    for (final key in inviteTokenKeys) {
      final raw = uri.queryParameters[key];
      if (raw != null && raw.trim().isNotEmpty) {
        return raw.trim();
      }
    }
    return null;
  }

  /// Begin listening for invite deep links.
  ///
  /// Fires [onToken] for the launch link (if the app was cold-started from a
  /// link) and for every subsequent link received while running. Links without
  /// an invite token are ignored. Returns once the launch link has been checked
  /// so the caller can sequence UI (e.g. show the redeem sheet) deterministically.
  Future<void> start(void Function(String token) onToken) async {
    // Cold-start link (the app was launched by tapping the invite).
    final initial = await _appLinks.getInitialLink();
    if (initial != null) {
      final token = parseInviteToken(initial);
      if (token != null) onToken(token);
    }
    // Warm links while the app is already running.
    _sub = _appLinks.uriLinkStream.listen((uri) {
      final token = parseInviteToken(uri);
      if (token != null) onToken(token);
    });
  }

  /// Stop listening; idempotent.
  Future<void> dispose() async {
    await _sub?.cancel();
    _sub = null;
  }
}
