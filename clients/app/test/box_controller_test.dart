import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/box_controller.dart';
import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_secret_store.dart';

/// Tests the [BoxController] orchestration against a `MockClient`-backed
/// [BardApi] and an in-memory secret store — no network, no platform channels
/// (CLAUDE.md §9). Asserts the ADR-0016 invariants: redeem auto-provisions the
/// device keypair, registers the PUBLIC key, persists the PRIVATE key locally,
/// and the per-device token self-signs from that private key.
void main() {
  /// A redeem 200 body under the new contract — NO deviceSecret; the device owns
  /// its keypair.
  String redeemBody({String deviceId = 'my-iphone', String channelId = 'north'}) =>
      jsonEncode({
        'device': {'deviceId': deviceId},
        'channelId': channelId,
      });

  BardApi apiFor(MockClient client) => BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: 'manager',
        httpClient: client,
        listTimeout: const Duration(milliseconds: 50),
      );

  test('createBox returns the invite for sharing', () async {
    final client = MockClient(
      (_) async => http.Response(
        jsonEncode({
          'invite': {'inviteId': 'i', 'channelId': 'north'},
          'inviteToken': 'tok',
          'inviteUrl': 'bard://invite?invite=tok',
        }),
        200,
      ),
    );
    final controller = BoxController(
      apiFactory: () => apiFor(client),
      secretStore: FakeSecretStore(),
    );
    final invite = await controller.createBox('north', label: 'North');
    expect(invite, isNotNull);
    expect(invite!.inviteUrl, 'bard://invite?invite=tok');
    expect(controller.error, isNull);
  });

  test('redeem registers the public key, persists the private key, records the box',
      () async {
    final store = FakeSecretStore();
    String? sentPublicKey;
    final client = MockClient((req) async {
      expect(req.headers['Authorization'], isNull, reason: 'redeem is no-auth');
      sentPublicKey =
          (jsonDecode(req.body) as Map<String, dynamic>)['publicKey'] as String?;
      return http.Response(redeemBody(), 200);
    });
    final controller = BoxController(
      apiFactory: () => apiFor(client),
      secretStore: store,
    );

    final result =
        await controller.redeem('tok', deviceId: 'my-iphone', label: 'My iPhone');

    expect(result, isNotNull);
    expect(controller.joinedBox?.channelId, 'north');
    expect(controller.joinedBox?.deviceId, 'my-iphone');
    // The device registered a 32-byte Ed25519 public key.
    expect(sentPublicKey, isNotNull);
    expect(base64.decode(sentPublicKey!).length, 32);
    // The PRIVATE key was stored under the channel/device namespace, and its
    // public half matches what was sent.
    final storedPriv =
        await store.readDevicePrivateKey(channelId: 'north', deviceId: 'my-iphone');
    expect(storedPriv, isNotNull);
    final privBytes = base64.decode(storedPriv!);
    expect(privBytes.length, 64);
    expect(base64.encode(privBytes.sublist(32, 64)), sentPublicKey);
  });

  test('redeem surfaces a server error and does not record a box', () async {
    final client = MockClient(
      (_) async => http.Response(
        jsonEncode({'error': 'unauthorized', 'detail': 'invite has expired'}),
        401,
      ),
    );
    final controller = BoxController(
      apiFactory: () => apiFor(client),
      secretStore: FakeSecretStore(),
    );
    final result = await controller.redeem('tok', deviceId: 'd');
    expect(result, isNull);
    expect(controller.joinedBox, isNull);
    expect(controller.error, contains('unauthorized'));
  });

  test('refreshMembers fetches members for the joined box', () async {
    final client = MockClient((req) async {
      if (req.url.path.endsWith('/redeem')) {
        return http.Response(redeemBody(), 200);
      }
      expect(req.url.toString(), 'https://reg.test/channels/north/members');
      return http.Response(
        jsonEncode({'channelId': 'north', 'deviceIds': ['my-iphone', 'mac-1']}),
        200,
      );
    });
    final controller = BoxController(
      apiFactory: () => apiFor(client),
      secretStore: FakeSecretStore(),
    );
    await controller.redeem('tok', deviceId: 'my-iphone');
    final members = await controller.refreshMembers();
    expect(members?.deviceIds, ['my-iphone', 'mac-1']);
    expect(controller.members?.deviceIds, ['my-iphone', 'mac-1']);
  });

  test('refreshMembers is a no-op before any box is joined', () async {
    final controller = BoxController(
      apiFactory: () => apiFor(MockClient((_) async => http.Response('{}', 200))),
      secretStore: FakeSecretStore(),
    );
    expect(await controller.refreshMembers(), isNull);
  });

  test('mintDeviceToken self-signs a token verifiable with the registered key',
      () async {
    final store = FakeSecretStore();
    String? sentPublicKey;
    final client = MockClient((req) async {
      sentPublicKey =
          (jsonDecode(req.body) as Map<String, dynamic>)['publicKey'] as String?;
      return http.Response(redeemBody(), 200);
    });
    final controller = BoxController(
      apiFactory: () => apiFor(client),
      secretStore: store,
    );
    await controller.redeem('tok', deviceId: 'my-iphone');

    final token = await controller.mintDeviceToken();
    expect(token, isNotNull);
    // The server holds the registered public key; the self-signed token verifies
    // against it (alg EdDSA).
    final jwt =
        JWT.verify(token!, EdDSAPublicKey(base64.decode(sentPublicKey!)));
    expect(jwt.subject, 'my-iphone');
    expect(jwt.issuer, 'bardllm-pro');
    expect(jwt.header?['alg'], 'EdDSA');
  });

  test('mintDeviceToken returns null with no joined box', () async {
    final controller = BoxController(
      apiFactory: () => apiFor(MockClient((_) async => http.Response('{}', 200))),
      secretStore: FakeSecretStore(),
    );
    expect(await controller.mintDeviceToken(), isNull);
  });

  test('mintDeviceToken returns null when no private key is stored', () async {
    final store = FakeSecretStore();
    final client =
        MockClient((_) async => http.Response(redeemBody(), 200));
    final controller = BoxController(
      apiFactory: () => apiFor(client),
      secretStore: store,
    );
    await controller.redeem('tok', deviceId: 'my-iphone');
    // Simulate the key being wiped after the box was recorded.
    await store.deleteDevicePrivateKey(channelId: 'north', deviceId: 'my-iphone');
    expect(await controller.mintDeviceToken(), isNull);
  });

  group('owner context', () {
    test('isOwner is false before any box and after a member redeem', () async {
      final client =
          MockClient((_) async => http.Response(redeemBody(), 200));
      final controller = BoxController(
        apiFactory: () => apiFor(client),
        secretStore: FakeSecretStore(),
      );
      expect(controller.isOwner, isFalse);
      await controller.redeem('tok', deviceId: 'my-iphone');
      expect(controller.isOwner, isFalse,
          reason: 'a redeemer is a member, not the owner');
    });

    test('enterAsOwner records an owner box and notifies', () async {
      var notified = 0;
      final controller = BoxController(
        apiFactory: () => apiFor(MockClient((_) async => http.Response('{}', 200))),
        secretStore: FakeSecretStore(),
      )..addListener(() => notified++);
      controller.enterAsOwner('north', deviceId: 'owner-mac', label: 'North');
      expect(controller.isOwner, isTrue);
      expect(controller.joinedBox?.channelId, 'north');
      expect(controller.joinedBox?.deviceId, 'owner-mac');
      expect(controller.members, isNull);
      expect(notified, greaterThan(0));
    });
  });

  group('removeMember', () {
    test('owner removes a member and adopts the updated membership', () async {
      final client = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.toString(), 'https://reg.test/channels/north/members/mac-1/remove');
        expect(req.headers['Authorization'], 'Bearer manager');
        return http.Response(
          jsonEncode({'channelId': 'north', 'deviceIds': ['owner-mac']}),
          200,
        );
      });
      final controller = BoxController(
        apiFactory: () => apiFor(client),
        secretStore: FakeSecretStore(),
      )..enterAsOwner('north', deviceId: 'owner-mac', label: 'North');

      final updated = await controller.removeMember('mac-1');
      expect(updated?.deviceIds, ['owner-mac']);
      expect(controller.members?.deviceIds, ['owner-mac']);
      expect(controller.error, isNull);
    });

    test('is a no-op before any box is joined', () async {
      final controller = BoxController(
        apiFactory: () => apiFor(MockClient((_) async => http.Response('{}', 200))),
        secretStore: FakeSecretStore(),
      );
      expect(await controller.removeMember('mac-1'), isNull);
    });

    test('is a no-op for a non-owner (member) box', () async {
      final client =
          MockClient((_) async => http.Response(redeemBody(), 200));
      final controller = BoxController(
        apiFactory: () => apiFor(client),
        secretStore: FakeSecretStore(),
      );
      await controller.redeem('tok', deviceId: 'my-iphone');
      expect(await controller.removeMember('mac-1'), isNull,
          reason: 'members cannot evict; only owners');
    });

    test('surfaces a 404 and keeps the prior membership', () async {
      final client = MockClient((req) async {
        if (req.url.path.endsWith('/remove')) {
          return http.Response(
            jsonEncode({'error': 'not_found', 'detail': 'device is not a member'}),
            404,
          );
        }
        return http.Response(
          jsonEncode({'channelId': 'north', 'deviceIds': ['owner-mac', 'mac-1']}),
          200,
        );
      });
      final controller = BoxController(
        apiFactory: () => apiFor(client),
        secretStore: FakeSecretStore(),
      )..enterAsOwner('north', deviceId: 'owner-mac', label: 'North');
      await controller.refreshMembers();

      final result = await controller.removeMember('mac-1');
      expect(result, isNull);
      expect(controller.error, contains('not_found'));
      expect(controller.members?.deviceIds, ['owner-mac', 'mac-1'],
          reason: 'a failed remove leaves the list untouched');
    });
  });
}
