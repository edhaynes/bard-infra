import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api.dart';
import '../device_auth.dart';
import '../secure_store.dart';
import 'box_link.dart';
import 'box_models.dart';
import 'device_identity.dart';

/// Builds a [BardApi] for a box call. When [tokenProvider] is supplied the api
/// runs in per-device mode (the bearer is minted fresh per request from the
/// device's own key, ADR-0016 §4); when omitted it falls back to the static
/// backend token (only the no-auth redeem path uses that fallback).
typedef BoxApiFactory = BardApi Function({String Function()? tokenProvider});

/// Builds the box receive link (WS to the Router `/v1/agent-link`) given the
/// async [tokenProvider] that mints THIS device's EdDSA token per (re)connect.
/// Injected (CLAUDE.md §3 swappable backend) so unit tests bind a [BoxLink] over
/// a fake transport — no real socket (CLAUDE.md §9). Null in the factory means
/// "no link" (e.g. a controller built without a Router base), and the ping
/// receive path is simply inert.
typedef BoxLinkFactory = BoxLink? Function({
  required Future<String?> Function() tokenProvider,
});

/// Orchestrates the box onboarding flow for the UI (CLAUDE.md §2: logic out of
/// widgets). Provisions the device's single identity, self-registers it, creates
/// boxes it OWNS, redeems invites to join, and exposes the joined box + members.
/// A [ChangeNotifier] so the box screens rebuild via `ListenableBuilder`.
///
/// ADR-0016 §1/§4: there is ONE device identity ([DeviceIdentity]). Owner actions
/// (create channel, create invite, members, remove) are authed by the device's
/// OWN self-signed token — never the baked `BARD_AUTH_TOKEN` (this closes bug
/// #67). The [apiFactory] builds a [BardApi]; in per-device mode it is handed a
/// `tokenProvider` that mints from [_identity].
///
/// Collaborators are injected (DI seam): [apiFactory] builds the api,
/// [secretStore] persists the device key, [deviceIdentity] owns the single
/// identity. Tests bind a fake store and a `MockClient`-backed api.
class BoxController extends ChangeNotifier {
  BoxController({
    required BoxApiFactory apiFactory,
    required SecretStore secretStore,
    DeviceAuth deviceAuth = const DeviceAuth(),
    DeviceIdentity? deviceIdentity,
    SeedFactory? seedFactory,
    BoxLinkFactory? linkFactory,
  })  : _apiFactory = apiFactory,
        _linkFactory = linkFactory,
        _identity = deviceIdentity ??
            DeviceIdentity(
              secretStore: secretStore,
              deviceAuth: deviceAuth,
              seedFactory: seedFactory,
            );

  // ignore_for_file: prefer_initializing_formals — the public `apiFactory` named
  // param maps to the private `_apiFactory` field; an initializing formal can't
  // be a private named param.
  final BoxApiFactory _apiFactory;
  final DeviceIdentity _identity;

  /// Builds the receive link when entering a box. Null when the controller has
  /// no Router WS endpoint wired — the ping send still works, only the inbound
  /// push path is inert.
  final BoxLinkFactory? _linkFactory;

  JoinedBox? _joinedBox;
  ChannelMembers? _members;
  bool _busy = false;
  String? _error;

  /// The live receive link for the joined box (WS to the Router), or null when
  /// no box is in view / no [_linkFactory] was supplied. Opened on entering a
  /// box and closed on leave/dispose so the socket lifecycle tracks the view.
  BoxLink? _link;

  /// Re-broadcasts [BoxLink.pings] so the UI subscribes to ONE stable stream
  /// across reconnects and across entering different boxes. Pings for the
  /// currently-joined box are forwarded; created lazily on first listen.
  final StreamController<BoxPing> _pings = StreamController<BoxPing>.broadcast();

  /// Forwards the active link's pings into [_pings]; cancelled when the link is
  /// torn down. Kept so re-entering a box re-subscribes cleanly.
  StreamSubscription<BoxPing>? _linkSub;

  /// The last ping received while viewing the joined box, or null. The Box
  /// screen watches this (via [notifyListeners]) to raise the in-app banner.
  BoxPing? _lastPing;

  /// Inbound pings for the joined box as a stable broadcast stream (survives WS
  /// reconnects). The UI MAY listen to this directly for transient banners;
  /// [lastPing] is the notifier-friendly snapshot for `ListenableBuilder`.
  Stream<BoxPing> get pings => _pings.stream;

  /// The most recent ping received while in the current box, or null. Surfaced
  /// via [notifyListeners] so the Box screen shows `Ping from <from>`.
  BoxPing? get lastPing => _lastPing;

  /// In-memory snapshot of the provisioned identity, so the api's synchronous
  /// `tokenProvider` can mint a fresh token without an async store read mid-call.
  /// Set whenever the identity is provisioned/loaded; null until then.
  ProvisionedIdentity? _activeIdentity;

  /// The box this device has joined this session, or null before a redeem.
  JoinedBox? get joinedBox => _joinedBox;

