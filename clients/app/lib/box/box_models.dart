import '../api.dart';

/// Typed views over the FROZEN invite contract (`contracts/invite.schema.json`).
///
/// These mirror the redeem / create-invite / membership response shapes exactly;
/// parsing lives here (not in widgets) so the box screens consume typed values
/// and the contract is asserted in one place (CLAUDE.md §2, §11). Each `fromJson`
/// throws [BardApiException.malformed] on a shape that violates the contract, so
/// the UI surfaces a clear error rather than a late null-deref.

/// `POST /invites` 200 body: the new invite record + the shareable token + a
/// ready-to-send URL embedding it (`CreateInviteResponse`).
class InviteResult {
  const InviteResult({
    required this.inviteId,
    required this.channelId,
    required this.inviteToken,
    required this.inviteUrl,
  });

  /// `invite.inviteId` — unique id of the minted invite (equals the token jti).
  final String inviteId;

  /// `invite.channelId` — the channel the invite admits a device into.
  final String channelId;

  /// The shareable, single-use bearer carried in [inviteUrl].
  final String inviteToken;

  /// The link an owner sends over text/email/AirDrop; opening it drives redeem.
  final String inviteUrl;

  factory InviteResult.fromJson(Map<String, dynamic> json) {
    final invite = json['invite'];
    if (invite is! Map) {
      throw BardApiException.malformed('POST /invites: "invite" is not an object');
    }
    final inviteId = invite['inviteId'];
    final channelId = invite['channelId'];
    final token = json['inviteToken'];
    final url = json['inviteUrl'];
    if (inviteId is! String || inviteId.isEmpty) {
      throw BardApiException.malformed('POST /invites: missing invite.inviteId');
    }
    if (channelId is! String || channelId.isEmpty) {
      throw BardApiException.malformed('POST /invites: missing invite.channelId');
    }
    if (token is! String || token.isEmpty) {
      throw BardApiException.malformed('POST /invites: missing inviteToken');
    }
    if (url is! String || url.isEmpty) {
      throw BardApiException.malformed('POST /invites: missing inviteUrl');
    }
    return InviteResult(
      inviteId: inviteId,
      channelId: channelId,
      inviteToken: token,
      inviteUrl: url,
    );
  }
}

/// `POST /invites/{token}/redeem` 200 body (`RedeemResponse`): the device is now
/// ACTIVE in [channelId] and holds the one-time [deviceSecret].
class RedeemResult {
  const RedeemResult({
    required this.deviceId,
    required this.channelId,
    required this.deviceSecret,
  });

  /// `device.deviceId` — the authoritative id the registry recorded.
  final String deviceId;

  /// `channelId` — the box this device joined.
  final String channelId;

  /// `deviceSecret` — per-device HMAC signing secret. ONE-TIME disclosure: it
  /// must be persisted (secure store) here; it is never recoverable again.
  final String deviceSecret;

  factory RedeemResult.fromJson(Map<String, dynamic> json) {
    final device = json['device'];
    if (device is! Map) {
      throw BardApiException.malformed('redeem: "device" is not an object');
    }
    final deviceId = device['deviceId'];
    final secret = json['deviceSecret'];
    final channelId = json['channelId'];
    if (deviceId is! String || deviceId.isEmpty) {
      throw BardApiException.malformed('redeem: missing device.deviceId');
    }
    if (secret is! String || secret.isEmpty) {
      throw BardApiException.malformed('redeem: missing deviceSecret');
    }
    if (channelId is! String || channelId.isEmpty) {
      throw BardApiException.malformed('redeem: missing channelId');
    }
    return RedeemResult(
      deviceId: deviceId,
      channelId: channelId,
      deviceSecret: secret,
    );
  }
}

/// `GET /channels/{channelId}/members` projection (`ChannelMembership`).
class ChannelMembers {
  const ChannelMembers({required this.channelId, required this.deviceIds});

  final String channelId;
  final List<String> deviceIds;

  factory ChannelMembers.fromJson(Map<String, dynamic> json) {
    final channelId = json['channelId'];
    final ids = json['deviceIds'];
    if (channelId is! String || channelId.isEmpty) {
      throw BardApiException.malformed('members: missing channelId');
    }
    if (ids is! List) {
      throw BardApiException.malformed('members: "deviceIds" is not an array');
    }
    return ChannelMembers(
      channelId: channelId,
      deviceIds: ids.map((e) {
        if (e is! String) {
          throw BardApiException.malformed('members: a deviceId is not a string');
        }
        return e;
      }).toList(growable: false),
    );
  }
}

/// A box this device has joined — the local record persisted after a redeem.
/// Holds the [channelId] and the [deviceId] the device was admitted under; the
/// secret lives only in the secure store, never here.
class JoinedBox {
  const JoinedBox({
    required this.channelId,
    required this.deviceId,
    this.label,
    this.isOwner = false,
  });

  final String channelId;
  final String deviceId;
  final String? label;

  /// True when this device is the box's owner/manager — the one that created the
  /// box and holds the manager token. The owner sees management actions (remove
  /// a member, add people) that ordinary members do not. A device that joined by
  /// redeeming an invite is NOT an owner (defaults false).
  final bool isOwner;
}
