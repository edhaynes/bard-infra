import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/box_models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Contract tests for the box-onboarding [BardApi] methods against the FROZEN
/// invite contract (contracts/invite.schema.json). All requests go through a
/// `MockClient` — no real network (CLAUDE.md §9). Covers the wire shape of each
/// request, the success parse, and the failure branches (envelope + malformed).
void main() {
  const router = 'https://router.test:8443';
  const registry = 'https://registry.test:8081';
  const token = 'manager-jwt';

  BardApi apiWith(MockClient client) => BardApi(
        routerBaseUrl: router,
        registryBaseUrl: registry,
        token: token,
        httpClient: client,
        listTimeout: const Duration(milliseconds: 50),
      );

  /// A device-token-mode api whose bearer is the supplied static [deviceToken].
  BardApi deviceApiWith(MockClient client, {String deviceToken = 'dev-jwt'}) =>
      BardApi(
        routerBaseUrl: router,
        registryBaseUrl: registry,
        token: 'BAKED-SHOULD-NOT-BE-USED',
        httpClient: client,
        listTimeout: const Duration(milliseconds: 50),
        tokenProvider: () => deviceToken,
      );

  group('selfRegister (POST /devices/self-register, no-auth)', () {
    test('posts deviceId + publicKey without an Authorization header', () async {
      String? seenAuth;
      Map<String, dynamic>? seenBody;
      final client = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.toString(), '$registry/devices/self-register');
        seenAuth = req.headers['Authorization'];
        seenBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'device': {'deviceId': 'dev-1'}}), 200);
      });
      await apiWith(client).selfRegister(deviceId: 'dev-1', publicKey: 'pub==');
      expect(seenAuth, isNull, reason: 'self-register bootstraps the identity');
      expect(seenBody, {'deviceId': 'dev-1', 'publicKey': 'pub=='});
    });

    test('throws on a non-200', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'error': 'bad_request'}), 400),
      );
      await expectLater(
        apiWith(client).selfRegister(deviceId: 'd', publicKey: 'p'),
        throwsA(predicate<BardApiException>(
            (e) => e.kind == ApiFailureKind.errorEnvelope)),
      );
    });
  });

  group('createChannel (POST /channels, device-token auth)', () {
    test('creates a channel with the DEVICE token and returns the channel id',
        () async {
      String? seenAuth;
      Map<String, dynamic>? seenBody;
      final client = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.toString(), '$registry/channels');
        seenAuth = req.headers['Authorization'];
        seenBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(
            jsonEncode({'channel': {'channelId': 'north'}}), 200);
      });
      final id =
          await deviceApiWith(client).createChannel('north', label: 'North');
      expect(id, 'north');
      expect(seenAuth, 'Bearer dev-jwt',
          reason: 'owner create uses the device token, not BARD_AUTH_TOKEN');
      expect(seenBody, {'channelId': 'north', 'label': 'North'});
    });

    test('omits label when not supplied', () async {
      Map<String, dynamic>? seenBody;
      final client = MockClient((req) async {
        seenBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(
            jsonEncode({'channel': {'channelId': 'c'}}), 200);
      });
      await deviceApiWith(client).createChannel('c');
      expect(seenBody, {'channelId': 'c'});
    });

    test('throws on a non-200', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'error': 'unauthorized'}), 401),
      );
      await expectLater(
        deviceApiWith(client).createChannel('c'),
        throwsA(isA<BardApiException>()),
      );
    });

    test('throws malformed when channel is not an object', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'channel': 'x'}), 200),
      );
      await expectLater(
        deviceApiWith(client).createChannel('c'),
        throwsA(predicate<BardApiException>(
            (e) => e.kind == ApiFailureKind.malformed)),
      );
    });

    test('throws malformed when channel.channelId is missing', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'channel': {}}), 200),
      );
      await expectLater(
        deviceApiWith(client).createChannel('c'),
        throwsA(predicate<BardApiException>(
            (e) => e.kind == ApiFailureKind.malformed)),
      );
    });
  });

  group('createInvite (POST /invites, manager-auth)', () {
    test('sends channelId/label/ttl and parses the CreateInviteResponse', () async {
      late Map<String, dynamic> sentBody;
      final client = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.toString(), '$registry/invites');
        expect(req.headers['Authorization'], 'Bearer $token');
        sentBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'invite': {
              'inviteId': 'inv-1',
              'channelId': 'north-crew',
              'createdAt': '2026-06-17T00:00:00Z',
              'expiresAt': '2026-06-17T01:00:00Z',
              'redeemed': false,
              'redeemedAt': null,
              'redeemedBy': null,
              'label': 'North site crew',
            },
            'inviteToken': 'tok-abc',
            'inviteUrl': 'bard://invite?invite=tok-abc',
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final result = await apiWith(client).createInvite(
        'north-crew',
        label: 'North site crew',
        ttlSeconds: 3600,
      );

      expect(sentBody['channelId'], 'north-crew');
      expect(sentBody['label'], 'North site crew');
      expect(sentBody['ttlSeconds'], 3600);
      expect(result.inviteId, 'inv-1');
      expect(result.channelId, 'north-crew');
      expect(result.inviteToken, 'tok-abc');
      expect(result.inviteUrl, 'bard://invite?invite=tok-abc');
    });

    test('omits label/ttl when not given', () async {
      late Map<String, dynamic> sentBody;
      final client = MockClient((req) async {
        sentBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'invite': {'inviteId': 'i', 'channelId': 'c'},
            'inviteToken': 't',
            'inviteUrl': 'u',
          }),
          200,
        );
      });
      await apiWith(client).createInvite('c');
      expect(sentBody.containsKey('label'), isFalse);
      expect(sentBody.containsKey('ttlSeconds'), isFalse);
    });

    test('throws the error envelope on a 401 unauthorized', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'error': 'unauthorized'}), 401),
      );
      await expectLater(
        apiWith(client).createInvite('c'),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.errorEnvelope && e.error?.code == 'unauthorized',
        )),
      );
    });

    test('throws malformed when invite is missing required fields', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'invite': {'channelId': 'c'}, 'inviteToken': 't', 'inviteUrl': 'u'}),
          200,
        ),
      );
      await expectLater(
        apiWith(client).createInvite('c'),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });
  });

  group('redeemInvite (POST /invites/{token}/redeem, NO auth)', () {
    // A representative base64-encoded 32-byte Ed25519 public key.
    final publicKey = base64.encode(List<int>.filled(32, 9));

    test('omits Authorization, sends publicKey, path-encodes token, parses body',
        () async {
      String? auth;
      late Map<String, dynamic> sentBody;
      final client = MockClient((req) async {
        expect(req.method, 'POST');
        // Token with a slash must be percent-encoded into a single path segment.
        expect(req.url.toString(), '$registry/invites/tok%2Fwith-slash/redeem');
        auth = req.headers['Authorization'];
        sentBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'device': {'deviceId': 'my-iphone', 'state': 'active'},
            'channelId': 'north-crew',
          }),
          200,
        );
      });

      final result = await apiWith(client).redeemInvite(
        'tok/with-slash',
        deviceId: 'my-iphone',
        publicKey: publicKey,
        label: 'My iPhone',
      );

      expect(auth, isNull, reason: 'redeem MUST NOT send a bearer');
      expect(sentBody['deviceId'], 'my-iphone');
      expect(sentBody['publicKey'], publicKey,
          reason: 'the device registers its own public key');
      expect(sentBody['label'], 'My iPhone');
      expect(result.deviceId, 'my-iphone');
      expect(result.channelId, 'north-crew');
    });

    test('maps a 401 (expired/used/unknown invite) to the error envelope', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'error': 'unauthorized', 'detail': 'invite has expired'}),
          401,
        ),
      );
      await expectLater(
        apiWith(client).redeemInvite('t', deviceId: 'd', publicKey: publicKey),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.errorEnvelope && e.error?.code == 'unauthorized',
        )),
      );
    });

    test('throws malformed when channelId is missing', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'device': {'deviceId': 'd'}}),
          200,
        ),
      );
      await expectLater(
        apiWith(client).redeemInvite('t', deviceId: 'd', publicKey: publicKey),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });
  });

  group('channelMembers (GET /channels/{id}/members, manager-auth)', () {
    test('parses the ChannelMembership projection', () async {
      final client = MockClient((req) async {
        expect(req.method, 'GET');
        expect(req.url.toString(), '$registry/channels/north-crew/members');
        expect(req.headers['Authorization'], 'Bearer $token');
        return http.Response(
          jsonEncode({
            'channelId': 'north-crew',
            'deviceIds': ['a', 'b', 'c'],
          }),
          200,
        );
      });
      final members = await apiWith(client).channelMembers('north-crew');
      expect(members.channelId, 'north-crew');
      expect(members.deviceIds, ['a', 'b', 'c']);
    });

    test('parses an empty channel', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'channelId': 'c', 'deviceIds': <String>[]}),
          200,
        ),
      );
      final members = await apiWith(client).channelMembers('c');
      expect(members.deviceIds, isEmpty);
    });

    test('throws malformed when deviceIds is not an array', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'channelId': 'c', 'deviceIds': 'nope'}),
          200,
        ),
      );
      await expectLater(
        apiWith(client).channelMembers('c'),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });

    test('throws malformed when a deviceId element is not a string', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'channelId': 'c', 'deviceIds': [1, 2]}),
          200,
        ),
      );
      await expectLater(
        apiWith(client).channelMembers('c'),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });
  });

  group('removeMember (POST /channels/{id}/members/{deviceId}/remove)', () {
    test('posts to the remove path with manager-auth and parses the updated membership',
        () async {
      String? method;
      final client = MockClient((req) async {
        method = req.method;
        expect(req.url.toString(), '$registry/channels/north-crew/members/mac-1/remove');
        expect(req.headers['Authorization'], 'Bearer $token');
        return http.Response(
          jsonEncode({
            'channelId': 'north-crew',
            'deviceIds': ['my-iphone'],
          }),
          200,
        );
      });
      final members = await apiWith(client).removeMember('north-crew', 'mac-1');
      expect(method, 'POST');
      expect(members.channelId, 'north-crew');
      expect(members.deviceIds, ['my-iphone']);
    });

    test('percent-encodes both path segments', () async {
      final client = MockClient((req) async {
        expect(
          req.url.toString(),
          '$registry/channels/north%2Fcrew/members/mac%2F1/remove',
        );
        return http.Response(
          jsonEncode({'channelId': 'north/crew', 'deviceIds': <String>[]}),
          200,
        );
      });
      await apiWith(client).removeMember('north/crew', 'mac/1');
    });

    test('maps a 404 (not a member) to the error envelope', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'error': 'not_found', 'detail': 'device is not a member'}),
          404,
        ),
      );
      await expectLater(
        apiWith(client).removeMember('c', 'gone'),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.errorEnvelope && e.error?.code == 'not_found',
        )),
      );
    });

    test('maps a bare 404 (no envelope) to an httpStatus failure', () async {
      final client = MockClient((_) async => http.Response('not found', 404));
      await expectLater(
        apiWith(client).removeMember('c', 'gone'),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.httpStatus && e.statusCode == 404,
        )),
      );
    });

    test('throws malformed when the updated membership is the wrong shape', () async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'channelId': 'c'}), 200),
      );
      await expectLater(
        apiWith(client).removeMember('c', 'd'),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });
  });

  group('per-device-token mode (tokenProvider)', () {
    test('presents the freshly-minted device token as the bearer', () async {
      var calls = 0;
      String? seenAuth;
      final client = MockClient((req) async {
        seenAuth = req.headers['Authorization'];
        return http.Response(
          jsonEncode({'channelId': 'c', 'deviceIds': <String>[]}),
          200,
        );
      });
      final api = BardApi(
        routerBaseUrl: router,
        registryBaseUrl: registry,
        token: 'static-should-not-be-used',
        httpClient: client,
        tokenProvider: () => 'device-token-${++calls}',
      );
      await api.channelMembers('c');
      expect(seenAuth, 'Bearer device-token-1');
      await api.channelMembers('c');
      expect(seenAuth, 'Bearer device-token-2', reason: 'minted fresh per call');
    });
  });

  group('box model parsing edge cases', () {
    test('InviteResult rejects a non-object invite', () {
      expect(
        () => InviteResult.fromJson({'invite': 'x', 'inviteToken': 't', 'inviteUrl': 'u'}),
        throwsA(isA<BardApiException>()),
      );
    });

    test('RedeemResult rejects a non-object device', () {
      expect(
        () => RedeemResult.fromJson({'device': 1, 'channelId': 'c'}),
        throwsA(isA<BardApiException>()),
      );
    });

    test('ChannelMembers rejects a missing channelId', () {
      expect(
        () => ChannelMembers.fromJson({'deviceIds': <String>[]}),
        throwsA(isA<BardApiException>()),
      );
    });
  });
}
