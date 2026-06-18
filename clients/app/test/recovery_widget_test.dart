import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/box/box_controller.dart';
import 'package:bard_pro/box/box_screen.dart';
import 'package:bard_pro/box/device_identity.dart';
import 'package:bard_pro/box/omg_screen.dart';
import 'package:bard_pro/box/recovery_controller.dart';
import 'package:bard_pro/box/recovery_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_secret_store.dart';
import 'support/fake_seed_wrapper.dart';
import 'support/fixed_identity.dart';

/// Widget tests for the S7 recovery UI (ADR-0016 §5): the OMG one-screen
/// (show-once + wipe), the escrow-setup flow, the recover flow, and the Box
/// onboarding entry points. No platform channels (FakeSecretStore, injected
/// clipboard) and no real sockets (httpClient injected) — CLAUDE.md §9.
///
/// These bind a [FakeSeedWrapper] (a trivial, synchronous wrap) rather than the
/// real Argon2id [SeedWrapper], whose isolate-backed KDF does not complete in
/// the widget-test fake-async zone. The real crypto round-trips are covered by
/// `seed_recovery_test.dart` / `recovery_test.dart`; here we test UI wiring.
void main() {
  const wrapper = FakeSeedWrapper();

  BoxApiFactory apiFactory(MockClient client) => ({tokenProvider}) => BardApi(
        routerBaseUrl: 'https://r.test',
        registryBaseUrl: 'https://reg.test',
        token: 'baked',
        httpClient: client,
        listTimeout: const Duration(milliseconds: 100),
        tokenProvider: tokenProvider,
      );

  /// Tap [key], then let the controller's async (the MockClient response) run to
  /// completion under [tester.runAsync] while polling `busy` — `pumpAndSettle`
  /// alone hangs on the in-flight spinner's animation while the call is pending.
  Future<void> tapAndSettle(
      WidgetTester tester, Key key, bool Function() busy) async {
    await tester.tap(find.byKey(key));
    await tester.pump(); // kick off the future + show the spinner
    await tester.runAsync(() async {
      var guard = 0;
      while (busy() && guard++ < 500) {
        await Future<void>.delayed(const Duration(milliseconds: 5));
      }
    });
    await tester.pumpAndSettle(); // busy is false now → settles cleanly
  }

  RecoveryController recoveryWith(
    MockClient client, {
    FakeSecretStore? store,
    SeedFactory? seedFactory,
    String Function()? omgGenerator,
  }) =>
      RecoveryController(
        apiFactory: apiFactory(client),
        identity: DeviceIdentity(
          secretStore: store ?? FakeSecretStore(),
          seedFactory: seedFactory ?? fixtureSeedFactory,
        ),
        wrapper: wrapper,
        omgGenerator: omgGenerator ?? () => fixtureOmgCode,
      );

  group('OmgScreen (show once + wipe)', () {
    testWidgets('shows the code, copies it, and gates Done behind the checkbox',
        (tester) async {
      String? copied;
      var confirmed = 0;
      await tester.pumpWidget(MaterialApp(
        home: OmgScreen(
          code: fixtureOmgCode,
          onConfirmed: () => confirmed++,
          onCopy: (t) async => copied = t,
        ),
      ));

      // The code is shown.
      expect(find.text(fixtureOmgCode), findsOneWidget);

      // Done is disabled until the user confirms they saved it.
      final doneBefore = tester.widget<FilledButton>(find.byKey(const Key('omg-confirm')));
      expect(doneBefore.onPressed, isNull);

      // Copy works.
      await tester.tap(find.byKey(const Key('omg-copy')));
      await tester.pump();
      expect(copied, fixtureOmgCode);

      // Tick the checkbox → Done enables.
      await tester.tap(find.byKey(const Key('omg-saved-check')));
      await tester.pump();
      final doneAfter = tester.widget<FilledButton>(find.byKey(const Key('omg-confirm')));
      expect(doneAfter.onPressed, isNotNull);

      // Confirm fires onConfirmed and wipes the on-screen code.
      await tester.tap(find.byKey(const Key('omg-confirm')));
      await tester.pump();
      expect(confirmed, 1);
      expect(find.text(fixtureOmgCode), findsNothing,
          reason: 'the code is wiped from the widget after confirm');
    });

    testWidgets('the default copy hook writes the code to the clipboard',
        (tester) async {
      // Exercises the production _copyToClipboard (no injected onCopy). The
      // flutter_test binding mocks the Clipboard SystemChannel, so no real
      // platform call is made.
      final clipboard = <MethodCall>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') clipboard.add(call);
          return null;
        },
      );
      await tester.pumpWidget(MaterialApp(
        home: OmgScreen(code: fixtureOmgCode, onConfirmed: () {}),
      ));
      await tester.tap(find.byKey(const Key('omg-copy')));
      await tester.pump();
      expect(clipboard, hasLength(1));
      expect(
        (clipboard.first.arguments as Map)['text'],
        fixtureOmgCode,
      );
    });
  });

  group('EscrowSetupScreen (first-run)', () {
    testWidgets('submit → escrow → OMG screen → Done finishes the flow',
        (tester) async {
      final store = FakeSecretStore();
      var escrowed = false;
      final client = MockClient((req) async {
        expect(req.url.path, '/recovery/escrow');
        escrowed = true;
        return http.Response('{}', 200);
      });
      var done = 0;
      final controller = recoveryWith(client, store: store);
      await tester.pumpWidget(MaterialApp(
        home: EscrowSetupScreen(controller: controller, onDone: () => done++),
      ));

      // Submit is disabled until both fields are filled.
      expect(
        tester.widget<FilledButton>(find.byKey(const Key('escrow-submit'))).onPressed,
        isNull,
      );
      await tester.enterText(find.byKey(const Key('handle-field')), 'ada@example.com');
      await tester.enterText(find.byKey(const Key('password-field')), fixtureSecretString);
      await tester.pump();
      await tapAndSettle(tester, const Key('escrow-submit'), () => controller.busy);

      // The escrow happened and the OMG screen is shown.
      expect(escrowed, isTrue);
      expect(find.byKey(const Key('omg-code')), findsOneWidget);
      expect(find.text(fixtureOmgCode), findsOneWidget);

      // Confirm on the OMG screen → onDone fires, OMG screen pops.
      await tester.tap(find.byKey(const Key('omg-saved-check')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('omg-confirm')));
      await tester.pumpAndSettle();
      expect(done, 1);
    });

    testWidgets('shows an error when escrow fails', (tester) async {
      final client = MockClient(
        (_) async => http.Response(jsonEncode({'error': 'conflict'}), 409),
      );
      final controller = recoveryWith(client);
      await tester.pumpWidget(MaterialApp(home: EscrowSetupScreen(controller: controller)));
      await tester.enterText(find.byKey(const Key('handle-field')), 'h');
      await tester.enterText(find.byKey(const Key('password-field')), 'p');
      await tester.pump();
      await tapAndSettle(tester, const Key('escrow-submit'), () => controller.busy);
      expect(find.byKey(const Key('escrow-error')), findsOneWidget);
      expect(find.byKey(const Key('omg-code')), findsNothing);
    });

    testWidgets('pressing Done on the password field submits (onSubmitted)',
        (tester) async {
      var escrowed = false;
      final controller = recoveryWith(
        MockClient((_) async {
          escrowed = true;
          return http.Response('{}', 200);
        }),
      );
      await tester.pumpWidget(
          MaterialApp(home: EscrowSetupScreen(controller: controller)));
      await tester.enterText(find.byKey(const Key('handle-field')), 'ada@example.com');
      await tester.enterText(
          find.byKey(const Key('password-field')), fixtureSecretString);
      await tester.pump();
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      await tester.runAsync(() async {
        var g = 0;
        while (controller.busy && g++ < 500) {
          await Future<void>.delayed(const Duration(milliseconds: 5));
        }
      });
      await tester.pumpAndSettle();
      expect(escrowed, isTrue);
      expect(find.byKey(const Key('omg-code')), findsOneWidget);
    });
  });

  group('RecoverScreen (fresh install)', () {
    /// An escrow GET body wrapping the fixture seed under [password]/[omg].
    Future<String> escrowJson({required String password, required String omg}) async {
      const w = wrapper;
      return jsonEncode({
        'publicKey': fixturePublicKeyBase64,
        'wraps': {
          'password': await w.wrap(seed: fixtureSeed, secret: password),
          'omg': await w.wrap(seed: fixtureSeed, secret: omg),
        },
      });
    }

    testWidgets('recovers by password and shows the success view', (tester) async {
      final body = await escrowJson(password: fixtureSecretString, omg: fixtureOmgSecret);
      final store = FakeSecretStore();
      final client = MockClient((req) async {
        if (req.url.path.startsWith('/recovery/escrow/')) {
          return http.Response(body, 200);
        }
        return http.Response(jsonEncode({'device': {'deviceId': 'x'}}), 200);
      });
      final controller = RecoveryController(
        apiFactory: apiFactory(client),
        identity: DeviceIdentity(secretStore: store),
        wrapper: wrapper,
      );
      await tester.pumpWidget(MaterialApp(home: RecoverScreen(controller: controller)));

      await tester.enterText(
          find.byKey(const Key('recover-handle-field')), 'ada@example.com');
      await tester.enterText(
          find.byKey(const Key('recover-secret-field')), fixtureSecretString);
      await tester.pump();
      await tapAndSettle(tester, const Key('recover-submit'), () => controller.busy);

      expect(find.byKey(const Key('recover-success')), findsOneWidget);
      expect((await store.readDeviceIdentity())?.deviceId, fixtureDeviceId);
    });

    testWidgets('recovers by OMG code after switching the mode toggle',
        (tester) async {
      final body = await escrowJson(password: fixtureSecretString, omg: fixtureOmgSecret);
      final store = FakeSecretStore();
      final client = MockClient((req) async {
        if (req.url.path.startsWith('/recovery/escrow/')) {
          return http.Response(body, 200);
        }
        return http.Response(jsonEncode({'device': {'deviceId': 'x'}}), 200);
      });
      final controller = RecoveryController(
        apiFactory: apiFactory(client),
        identity: DeviceIdentity(secretStore: store),
        wrapper: wrapper,
      );
      await tester.pumpWidget(MaterialApp(home: RecoverScreen(controller: controller)));

      // Switch to "Recovery code" mode.
      await tester.tap(find.text('Recovery code'));
      await tester.pump();
      await tester.enterText(
          find.byKey(const Key('recover-handle-field')), 'ada@example.com');
      await tester.enterText(
          find.byKey(const Key('recover-secret-field')), fixtureOmgCode);
      await tester.pump();
      await tapAndSettle(tester, const Key('recover-submit'), () => controller.busy);
      expect(find.byKey(const Key('recover-success')), findsOneWidget);
    });

    testWidgets('shows an error for a wrong password', (tester) async {
      final body = await escrowJson(password: fixtureSecretString, omg: fixtureOmgSecret);
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient((_) async => http.Response(body, 200))),
        identity: DeviceIdentity(secretStore: FakeSecretStore()),
        wrapper: wrapper,
      );
      await tester.pumpWidget(MaterialApp(home: RecoverScreen(controller: controller)));
      await tester.enterText(
          find.byKey(const Key('recover-handle-field')), 'ada@example.com');
      await tester.enterText(
          find.byKey(const Key('recover-secret-field')), 'wrong-password');
      await tester.pump();
      await tapAndSettle(tester, const Key('recover-submit'), () => controller.busy);
      expect(find.byKey(const Key('recover-error')), findsOneWidget);
      expect(find.byKey(const Key('recover-success')), findsNothing);
    });

    testWidgets('pressing Done on the secret field submits (onSubmitted)',
        (tester) async {
      final body = await escrowJson(password: fixtureSecretString, omg: 'X');
      final store = FakeSecretStore();
      final controller = RecoveryController(
        apiFactory: apiFactory(MockClient((req) async {
          if (req.url.path.startsWith('/recovery/escrow/')) {
            return http.Response(body, 200);
          }
          return http.Response(jsonEncode({'device': {'deviceId': 'x'}}), 200);
        })),
        identity: DeviceIdentity(secretStore: store),
        wrapper: wrapper,
      );
      await tester.pumpWidget(MaterialApp(home: RecoverScreen(controller: controller)));
      await tester.enterText(
          find.byKey(const Key('recover-handle-field')), 'ada@example.com');
      await tester.enterText(
          find.byKey(const Key('recover-secret-field')), fixtureSecretString);
      await tester.pump();
      // Submit via the keyboard "done" action (onSubmitted), not the button.
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      await tester.runAsync(() async {
        var g = 0;
        while (controller.busy && g++ < 500) {
          await Future<void>.delayed(const Duration(milliseconds: 5));
        }
      });
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('recover-success')), findsOneWidget);
    });
  });

  group('BoxScreen onboarding recovery entry points', () {
    BoxController boxControllerWith(MockClient client) => BoxController(
          apiFactory: apiFactory(client),
          secretStore: FakeSecretStore(),
          seedFactory: fixtureSeedFactory,
        );

    testWidgets('shows Set up recovery + Recover when a recoveryController is given',
        (tester) async {
      final client = MockClient((_) async => http.Response('{}', 200));
      await tester.pumpWidget(MaterialApp(
        home: BoxScreen(
          controller: boxControllerWith(client),
          recoveryController: recoveryWith(client),
        ),
      ));
      expect(find.byKey(const Key('open-setup-recovery')), findsOneWidget);
      expect(find.byKey(const Key('open-recover-device')), findsOneWidget);
    });

    testWidgets('hides the recovery actions when no recoveryController is given',
        (tester) async {
      final client = MockClient((_) async => http.Response('{}', 200));
      await tester.pumpWidget(MaterialApp(
        home: BoxScreen(controller: boxControllerWith(client)),
      ));
      expect(find.byKey(const Key('open-setup-recovery')), findsNothing);
      expect(find.byKey(const Key('open-recover-device')), findsNothing);
    });

    testWidgets('Set up recovery opens the escrow-setup screen', (tester) async {
      final client = MockClient((_) async => http.Response('{}', 200));
      await tester.pumpWidget(MaterialApp(
        home: BoxScreen(
          controller: boxControllerWith(client),
          recoveryController: recoveryWith(client),
        ),
      ));
      await tester.tap(find.byKey(const Key('open-setup-recovery')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('escrow-submit')), findsOneWidget);
    });
  });
}
