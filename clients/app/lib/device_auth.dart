import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';

/// Mints the per-device fabric token from the stored device secret.
///
/// After a box redemption the device holds an HMAC secret (the one-time
/// `deviceSecret`). Fabric calls authenticate by presenting a short-lived JWT
/// signed with that secret; the registry/router's `PerDeviceVerifier` reads the
/// `sub` (deviceId), looks the device's secret up server-side, and verifies the
/// signature against it (common/device_auth.py).
///
/// Claim shape pinned to that verifier (it `require`s `["exp", "iss", "sub"]`,
/// checks `iss == issuer`, HS256, 30s leeway):
///   - `sub` = deviceId
///   - `iss` = [issuer] (default `bardllm-pro`, the server's `jwt_issuer`)
///   - `iat` / `exp` stamped by the signer from the ambient clock and [ttl]
///   - `aud` = [audience] when supplied (the verifier does not require it, but
///     the onboarding contract names it; harmless and forward-compatible)
///
/// Issue/expiry time comes from `package:clock` (which `dart_jsonwebtoken` uses
/// internally), so tests pin time with `withClock` rather than wall-clock
/// flakiness. The secret is HMAC keying material: read from the secure store at
/// call time, never logged (CLAUDE.md §7).
class DeviceAuth {
  const DeviceAuth({
    this.issuer = defaultIssuer,
    this.audience,
    this.ttl = const Duration(hours: 1),
  });

  /// The server's configured `jwt_issuer` (common/config.py default).
  static const defaultIssuer = 'bardllm-pro';

  final String issuer;

  /// Optional `aud` claim. The per-device verifier ignores it; included only
  /// because the onboarding brief names it.
  final String? audience;

  final Duration ttl;

  /// Mint a signed HS256 token for [deviceId] using its [deviceSecret].
  ///
  /// [deviceSecret] MUST be the secret disclosed at redemption (>= 32 bytes per
  /// the server's RFC 7518 minimum). Throws [ArgumentError] on an empty id or
  /// secret — a missing credential is a fail-fast, never a `Bearer ` with no
  /// signature (CLAUDE.md §0.11).
  String mintToken({required String deviceId, required String deviceSecret}) {
    if (deviceId.isEmpty) {
      throw ArgumentError.value(deviceId, 'deviceId', 'must not be empty');
    }
    if (deviceSecret.isEmpty) {
      throw ArgumentError.value('<redacted>', 'deviceSecret', 'must not be empty');
    }
    final jwt = JWT(
      const <String, dynamic>{},
      subject: deviceId,
      issuer: issuer,
      audience: audience == null ? null : Audience.one(audience!),
    );
    return jwt.sign(
      SecretKey(deviceSecret),
      algorithm: JWTAlgorithm.HS256,
      expiresIn: ttl,
    );
  }
}
