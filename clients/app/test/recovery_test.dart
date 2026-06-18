import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/box_controller.dart';
import 'package:bard_pro/box/crockford.dart';
import 'package:bard_pro/box/device_identity.dart';
import 'package:bard_pro/box/recovery_controller.dart';
import 'package:bard_pro/box/seed_recovery.dart';
import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_secret_store.dart';
import 'support/fixed_identity.dart';

/// Integration tests for the S7 recovery flow (ADR-0016 §5): the escrow POST/GET
/// wiring and the [RecoveryController] setUpEscrow + recover orchestration. No
/// network (MockClient), no platform channels (FakeSecretStore) — CLAUDE.md §9.
void main() {
  // A fast KDF so the suite stays quick; the wire format is identical. The
  // inline runner keeps the crypto on the test isolate (no spawn) for
  // determinism (CLAUDE.md §3: swappable seam).
  SeedWrapper fastWrapper() => SeedWrapper(
        params: const Argon2Params(parallelism: 1, memory: 1024, iterations: 1),
        runner: inlineRunner,
      );

  BoxApiFactory apiFactory(MockClient client) => ({tokenProvider}) => BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: 'BAKED-SHOULD-NOT-BE-USED',
        httpClient: client,
        listTimeout: const Duration(milliseconds: 100),
        tokenProvider: tokenProvider,
      );

  group('BardApi escrow wiring (frozen contract)', () {
    test('escrowSeed POSTs {handle, publicKey, wraps} with the device token',
        () async {
      String? seenAuth;
      Map<String, dynamic>? seenBody;
      final client = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.path, '/recovery/escrow');
        seenAuth = req.headers['Authorization'];
        seenBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response('{}', 200);
      });
      final api = BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: '',
        httpClient: client,
        tokenProvider: () => 'DEVICE-TOKEN',
      );
      await api.escrowSeed(
        handle: 'ada@example.com',
        publicKey: fixturePublicKeyBase64,
        wraps: const EscrowWraps(password: 'PW-BLOB', omg: 'OMG-BLOB'), // pragma: allowlist secret
      );
      expect(seenAuth, 'Bearer DEVICE-TOKEN');
      expect(seenBody, {
        'handle': 'ada@example.com',
        'publicKey': fixturePublicKeyBase64,
        'wraps': {'password': 'PW-BLOB', 'omg': 'OMG-BLOB'}, // pragma: allowlist secret
      });
    });

    test('escrowSeed throws on a non-200', () async {
      final api = BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: '',
        httpClient: MockClient(
          (_) async => http.Response(jsonEncode({'error': 'conflict'}), 409),
        ),
        tokenProvider: () => 'T',
      );
      await expectLater(
        api.escrowSeed(
          handle: 'h',
          publicKey: 'k',
          wraps: const EscrowWraps(password: 'p', omg: 'o'),
        ),
        throwsA(isA<BardApiException>()),
      );
    });

    test('fetchEscrow GETs /recovery/escrow/{handle} with NO auth and parses it',
        () async {
      String? seenAuth;
      late String seenUrl;
      final client = MockClient((req) async {
        expect(req.method, 'GET');
        seenUrl = req.url.toString();
        seenAuth = req.headers['Authorization'];
        return http.Response(
          jsonEncode({
            'publicKey': fixturePublicKeyBase64,
            'wraps': {'password': 'PW', 'omg': 'OMG'}, // pragma: allowlist secret
          }),
          200,
        );
      });
      final api = BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: 'baked',
        httpClient: client,
      );
      final record = await api.fetchEscrow('ada@example.com');
      expect(seenUrl, 'https://reg.test/recovery/escrow/ada%40example.com');
      expect(seenAuth, isNull, reason: 'recovery fetch is no-auth');
      expect(record.publicKey, fixturePublicKeyBase64);
      expect(record.wraps.password, 'PW');
      expect(record.wraps.omg, 'OMG');
    });

    test('fetchEscrow throws on a 404 (unknown handle)', () async {
      final api = BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: '',
        httpClient: MockClient(
          (_) async => http.Response(jsonEncode({'error': 'not_found'}), 404),
        ),
      );
      await expectLater(api.fetchEscrow('nobody'), throwsA(isA<BardApiException>()));
    });

    test('fetchEscrow throws malformed on a bad body', () async {
      final api = BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: '',
        httpClient: MockClient(
          (_) async => http.Response(jsonEncode({'publicKey': 'k'}), 200),
        ),
      );
      await expectLater(api.fetchEscrow('h'), throwsA(isA<BardApiException>()));
    });
  });

  group('RecoveryController.setUpEscrow (first-run)', () {
    test('wraps the seed twice and escrows both ciphertexts; returns the OMG code',
        () async {
      final store = FakeSecretStore();
      final identity =
          DeviceIdentity(secretStore: store, seedFactory: fixtureSeedFactory);
      Map<String, dynamic>? escrowed;
      String? seenAuth;
      final client = MockClient((req) async {
        expect(req.url.path, '/recovery/escrow');
        seenAuth = req.headers['Authorization'];
        escrowed = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response('{}', 200);
      });
      final controller = RecoveryController(
        apiFactory: apiFactory(client),
        identity: identity,
        wrapper: fastWrapper(),
        omgGenerator: () => fixtureOmgCode,
      );

      final result = await controller.setUpEscrow(
        handle: 'ada@example.com',
        password: fixtureSecretString,
      );

      expect(result, isNotNull);
      expect(result!.omgCode, fixtureOmgCode);
      expect(result.handle, 'ada@example.com');
      expect(controller.error, isNull);
      // The escrow carried the handle, the DERIVED public key, and two wraps.
      expect(escrowed!['handle'], 'ada@example.com');
      expect(escrowed!['publicKey'], fixturePublicKeyBase64);
      final wraps = escrowed!['wraps'] as Map<String, dynamic>;
      expect(wraps['password'], isA<String>());
      expect(wraps['omg'], isA<String>());
      expect(wraps['password'], isNot(wraps['omg']));
      // The seed plaintext is NEVER in the escrow body (zero-knowledge).
      expect(req2Json(escrowed!), isNot(contains(base64.encode(fixtureSeed))));
      // The owner token, not the baked token.
      expect(seenAuth, startsWith('Bearer '));
      expect(seenAuth, isNot(contains('BAKED-SHOULD-NOT-BE-USED')));

      // The two wraps each decrypt back to the device seed with the right secret.
      final w = fastWrapper();
      expect(await w.unwrap(blob: wraps['password'] as String,
          secret: fixtureSecretString), fixtureSeed);
      expect(await w.unwrap(blob: wraps['omg'] as String,
          secret: Crockford.normalizeOmgCode(fixtureOmgCode)!), fixtureSeed);
    });

    test('validates a blank handle/password before any network call', () async {
      var called = false;
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient((_) async {
          called = true;
          return http.Response('{}', 200);
        })),
        identity: DeviceIdentity(secretStore: FakeSecretStore()),
        wrapper: fastWrapper(),
      );
      expect(await controller.setUpEscrow(handle: '  ', password: 'x'), isNull);
      expect(await controller.setUpEscrow(handle: 'h', password: ''), isNull);
      expect(controller.error, isNotNull);
      expect(called, isFalse);
    });

    test('surfaces an escrow POST failure via error', () async {
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient(
          (_) async => http.Response(jsonEncode({'error': 'conflict'}), 409),
        )),
        identity: DeviceIdentity(secretStore: FakeSecretStore(), seedFactory: fixtureSeedFactory),
        wrapper: fastWrapper(),
        omgGenerator: () => fixtureOmgCode,
      );
      final result = await controller.setUpEscrow(handle: 'h', password: 'p');
      expect(result, isNull);
      expect(controller.error, contains('conflict'));
    });

    test('uses the real Argon2id wrapper by default (no injected wrapper)',
        () async {
      // Exercises the `wrapper ?? SeedWrapper()` default branch end-to-end with
      // the production KDF, proving the default wrap actually round-trips.
      Map<String, dynamic>? escrowed;
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient((req) async {
          escrowed = jsonDecode(req.body) as Map<String, dynamic>;
          return http.Response('{}', 200);
        })),
        identity: DeviceIdentity(
            secretStore: FakeSecretStore(), seedFactory: fixtureSeedFactory),
        // no wrapper, no omgGenerator → defaults.
      );
      final result = await controller.setUpEscrow(
          handle: 'ada@example.com', password: fixtureSecretString);
      expect(result, isNotNull);
      final wraps = (escrowed!['wraps'] as Map)['password'] as String;
      // The default SeedWrapper unwraps it back to the seed.
      expect(await SeedWrapper().unwrap(blob: wraps, secret: fixtureSecretString),
          fixtureSeed);
    });
  });

  group('RecoveryController.recover (fresh install)', () {
    /// An escrow record produced by wrapping the fixture seed under [password]
    /// and [omgSecret], so recovery can decrypt it back.
    Future<Map<String, dynamic>> escrowBody({
      required String password,
      required String omgSecret,
    }) async {
      final w = fastWrapper();
      return {
        'publicKey': fixturePublicKeyBase64,
        'wraps': {
          'password': await w.wrap(seed: fixtureSeed, secret: password),
          'omg': await w.wrap(seed: fixtureSeed, secret: omgSecret),
        },
      };
    }

    test('recovers via PASSWORD: rebuilds the same identity + self-registers',
        () async {
      final body = await escrowBody(
        password: fixtureSecretString,
        omgSecret: fixtureOmgSecret,
      );
      final store = FakeSecretStore(); // a FRESH install — empty store.
      String? registeredPublicKey;
      String? registeredDeviceId;
      final client = MockClient((req) async {
        if (req.url.path.startsWith('/recovery/escrow/')) {
          return http.Response(jsonEncode(body), 200);
        }
        expect(req.url.path, '/devices/self-register');
        final b = jsonDecode(req.body) as Map<String, dynamic>;
        registeredDeviceId = b['deviceId'] as String?;
        registeredPublicKey = b['publicKey'] as String?;
        return http.Response(jsonEncode({'device': {'deviceId': 'x'}}), 200);
      });
      final identity = DeviceIdentity(secretStore: store);
      final controller = RecoveryController(
        apiFactory: apiFactory(client),
        identity: identity,
        wrapper: fastWrapper(),
      );

      final restored = await controller.recover(
        handle: 'ada@example.com',
        secret: fixtureSecretString,
        usingOmgCode: false,
      );

      expect(restored, isNotNull);
      expect(controller.error, isNull);
      // The recovered identity is the SAME one (stable, key-derived id).
      expect(restored!.deviceId, fixtureDeviceId);
      expect(restored.publicKeyBase64, fixturePublicKeyBase64);
      // It self-registered the restored key under the same deviceId → memberships
      // (keyed by deviceId server-side) are preserved.
      expect(registeredDeviceId, fixtureDeviceId);
      expect(registeredPublicKey, fixturePublicKeyBase64);
      // And it is persisted locally for subsequent launches.
      expect((await store.readDeviceIdentity())?.deviceId, fixtureDeviceId);
    });

    test('recovers via OMG CODE (typed loosely, with confusables)', () async {
      final body = await escrowBody(
        password: fixtureSecretString,
        omgSecret: fixtureOmgSecret,
      );
      final store = FakeSecretStore();
      final client = MockClient((req) async {
        if (req.url.path.startsWith('/recovery/escrow/')) {
          return http.Response(jsonEncode(body), 200);
        }
        return http.Response(jsonEncode({'device': {'deviceId': 'x'}}), 200);
      });
      final controller = RecoveryController(
        apiFactory: apiFactory(client),
        identity: DeviceIdentity(secretStore: store),
        wrapper: fastWrapper(),
      );

      // The user types it with lowercase + spaces instead of dashes.
      final restored = await controller.recover(
        handle: 'ada@example.com',
        secret: '7k3p9 r2m4x wq8tb', // pragma: allowlist secret
        usingOmgCode: true,
      );
      expect(restored, isNotNull);
      expect(restored!.deviceId, fixtureDeviceId);
    });

    test('a wrong password surfaces a friendly error, no identity restored',
        () async {
      final body = await escrowBody(
        password: fixtureSecretString,
        omgSecret: fixtureOmgSecret,
      );
      final store = FakeSecretStore();
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient(
          (_) async => http.Response(jsonEncode(body), 200),
        )),
        identity: DeviceIdentity(secretStore: store),
        wrapper: fastWrapper(),
      );
      final restored = await controller.recover(
        handle: 'ada@example.com',
        secret: 'wrong-password', // pragma: allowlist secret
        usingOmgCode: false,
      );
      expect(restored, isNull);
      expect(controller.error, contains("didn't match"));
      expect(await store.readDeviceIdentity(), isNull);
    });

    test('a malformed OMG code is rejected before any decrypt', () async {
      final body = await escrowBody(
        password: fixtureSecretString,
        omgSecret: fixtureOmgSecret,
      );
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient(
          (_) async => http.Response(jsonEncode(body), 200),
        )),
        identity: DeviceIdentity(secretStore: FakeSecretStore()),
        wrapper: fastWrapper(),
      );
      final restored = await controller.recover(
        handle: 'ada@example.com',
        secret: 'too-short', // not 15 Crockford symbols // pragma: allowlist secret
        usingOmgCode: true,
      );
      expect(restored, isNull);
      expect(controller.error, contains('recovery code'));
    });

    test('validates a blank handle/secret before any network call', () async {
      var called = false;
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient((_) async {
          called = true;
          return http.Response('{}', 200);
        })),
        identity: DeviceIdentity(secretStore: FakeSecretStore()),
        wrapper: fastWrapper(),
      );
      expect(
        await controller.recover(handle: '', secret: 'x', usingOmgCode: false),
        isNull,
      );
      expect(
        await controller.recover(handle: 'h', secret: '  ', usingOmgCode: true),
        isNull,
      );
      expect(called, isFalse);
    });

    test('surfaces an unknown-handle (404) via error', () async {
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient(
          (_) async => http.Response(jsonEncode({'error': 'not_found'}), 404),
        )),
        identity: DeviceIdentity(secretStore: FakeSecretStore()),
        wrapper: fastWrapper(),
      );
      final restored = await controller.recover(
        handle: 'nobody@example.com',
        secret: fixtureSecretString,
        usingOmgCode: false,
      );
      expect(restored, isNull);
      expect(controller.error, contains('not_found'));
    });
  });

  group('round-trip: escrow then recover reconstructs the identity', () {
    test('a device that escrows can be recovered on a fresh install by password',
        () async {
      // Phase 1: the original device escrows its seed.
      Map<String, dynamic>? escrowed;
      final originStore = FakeSecretStore();
      final originIdentity =
          DeviceIdentity(secretStore: originStore, seedFactory: fixtureSeedFactory);
      final originClient = MockClient((req) async {
        escrowed = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response('{}', 200);
      });
      final setup = await RecoveryController(
        apiFactory: apiFactory(originClient),
        identity: originIdentity,
        wrapper: fastWrapper(),
        omgGenerator: () => fixtureOmgCode,
      ).setUpEscrow(handle: 'ada@example.com', password: fixtureSecretString);
      expect(setup, isNotNull);
      final originId = await originIdentity.current();

      // Phase 2: a brand-new install fetches that escrow and recovers by password.
      final freshStore = FakeSecretStore();
      final freshIdentity = DeviceIdentity(secretStore: freshStore);
      final freshClient = MockClient((req) async {
        if (req.url.path.startsWith('/recovery/escrow/')) {
          // Serve exactly what was escrowed in phase 1.
          return http.Response(
            jsonEncode({
              'publicKey': escrowed!['publicKey'],
              'wraps': escrowed!['wraps'],
            }),
            200,
          );
        }
        return http.Response(jsonEncode({'device': {'deviceId': 'x'}}), 200);
      });
      final restored = await RecoveryController(
        apiFactory: apiFactory(freshClient),
        identity: freshIdentity,
        wrapper: fastWrapper(),
      ).recover(
        handle: 'ada@example.com',
        secret: fixtureSecretString,
        usingOmgCode: false,
      );

      // The fresh install now holds the SAME identity as the origin device.
      expect(restored!.deviceId, originId!.deviceId);
      expect(restored.privateKeyBase64, originId.privateKeyBase64);
      // And its token verifies under the originally-escrowed public key.
      final token = freshIdentity.mintTokenFor(restored);
      final jwt = JWT.verify(
          token, EdDSAPublicKey(base64.decode(escrowed!['publicKey'] as String)));
      expect(jwt.subject, originId.deviceId);
    });

    test('the same device can also be recovered by its OMG code', () async {
      Map<String, dynamic>? escrowed;
      final originIdentity = DeviceIdentity(
          secretStore: FakeSecretStore(), seedFactory: fixtureSeedFactory);
      await RecoveryController(
        apiFactory: apiFactory(MockClient((req) async {
          escrowed = jsonDecode(req.body) as Map<String, dynamic>;
          return http.Response('{}', 200);
        })),
        identity: originIdentity,
        wrapper: fastWrapper(),
        omgGenerator: () => fixtureOmgCode,
      ).setUpEscrow(handle: 'ada@example.com', password: fixtureSecretString);

      final restored = await RecoveryController(
        apiFactory: apiFactory(MockClient((req) async {
          if (req.url.path.startsWith('/recovery/escrow/')) {
            return http.Response(
              jsonEncode(
                  {'publicKey': escrowed!['publicKey'], 'wraps': escrowed!['wraps']}),
              200,
            );
          }
          return http.Response(jsonEncode({'device': {'deviceId': 'x'}}), 200);
        })),
        identity: DeviceIdentity(secretStore: FakeSecretStore()),
        wrapper: fastWrapper(),
      ).recover(
        handle: 'ada@example.com',
        secret: fixtureOmgCode,
        usingOmgCode: true,
      );
      expect(restored!.deviceId, fixtureDeviceId);
    });
  });
}

/// Re-encode an escrow body to a string so a test can assert the seed plaintext
/// is absent (zero-knowledge escrow).
String req2Json(Map<String, dynamic> body) => jsonEncode(body);
