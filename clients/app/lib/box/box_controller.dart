import 'package:flutter/foundation.dart';

import '../api.dart';
import '../device_auth.dart';
import '../secure_store.dart';
import 'box_models.dart';

/// Orchestrates the box onboarding flow for the UI (CLAUDE.md §2: logic out of
/// widgets). Creates invites, redeems them, persists the one-time secret, and
/// exposes the joined box + its members. A [ChangeNotifier] so the box screens
/// rebuild via `ListenableBuilder`, matching the app's existing state pattern
/// (no third-party state dep).
///
/// Collaborators are injected (DI seam): [apiFactory] builds a [BardApi] bound
/// to the right base URL/token (manager token for create/members; per-device
/// token for fabric calls), and [secretStore] persists the credential. Tests
/// bind a fake store and a `MockClient`-backed api.
class BoxController extends ChangeNotifier {
  // ignore_for_file: prefer_initializing_formals — the public named params map
  // to private fields; an initializing formal can't be a private named param.
  BoxController({
    required BardApi Function() apiFactory,
    required SecretStore secretStore,
    DeviceAuth deviceAuth = const DeviceAuth(),
  })  : _apiFactory = apiFactory,
        _secretStore = secretStore,
        _deviceAuth = deviceAuth;

  final BardApi Function() _apiFactory;
  final SecretStore _secretStore;
  final DeviceAuth _deviceAuth;

  JoinedBox? _joinedBox;
  ChannelMembers? _members;
  bool _busy = false;
  String? _error;

  /// The box this device has joined this session, or null before a redeem.
  JoinedBox? get joinedBox => _joinedBox;

  /// Last-fetched membership for [joinedBox], or null until [refreshMembers].
  ChannelMembers? get members => _members;

  /// True while a create/redeem/members call is in flight (drives spinners).
  bool get busy => _busy;

  /// True when the joined box is owned/managed by this device (creator / manager
  /// token holder). Drives the owner-only management UI (remove member, add
  /// people). False for a member that joined by redeeming an invite.
  bool get isOwner => _joinedBox?.isOwner ?? false;

  /// Last user-facing error message, or null when the last action succeeded.
  String? get error => _error;

  /// Create a box (channel) and return the shareable invite for the OS share
  /// sheet. The caller (create_box.dart) hands [InviteResult.inviteUrl] to
  /// `Share.share`. Surfaces failures via [error] and returns null.
  Future<InviteResult?> createBox(String channelId, {String? label}) async {
    return _run(() async {
      final api = _apiFactory();
      try {
        return await api.createInvite(channelId, label: label);
      } finally {
        api.close();
      }
    });
  }

  /// Record the OWNER context for a box this device created/manages, so the Box
  /// screen renders the owner-only management UI. [deviceId] is the owner's own
  /// device id within the box; [label] is the box's human name. Membership is
  /// cleared so the next [refreshMembers] reloads under the owner view. The
  /// manager credential lives in the [BardApi] [apiFactory] builds, not here.
  void enterAsOwner(String channelId, {required String deviceId, String? label}) {
    _joinedBox = JoinedBox(
      channelId: channelId,
      deviceId: deviceId,
      label: label,
      isOwner: true,
    );
    _members = null;
    _error = null;
    notifyListeners();
  }

  /// Redeem an invite [token] under [deviceId]/[label]: admits this device
  /// ACTIVE into the box, persists the one-time secret, and records the joined
  /// box. Returns the [RedeemResult] on success (secret already stored) or null
  /// on failure (message in [error]).
  Future<RedeemResult?> redeem(
    String token, {
    required String deviceId,
    String? label,
  }) async {
    return _run(() async {
      final api = _apiFactory();
      RedeemResult result;
      try {
        result = await api.redeemInvite(token, deviceId: deviceId, label: label);
      } finally {
        api.close();
      }
      // Persist the ONE-TIME secret before anything else can drop it.
      await _secretStore.writeDeviceSecret(
        channelId: result.channelId,
        deviceId: result.deviceId,
        secret: result.deviceSecret,
      );
      _joinedBox = JoinedBox(
        channelId: result.channelId,
        deviceId: result.deviceId,
        label: label,
      );
      _members = null;
      return result;
    });
  }

  /// Fetch the current membership of [joinedBox]. No-op when no box is joined.
  Future<ChannelMembers?> refreshMembers() async {
    final box = _joinedBox;
    if (box == null) return null;
    return _run(() async {
      final api = _apiFactory();
      try {
        final m = await api.channelMembers(box.channelId);
        _members = m;
        return m;
      } finally {
        api.close();
      }
    });
  }

  /// Evict [deviceId] from the joined box (owner-only; manager-auth). Drives
  /// `POST /channels/{id}/members/{deviceId}/remove`, then adopts the UPDATED
  /// membership the server returns so the list reflects the removal without a
  /// second round-trip. No-op (returns null) when no box is joined or this device
  /// is not the owner. Surfaces failures via [error] and returns null.
  Future<ChannelMembers?> removeMember(String deviceId) async {
    final box = _joinedBox;
    if (box == null || !box.isOwner) return null;
    return _run(() async {
      final api = _apiFactory();
      try {
        final updated = await api.removeMember(box.channelId, deviceId);
        _members = updated;
        return updated;
      } finally {
        api.close();
      }
    });
  }

  /// Mint a per-device fabric token for the joined box from the stored secret,
  /// or null when no box is joined or no secret is stored. This is the bearer a
  /// device-mode [BardApi] presents for fabric calls.
  Future<String?> mintDeviceToken() async {
    final box = _joinedBox;
    if (box == null) return null;
    final secret = await _secretStore.readDeviceSecret(
      channelId: box.channelId,
      deviceId: box.deviceId,
    );
    if (secret == null) return null;
    return _deviceAuth.mintToken(deviceId: box.deviceId, deviceSecret: secret);
  }

  /// Run [action] with busy/error bookkeeping and notification. Returns the
  /// action's result, or null when it threw a [BardApiException] (message
  /// captured in [error]).
  Future<T?> _run<T>(Future<T> Function() action) async {
    _busy = true;
    _error = null;
    notifyListeners();
    try {
      final result = await action();
      return result;
    } on BardApiException catch (e) {
      _error = e.message;
      return null;
    } finally {
      _busy = false;
      notifyListeners();
    }
  }
}
