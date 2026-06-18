import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/box_controller.dart';
import 'package:bard_pro/box/box_link.dart';
import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_box_link.dart';
import 'support/fake_secret_store.dart';

/// S6 controller wiring: the [BoxController] sends pings over the device token
/// and surfaces RECEIVED pings to the UI. Driven against a `MockClient` api and
/// a FAKE link transport — no network, no socket (CLAUDE.md §9).
void main() {
  /// A redeem 200 body.
  String redeemBody({String channelId = 'north'}) => jsonEncode({
        'device': {'deviceId': 'dev-fixed'},
        'channelId': channelId,
      });

  /// A `box.ping` frame (FROZEN contract).
  String pingFrame({String channelId = 'north', String from = 'mac-1'}) =>
      '{"type":"box.ping","channelId":"$channelId","from":"$from",'
      '"ts":"2026-06-18T12:00:00Z"}';

  /// Build a controller bound to [client] with a fake link over [transport] so
  /// the receive path runs in-process. The link's token provider mints the real
  /// device token from the stored identity (so we can assert it self-signs).
  BoxController controllerFor(
    MockClient client, {
    required FakeTransport transport,
    FakeSecretStore? store,
  }) {
    final s = store ?? FakeSecretStore();
    return BoxController(
      apiFactory: ({tokenProvider}) => BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: 'BAKED-SHOULD-NOT-BE-USED',
        httpClient: client,
        listTimeout: const Duration(milliseconds: 50),
        messageTimeout: const Duration(milliseconds: 50),
        tokenProvider: tokenProvider,
      ),
      secretStore: s,
      deviceIdFactory: () => 'dev-fixed',
      linkFactory: ({required tokenProvider}) => BoxLink(
        routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
        tokenProvider: tokenProvider,
        transport: transport,
        delay: (_) async {},
      ),
    );
  }

  group('pingBox (POST /channels/{id}/ping, device token)', () {
    test('pings the joined box with the DEVICE token and returns the split',
        () async {
      final transport = FakeTransport();
      String? seenAuth;
      late String seenUrl;
      final client = MockClient((req) async {
        final path = req.url.path;
        if (path.endsWith('/redeem')) {
          return http.Response(redeemBody(), 200);
        }
        // The ping call.
        seenUrl = req.url.toString();
        seenAuth = req.headers['Authorization'];
        return http.Response(
          jsonEncode({'delivered': ['mac-1'], 'offline': <String>[]}),
          200,
        );
      });
      final store = FakeSecretStore();
      final controller = controllerFor(client, transport: transport, store: store);

      await controller.redeem('tok', label: 'My iPhone');
      final result = await controller.pingBox();

      expect(result, isNotNull);
      expect(result!.delivered, ['mac-1']);
      expect(seenUrl, 'https://r.test/channels/north/ping');
      expect(seenAuth, startsWith('Bearer '));
      expect(seenAuth, isNot(contains('BAKED-SHOULD-NOT-BE-USED')));
      // The bearer is THIS device's self-signed EdDSA token.
      final stored = await store.readDeviceIdentity();
      final pub = base64.decode(stored!.privateKey).sublist(32, 64);
      final jwt =
          JWT.verify(seenAuth!.substring('Bearer '.length), EdDSAPublicKey(pub));
      expect(jwt.subject, 'dev-fixed');
      expect(jwt.header?['alg'], 'EdDSA');

      controller.dispose();
    });

    test('pingBox is a no-op (null) before any box is joined', () async {
      final transport = FakeTransport();
      final controller = controllerFor(
        MockClient((_) async => http.Response('{}', 200)),
        transport: transport,
      );
      expect(await controller.pingBox(), isNull);
      controller.dispose();
    });

    test('surfaces a ping failure via error and returns null', () async {
      final transport = FakeTransport();
      final client = MockClient((req) async {
        if (req.url.path.endsWith('/redeem')) {
          return http.Response(redeemBody(), 200);
        }
        return http.Response(
          jsonEncode({'error': 'forbidden', 'detail': 'not a member'}),
          403,
        );
      });
      final controller = controllerFor(client, transport: transport);
      await controller.redeem('tok');
      expect(await controller.pingBox(), isNull);
      expect(controller.error, contains('forbidden'));
      controller.dispose();
    });
  });

  group('receiving pings over the link', () {
    test('a box.ping frame surfaces on lastPing + pings and notifies', () async {
      final transport = FakeTransport();
      final client = MockClient(
        (_) async => http.Response(redeemBody(), 200),
      );
      final controller = controllerFor(client, transport: transport);

      final streamed = <BoxPing>[];
      controller.pings.listen(streamed.add);
      var notifications = 0;
      controller.addListener(() => notifications++);

      await controller.redeem('tok'); // opens the link
      await transport.connected.first;
      final before = notifications;

      transport.connections.last.emit(pingFrame(from: 'pixel-9'));
      await Future<void>.delayed(Duration.zero);

      expect(controller.lastPing?.from, 'pixel-9');
      expect(streamed.single.from, 'pixel-9');
      expect(notifications, greaterThan(before),
          reason: 'a received ping rebuilds the box screen');

      controller.dispose();
    });

    test('ignores a ping for a DIFFERENT channel', () async {
      final transport = FakeTransport();
      final controller = controllerFor(
        MockClient((_) async => http.Response(redeemBody(), 200)),
        transport: transport,
      );
      await controller.redeem('tok');
      await transport.connected.first;

      transport.connections.last.emit(pingFrame(channelId: 'south'));
      await Future<void>.delayed(Duration.zero);
      expect(controller.lastPing, isNull,
          reason: 'pings for another box are not surfaced here');
      controller.dispose();
    });

    test('clearLastPing resets the banner snapshot', () async {
      final transport = FakeTransport();
      final controller = controllerFor(
        MockClient((_) async => http.Response(redeemBody(), 200)),
        transport: transport,
      );
      await controller.redeem('tok');
      await transport.connected.first;
      transport.connections.last.emit(pingFrame());
      await Future<void>.delayed(Duration.zero);
      expect(controller.lastPing, isNotNull);

      controller.clearLastPing();
      expect(controller.lastPing, isNull);
      controller.clearLastPing(); // idempotent no-op
      controller.dispose();
    });

    test('leaveBox closes the link and forgets the box', () async {
      final transport = FakeTransport();
      final controller = controllerFor(
        MockClient((_) async => http.Response(redeemBody(), 200)),
        transport: transport,
      );
      await controller.redeem('tok');
      await transport.connected.first;
      expect(controller.joinedBox, isNotNull);

      controller.leaveBox();
      await Future<void>.delayed(Duration.zero);
      expect(controller.joinedBox, isNull);
      expect(transport.connections.last.closed, isTrue);
      controller.dispose();
    });

    test('re-entering a box opens a fresh link (no leak across entries)',
        () async {
      final transport = FakeTransport();
      final controller = controllerFor(
        MockClient((_) async => http.Response(redeemBody(), 200)),
        transport: transport,
      );
      await controller.redeem('tok');
      await transport.connected.first;
      // enterAsOwner re-enters → the prior link is closed, a new one opens.
      controller.enterAsOwner('north', deviceId: 'dev-fixed', label: 'North');
      await transport.connected.elementAt(1);
      expect(transport.connections, hasLength(2));
      expect(transport.connections.first.closed, isTrue);
      controller.dispose();
    });
  });
}
