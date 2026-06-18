import 'dart:convert';
import 'dart:typed_data';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/box_controller.dart';
import 'package:bard_pro/device_auth.dart';
import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_secret_store.dart';
import 'support/fixed_identity.dart';

/// Tests the [BoxController] orchestration against a `MockClient`-backed
/// [BardApi] and an in-memory secret store — no network, no platform channels
/// (CLAUDE.md §9). Asserts the ADR-0016 S5 invariants:
///   - ONE device identity self-registers (POST /devices/self-register),
///   - create-box mints a DEVICE token (not BARD_AUTH_TOKEN) for POST /channels
///     and POST /invites,
///   - redeem joins under the same single identity,
///   - owner management (members, remove, add-via-share) uses the device token.
void main() {
  /// A redeem 200 body — NO deviceSecret; the device owns its keypair. The
  /// server echoes the device's DERIVED id (the fixture's stable deviceId).
  String redeemBody({String? deviceId, String channelId = 'north'}) =>
      jsonEncode({
        'device': {'deviceId': deviceId ?? fixtureDeviceId},
        'channelId': channelId,
      });

  /// A create-channel 200 body echoing the requested id.
  String channelBody(String channelId) =>
      jsonEncode({'channel': {'channelId': channelId}});

  /// An invite 200 body for [channelId].
  String inviteBody(String channelId, {String token = 'tok'}) => jsonEncode({
        'invite': {'inviteId': 'i', 'channelId': channelId},
        'inviteToken': token,
        'inviteUrl': 'bard://invite?invite=$token',
      });

  /// Build a controller bound to [client] with the fixed-seed identity so the
  /// derived deviceId is deterministic and assertable. [seed] overrides the seed
  /// (a different seed → a different derived id) to prove the stored identity
  /// wins on a relaunch.
  BoxController controllerFor(
    MockClient client, {
    FakeSecretStore? store,
    Uint8List? seed,
  }) =>
      BoxController(
        apiFactory: ({tokenProvider}) => BardApi(
          routerBaseUrl: 'https://r.test',
          registryBaseUrl: 'https://reg.test',
          token: 'BAKED-SHOULD-NOT-BE-USED',
          httpClient: client,
          listTimeout: const Duration(milliseconds: 50),
          tokenProvider: tokenProvider,
        ),
        secretStore: store ?? FakeSecretStore(),
        seedFactory: () => seed ?? fixtureSeed,
      );

  /// A seed distinct from the fixture, so a controller built with it derives a
  /// DIFFERENT deviceId — used to prove a relaunch reuses the STORED identity.
  final otherSeed = Uint8List.fromList(
    List<int>.generate(32, (i) => (fixtureSeed[i] ^ 0xff) & 0xff),
  );

  group('selfRegister (first launch, idempotent)', () {
    test('generates one identity, registers its public key, persists privkey',
        () async {
      final store = FakeSecretStore();
      String? sentDeviceId;
      String? sentPublicKey;
      String? seenAuth;
      final client = MockClient((req) async {
        expect(req.url.path, '/devices/self-register');
        seenAuth = req.headers['Authorization'];
        final body = jsonDecode(req.body) as Map<String, dynamic>;
        sentDeviceId = body['deviceId'] as String?;
        sentPublicKey = body['publicKey'] as String?;
        return http.Response(jsonEncode({'device': {'deviceId': fixtureDeviceId}}), 200);
      });
      final controller = controllerFor(client, store: store);

      final id = await controller.selfRegister();
      expect(id, fixtureDeviceId);
      expect(seenAuth, isNull, reason: 'self-register is no-auth');
      expect(sentDeviceId, fixtureDeviceId);
      // A 32-byte Ed25519 public key was registered.
      expect(base64.decode(sentPublicKey!).length, 32);
      // The private key is persisted under the device-identity namespace, and
      // its public half matches what was sent.
      final stored = await store.readDeviceIdentity();
      expect(stored, isNotNull);
      final privBytes = base64.decode(stored!.privateKey);
      expect(privBytes.length, 64);
      expect(base64.encode(privBytes.sublist(32, 64)), sentPublicKey);
    });

    test('is idempotent: relaunch reuses the SAME identity', () async {
      final store = FakeSecretStore();
      final publicKeys = <String>[];
      final client = MockClient((req) async {
        final body = jsonDecode(req.body) as Map<String, dynamic>;
        publicKeys.add(body['publicKey'] as String);
        return http.Response(jsonEncode({'device': {'deviceId': fixtureDeviceId}}), 200);
      });
      final c1 = controllerFor(client, store: store);
      await c1.selfRegister();
      // A "second launch" over the SAME store must not mint a new identity.
      final c2 = controllerFor(client, store: store, seed: otherSeed);
      final id2 = await c2.selfRegister();
      expect(id2, fixtureDeviceId, reason: 'the stored identity wins over a new id');
      expect(publicKeys.first, publicKeys.last, reason: 'same public key both times');
    });

    test('surfaces a self-register failure via error and returns null', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'error': 'bad_request'}), 400),
      );
      final controller = controllerFor(client);
      expect(await controller.selfRegister(), isNull);
      expect(controller.error, contains('bad_request'));
    });
  });

  group('createBox (device-token owner flow, closes #67)', () {
    test('self-registers, creates the channel + invite with the DEVICE token',
        () async {
      final store = FakeSecretStore();
      final authByPath = <String, String?>{};
      String? registeredPublicKey;
      final client = MockClient((req) async {
        final path = req.url.path;
        authByPath[path] = req.headers['Authorization'];
        if (path == '/devices/self-register') {
          registeredPublicKey =
              (jsonDecode(req.body) as Map<String, dynamic>)['publicKey'] as String?;
          return http.Response(jsonEncode({'device': {'deviceId': fixtureDeviceId}}), 200);
        }
        if (path == '/channels') {
          expect(jsonDecode(req.body), {'channelId': 'north', 'label': 'North'});
          return http.Response(channelBody('north'), 200);
        }
        if (path == '/invites') {
          return http.Response(inviteBody('north'), 200);
        }
        return http.Response('{}', 404);
      });
      final controller = controllerFor(client, store: store);

      final invite = await controller.createBox('north', label: 'North');
      expect(invite, isNotNull);
      expect(invite!.inviteUrl, 'bard://invite?invite=tok');
      expect(controller.error, isNull);
      // The owner context is recorded.
      expect(controller.isOwner, isTrue);
      expect(controller.joinedBox?.channelId, 'north');
      expect(controller.joinedBox?.deviceId, fixtureDeviceId);

      // Self-register is no-auth; the OWNER calls carry a self-signed DEVICE
      // token that verifies under the registered public key — NEVER the baked
      // BARD_AUTH_TOKEN.
      expect(authByPath['/devices/self-register'], isNull);
      for (final path in ['/channels', '/invites']) {
        final auth = authByPath[path];
        expect(auth, isNotNull);
        expect(auth, startsWith('Bearer '));
        expect(auth, isNot(contains('BAKED-SHOULD-NOT-BE-USED')));
        final token = auth!.substring('Bearer '.length);
        final jwt =
            JWT.verify(token, EdDSAPublicKey(base64.decode(registeredPublicKey!)));
        expect(jwt.subject, fixtureDeviceId);
        expect(jwt.header?['alg'], 'EdDSA');
      }
    });

    test('honours a server-renamed channel id for the invite', () async {
      final client = MockClient((req) async {
        final path = req.url.path;
        if (path == '/devices/self-register') {
          return http.Response(jsonEncode({'device': {'deviceId': fixtureDeviceId}}), 200);
        }
        if (path == '/channels') {
          // The server canonicalises the id.
          return http.Response(channelBody('north-1'), 200);
        }
        expect(path, '/invites');
        expect(jsonDecode(req.body)['channelId'], 'north-1',
            reason: 'the invite is for the id the server returned');
        return http.Response(inviteBody('north-1'), 200);
      });
      final controller = controllerFor(client);
      final invite = await controller.createBox('north', label: 'North');
      expect(invite, isNotNull);
      expect(controller.joinedBox?.channelId, 'north-1');
    });

    test('surfaces a create-channel failure and records no box', () async {
      final client = MockClient((req) async {
        if (req.url.path == '/devices/self-register') {
          return http.Response(jsonEncode({'device': {'deviceId': fixtureDeviceId}}), 200);
        }
        return http.Response(jsonEncode({'error': 'unauthorized'}), 401);
      });
      final controller = controllerFor(client);
      final invite = await controller.createBox('north', label: 'North');
      expect(invite, isNull);
      expect(controller.joinedBox, isNull);
      expect(controller.error, contains('unauthorized'));
    });
  });

  group('redeem (join under the single identity)', () {
    test('registers the device public key, records the box', () async {
      final store = FakeSecretStore();
      String? sentPublicKey;
      String? sentDeviceId;
      final client = MockClient((req) async {
        expect(req.headers['Authorization'], isNull, reason: 'redeem is no-auth');
        final body = jsonDecode(req.body) as Map<String, dynamic>;
        sentPublicKey = body['publicKey'] as String?;
        sentDeviceId = body['deviceId'] as String?;
        return http.Response(redeemBody(), 200);
      });
      final controller = controllerFor(client, store: store);

      final result = await controller.redeem('tok', label: 'My iPhone');

      expect(result, isNotNull);
      expect(controller.joinedBox?.channelId, 'north');
      expect(controller.joinedBox?.deviceId, fixtureDeviceId);
      expect(controller.isOwner, isFalse, reason: 'a redeemer is a member');
      // The device joined under its SINGLE identity's deviceId, not a slug.
      expect(sentDeviceId, fixtureDeviceId);
      expect(base64.decode(sentPublicKey!).length, 32);
      // The same single identity was persisted, and its public half matches.
      final stored = await store.readDeviceIdentity();
      expect(stored?.deviceId, fixtureDeviceId);
      final privBytes = base64.decode(stored!.privateKey);
      expect(base64.encode(privBytes.sublist(32, 64)), sentPublicKey);
    });

    test('reuses an already-provisioned identity (one key per device)', () async {
      final store = FakeSecretStore();
      // Provision via self-register first.
      final c1 = controllerFor(
        MockClient((_) async =>
            http.Response(jsonEncode({'device': {'deviceId': fixtureDeviceId}}), 200)),
        store: store,
      );
      await c1.selfRegister();
      final firstKey = (await store.readDeviceIdentity())!.privateKey;

      String? redeemPublicKey;
      final c2 = controllerFor(
        MockClient((req) async {
          redeemPublicKey =
              (jsonDecode(req.body) as Map<String, dynamic>)['publicKey'] as String?;
          return http.Response(redeemBody(), 200);
        }),
        store: store,
        seed: otherSeed,
      );
      await c2.redeem('tok', label: 'My iPhone');
      // Redeem used the EXISTING identity's key, not a fresh one.
      final secondKey = (await store.readDeviceIdentity())!.privateKey;
      expect(secondKey, firstKey);
      expect(base64.encode(base64.decode(firstKey).sublist(32, 64)), redeemPublicKey);
    });

    test('surfaces a server error and does not record a box', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'error': 'unauthorized', 'detail': 'invite has expired'}),
          401,
        ),
      );
      final controller = controllerFor(client);
      final result = await controller.redeem('tok');
      expect(result, isNull);
      expect(controller.joinedBox, isNull);
      expect(controller.error, contains('unauthorized'));
    });
  });

  group('owner management (device-token auth)', () {
    /// A controller already in owner context for box 'north'.
    BoxController ownerControllerFor(MockClient client, {FakeSecretStore? store}) =>
        controllerFor(client, store: store)
          ..enterAsOwner('north', deviceId: fixtureDeviceId, label: 'North');

    test('refreshMembers fetches members with the device token', () async {
      final store = FakeSecretStore();
      // Provision an identity so the device token is non-empty.
      await store.writeDeviceIdentity(
        deviceId: fixtureDeviceId,
        privateKey: base64.encode(_freshPriv()),
      );
      String? seenAuth;
      final client = MockClient((req) async {
        seenAuth = req.headers['Authorization'];
        return http.Response(
          jsonEncode({'channelId': 'north', 'deviceIds': [fixtureDeviceId, 'mac-1']}),
          200,
        );
      });
      final controller = ownerControllerFor(client, store: store);
      final members = await controller.refreshMembers();
      expect(members?.deviceIds, [fixtureDeviceId, 'mac-1']);
      expect(seenAuth, startsWith('Bearer '),
          reason: 'owner read uses the device token');
      expect(seenAuth, isNot(contains('BAKED-SHOULD-NOT-BE-USED')));
    });

    test('refreshMembers is a no-op before any box is joined', () async {
      final controller =
          controllerFor(MockClient((_) async => http.Response('{}', 200)));
      expect(await controller.refreshMembers(), isNull);
    });

    test('owner removes a member with the device token and adopts the update',
        () async {
      final store = FakeSecretStore();
      await store.writeDeviceIdentity(
        deviceId: fixtureDeviceId,
        privateKey: base64.encode(_freshPriv()),
      );
      String? seenAuth;
      final client = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.toString(),
            'https://reg.test/channels/north/members/mac-1/remove');
        seenAuth = req.headers['Authorization'];
        return http.Response(
          jsonEncode({'channelId': 'north', 'deviceIds': [fixtureDeviceId]}),
          200,
        );
      });
      final controller = ownerControllerFor(client, store: store);
      final updated = await controller.removeMember('mac-1');
      expect(updated?.deviceIds, [fixtureDeviceId]);
      expect(controller.members?.deviceIds, [fixtureDeviceId]);
      expect(seenAuth, startsWith('Bearer '));
      expect(seenAuth, isNot(contains('BAKED-SHOULD-NOT-BE-USED')));
    });

    test('removeMember is a no-op before any box / for a non-owner', () async {
      final controller =
          controllerFor(MockClient((_) async => http.Response('{}', 200)));
      expect(await controller.removeMember('mac-1'), isNull);
      // member context
      final member = controllerFor(
        MockClient((_) async => http.Response(redeemBody(), 200)),
      );
      await member.redeem('tok');
      expect(await member.removeMember('mac-1'), isNull,
          reason: 'members cannot evict; only owners');
    });

    test('createInvite (add-people) mints a fresh invite with the device token',
        () async {
      final store = FakeSecretStore();
      await store.writeDeviceIdentity(
        deviceId: fixtureDeviceId,
        privateKey: base64.encode(_freshPriv()),
      );
      String? seenAuth;
      final client = MockClient((req) async {
        expect(req.url.path, '/invites');
        seenAuth = req.headers['Authorization'];
        return http.Response(inviteBody('north', token: 'tok2'), 200);
      });
      final controller = ownerControllerFor(client, store: store);
      final invite = await controller.createInvite(label: 'North');
      expect(invite?.inviteUrl, 'bard://invite?invite=tok2');
      expect(seenAuth, startsWith('Bearer '));
      expect(seenAuth, isNot(contains('BAKED-SHOULD-NOT-BE-USED')));
    });

    test('createInvite is a no-op for a non-owner / before any box', () async {
      final controller =
          controllerFor(MockClient((_) async => http.Response('{}', 200)));
      expect(await controller.createInvite(), isNull);
    });

    test('enterAsOwner records an owner box and notifies', () async {
      var notified = 0;
      final controller =
          controllerFor(MockClient((_) async => http.Response('{}', 200)))
            ..addListener(() => notified++);
      controller.enterAsOwner('north', deviceId: fixtureDeviceId, label: 'North');
      expect(controller.isOwner, isTrue);
      expect(controller.joinedBox?.channelId, 'north');
      expect(controller.members, isNull);
      expect(notified, greaterThan(0));
    });
  });

  group('mintDeviceToken', () {
    test('self-signs a token verifiable with the registered key', () async {
      final store = FakeSecretStore();
      String? sentPublicKey;
      final client = MockClient((req) async {
        sentPublicKey =
            (jsonDecode(req.body) as Map<String, dynamic>)['publicKey'] as String?;
        return http.Response(jsonEncode({'device': {'deviceId': fixtureDeviceId}}), 200);
      });
      final controller = controllerFor(client, store: store);
      await controller.selfRegister();

      final token = await controller.mintDeviceToken();
      expect(token, isNotNull);
      final jwt = JWT.verify(token!, EdDSAPublicKey(base64.decode(sentPublicKey!)));
      expect(jwt.subject, fixtureDeviceId);
      expect(jwt.issuer, 'bardllm-pro');
      expect(jwt.header?['alg'], 'EdDSA');
    });

    test('returns null when no identity is provisioned', () async {
      final controller =
          controllerFor(MockClient((_) async => http.Response('{}', 200)));
      expect(await controller.mintDeviceToken(), isNull);
    });
  });
}

/// A fresh 64-byte Ed25519 private representation for seeding the fake store with
/// a usable identity (so device-token minting produces a real EdDSA signature).
List<int> _freshPriv() =>
    base64.decode(DeviceAuth.generateKeyPair().privateKeyBase64);
