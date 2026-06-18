import 'dart:convert';

import 'package:bard_pro/box/box_link.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_box_link.dart';

/// Unit tests for the box receive link ([BoxLink]) — the self-healing WebSocket
/// to the Router `/v1/agent-link`. Driven against a FAKE transport (no real
/// socket, CLAUDE.md §9): asserts the FROZEN ping parse, the device-token-per-
/// connect, the reconnect-with-backoff loop, and a clean close.
void main() {
  /// The S6 fixture deviceId — the `sub` claim baked into [fakeToken] below, and
  /// therefore the `agentId` the link must put in its hello (Router requires
  /// `claims.sub == agentId`, broker.py #54).
  const fakeDeviceId = 'mac-fixture-1';

  /// The S6 fixture device token: a CLEARLY-FAKE EdDSA JWT (header.payload.sig
  /// with an all-zero signature `JWT.decode` never verifies) whose `sub` is
  /// [fakeDeviceId]. The link decodes this `sub` to fill the hello's `agentId`.
  /// No real secret — the signature is 64 zero bytes (CLAUDE.md §7); the
  /// canonical fake fixture string lives in the payload's `dev` claim so a
  /// secret-shaped literal still never lands in the repo.
  const fakeToken =
      'eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9' // pragma: allowlist secret
      '.eyJzdWIiOiJtYWMtZml4dHVyZS0xIiwiaXNzIjoiYmFyZGxsbS1wcm8iLCJkZXYiOiJhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejAxMjM0NTY3ODlBQkNERUYifQ' // pragma: allowlist secret
      '.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

  /// A `box.ping` frame for [from] in [channelId] (the FROZEN contract).
  String pingFrame({
    String channelId = 'north',
    String from = 'mac-1',
    String ts = '2026-06-18T12:00:00Z',
  }) =>
      '{"type":"box.ping","channelId":"$channelId","from":"$from","ts":"$ts"}';

  group('BoxPing.tryParse', () {
    test('parses a well-formed ping frame', () {
      final ping = BoxPing.tryParse(pingFrame());
      expect(ping, isNotNull);
      expect(ping!.channelId, 'north');
      expect(ping.from, 'mac-1');
      expect(ping.ts, '2026-06-18T12:00:00Z');
    });

    test('returns null on non-JSON', () {
      expect(BoxPing.tryParse('not json'), isNull);
    });

    test('returns null on a JSON array (not an object)', () {
      expect(BoxPing.tryParse('[1,2,3]'), isNull);
    });

    test('returns null on a different frame type', () {
      expect(BoxPing.tryParse('{"type":"box.presence","channelId":"n"}'), isNull);
    });

    test('returns null when channelId / from / ts is missing or blank', () {
      expect(BoxPing.tryParse('{"type":"box.ping","from":"m","ts":"t"}'), isNull);
      expect(
        BoxPing.tryParse('{"type":"box.ping","channelId":"n","ts":"t"}'),
        isNull,
      );
      expect(
        BoxPing.tryParse('{"type":"box.ping","channelId":"n","from":"m"}'),
        isNull,
      );
      expect(
        BoxPing.tryParse('{"type":"box.ping","channelId":"","from":"m","ts":"t"}'),
        isNull,
      );
    });
  });

  group('BoxLink.agentLinkUri', () {
    test('derives ws:// from http and preserves host/port', () {
      expect(
        BoxLink.agentLinkUri('http://127.0.0.1:8080').toString(),
        'ws://127.0.0.1:8080/v1/agent-link',
      );
    });

    test('derives wss:// from https', () {
      expect(
        BoxLink.agentLinkUri('https://router.example:8443').toString(),
        'wss://router.example:8443/v1/agent-link',
      );
    });
  });

  group('BoxLink lifecycle', () {
    test('open connects with the device token and surfaces parsed pings',
        () async {
      final transport = FakeTransport();
      final link = BoxLink(
        routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
        tokenProvider: () async => fakeToken,
        transport: transport,
        delay: _noDelay,
      );
      final received = <BoxPing>[];
      link.pings.listen(received.add);

      link.open();
      await transport.connected.first; // wait for the handshake
      await Future<void>.delayed(Duration.zero); // let the hello be written
      expect(transport.tokens, [fakeToken],
          reason: 'the device token authenticates the upgrade');

      // The FIRST frame on the wire MUST be a well-formed registration hello:
      // the Router blocks on it and reads the identity from it, not the header
      // (bug: without this the box receive-link never registers, no pings).
      expect(transport.connections.single.sent, isNotEmpty,
          reason: 'a hello must be sent on connect');
      final hello =
          jsonDecode(transport.connections.single.sent.first) as Map<String, dynamic>;
      expect(hello['type'], 'hello');
      expect(hello['agentId'], fakeDeviceId,
          reason: "agentId is the token's sub (broker.py #54: sub == agentId)");
      expect(hello['authToken'], fakeToken,
          reason: 'the hello carries the self-minted EdDSA token verbatim');

      transport.connections.last.emit(pingFrame(from: 'pixel-9'));
      await Future<void>.delayed(Duration.zero);
      expect(received, hasLength(1));
      expect(received.single.from, 'pixel-9');

      // An unmodeled frame is ignored, not crashing the link.
      transport.connections.last.emit('{"type":"box.presence"}');
      await Future<void>.delayed(Duration.zero);
      expect(received, hasLength(1));

      await link.dispose();
    });

    test('open is idempotent: a second call does not open a second socket',
        () async {
      final transport = FakeTransport();
      final link = BoxLink(
        routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
        tokenProvider: () async => fakeToken,
        transport: transport,
        delay: _noDelay,
      );
      link.open();
      await transport.connected.first;
      link.open(); // no-op while live
      await Future<void>.delayed(Duration.zero);
      expect(transport.connections, hasLength(1));
      await link.dispose();
    });

    test('reconnects with backoff on a drop, re-minting the token each time',
        () async {
      final waits = <Duration>[];
      final transport = FakeTransport();
      var minted = 0;
      final link = BoxLink(
        routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
        tokenProvider: () async {
          minted++;
          return fakeToken;
        },
        transport: transport,
        initialBackoff: const Duration(seconds: 1),
        maxBackoff: const Duration(seconds: 30),
        // Record the scheduled backoff and resolve immediately so the loop runs
        // without real waits.
        delay: (d) async => waits.add(d),
      );

      link.open();
      await transport.connected.first;
      expect(minted, 1);

      // The first connection registered with a hello.
      await Future<void>.delayed(Duration.zero);
      expect(transport.connections.first.sent.first,
          contains('"type":"hello"'),
          reason: 'the first link registered');

      // First drop → reconnect after the initial backoff.
      transport.connections.last.dropDone();
      await transport.connected.elementAt(1);
      expect(waits, [const Duration(seconds: 1)]);
      expect(minted, 2, reason: 'a fresh token per reconnect');

      // The reconnected link MUST send a fresh hello to re-register — otherwise
      // the new socket sits unregistered and pings stop after the first drop.
      await Future<void>.delayed(Duration.zero);
      final reHello =
          jsonDecode(transport.connections[1].sent.first) as Map<String, dynamic>;
      expect(reHello['type'], 'hello');
      expect(reHello['agentId'], fakeDeviceId);
      expect(reHello['authToken'], fakeToken);

      // Second drop → backoff doubled.
      transport.connections.last.dropDone();
      await transport.connected.elementAt(2);
      expect(waits, [const Duration(seconds: 1), const Duration(seconds: 2)]);
      expect(minted, 3);

      await link.dispose();
    });

    test('a failed handshake schedules a backoff retry', () async {
      final waits = <Duration>[];
      // First connect throws, the retry succeeds.
      final transport = FakeTransport(failFirst: true);
      final link = BoxLink(
        routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
        tokenProvider: () async => fakeToken,
        transport: transport,
        delay: (d) async => waits.add(d),
      );
      link.open();
      // Wait for the first (failing) and the retried (succeeding) attempt.
      await transport.connected.first;
      expect(waits, [const Duration(seconds: 1)],
          reason: 'the failed handshake backed off once before succeeding');
      await link.dispose();
    });

    test('retries when no token is available yet (fresh install)', () async {
      final waits = <Duration>[];
      var calls = 0;
      final transport = FakeTransport();
      final link = BoxLink(
        routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
        // No identity on the first call; provisioned by the second.
        tokenProvider: () async => (calls++ == 0) ? null : fakeToken,
        transport: transport,
        delay: (d) async => waits.add(d),
      );
      link.open();
      await transport.connected.first;
      expect(waits, hasLength(1), reason: 'backed off while the token was absent');
      await link.dispose();
    });

    test('close stops the reconnect loop and shuts the socket', () async {
      final transport = FakeTransport();
      final link = BoxLink(
        routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
        tokenProvider: () async => fakeToken,
        transport: transport,
        delay: _noDelay,
      );
      link.open();
      await transport.connected.first;
      expect(link.isOpen, isTrue);

      await link.close();
      expect(link.isOpen, isFalse);
      expect(transport.connections.last.closed, isTrue);

      // A drop after close must NOT reconnect.
      transport.connections.last.dropDone();
      await Future<void>.delayed(Duration.zero);
      expect(transport.connections, hasLength(1));
    });

    test('a ping arriving after dispose is dropped without error', () async {
      final transport = FakeTransport();
      final link = BoxLink(
        routerWsUri: Uri.parse('ws://r.test/v1/agent-link'),
        tokenProvider: () async => fakeToken,
        transport: transport,
        delay: _noDelay,
      );
      link.open();
      await transport.connected.first;
      final conn = transport.connections.last;
      await link.dispose();
      // No throw — the controller is closed and the frame is dropped.
      conn.emit(pingFrame());
      await Future<void>.delayed(Duration.zero);
    });
  });
}

/// A zero-duration backoff for tests that don't assert on the wait value.
Future<void> _noDelay(Duration _) async {}
