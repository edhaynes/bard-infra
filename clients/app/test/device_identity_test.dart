import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/device_identity.dart';
import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_secret_store.dart';

/// Unit tests for [DeviceIdentity] — the SINGLE device identity (ADR-0016 §1).
/// Covers first-launch keygen + persistence, idempotent self-register, the
/// derived public key, and token minting. No network (MockClient), no platform
/// channel (FakeSecretStore) — CLAUDE.md §9.
void main() {
  BardApi apiFor(MockClient client) => BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: 'baked',
        httpClient: client,
        listTimeout: const Duration(milliseconds: 50),
      );

  test('ensureProvisioned generates one identity and self-registers it', () async {
    final store = FakeSecretStore();
    String? sentDeviceId;
    String? sentPublicKey;
    final client = MockClient((req) async {
      expect(req.url.path, '/devices/self-register');
      final body = jsonDecode(req.body) as Map<String, dynamic>;
      sentDeviceId = body['deviceId'] as String?;
      sentPublicKey = body['publicKey'] as String?;
      return http.Response(jsonEncode({'device': {'deviceId': 'dev-x'}}), 200);
    });
    final identity = DeviceIdentity(secretStore: store, idFactory: () => 'dev-x');

    final provisioned = await identity.ensureProvisioned(apiFor(client));
    expect(provisioned.deviceId, 'dev-x');
    expect(sentDeviceId, 'dev-x');
    expect(base64.decode(sentPublicKey!).length, 32);
    // The derived public key matches what was registered.
    expect(provisioned.publicKeyBase64, sentPublicKey);
    // The private key is persisted.
    expect((await store.readDeviceIdentity())?.deviceId, 'dev-x');
  });

  test('ensureProvisioned is idempotent over the same store', () async {
    final store = FakeSecretStore();
    final pubKeys = <String>[];
    final client = MockClient((req) async {
      pubKeys.add((jsonDecode(req.body) as Map<String, dynamic>)['publicKey'] as String);
      return http.Response(jsonEncode({'device': {'deviceId': 'dev-x'}}), 200);
    });
    final first = DeviceIdentity(secretStore: store, idFactory: () => 'dev-x');
    await first.ensureProvisioned(apiFor(client));
    // A new DeviceIdentity over the same store (a relaunch) must reuse the key.
    final second = DeviceIdentity(secretStore: store, idFactory: () => 'dev-DIFFERENT');
    final p2 = await second.ensureProvisioned(apiFor(client));
    expect(p2.deviceId, 'dev-x');
    expect(pubKeys.first, pubKeys.last);
  });

  test('ensureProvisioned propagates a self-register failure (fail-fast)', () async {
    final store = FakeSecretStore();
    final client = MockClient(
      (_) async => http.Response(jsonEncode({'error': 'bad_request'}), 400),
    );
    final identity = DeviceIdentity(secretStore: store, idFactory: () => 'dev-x');
    await expectLater(
      identity.ensureProvisioned(apiFor(client)),
      throwsA(isA<BardApiException>()),
    );
    // The identity was still generated + persisted, so the next attempt reuses it.
    expect(await store.readDeviceIdentity(), isNotNull);
  });

  test('provisionLocal generates without a network call and reuses on second call',
      () async {
    final identity = DeviceIdentity(
      secretStore: FakeSecretStore(),
      idFactory: () => 'dev-x',
    );
    final a = await identity.provisionLocal();
    final b = await identity.provisionLocal();
    expect(a.privateKeyBase64, b.privateKeyBase64);
    expect(a.deviceId, 'dev-x');
  });

  test('current returns null before provisioning, the identity after', () async {
    final store = FakeSecretStore();
    final identity = DeviceIdentity(secretStore: store, idFactory: () => 'dev-x');
    expect(await identity.current(), isNull);
    await identity.provisionLocal();
    expect((await identity.current())?.deviceId, 'dev-x');
  });

  test('mintToken returns null without an identity, a verifiable token with one',
      () async {
    final store = FakeSecretStore();
    final identity = DeviceIdentity(secretStore: store, idFactory: () => 'dev-x');
    expect(await identity.mintToken(), isNull);

    final provisioned = await identity.provisionLocal();
    final token = await identity.mintToken();
    expect(token, isNotNull);
    final jwt =
        JWT.verify(token!, EdDSAPublicKey(base64.decode(provisioned.publicKeyBase64)));
    expect(jwt.subject, 'dev-x');
    expect(jwt.header?['alg'], 'EdDSA');
  });

  test('default device id factory yields a "dev-" prefixed id', () async {
    // Exercises the default _defaultDeviceId branch (no injected factory).
    final identity = DeviceIdentity(secretStore: FakeSecretStore());
    final provisioned = await identity.provisionLocal();
    expect(provisioned.deviceId, startsWith('dev-'));
    expect(provisioned.deviceId.length, greaterThan('dev-'.length));
  });
}
