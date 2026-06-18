import 'dart:convert';
import 'dart:typed_data';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/crockford.dart';
import 'package:bard_pro/box/device_identity.dart';
import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_secret_store.dart';
import 'support/fixed_identity.dart';

/// Unit tests for [DeviceIdentity] — the SINGLE device identity (ADR-0016 §1)
/// with its STABLE, key-derived deviceId (§5 prerequisite refactor). Covers
/// first-launch keygen + persistence, the DERIVED deviceId, idempotent
/// self-register, seed-based recovery, and token minting. No network
/// (MockClient), no platform channel (FakeSecretStore) — CLAUDE.md §9.
void main() {
  BardApi apiFor(MockClient client) => BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: 'baked',
        httpClient: client,
        listTimeout: const Duration(milliseconds: 50),
      );

  DeviceIdentity fixedIdentity(FakeSecretStore store) =>
      DeviceIdentity(secretStore: store, seedFactory: fixtureSeedFactory);

  test('ensureProvisioned generates one identity with a key-derived id', () async {
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
    final identity = fixedIdentity(store);

    final provisioned = await identity.ensureProvisioned(apiFor(client));
    // The deviceId is DERIVED from the public key — not random, not the server's
    // echoed value — so it is reproducible from the seed.
    expect(provisioned.deviceId, fixtureDeviceId);
    expect(provisioned.deviceId, deriveDeviceId(base64.decode(sentPublicKey!)));
    expect(sentDeviceId, fixtureDeviceId);
    expect(base64.decode(sentPublicKey!).length, 32);
    expect(provisioned.publicKeyBase64, sentPublicKey);
    expect((await store.readDeviceIdentity())?.deviceId, fixtureDeviceId);
  });

  test('the derived id is deterministic: same seed → same id', () async {
    final a = await fixedIdentity(FakeSecretStore()).provisionLocal();
    final b = await fixedIdentity(FakeSecretStore()).provisionLocal();
    expect(a.deviceId, b.deviceId);
    expect(a.deviceId, fixtureDeviceId);
    // Shape: the "dev-" prefix + Crockford base32 of sha256(pubkey)[:10].
    expect(a.deviceId, startsWith(deviceIdPrefix));
    final suffix = a.deviceId.substring(deviceIdPrefix.length);
    expect(suffix.length, (deviceIdHashBytes * 8 / 5).ceil());
    for (final ch in suffix.split('')) {
      expect(Crockford.alphabet.contains(ch), isTrue, reason: '$ch is Crockford');
    }
  });

  test('a different seed yields a different derived id', () async {
    final otherSeed = Uint8List.fromList(
      List<int>.generate(32, (i) => (fixtureSeed[i] ^ 0xff) & 0xff),
    );
    final other = await DeviceIdentity(
      secretStore: FakeSecretStore(),
      seedFactory: () => otherSeed,
    ).provisionLocal();
    expect(other.deviceId, isNot(fixtureDeviceId));
  });

  test('ensureProvisioned is idempotent over the same store', () async {
    final store = FakeSecretStore();
    final pubKeys = <String>[];
    final client = MockClient((req) async {
      pubKeys.add((jsonDecode(req.body) as Map<String, dynamic>)['publicKey'] as String);
      return http.Response(jsonEncode({'device': {'deviceId': 'dev-x'}}), 200);
    });
    await fixedIdentity(store).ensureProvisioned(apiFor(client));
    // A new DeviceIdentity over the same store (a relaunch) must reuse the key,
    // even when handed a DIFFERENT seed.
    final otherSeed = Uint8List.fromList(List<int>.filled(32, 9));
    final second = DeviceIdentity(secretStore: store, seedFactory: () => otherSeed);
    final p2 = await second.ensureProvisioned(apiFor(client));
    expect(p2.deviceId, fixtureDeviceId);
    expect(pubKeys.first, pubKeys.last);
  });

  test('ensureProvisioned propagates a self-register failure (fail-fast)', () async {
    final store = FakeSecretStore();
    final client = MockClient(
      (_) async => http.Response(jsonEncode({'error': 'bad_request'}), 400),
    );
    await expectLater(
      fixedIdentity(store).ensureProvisioned(apiFor(client)),
      throwsA(isA<BardApiException>()),
    );
    // The identity was still generated + persisted, so the next attempt reuses it.
    expect(await store.readDeviceIdentity(), isNotNull);
  });

  test('provisionLocal generates without a network call and reuses on second call',
      () async {
    final identity = fixedIdentity(FakeSecretStore());
    final a = await identity.provisionLocal();
    final b = await identity.provisionLocal();
    expect(a.privateKeyBase64, b.privateKeyBase64);
    expect(a.deviceId, fixtureDeviceId);
  });

  test('current returns null before provisioning, the identity after', () async {
    final store = FakeSecretStore();
    final identity = fixedIdentity(store);
    expect(await identity.current(), isNull);
    await identity.provisionLocal();
    expect((await identity.current())?.deviceId, fixtureDeviceId);
  });

  test('restoreFromSeed rebuilds the SAME identity (recovery determinism)', () async {
    final store = FakeSecretStore();
    final identity = fixedIdentity(store);
    final original = await identity.provisionLocal();

    // A "fresh install": a new store, recover from the original's seed.
    final freshStore = FakeSecretStore();
    final fresh = DeviceIdentity(secretStore: freshStore);
    final restored = await fresh.restoreFromSeed(original.seed);

    // Same seed → same keypair → same deviceId → membership preserved.
    expect(restored.deviceId, original.deviceId);
    expect(restored.publicKeyBase64, original.publicKeyBase64);
    expect(restored.privateKeyBase64, original.privateKeyBase64);
    expect((await freshStore.readDeviceIdentity())?.deviceId, original.deviceId);
  });

  test('ProvisionedIdentity.seed is the leading 32 bytes of the private key',
      () async {
    final id = await fixedIdentity(FakeSecretStore()).provisionLocal();
    final priv = base64.decode(id.privateKeyBase64);
    expect(id.seed, priv.sublist(0, 32));
    expect(id.seed, fixtureSeed);
  });

  test('mintToken returns null without an identity, a verifiable token with one',
      () async {
    final store = FakeSecretStore();
    final identity = fixedIdentity(store);
    expect(await identity.mintToken(), isNull);

    final provisioned = await identity.provisionLocal();
    final token = await identity.mintToken();
    expect(token, isNotNull);
    final jwt =
        JWT.verify(token!, EdDSAPublicKey(base64.decode(provisioned.publicKeyBase64)));
    expect(jwt.subject, fixtureDeviceId);
    expect(jwt.header?['alg'], 'EdDSA');
  });

  test('the production path (no injected seed) derives a "dev-" prefixed id',
      () async {
    // Exercises the random-keypair branch (no injected seedFactory).
    final identity = DeviceIdentity(secretStore: FakeSecretStore());
    final provisioned = await identity.provisionLocal();
    expect(provisioned.deviceId, startsWith(deviceIdPrefix));
    expect(provisioned.deviceId.length, greaterThan(deviceIdPrefix.length));
    // And it matches the derivation of its own public key.
    expect(provisioned.deviceId,
        deriveDeviceId(base64.decode(provisioned.publicKeyBase64)));
  });
}
