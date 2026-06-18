import 'dart:convert';

import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:ed25519_edwards/ed25519_edwards.dart' as ed;

/// The device's own Ed25519 identity (ADR-0016 §1). Generated on-device at first
/// launch; the [privateKeyBase64] half NEVER leaves the device (it lives only in
/// the OS keystore, [SecretStore]), while [publicKeyBase64] is what the device
/// hands the registry at enroll/redeem so the server can verify its self-signed
/// tokens.
///
/// Encodings match the FROZEN contract:
///   - [publicKeyBase64] — base64 of the raw 32-byte Ed25519 public key (what
///     the backend stores and verifies against; `EdDSAPublicKey` consumes it).
///   - [privateKeyBase64] — base64 of `ed25519_edwards`' 64-byte private-key
///     representation (32-byte RFC 8032 seed ++ 32-byte public key), which is
///     exactly what `EdDSAPrivateKey` expects. Treated as secret keying
///     material: persisted in the keystore, never logged (CLAUDE.md §0.2 / §7).
class DeviceKeyPair {
  const DeviceKeyPair({
    required this.privateKeyBase64,
    required this.publicKeyBase64,
  });

  final String privateKeyBase64;
  final String publicKeyBase64;
}

/// Mints the per-device fabric token by SELF-SIGNING with the device's own
/// Ed25519 private key (ADR-0016 §2). There is no longer a server-minted shared
/// HMAC secret: the device generates its keypair, keeps the private half, and
/// signs EdDSA JWTs the registry/router verify against the stored public key
/// (the `PerDeviceVerifier` algorithm parameter, common/device_auth.py).
///
/// Claim shape pinned to that verifier (it `require`s `["exp", "iss", "sub"]`,
/// checks `iss == issuer`, 30s leeway) — only the algorithm changes (HS256 →
/// EdDSA):
///   - `sub` = deviceId
///   - `iss` = [issuer] (default `bardllm-pro`, the server's `jwt_issuer`)
///   - `iat` / `exp` stamped by the signer from the ambient clock and [ttl]
///   - `aud` = [audience] when supplied (the verifier does not require it, but
///     the onboarding contract names it; harmless and forward-compatible)
///
/// Issue/expiry time comes from `package:clock` (which `dart_jsonwebtoken` uses
/// internally), so tests pin time with `withClock` rather than wall-clock
/// flakiness.
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

  /// Generate a fresh Ed25519 device identity (ADR-0016 §1). The private half is
  /// returned for the caller to persist in the keystore; it is never emitted
  /// anywhere else. Pure-Dart CSPRNG keygen (`ed25519_edwards`), no platform
  /// channel — so the first-launch auto-provision works on every target.
  static DeviceKeyPair generateKeyPair() {
    final kp = ed.generateKey();
    return DeviceKeyPair(
      // ed25519_edwards' 64-byte private representation (seed ++ pubkey) is what
      // EdDSAPrivateKey consumes verbatim, so persist it whole.
      privateKeyBase64: base64.encode(kp.privateKey.bytes),
      // Raw 32-byte public key — the value sent to the registry per the contract.
      publicKeyBase64: base64.encode(kp.publicKey.bytes),
    );
  }

  /// Self-sign an EdDSA token for [deviceId] with the device's own
  /// [privateKeyBase64] (the base64 64-byte representation from [generateKeyPair]
  /// or the keystore).
  ///
  /// Throws [ArgumentError] on an empty id or private key, or on a private key
  /// that is not the expected 64-byte Ed25519 representation — a missing/garbled
  /// credential is a fail-fast, never a `Bearer ` with no valid signature
  /// (CLAUDE.md §0.11). The key value is never echoed in the error (§7).
  String mintToken({required String deviceId, required String privateKeyBase64}) {
    if (deviceId.isEmpty) {
      throw ArgumentError.value(deviceId, 'deviceId', 'must not be empty');
    }
    if (privateKeyBase64.isEmpty) {
      throw ArgumentError.value(
          '<redacted>', 'privateKeyBase64', 'must not be empty');
    }
    final List<int> keyBytes;
    try {
      keyBytes = base64.decode(privateKeyBase64);
    } on FormatException {
      throw ArgumentError.value(
          '<redacted>', 'privateKeyBase64', 'must be valid base64');
    }
    if (keyBytes.length != ed.PrivateKeySize) {
      throw ArgumentError.value('<redacted>', 'privateKeyBase64',
          'must decode to ${ed.PrivateKeySize} bytes (got ${keyBytes.length})');
    }
    final jwt = JWT(
      const <String, dynamic>{},
      subject: deviceId,
      issuer: issuer,
      audience: audience == null ? null : Audience.one(audience!),
    );
    return jwt.sign(
      EdDSAPrivateKey(keyBytes),
      algorithm: JWTAlgorithm.EdDSA,
      expiresIn: ttl,
    );
  }
}
