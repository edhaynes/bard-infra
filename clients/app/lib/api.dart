import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'box/box_models.dart';
import 'model_info.dart';
import 'protocol.dart';

/// Thin client over the Bard Router/Registry HTTP contracts.
///
/// Mirrors `contracts/router.openapi.yaml` (`POST /v1/message`) and
/// `contracts/registry.openapi.yaml` (`GET /agents`). All business logic lives
/// here, not in the widgets (CLAUDE.md §2).
///
/// The [http.Client] is injected (CLAUDE.md §2: DI; §9: no network in unit
/// tests) so tests drive it with `package:http/testing.dart`'s `MockClient` —
/// no real sockets, no new dependency.
class BardApi {
  BardApi({
    required this.routerBaseUrl,
    required this.registryBaseUrl,
    required this.token,
    http.Client? httpClient,
    this.listTimeout = const Duration(seconds: 10),
    this.messageTimeout = const Duration(seconds: 30),
    String Function()? idFactory,
    String Function()? tokenProvider,
  })  : _client = httpClient ?? http.Client(),
        _ownsClient = httpClient == null,
        _idFactory = idFactory ?? _defaultId,
        // ignore: prefer_initializing_formals
        _tokenProvider = tokenProvider;

  final String routerBaseUrl;
  final String registryBaseUrl;

  /// Static bearer (manager credential / legacy fleet token). Used unless a
  /// [_tokenProvider] (per-device mode) is supplied.
  final String token;
  final Duration listTimeout;
  final Duration messageTimeout;

  final http.Client _client;
  final bool _ownsClient;
  final String Function() _idFactory;

  /// Per-device-token mode (CLAUDE.md §3 swappable auth seam): when set, the
  /// bearer for authenticated calls is minted fresh per request from this
  /// provider (a [DeviceAuth] over the stored secret) instead of the static
  /// [token]. Short-lived device JWTs are re-minted, never cached stale.
  final String Function()? _tokenProvider;

  /// The bearer to present: the per-device provider's fresh token when in
  /// device mode, otherwise the static [token].
  String get _bearer {
    final provider = _tokenProvider;
    return provider != null ? provider() : token;
  }

  Map<String, String> get _headers {
    // Resolve the bearer once: in per-device mode the provider mints a fresh
    // token per call, so evaluating it twice would yield two different tokens.
    final bearer = _bearer;
    return {
      if (bearer.isNotEmpty) 'Authorization': 'Bearer $bearer',
      'Content-Type': 'application/json',
    };
  }

  /// `GET /agents` on the Registry → the professional model/agent list.
  ///
  /// Throws [BardApiException] on a non-200 status (parsing the error envelope
  /// when present), on a timeout, or on a malformed body.
  Future<List<ModelInfo>> listAgents() async {
    final uri = Uri.parse('$registryBaseUrl/agents');
    final resp = await _send(() => _client.get(uri, headers: _headers), listTimeout);
    if (resp.statusCode != 200) {
      throw _errorFor(resp);
    }
    final decoded = _decode(resp.body);
    if (decoded is! List) {
      throw BardApiException.malformed('GET /agents did not return a JSON array');
    }
    return decoded.map((e) {
      if (e is! Map) {
        throw BardApiException.malformed('agent entry is not a JSON object');
      }
      return ModelInfo.fromAgentJson(Map<String, dynamic>.from(e));
    }).toList(growable: false);
  }

  /// `POST /v1/message` on the Router → the agent's typed [BardResponse].
  ///
  /// Throws [BardApiException] carrying the contract error envelope on any
  /// non-200 (e.g. `502 agent_unavailable retry=true`), on a timeout, or when
  /// the 200 body does not conform to the frozen `Response` schema.
  Future<BardResponse> sendMessage({
    required String targetAgent,
    required String content,
    String? sessionId,
  }) async {
    final request = BardRequest(
      id: _idFactory(),
      type: MessageType.text,
      content: content,
      metadata: RequestMetadata(
        targetAgent: targetAgent,
        authToken: _bearer,
        sessionId: sessionId,
      ),
    );
    final uri = Uri.parse('$routerBaseUrl/v1/message');
    final resp = await _send(
      () => _client.post(uri, headers: _headers, body: jsonEncode(request.toJson())),
      messageTimeout,
    );
    if (resp.statusCode != 200) {
      throw _errorFor(resp);
    }
    final decoded = _decode(resp.body);
    if (decoded is! Map) {
      throw BardApiException.malformed('POST /v1/message did not return a JSON object');
    }
    try {
      return BardResponse.fromJson(Map<String, dynamic>.from(decoded));
    } on ProtocolFormatException catch (e) {
      throw BardApiException.malformed(e.message);
    }
  }

