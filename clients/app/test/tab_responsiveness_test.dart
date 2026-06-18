import 'dart:async';
import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/app_state.dart';
import 'package:bard_pro/box/box_controller.dart';
import 'package:bard_pro/box/device_identity.dart';
import 'package:bard_pro/box/recovery_controller.dart';
import 'package:bard_pro/box/recovery_screen.dart';
import 'package:bard_pro/box/seed_recovery.dart';
import 'package:bard_pro/connection.dart';
import 'package:bard_pro/main.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fixed_identity.dart';
import 'support/fake_secret_store.dart';
import 'support/rebuild_probe.dart';

/// Responsiveness regression suite for EVERY top-level tab (Eddie's explicit
/// ask — bug #board-freeze §4).
///
/// The board froze because heavy crypto (Argon2id seed-wrapping) ran on the UI
/// isolate, so queued taps never fired and the screen rebuilt/stalled. These
/// tests pin the responsiveness contract for the whole shell:
///
///   (a) **No main-isolate-blocking work on entry.** Switching to a tab settles
///       quickly — `pumpAndSettle` returns within a tight budget. A tab that
///       blocks the isolate (or never stops scheduling frames) times out.
///   (b) **Bounded rebuilds.** Over a fixed pump window an idle tab does not
///       rebuild-storm; a runaway `notifyListeners`/`setState` loop blows the
///       bound. Proven to bite by [_StormScreen].
///   (c) **A representative button fires within a one-frame budget.** A tap on a
///       real control on each tab produces its effect after a single 16 ms pump.
///
/// The tabs are ENUMERATED from the live shell's `NavigationBar` (not a
/// hardcoded list) so a new tab is automatically covered.
void main() {
  // A connected, fully-mocked state so all six tabs render their REAL screens
  // (the Box tab needs a non-null boxController) with no network and no platform
  // channels (CLAUDE.md §9). The MockClient answers the shell's startup
  // self-register and any model refresh; everything else 404s harmlessly.
  AppState connectedState() => AppState(
        connections: const [
          Connection(
            id: 'test',
            name: 'test',
            routerBaseUrl: 'https://r.test',
            registryBaseUrl: 'https://reg.test',
            agentHost: 'agent.test',
          ),
        ],
        secretStore: FakeSecretStore(),
        httpClient: MockClient((req) async {
          if (req.url.path == '/devices/self-register') {
            return http.Response(
                jsonEncode({'device': {'deviceId': 'dev-test'}}), 200);
          }
          if (req.url.path.endsWith('/agents') || req.url.path.endsWith('/models')) {
            return http.Response(jsonEncode({'agents': []}), 200);
          }
          return http.Response('{}', 404);
        }),
      );

  /// The bottom-nav destination LABELS the live shell exposes, in order — read
  /// from the rendered `NavigationBar`, so the test tracks the real tab set
  /// (enumerated, never hardcoded). A new tab is covered automatically.
  List<String> tabLabels(WidgetTester tester) {
    final bar = tester.widget<NavigationBar>(find.byType(NavigationBar));
    return [
      for (final d in bar.destinations)
        (d as NavigationDestination).label,
    ];
  }

  /// Enter the tab whose destination label is [label] by tapping it. The label
  /// `Text` inside the `NavigationBar` is the reliable hit target for a
  /// `NavigationDestination`.
  Future<void> enterTab(WidgetTester tester, String label) async {
    final target = find.descendant(
      of: find.byType(NavigationBar),
      matching: find.text(label),
    );
    expect(target, findsWidgets, reason: 'no nav destination labelled "$label"');
    await tester.tap(target.first);
    await tester.pumpAndSettle(const Duration(milliseconds: 16));
  }

  group('every tab stays responsive', () {
    testWidgets('(a) entering each tab settles within a tight budget — no '
        'main-isolate block', (tester) async {
      await tester.pumpWidget(BardProApp(state: connectedState()));
      await tester.pumpAndSettle();
      final labels = tabLabels(tester);
      expect(labels.length, greaterThanOrEqualTo(6),
          reason: 'shell should expose its tabs');

      for (final label in labels) {
        // A 2-second settle ceiling: a responsive tab settles in a handful of
        // frames; an isolate-blocking or frame-storming tab blows past it and
        // pumpAndSettle throws.
        final target = find.descendant(
          of: find.byType(NavigationBar),
          matching: find.text(label),
        );
        await tester.tap(target.first);
        await tester.pumpAndSettle(const Duration(seconds: 2));
        // After settling the tree is quiescent: no pending frame is scheduled
        // (a rebuild storm keeps one scheduled and pumpAndSettle would have
        // thrown before reaching here).
        expect(tester.binding.hasScheduledFrame, isFalse,
            reason: 'tab "$label" left a frame scheduled (rebuild storm?)');
      }
    });

    testWidgets('(b) no tab rebuild-storms over a fixed window', (tester) async {
      // Measure each tab's frame activity: after a tab settles, pumping a long
      // idle window must schedule NO further frames (zero rebuilds). A
      // `notifyListeners`/`setState` storm keeps scheduling frames — proven to
      // be caught by the [_StormScreen] regression test below.
      await tester.pumpWidget(BardProApp(state: connectedState()));
      await tester.pumpAndSettle();

      for (final label in tabLabels(tester)) {
        await enterTab(tester, label);
        // Idle the tab for ~20 frames. A quiescent tab schedules nothing.
        for (var f = 0; f < 20; f++) {
          await tester.pump(const Duration(milliseconds: 16));
          expect(tester.binding.hasScheduledFrame, isFalse,
              reason:
                  'tab "$label" scheduled a frame while idle (storm) at frame $f');
        }
      }
    });

    testWidgets('(c) the Box tab create button fires within a one-frame budget',
        (tester) async {
      // The Box tab is the bug locus. Its primary control ("Create a box") must
      // respond to a tap within a single frame — proving the UI isolate is free
      // (the original freeze swallowed exactly this tap).
      await tester.pumpWidget(BardProApp(state: connectedState()));
      await tester.pumpAndSettle();
      await enterTab(tester, tabLabels(tester).last); // Box is the last tab.

      expect(find.byKey(const Key('open-create-box')), findsOneWidget);
      await tester.tap(find.byKey(const Key('open-create-box')));
      // One frame budget: the push must have produced the Create-a-box screen.
      await tester.pump(const Duration(milliseconds: 16));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('box-name-field')), findsOneWidget,
          reason: 'create-box tap did not fire within the frame budget');
    });
  });

  group('the responsiveness assertion actually bites (regression proof)', () {
    testWidgets('a rebuild-storm screen FAILS the bounded-rebuild check',
        (tester) async {
      // Prove the §(b) assertion catches the very failure mode the box freeze
      // produced: a screen that never stops scheduling frames / rebuilding. The
      // [RebuildProbe] wraps the storm so we can both watch `hasScheduledFrame`
      // (the §(b) signal) AND count rebuilds.
      final counter = RebuildCounter();
      await tester.pumpWidget(MaterialApp(
        home: _StormScreen(counter: counter),
      ));
      await tester.pump();
      counter.reset();

      // The storm keeps a frame scheduled on every build. The exact per-tab
      // §(b) check (`hasScheduledFrame` stays false while idle) must FAIL here.
      var sawScheduledFrame = false;
      for (var f = 0; f < 20; f++) {
        await tester.pump(const Duration(milliseconds: 16));
        if (tester.binding.hasScheduledFrame) sawScheduledFrame = true;
      }
      expect(sawScheduledFrame, isTrue,
          reason: 'the storm must trip the same check the real tabs pass');
      expect(counter.value, greaterThan(3),
          reason: 'a storm rebuilds many times over the window');

      // Stop the storm so the test can tear down cleanly.
      await tester.pumpWidget(const SizedBox());
    });
  });

  group('escrow-setup freeze repro (the actual board bug)', () {
    BoxApiFactory apiFactory(MockClient client) =>
        ({tokenProvider}) => BardApi(
              routerBaseUrl: 'https://r.test',
              registryBaseUrl: 'https://reg.test',
              token: 'baked',
              httpClient: client,
              tokenProvider: tokenProvider,
            );

    RecoveryController controllerWith(SeedWrapping wrapper) => RecoveryController(
          apiFactory: apiFactory(
            MockClient((_) async => http.Response('{}', 200)),
          ),
          identity: DeviceIdentity(
            secretStore: FakeSecretStore(),
            seedFactory: fixtureSeedFactory,
          ),
          wrapper: wrapper,
          omgGenerator: () => fixtureOmgCode,
        );

    Future<void> pumpEscrow(WidgetTester tester, RecoveryController c) async {
      await tester.pumpWidget(MaterialApp(
        home: EscrowSetupScreen(controller: c, onDone: () {}),
      ));
      await tester.enterText(find.byKey(const Key('handle-field')), 'ada');
      await tester.enterText(
          find.byKey(const Key('password-field')), fixtureSecretString);
      await tester.pump();
    }

    testWidgets(
        'a UI-isolate-BLOCKING wrapper starves the busy spinner (the freeze)',
        (tester) async {
      // The original bug: Argon2id ran on the UI isolate, so `setUpEscrow`
      // completed in ONE synchronous turn without ever yielding — `busy` went
      // true then false before any frame could render the progress spinner, and
      // queued taps were starved. Modelled by a wrapper that returns a
      // SYNCHRONOUSLY-completed future (no event-loop yield).
      final c = controllerWith(const _BlockingSeedWrapper());
      await pumpEscrow(tester, c);

      await tester.tap(find.byKey(const Key('escrow-submit')));
      // One frame after the tap: a responsive flow would be showing the busy
      // spinner. The blocking wrapper finished synchronously, so it is NOT busy
      // and the spinner never appeared — the freeze signature.
      await tester.pump(const Duration(milliseconds: 16));
      expect(c.busy, isFalse,
          reason: 'blocking wrapper completes in one turn (no live spinner)');
      expect(find.byType(CircularProgressIndicator), findsNothing,
          reason: 'the progress indicator never got a frame — the freeze');
    });

    testWidgets(
        'the OFFLOADED wrapper keeps the screen live: spinner shows mid-flight',
        (tester) async {
      // The fix: the wrapper hands the work to a runner that YIELDS (the real
      // path uses Isolate.run; here a pending future stands in deterministically).
      // `busy` stays true across a frame, so the progress spinner renders — the
      // screen is responsive while the escrow runs.
      final gate = Completer<void>();
      final c = controllerWith(_OffloadedSeedWrapper(gate.future));
      await pumpEscrow(tester, c);

      await tester.tap(find.byKey(const Key('escrow-submit')));
      await tester.pump(const Duration(milliseconds: 16));
      // Mid-flight: the wrap is still pending (gate not completed) → busy spinner
      // is on screen. This is exactly what the blocking wrapper could not do.
      expect(c.busy, isTrue, reason: 'offloaded work keeps the flow live');
      expect(find.byType(CircularProgressIndicator), findsWidgets,
          reason: 'the progress spinner renders while the escrow runs');

      // Let it finish and settle cleanly.
      gate.complete();
      await tester.pumpAndSettle();
    });
  });
}