  /// Last-fetched membership for [joinedBox], or null until [refreshMembers].
  ChannelMembers? get members => _members;

  /// True while a create/redeem/members call is in flight (drives spinners).
  bool get busy => _busy;

  /// True when the joined box is owned by this device (the creator). Drives the
  /// owner-only management UI. False for a member that joined via an invite.
  bool get isOwner => _joinedBox?.isOwner ?? false;

  /// Last user-facing error message, or null when the last action succeeded.
  String? get error => _error;

  /// Build a device-mode [BardApi]: every authenticated call presents a FRESH
  /// device token minted from the active identity (ADR-0016 §4 — no baked
  /// token). Used for all owner/management calls. The provider re-mints per
  /// request from [_activeIdentity]; the empty string (no identity yet) means
  /// "no Authorization header".
  BardApi _deviceApi() => _apiFactory(
        tokenProvider: () {
          final id = _activeIdentity;
          return id == null ? '' : _identity.mintTokenFor(id);
        },
      );

  /// Build a no-auth [BardApi] for the redeem path (the invite token in the URL
  /// is the authorization; no bearer is sent regardless).
  BardApi _plainApi() => _apiFactory();

  /// Open the receive link for the box just entered (S6): build a [BoxLink]
  /// authed by THIS device's token, forward its pings into [_pings], and stash
  /// the latest as [_lastPing] for the in-app banner. Idempotent — closes any
  /// prior link first so re-entering a box never leaks a socket. No-op when no
  /// [_linkFactory] was supplied (the send path still works).
  void _openLink() {
    _closeLink();
    final factory = _linkFactory;
    if (factory == null) return;
    final link = factory(
      // The link re-mints a fresh EdDSA token per (re)connect from the active
      // identity, loading it from the store on first need (post-relaunch).
      tokenProvider: () async {
        _activeIdentity ??= await _identity.current();
        final id = _activeIdentity;
        return id == null ? null : _identity.mintTokenFor(id);
      },
    );
    if (link == null) return;
    _link = link;
    _linkSub = link.pings.listen((ping) {
      // Only surface pings for the box currently in view.
      if (_joinedBox?.channelId != ping.channelId) return;
      _lastPing = ping;
      if (!_pings.isClosed) _pings.add(ping);
      notifyListeners();
    });
    link.open();
  }

  /// Tear the receive link down (leaving the box): cancel the forward and close
  /// the socket. Safe to call when no link is open.
  void _closeLink() {
    final sub = _linkSub;
    final link = _link;
    _linkSub = null;
    _link = null;
    unawaited(sub?.cancel());
    unawaited(link?.dispose());
  }

  /// Send a ping to every other connected member of the joined box (S6):
  /// `POST /channels/{id}/ping` with THIS device's token. No-op (returns null)
  /// when no box is joined. Returns the `{delivered, offline}` split on success
  /// or null on failure (message in [error]).
  Future<PingResult?> pingBox() async {
    final box = _joinedBox;
    if (box == null) return null;
    return _run(() async {
      final api = _deviceApi();
      try {
        return await api.pingBox(box.channelId);
      } finally {
        api.close();
      }
    });
  }

  /// Clear the last-shown ping after the UI has surfaced it, so the banner does
  /// not re-fire on an unrelated rebuild. Does not touch the live stream.
  void clearLastPing() {
    if (_lastPing == null) return;
    _lastPing = null;
    notifyListeners();
  }

  /// Self-register the device's single identity on first launch and re-affirm it
  /// on every relaunch (ADR-0016 §3). Idempotent and safe; surfaces failures via
  /// [error] and returns null, otherwise returns the provisioned id.
  Future<String?> selfRegister() async {
    return _run(() async {
      final api = _deviceApi();
      try {
        final id = await _identity.ensureProvisioned(api);
        _activeIdentity = id;
        return id.deviceId;
      } finally {
        api.close();
      }
    });
  }

  /// Create a box this device OWNS and return the shareable invite. Provisions +
  /// self-registers the device identity (idempotent), then:
  ///   1. `POST /channels` (device-token auth) → the box, owned by this device,
  ///   2. `POST /invites` (device-token auth) → the shareable invite,
  /// and records the OWNER context so the Box screen shows management UI. The
  /// caller hands [InviteResult.inviteUrl] to the OS share sheet. Surfaces
  /// failures via [error] and returns null.
  ///
  /// The baked `BARD_AUTH_TOKEN` is never used here — every call is signed by the
  /// device's own key (ADR-0016 §4, closes #67).
  Future<InviteResult?> createBox(String channelId, {String? label}) async {
    return _run(() async {
      final api = _deviceApi();
      try {
        // Ensure the device is provisioned + registered so its self-signed token
        // verifies server-side before it tries to own a channel.
        final id = await _identity.ensureProvisioned(api);
        _activeIdentity = id;
        final createdId = await api.createChannel(channelId, label: label);
        final invite = await api.createInvite(createdId, label: label);
        _joinedBox = JoinedBox(
          channelId: createdId,
          deviceId: id.deviceId,
          label: label,
          isOwner: true,
        );
        _members = null;
        _openLink();
        return invite;
      } finally {
        api.close();
      }
    });
  }

