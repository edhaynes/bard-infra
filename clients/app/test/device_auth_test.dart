import 'package:bard_pro/device_auth.dart';
import 'package:clock/clock.dart';
import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for the per-device JWT minter. The token must verify against the
/// device secret and carry the claim shape the server's `PerDeviceVerifier`
/// requires (`sub`, `iss`, `exp`, `iat`, HS256). Time is pinned with `withClock`
/// so `iat`/`exp` are deterministic (no wall-clock flakiness, CLAUDE.md §9).
void main() {
  // A 32-byte secret like the registry mints (RFC 7518 HS256 minimum).
  const secret = 'abcdefghijklmnopqrstuvwxyz0123456789ABCDEF';
  final fixed = DateTime.utc(2026, 6, 17, 12, 0, 0);

  test('mints a token that verifies with the device secret and right claims', () {
    final token = withClock(
      Clock.fixed(fixed),
      () => const DeviceAuth().mintToken(deviceId: 'my-iphone', deviceSecret: secret),
    );

    // The server verifies with the same per-device secret; HS256 only. We pin
    // the mint clock to a fixed instant, so skip the verifier's wall-clock
    // expiry check and assert exp/iat numerically below instead.
    final jwt = JWT.verify(token, SecretKey(secret), checkExpiresIn: false);
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

  test('header advertises HS256', () {
    final token = const DeviceAuth().mintToken(deviceId: 'd', deviceSecret: secret);
    final jwt = JWT.verify(token, SecretKey(secret));
    expect(jwt.header?['alg'], 'HS256');
  });

  test('honours a custom issuer, audience, and ttl', () {
    final token = withClock(
      Clock.fixed(fixed),
      () => const DeviceAuth(
        issuer: 'custom-iss',
        audience: 'bard-fabric',
        ttl: Duration(minutes: 5),
      ).mintToken(deviceId: 'd', deviceSecret: secret),
    );
    final jwt = JWT.verify(token, SecretKey(secret), checkExpiresIn: false);
    final claims = jwt.payload as Map<String, dynamic>;
    expect(jwt.issuer, 'custom-iss');
    expect(jwt.audience?.first, 'bard-fabric');
    expect((claims['exp'] as int) - (claims['iat'] as int), 300);
  });

  test('a token signed with secret A does NOT verify under secret B', () {
    final token = const DeviceAuth().mintToken(deviceId: 'd', deviceSecret: secret);
    expect(
      () => JWT.verify(token, SecretKey('a-different-secret-of-enough-length-xx')),
      throwsA(isA<JWTException>()),
    );
  });

  test('rejects an empty deviceId or secret (fail fast)', () {
    expect(
      () => const DeviceAuth().mintToken(deviceId: '', deviceSecret: secret),
      throwsArgumentError,
    );
    expect(
      () => const DeviceAuth().mintToken(deviceId: 'd', deviceSecret: ''),
      throwsArgumentError,
    );
  });

  test('the error for an empty secret does not leak the secret value', () {
    try {
      const DeviceAuth().mintToken(deviceId: 'd', deviceSecret: '');
      fail('expected ArgumentError');
    } on ArgumentError catch (e) {
      expect(e.invalidValue, '<redacted>');
    }
  });
}