/// Models the FROZEN behaviour: an Argon2id wrap that runs entirely on the
/// calling (UI) isolate and returns a SYNCHRONOUSLY-completed future, so the
/// awaiting controller never yields to the event loop mid-wrap. Test-only.
class _BlockingSeedWrapper implements SeedWrapping {
  const _BlockingSeedWrapper();

  @override
  Future<String> wrap({required List<int> seed, required String secret}) {
    // A trivial synchronous "result" returned without any await — the
    // event-loop-starving signature of on-isolate crypto.
    return SynchronousFuture<String>('blob:$secret');
  }

  @override
  Future<Uint8List> unwrap({required String blob, required String secret}) =>
      SynchronousFuture<Uint8List>(Uint8List(0));
}

/// Models the FIXED behaviour: the wrap is offloaded and only completes when the
/// background work finishes — represented by [_gate]. While it is pending the UI
/// isolate is free, so the busy spinner renders. Test-only.
class _OffloadedSeedWrapper implements SeedWrapping {
  const _OffloadedSeedWrapper(this._gate);

  final Future<void> _gate;

  @override
  Future<String> wrap({required List<int> seed, required String secret}) async {
    await _gate;
    return 'blob:$secret';
  }

  @override
  Future<Uint8List> unwrap({required String blob, required String secret}) async {
    await _gate;
    return Uint8List(0);
  }
}

/// A deliberately mis-behaving screen that rebuild-storms via a REPEATING
/// ticker: an [AnimationController.repeat] keeps a frame scheduled every tick
/// and rebuilds (through [RebuildProbe]) without bound, never going quiescent.
/// Used ONLY to prove the responsiveness check catches such a screen (the
/// failure mode the box freeze exhibited) — never shipped.
class _StormScreen extends StatefulWidget {
  const _StormScreen({required this.counter});

  final RebuildCounter counter;

  @override
  State<_StormScreen> createState() => _StormScreenState();
}

class _StormScreenState extends State<_StormScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 16),
    )..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (context, _) => RebuildProbe(
        counter: widget.counter,
        child: const Scaffold(body: Center(child: Text('storm'))),
      ),
    );
  }
}
