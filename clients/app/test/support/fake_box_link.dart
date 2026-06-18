import 'dart:async';

import 'package:bard_pro/box/box_link.dart';

/// A fake [BoxLinkTransport] for S6 tests: records each [connect] (token + URI)
/// and hands back a [FakeConnection] the test drives (emit frames, drop, assert
/// closed). No real socket — the whole reconnect/parse path runs in-process
/// (CLAUDE.md §9: no native networking in unit tests).
class FakeTransport implements BoxLinkTransport {
  FakeTransport({this.failFirst = false});

  /// When true the FIRST [connect] throws (a failed handshake) so the backoff
  /// retry path is exercised; later attempts succeed.
  final bool failFirst;

  /// Every token presented to [connect], in order (for token-per-connect asserts).
  final List<String> tokens = [];

  /// Every connection handed out, in order.
  final List<FakeConnection> connections = [];

  var _attempt = 0;

  /// Completes once at least [n] successful handshakes have happened. Polls the
  /// [connections] list rather than a broadcast stream so a test that awaits the
  /// Nth connection never misses an event fired before it subscribed (the
  /// broadcast-stream race). [n] defaults to "the next one beyond what exists".
  Future<void> waitFor([int? n]) async {
    final target = n ?? connections.length + 1;
    while (connections.length < target) {
      await Future<void>.delayed(Duration.zero);
    }
  }

  /// Back-compat alias for the first handshake (`await transport.connected.first`
  /// reads naturally in the tests). [first] resolves once one connection exists.
  ConnectedView get connected => ConnectedView(this);

  @override
  Future<BoxLinkConnection> connect(Uri uri, {required String token}) async {
    tokens.add(token);
    if (failFirst && _attempt++ == 0) {
      throw StateError('handshake failed');
    }
    final conn = FakeConnection();
    connections.add(conn);
    return conn;
  }
}

/// A tiny view giving the tests `transport.connected.first` /
/// `.elementAt(n)` semantics over a polled list (no broadcast-stream race).
class ConnectedView {
  ConnectedView(this._transport);

  final FakeTransport _transport;

  /// Resolves once the first handshake has completed.
  Future<void> get first => _transport.waitFor(1);

  /// Resolves once the (index+1)th handshake has completed.
  Future<void> elementAt(int index) => _transport.waitFor(index + 1);
}

/// A fake [BoxLinkConnection]: a controllable frame stream, a record of frames
/// sent UP the link (the registration hello), and a close flag.
class FakeConnection implements BoxLinkConnection {
  final StreamController<String> _frames = StreamController<String>();

  /// True once [close] has been called (a clean leave / dispose).
  bool closed = false;

  /// Every frame the link wrote up the socket via [send], in order. The first
  /// is the registration hello (`{"type":"hello",...}`).
  final List<String> sent = [];

  @override
  Stream<String> get stream => _frames.stream;

  @override
  void send(String frame) => sent.add(frame);

  /// Push an inbound frame to the link. A no-op once the connection is closed
  /// (the link dropped it) so a "frame after dispose" test can emit safely.
  void emit(String frame) {
    if (_frames.isClosed) return;
    _frames.add(frame);
  }

  /// Simulate the remote closing cleanly (stream done → reconnect path).
  void dropDone() => _frames.close();

  @override
  Future<void> close() async {
    closed = true;
    if (!_frames.isClosed) await _frames.close();
  }
}