  /// `POST /invites` on the Registry (manager-auth) → a shareable channel
  /// invite. Mirrors `contracts/invite.schema.json#/$defs/CreateInviteRequest`
  /// / `CreateInviteResponse`. The bearer ([token]) is the manager credential.
  ///
  /// [channelId] names the box; [label] is an optional human-facing invite name;
  /// [ttlSeconds] overrides the server's default invite lifetime when set.
  /// Throws [BardApiException] on a non-200 or a malformed body.
  Future<InviteResult> createInvite(
    String channelId, {
    String? label,
    num? ttlSeconds,
  }) async {
    final uri = Uri.parse('$registryBaseUrl/invites');
    final body = <String, dynamic>{
      'channelId': channelId,
      'label': ?label,
      'ttlSeconds': ?ttlSeconds,
    };
    final resp = await _send(
      () => _client.post(uri, headers: _headers, body: jsonEncode(body)),
      listTimeout,
    );
    if (resp.statusCode != 200) {
      throw _errorFor(resp);
    }
    return InviteResult.fromJson(_decodeObject(resp.body, 'POST /invites'));
  }

  /// `POST /invites/{token}/redeem` on the Registry → the device is admitted
  /// ACTIVE into the channel in ONE step. Mirrors `RedeemRequest` /
  /// `RedeemResponse`. NO bearer is sent: the invite token in the path IS the
  /// authorization (the owner pre-authorized by sending the link), so this call
  /// deliberately omits the Authorization header even when [token] is set.
  ///
  /// [inviteToken] is the single-use invite bearer (from the deep link);
  /// [deviceId] is the stable id the redeeming device chooses for itself;
  /// [publicKey] is the device's OWN Ed25519 public key (base64 32-byte) which
  /// the registry stores to verify the device's self-signed tokens (ADR-0016 §3);
  /// [label] is an optional human device name. The device keeps the matching
  /// private key locally — the response carries no server-minted secret.
  Future<RedeemResult> redeemInvite(
    String inviteToken, {
    required String deviceId,
    required String publicKey,
    String? label,
  }) async {
    final uri =
        Uri.parse('$registryBaseUrl/invites/${Uri.encodeComponent(inviteToken)}/redeem');
    final body = <String, dynamic>{
      'deviceId': deviceId,
      'publicKey': publicKey,
      'label': ?label,
    };
    final resp = await _send(
      // No-auth on purpose: only Content-Type, never Authorization.
      () => _client.post(
        uri,
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      ),
      listTimeout,
    );
    if (resp.statusCode != 200) {
      throw _errorFor(resp);
    }
    return RedeemResult.fromJson(_decodeObject(resp.body, 'redeem'));
  }

  /// `GET /channels/{channelId}/members` on the Registry (manager-auth) → the
  /// channel's current membership (`ChannelMembership`). Throws
  /// [BardApiException] on a non-200 or a malformed body.
  Future<ChannelMembers> channelMembers(String channelId) async {
    final uri =
        Uri.parse('$registryBaseUrl/channels/${Uri.encodeComponent(channelId)}/members');
    final resp = await _send(() => _client.get(uri, headers: _headers), listTimeout);
    if (resp.statusCode != 200) {
      throw _errorFor(resp);
    }
    return ChannelMembers.fromJson(
      _decodeObject(resp.body, 'GET /channels/{id}/members'),
    );
  }

  /// `POST /channels/{channelId}/members/{deviceId}/remove` on the Registry
  /// (manager-auth, audited) → the member is evicted and the UPDATED membership
  /// (`ChannelMembership`) is returned. The bearer is the manager credential
  /// ([token]); only the owner/manager may evict a device.
  ///
  /// [channelId] names the box; [deviceId] is the member to remove. Both path
  /// segments are percent-encoded. Throws [BardApiException] on a non-200 (e.g.
  /// the contract's `404` when the device is not a member) or a malformed body.
  Future<ChannelMembers> removeMember(String channelId, String deviceId) async {
    final uri = Uri.parse(
      '$registryBaseUrl/channels/${Uri.encodeComponent(channelId)}'
      '/members/${Uri.encodeComponent(deviceId)}/remove',
    );
    final resp = await _send(
      () => _client.post(uri, headers: _headers),
      listTimeout,
    );
    if (resp.statusCode != 200) {
      throw _errorFor(resp);
    }
    return ChannelMembers.fromJson(
      _decodeObject(resp.body, 'POST /channels/{id}/members/{deviceId}/remove'),
    );
  }