  /// Mint a fresh invite for an existing OWNED box (the "Add people" flow). Reuses
  /// the device-token create-invite path. No-op (returns null) when no box is
  /// joined or this device is not the owner. Surfaces failures via [error].
  Future<InviteResult?> createInvite({String? label}) async {
    final box = _joinedBox;
    if (box == null || !box.isOwner) return null;
    return _run(() async {
      final api = _deviceApi();
      try {
        return await api.createInvite(box.channelId, label: label ?? box.label);
      } finally {
        api.close();
      }
    });
  }

  /// Record the OWNER context for a box this device created/manages (used by
  /// tests and recovery to enter the owner view without re-creating the box).
  void enterAsOwner(String channelId, {required String deviceId, String? label}) {
    _joinedBox = JoinedBox(
      channelId: channelId,
      deviceId: deviceId,
      label: label,
      isOwner: true,
    );
    _members = null;
    _error = null;
    _openLink();
    notifyListeners();
  }

  /// Redeem an invite [token] to JOIN a box (ADR-0016: the SINGLE device identity
  /// joins). Provisions the one device identity if needed, sends THIS device's
  /// public key to `POST /invites/{token}/redeem`, and records the joined box
  /// under the device's stable id. [label] is the human device name. Returns the
  /// [RedeemResult] on success or null on failure (message in [error]).
  ///
  /// The device's own [deviceId] is authoritative — the human label is just a
  /// display name. The private key never leaves the device; only the public key
  /// is sent, and the identity is already persisted by [DeviceIdentity].
  Future<RedeemResult?> redeem(String token, {String? label}) async {
    return _run(() async {
      // The single device identity (generated + persisted on first need).
      final id = await _identity.provisionLocal();
      _activeIdentity = id;
      final api = _plainApi();
      RedeemResult result;
      try {
        result = await api.redeemInvite(
          token,
          deviceId: id.deviceId,
          publicKey: id.publicKeyBase64,
          label: label,
        );
      } finally {
        api.close();
      }
      _joinedBox = JoinedBox(
        channelId: result.channelId,
        deviceId: result.deviceId,
        label: label,
      );
      _members = null;
      // A member joins → open its receive link so it gets pings from others.
      _openLink();
      return result;
    });
  }

  /// Fetch the current membership of [joinedBox] (owner device-token auth). No-op
  /// when no box is joined.
  Future<ChannelMembers?> refreshMembers() async {
    final box = _joinedBox;
    if (box == null) return null;
    return _run(() async {
      final api = _deviceApi();
      try {
        final m = await api.channelMembers(box.channelId);
        _members = m;
        return m;
      } finally {
        api.close();
      }
    });
  }

  /// Evict [deviceId] from the joined box (owner-only; device-token auth). Drives
  /// `POST /channels/{id}/members/{deviceId}/remove`, then adopts the UPDATED
  /// membership the server returns. No-op (returns null) when no box is joined or
  /// this device is not the owner. Surfaces failures via [error].
  Future<ChannelMembers?> removeMember(String deviceId) async {
    final box = _joinedBox;
    if (box == null || !box.isOwner) return null;
    return _run(() async {
      final api = _deviceApi();
      try {
        final updated = await api.removeMember(box.channelId, deviceId);
        _members = updated;
        return updated;
      } finally {
        api.close();
      }
    });
  }

  /// Self-sign a per-device fabric token from the stored identity, or null when
  /// no identity is provisioned. This is the bearer a device-mode [BardApi]
  /// presents for fabric calls (ADR-0016 §2).
  Future<String?> mintDeviceToken() => _identity.mintToken();

  /// Leave the joined box: tear the receive link down and forget the box, so the
  /// socket lifecycle tracks the view (S6 §4 — open on enter, close on leave).
  void leaveBox() {
    _closeLink();
    _lastPing = null;
    _joinedBox = null;
    _members = null;
    notifyListeners();
  }

  /// Close the receive link and the ping broadcast on disposal so no socket or
  /// stream controller outlives the controller (CLAUDE.md §12 resource cleanup).
  @override
  void dispose() {
    _closeLink();
    if (!_pings.isClosed) unawaited(_pings.close());
    super.dispose();
  }

  /// Run [action] with busy/error bookkeeping and notification. Loads the active
  /// identity into [_activeIdentity] first (best-effort, no network) so the api's
  /// `tokenProvider` mints a current bearer even after a relaunch when the
  /// in-memory snapshot was lost. Returns the action's result, or null when it
  /// threw a [BardApiException].
  Future<T?> _run<T>(Future<T> Function() action) async {
    _busy = true;
    _error = null;
    notifyListeners();
    try {
      _activeIdentity ??= await _identity.current();
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
