import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/box_controller.dart';
import 'package:bard_pro/box/box_link.dart';
import 'package:bard_pro/box/box_screen.dart';
import 'package:bard_pro/box/create_box.dart';
import 'package:bard_pro/box/redeem.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_box_link.dart';
import 'support/fake_secret_store.dart';

/// Widget tests for the box onboarding screens. Structure + flow only (CLAUDE.md
/// §14: visual sign-off is the user's). The share sheet is injected so no native
/// channel is hit; the api is `MockClient`-backed.
void main() {
  BoxController controllerWith(MockClient client) => BoxController(
        apiFactory: ({tokenProvider}) => BardApi(
          routerBaseUrl: 'https://r.test',
          registryBaseUrl: 'https://reg.test',
          token: 'manager',
          httpClient: client,
          listTimeout: const Duration(milliseconds: 50),
          tokenProvider: tokenProvider,
        ),
        secretStore: FakeSecretStore(),
        deviceIdFactory: () => 'dev-fixed',
      );

  group('CreateBoxScreen', () {
    testWidgets('create button is disabled until a name is entered', (tester) async {
      final controller = controllerWith(
        MockClient((_) async => http.Response('{}', 200)),
      );
      await tester.pumpWidget(MaterialApp(home: CreateBoxScreen(controller: controller)));

      final button = tester.widget<FilledButton>(
        find.byKey(const Key('create-and-share-button')),
      );
      expect(button.onPressed, isNull);

      await tester.enterText(find.byKey(const Key('box-name-field')), 'North');
      await tester.pump();
      final enabled = tester.widget<FilledButton>(
        find.byKey(const Key('create-and-share-button')),
      );
      expect(enabled.onPressed, isNotNull);
    });

    testWidgets('creating a box shares the invite url and shows the tile', (tester) async {
      String? shared;
      final controller = controllerWith(
        MockClient((req) async {
          final path = req.url.path;
          if (path == '/devices/self-register') {
            return http.Response(
                jsonEncode({'device': {'deviceId': 'dev-fixed'}}), 200);
          }
          if (path == '/channels') {
            return http.Response(
                jsonEncode({'channel': {'channelId': 'North'}}), 200);
          }
          return http.Response(
            jsonEncode({
              'invite': {'inviteId': 'i', 'channelId': 'North'},
              'inviteToken': 'tok',
              'inviteUrl': 'bard://invite?invite=tok',
            }),
            200,
          );
        }),
      );
      await tester.pumpWidget(MaterialApp(
        home: CreateBoxScreen(
          controller: controller,
          onShare: (text, {subject}) async => shared = text,
        ),
      ));

      await tester.enterText(find.byKey(const Key('box-name-field')), 'North');
      await tester.pump();
      await tester.tap(find.byKey(const Key('create-and-share-button')));
      await tester.pumpAndSettle();

      expect(shared, 'bard://invite?invite=tok');
      expect(find.byKey(const Key('invite-link-tile')), findsOneWidget);
    });

    testWidgets('shows an error when create fails', (tester) async {
      final controller = controllerWith(
        MockClient(
          (_) async => http.Response(jsonEncode({'error': 'unauthorized'}), 401),
        ),
      );
      await tester.pumpWidget(MaterialApp(
        home: CreateBoxScreen(
          controller: controller,
          onShare: (text, {subject}) async {},
        ),
      ));
      await tester.enterText(find.byKey(const Key('box-name-field')), 'North');
      await tester.pump();
      await tester.tap(find.byKey(const Key('create-and-share-button')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('create-box-error')), findsOneWidget);
    });
  });

  group('RedeemScreen', () {
    testWidgets('joining a box from a token shows the success view', (tester) async {
      final controller = controllerWith(
        MockClient(
          (_) async => http.Response(
            jsonEncode({
              'device': {'deviceId': 'my-iphone'},
              'channelId': 'north',
            }),
            200,
          ),
        ),
      );
      await tester.pumpWidget(
        MaterialApp(home: RedeemScreen(controller: controller, token: 'tok')),
      );

      expect(find.byKey(const Key('device-name-field')), findsOneWidget);
      await tester.enterText(find.byKey(const Key('device-name-field')), 'My iPhone');
      await tester.tap(find.byKey(const Key('join-button')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('redeem-success')), findsOneWidget);
    });

    testWidgets('parses the token from a pasted link', (tester) async {
      final controller = controllerWith(
        MockClient(
          (_) async => http.Response(
            jsonEncode({
              'device': {'deviceId': 'd'},
              'channelId': 'c',
            }),
            200,
          ),
        ),
      );
      await tester.pumpWidget(MaterialApp(
        home: RedeemScreen(controller: controller, link: 'bard://invite?invite=tok-from-link'),
      ));
      // The join form is shown (token resolved from the link), not the error.
      expect(find.byKey(const Key('join-button')), findsOneWidget);
      expect(find.byKey(const Key('redeem-no-token')), findsNothing);
    });

    testWidgets('shows the missing-code state for a link without a token', (tester) async {
      final controller = controllerWith(
        MockClient((_) async => http.Response('{}', 200)),
      );
      await tester.pumpWidget(MaterialApp(
        home: RedeemScreen(controller: controller, link: 'bard://invite?nope=1'),
      ));
      expect(find.byKey(const Key('redeem-no-token')), findsOneWidget);
      expect(find.byKey(const Key('join-button')), findsNothing);
    });

    testWidgets('shows an error when redeem fails', (tester) async {
      final controller = controllerWith(
        MockClient(
          (_) async => http.Response(
            jsonEncode({'error': 'unauthorized', 'detail': 'invite has expired'}),
            401,
          ),
        ),
      );
      await tester.pumpWidget(
        MaterialApp(home: RedeemScreen(controller: controller, token: 'tok')),
      );
      await tester.tap(find.byKey(const Key('join-button')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('redeem-error')), findsOneWidget);
      expect(find.byKey(const Key('redeem-success')), findsNothing);
    });
  });

  group('BoxScreen owner management (E2)', () {
    /// A membership response for `GET /channels/{id}/members`, the body shared by
    /// the load and (for remove) the second turn.
    http.Response membersBody(List<String> ids) => http.Response(
          jsonEncode({'channelId': 'north', 'deviceIds': ids}),
          200,
        );

    /// Build an owner-context controller already in box 'north' as 'owner-mac'.
    /// [handler] backs every call (members load, invite mint, remove).
    BoxController ownerController(MockClient client) {
      return BoxController(
        apiFactory: ({tokenProvider}) => BardApi(
          routerBaseUrl: 'https://r.test',
          registryBaseUrl: 'https://reg.test',
          token: 'manager',
          httpClient: client,
          listTimeout: const Duration(milliseconds: 50),
          tokenProvider: tokenProvider,
        ),
        secretStore: FakeSecretStore(),
        deviceIdFactory: () => 'owner-mac',
      )..enterAsOwner('north', deviceId: 'owner-mac', label: 'North');
    }

    Future<void> pumpScreen(
      WidgetTester tester,
      BoxController controller, {
      ShareCallback? onShare,
    }) async {
      await tester.pumpWidget(MaterialApp(
        home: BoxScreen(
          controller: controller,
          onShare: onShare ?? (text, {subject}) async {},
        ),
      ));
      // Load the member list under the owner view.
      await controller.refreshMembers();
      await tester.pumpAndSettle();
    }

    testWidgets('owner sees Add people, Suspend, and Remove on other members',
        (tester) async {
      final controller = ownerController(
        MockClient((_) async => membersBody(['owner-mac', 'mac-1'])),
      );
      await pumpScreen(tester, controller);

      expect(find.byKey(const Key('add-people')), findsOneWidget);
      expect(find.byKey(const Key('suspend-member')), findsOneWidget);
      // Remove on the OTHER device, never on this device.
      expect(find.byKey(const Key('remove-member-mac-1')), findsOneWidget);
      expect(find.byKey(const Key('remove-member-owner-mac')), findsNothing);
    });

    testWidgets('Suspend is present but disabled (coming soon)', (tester) async {
      final controller = ownerController(
        MockClient((_) async => membersBody(['owner-mac'])),
      );
      await pumpScreen(tester, controller);

      final suspend = tester.widget<OutlinedButton>(
        find.byKey(const Key('suspend-member')),
      );
      expect(suspend.onPressed, isNull, reason: 'Suspend is wired to nothing');
      // The "coming soon" hint rides on a Tooltip wrapping the disabled button.
      final tooltip = tester.widget<Tooltip>(
        find.ancestor(
          of: find.byKey(const Key('suspend-member')),
          matching: find.byType(Tooltip),
        ),
      );
      expect(tooltip.message, 'Suspend is coming soon');
    });

    testWidgets('a non-owner (member) sees no management actions', (tester) async {
      // A member context: redeem (no-auth) yields a non-owner joined box.
      final controller = BoxController(
        apiFactory: ({tokenProvider}) => BardApi(
          routerBaseUrl: 'https://r.test',
          registryBaseUrl: 'https://reg.test',
          token: 'manager',
          httpClient: MockClient((req) async {
            if (req.url.path.endsWith('/redeem')) {
              return http.Response(
                jsonEncode({
                  'device': {'deviceId': 'my-iphone'},
                  'channelId': 'north',
                }),
                200,
              );
            }
            return membersBody(['my-iphone', 'mac-1']);
          }),
          listTimeout: const Duration(milliseconds: 50),
          tokenProvider: tokenProvider,
        ),
        secretStore: FakeSecretStore(),
        deviceIdFactory: () => 'my-iphone',
      );
      await controller.redeem('tok', label: 'My iPhone');
      await tester.pumpWidget(MaterialApp(home: BoxScreen(controller: controller)));
      await controller.refreshMembers();
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('add-people')), findsNothing);
      expect(find.byKey(const Key('suspend-member')), findsNothing);
      expect(find.byKey(const Key('remove-member-mac-1')), findsNothing);
    });

    testWidgets('Remove runs confirm → API → refresh, dropping the member',
        (tester) async {
      var removeCalls = 0;
      final controller = ownerController(
        MockClient((req) async {
          if (req.url.path.endsWith('/remove')) {
            removeCalls++;
            // The remove endpoint returns the UPDATED membership.
            return membersBody(['owner-mac']);
          }
          return membersBody(['owner-mac', 'mac-1']);
        }),
      );
      await pumpScreen(tester, controller);
      expect(find.byKey(const Key('member-mac-1')), findsOneWidget);

      await tester.tap(find.byKey(const Key('remove-member-mac-1')));
      await tester.pumpAndSettle();
      // Confirm dialog up; cancel first to prove it gates the call.
      expect(find.byKey(const Key('remove-confirm')), findsOneWidget);
      await tester.tap(find.byKey(const Key('remove-cancel')));
      await tester.pumpAndSettle();
      expect(removeCalls, 0, reason: 'cancel must not call the API');
      expect(find.byKey(const Key('member-mac-1')), findsOneWidget);

      // Now confirm: API called, list refreshes to the returned membership.
      await tester.tap(find.byKey(const Key('remove-member-mac-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('remove-confirm')));
      await tester.pumpAndSettle();
      expect(removeCalls, 1);
      expect(find.byKey(const Key('member-mac-1')), findsNothing);
      expect(find.byKey(const Key('member-owner-mac')), findsOneWidget);
    });

    testWidgets('Add people mints an invite and shares the link', (tester) async {
      String? shared;
      String? subjectSeen;
      final controller = ownerController(
        MockClient((req) async {
          if (req.url.path.endsWith('/invites')) {
            return http.Response(
              jsonEncode({
                'invite': {'inviteId': 'i', 'channelId': 'north'},
                'inviteToken': 'tok2',
                'inviteUrl': 'bard://invite?invite=tok2',
              }),
              200,
            );
          }
          return membersBody(['owner-mac']);
        }),
      );
      await pumpScreen(
        tester,
        controller,
        onShare: (text, {subject}) async {
          shared = text;
          subjectSeen = subject;
        },
      );

      await tester.tap(find.byKey(const Key('add-people')));
      await tester.pumpAndSettle();
      expect(shared, 'bard://invite?invite=tok2');
      expect(subjectSeen, contains('North'));
    });
  });

  group('BoxScreen ping (S6)', () {
    /// A redeem 200 body so the controller can enter a member box.
    http.Response redeemResp() => http.Response(
          jsonEncode({'device': {'deviceId': 'dev-fixed'}, 'channelId': 'north'}),
          200,
        );

    /// A member controller in box 'north' with a fake receive link over
    /// [transport]; [client] backs the HTTP calls (redeem + ping). The redeem +
    /// link handshake run under [tester.runAsync] so the real async (MockClient
    /// + the link's `Future.delayed` polling) completes inside the widget test's
    /// fake-async zone (CLAUDE.md §9 keeps it off real sockets).
    Future<BoxController> memberInBox(
      WidgetTester tester,
      MockClient client,
      FakeTransport transport,
    ) async {
      final controller = BoxController(
        apiFactory: ({tokenProvider}) => BardApi(
          routerBaseUrl: 'https://r.test',
          registryBaseUrl: 'https://reg.test',
          token: 'manager',
          httpClient: client,
          listTimeout: const Duration(milliseconds: 50),
          messageTimeout: const Duration(milliseconds: 50),
          tokenProvider: tokenProvider,
        ),
        secretStore: FakeSecretStore(),
        deviceIdFactory: () => 'dev-fixed',
        linkFactory: ({required tokenProvider}) => BoxLink(
          routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
          tokenProvider: tokenProvider,
          transport: transport,
          delay: (_) async {},
        ),
      );
      await tester.runAsync(() async {
        await controller.redeem('tok'); // opens the link
        await transport.connected.first;
      });
      return controller;
    }

    testWidgets('Ping button POSTs to the ping endpoint and confirms',
        (tester) async {
      final transport = FakeTransport();
      String? pingUrl;
      String? pingAuth;
      final client = MockClient((req) async {
        if (req.url.path.endsWith('/redeem')) return redeemResp();
        pingUrl = req.url.toString();
        pingAuth = req.headers['Authorization'];
        return http.Response(
          jsonEncode({'delivered': ['mac-1'], 'offline': <String>[]}),
          200,
        );
      });
      final controller = await memberInBox(tester, client, transport);
      await tester.pumpWidget(MaterialApp(home: BoxScreen(controller: controller)));
      await tester.pump();

      expect(find.byKey(const Key('ping-box')), findsOneWidget);
      // Tapping fires the widget's async `_ping` handler (POST is real async via
      // MockClient); flush it under runAsync, then pump to build the SnackBar.
      await tester.tap(find.byKey(const Key('ping-box')));
      await tester.runAsync(() => Future<void>.delayed(Duration.zero));
      await tester.pump();

      expect(pingUrl, 'https://r.test/channels/north/ping');
      expect(pingAuth, startsWith('Bearer '));
      expect(pingAuth, isNot(contains('manager')));
      // The sent-confirmation banner appears.
      expect(find.byKey(const Key('ping-sent')), findsOneWidget);

      controller.dispose();
    });

    testWidgets('a received box.ping shows the in-app banner', (tester) async {
      final transport = FakeTransport();
      final client = MockClient((req) async {
        if (req.url.path.endsWith('/redeem')) return redeemResp();
        return http.Response('{}', 404);
      });
      final controller = await memberInBox(tester, client, transport);
      await tester.pumpWidget(MaterialApp(home: BoxScreen(controller: controller)));
      await tester.pump();

      // A peer pings: the frame arrives over the live link. The emit + stream
      // delivery is real async, so flush it under runAsync, then pump to build
      // the SnackBar.
      await tester.runAsync(() async {
        transport.connections.last.emit(
          '{"type":"box.ping","channelId":"north","from":"pixel-9",'
          '"ts":"2026-06-18T12:00:00Z"}',
        );
        await Future<void>.delayed(Duration.zero);
      });
      await tester.pump(); // build the SnackBar

      expect(find.byKey(const Key('ping-received')), findsOneWidget);
      expect(find.text('Ping from pixel-9'), findsOneWidget);

      controller.dispose();
    });
  });
}