  /// Releases the underlying client when this [BardApi] created it.
  void close() {
    if (_ownsClient) _client.close();
  }

  /// Decode a body that MUST be a JSON object, or throw [BardApiException]
  /// .malformed naming [what].
  static Map<String, dynamic> _decodeObject(String body, String what) {
    final decoded = _decode(body);
    if (decoded is! Map) {
      throw BardApiException.malformed('$what did not return a JSON object');
    }
    return Map<String, dynamic>.from(decoded);
  }

  Future<http.Response> _send(
    Future<http.Response> Function() call,
    Duration timeout,
  ) async {
    try {
      return await call().timeout(timeout);
    } on TimeoutException {
      throw BardApiException.timeout(timeout);
    } on http.ClientException catch (e) {
      throw BardApiException.network(e.message);
    }
  }

  /// Builds the exception for a non-200 response, parsing the contract error
  /// envelope (`{error, retry, detail}`) when the body is well-formed.
  BardApiException _errorFor(http.Response resp) {
    final decoded = _tryDecode(resp.body);
    if (decoded is Map && decoded['error'] is String) {
      try {
        return BardApiException.fromEnvelope(
          resp.statusCode,
          BardError.fromJson(Map<String, dynamic>.from(decoded)),
        );
      } on ProtocolFormatException {
        // Fall through to a status-only exception below.
      }
    }
    return BardApiException.status(resp.statusCode);
  }

  static dynamic _decode(String body) {
    try {
      return jsonDecode(body);
    } on FormatException catch (e) {
      throw BardApiException.malformed('invalid JSON: ${e.message}');
    }
  }

  static dynamic _tryDecode(String body) {
    try {
      return jsonDecode(body);
    } on FormatException {
      return null;
    }
  }

  static String _defaultId() {
    final now = DateTime.now().microsecondsSinceEpoch.toRadixString(16).padLeft(12, '0');
    return 'c3f9a1e2-7b4d-4a12-9f8b-${now.substring(now.length - 12)}';
  }
}

/// Categorises a failed API call so the UI can react (retryable vs not) and so
/// tests can assert on the branch without string-matching.
enum ApiFailureKind { errorEnvelope, httpStatus, timeout, network, malformed }

/// A failed Router/Registry call. Carries the parsed contract [error] envelope
/// when the server returned one, plus the [statusCode] and a [retryable] flag
/// (true for the contract's `502 agent_unavailable retry=true`).
class BardApiException implements Exception {
  BardApiException._({
    required this.kind,
    required this.message,
    this.statusCode,
    this.error,
    this.retryable = false,
  });

  factory BardApiException.fromEnvelope(int statusCode, BardError error) {
    return BardApiException._(
      kind: ApiFailureKind.errorEnvelope,
      message: error.detail?.isNotEmpty == true
          ? '${error.code}: ${error.detail}'
          : error.code,
      statusCode: statusCode,
      error: error,
      retryable: error.retry,
    );
  }

  factory BardApiException.status(int statusCode) => BardApiException._(
        kind: ApiFailureKind.httpStatus,
        message: 'HTTP $statusCode',
        statusCode: statusCode,
        retryable: statusCode >= 500,
      );

  factory BardApiException.timeout(Duration after) => BardApiException._(
        kind: ApiFailureKind.timeout,
        message: 'request timed out after ${after.inSeconds}s',
        retryable: true,
      );

  factory BardApiException.network(String detail) => BardApiException._(
        kind: ApiFailureKind.network,
        message: 'network error: $detail',
        retryable: true,
      );

  factory BardApiException.malformed(String detail) => BardApiException._(
        kind: ApiFailureKind.malformed,
        message: 'malformed response: $detail',
      );

  final ApiFailureKind kind;
  final String message;
  final int? statusCode;

  /// The parsed contract error envelope, when the server returned one.
  final BardError? error;

  /// True when retrying could plausibly succeed (timeout, network blip, or a
  /// `retry=true` envelope / 5xx).
  final bool retryable;

  @override
  String toString() => message;
}
