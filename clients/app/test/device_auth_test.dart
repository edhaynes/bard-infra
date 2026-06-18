import 'dart:convert';

import 'package:bard_pro/device_auth.dart';
import 'package:clock/clock.dart';
import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:ed25519_edwards/ed25519_edwards.dart' as ed;
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for the per-device EdDSA identity (ADR-0016): the device generates
/// its own Ed25519 keypair, self-signs JWTs with the private half, and the token
/// verifies against the public half — the claim shape the server's
/// `PerDeviceVerifier` requires (`sub`, `iss`, `exp`, `iat`, alg EdDSA). Time is
/// pinned with `withClock` so `iat`/`exp` are deterministic (CLAUDE.md §9).
void main() {
  final fixed = DateTime.utc(2026, 6, 17, 12, 0, 0);

  /// The matching `EdDSAPublicKey` for a [DeviceKeyPair] — what the registry
  /// stores and verifies against in production.
  EdDSAPublicKey publicKeyFor(DeviceKeyPair kp) =>
      EdDSAPublicKey(base64.decode(kp.publicKeyBase64));

  group('generateKeyPair', () {
    test('produces a 64-byte private key and a 32-byte public key', () {
      final kp = DeviceAuth.generateKeyPair();
      expect(base64.decode(kp.privateKeyBase64).length, ed.PrivateKeySize);
      expect(base64.decode(kp.publicKeyBase64).length, ed.PublicKeySize);
    });

    test('generates a fresh, unique identity each call', () {
      final a = DeviceAuth.generateKeyPair();
      final b = DeviceAuth.generateKeyPair();
      expect(a.privateKeyBase64, isNot(b.privateKeyBase64));
      expect(a.publicKeyBase64, isNot(b.publicKeyBase64));
    });

    test('the public half is the trailing 32 bytes of the private representation',
        () {
      final kp = DeviceAuth.generateKeyPair();
      final priv = base64.decode(kp.privateKeyBase64);
      final pub = base64.decode(kp.publicKeyBase64);
      // ed25519_edwards stores seed(32) ++ pubkey(32); the contract's publicKey
      // is exactly that trailing public half.
      expect(pub, priv.sublist(32, ed.PrivateKeySize));
    });
  });

  group('mintToken (self-signed EdDSA)', () {
    test('mints a token that verifies with the device public key and right claims',
        () {
      final kp = DeviceAuth.generateKeyPair();
      final token = withClock(
        Clock.fixed(fixed),
        () => const DeviceAuth().mintToken(
          deviceId: 'my-iphone',
          privateKeyBase64: kp.privateKeyBase64,
        ),
      );

      // The server verifies with the stored public key; alg EdDSA. We pin the
      // mint clock to a fixed instant, so skip the verifier's wall-clock expiry
      // check and assert exp/iat numerically below instead.
      final jwt = JWT.verify(token, publicKeyFor(kp), checkExpiresIn: false);
      final claims = jwt.payload as Map<String, dynamic>;

      expect(jwt.subject, 'my-iphone');
      expect(jwt.issuer, 'bardllm-pro');
      expect(claims['sub'], 'my-iphone');
      expect(claims['iss'], 'bardllm-pro');
      expect(claims.containsKey('iat'), isTrue);
      expect(claims.containsKey('exp'), isTrue);

      final iat = claims['iat'] as int;
      final exp = claims['exp'] as int;
      expect(iat, fixed.millisecondsSinceEpoch ~/ 1000);
      // Default ttl is one hour.
      expect(exp - iat, const Duration(hours: 1).inSeconds);
    });

    test('header advertises EdDSA', () {
      final kp = DeviceAuth.generateKeyPair();
      final token = const DeviceAuth()
          .mintToken(deviceId: 'd', privateKeyBase64: kp.privateKeyBase64);
      final jwt = JWT.verify(token, publicKeyFor(kp));
      expect(jwt.header?['alg'], 'EdDSA');
    });

    test('honours a custom issuer, audience, and ttl', () {
      final kp = DeviceAuth.generateKeyPair();
      final token = withClock(
        Clock.fixed(fixed),
        () => const DeviceAuth(
          issuer: 'custom-iss',
          audience: 'bard-fabric',
          ttl: Duration(minutes: 5),
        ).mintToken(deviceId: 'd', privateKeyBase64: kp.privateKeyBase64),
      );
      final jwt = JWT.verify(token, publicKeyFor(kp), checkExpiresIn: false);
      final claims = jwt.payload as Map<String, dynamic>;
      expect(jwt.issuer, 'custom-iss');
      expect(jwt.audience?.first, 'bard-fabric');
      expect((claims['exp'] as int) - (claims['iat'] as int), 300);
    });

    test('a token from device A does NOT verify under device B public key', () {
      final a = DeviceAuth.generateKeyPair();
      final b = DeviceAuth.generateKeyPair();
      final token = const DeviceAuth()
          .mintToken(deviceId: 'd', privateKeyBase64: a.privateKeyBase64);
      expect(
        () => JWT.verify(token, publicKeyFor(b)),
        throwsA(isA<JWTException>()),
      );
    });

    test('rejects an empty deviceId or private key (fail fast)', () {
      final kp = DeviceAuth.generateKeyPair();
      expect(
        () => const DeviceAuth()
            .mintToken(deviceId: '', privateKeyBase64: kp.privateKeyBase64),
        throwsArgumentError,
      );
      expect(
        () => const DeviceAuth().mintToken(deviceId: 'd', privateKeyBase64: ''),
        throwsArgumentError,
      );
    });

    test('rejects a non-base64 private key (fail fast, redacted)', () {
      try {
        const DeviceAuth().mintToken(
            deviceId: 'd',
            privateKeyBase64:
                'not base64!!!'); // pragma: allowlist secret — fake test value
        fail('expected ArgumentError');
      } on ArgumentError catch (e) {
        expect(e.invalidValue, '<redacted>');
        expect(e.message, contains('base64'));
      }
    });

    test('rejects a private key of the wrong byte length (fail fast)', () {
      // 32 bytes (a public key) is not the 64-byte private representation.
      final wrong = base64.encode(List<int>.filled(ed.PublicKeySize, 7));
      expect(
        () => const DeviceAuth().mintToken(deviceId: 'd', privateKeyBase64: wrong),
        throwsArgumentError,
      );
    });

    test('the error for an empty key does not leak the key value', () {
      try {
        const DeviceAuth().mintToken(deviceId: 'd', privateKeyBase64: '');
        fail('expected ArgumentError');
      } on ArgumentError catch (e) {
        expect(e.invalidValue, '<redacted>');
      }
    });
  });
}
