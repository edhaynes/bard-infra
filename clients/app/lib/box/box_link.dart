import 'dart:async';
import 'dart:convert';

import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// A single ping received over the box link (the FROZEN receive contract):
/// `{"type":"box.ping","channelId":"<id>","from":"<deviceId>","ts":"<iso8601>"}`.
///
/// Parsed once here (not in widgets) so the UI consumes a typed value
/// (CLAUDE.md §2). [ts] is kept as the raw ISO-8601 string — the UI only shows
/// `Ping from <from>`, and reparsing a server timestamp the client never
/// validates buys nothing.
class BoxPing {
  const BoxPing({
    required this.channelId,
    required this.from,
    required this.ts,
  });

  /// The box the ping was sent in (`channelId`).
  final String channelId;

  /// The deviceId that sent the ping (`from`).
  final String from;

  /// The server-stamped ISO-8601 send time (`ts`), raw.
  final String ts;

  /// Parse a `box.ping` frame, or return null when [frame] is not a well-formed
  /// ping (wrong `type`, non-JSON, missing/blank fields). A malformed or
  /// unrelated frame is ignored rather than crashing the link — the WS carries
  /// frames this client does not model yet, and a bad frame must not tear down
  /// the receive path (CLAUDE.md §12: no silent swallow of OUR errors, but an
  /// unmodeled peer frame is data, not an error).
  static BoxPing? tryParse(String frame) {
    final Object? decoded;
    try {
      decoded = jsonDecode(frame);
    } on FormatException {
      return null;
    }
    if (decoded is! Map) return null;
    if (decoded['type'] != 'box.ping') return null;
    final channelId = decoded['channelId'];
    final from = decoded['from'];
    final ts = decoded['ts'];
    if (channelId is! String || channelId.isEmpty) return null;
    if (from is! String || from.isEmpty) return null;
    if (ts is! String || ts.isEmpty) return null;
    return BoxPing(channelId: channelId, from: from, ts: ts);
  }
}

/// One live WebSocket leg: the frame [stream] and a [close] hook. The transport
/// abstraction (CLAUDE.md §3: swappable backend behind an interface) so unit
/// tests inject a fake leg with no real socket (CLAUDE.md §9) while production
/// uses [IoBoxLinkTransport] over `dart:io` WebSockets.
abstract class BoxLinkConnection {
  /// The inbound frames (raw text/binary already decoded to [String]). Completes
  /// (or errors) when the remote closes — [BoxLink] treats either as a drop and
  /// reconnects.
  Stream<String> get stream;

  /// Send one text [frame] up the socket. Used to write the registration hello
  /// (`{"type":"hello",...}`) as the FIRST frame: the Router's
  /// `handle_agent_link` blocks on `receive_json()` for that hello and reads the
  /// identity from it (NOT the upgrade header), so without this the link never
  /// registers and no pings are delivered (bug: box receive-link never registers).
  void send(String frame);

  /// Close the socket. Idempotent; safe to call after the stream already ended.
  Future<void> close();
}

/// Opens one [BoxLinkConnection] to the Router. Injected into [BoxLink] so the
/// reconnect/parse logic is unit-tested against a fake transport.
abstract class BoxLinkTransport {
  /// Open a WebSocket to [uri], presenting the device EdDSA token as a bearer.
  /// Throws on a failed handshake (the caller schedules a backoff retry).
  Future<BoxLinkConnection> connect(Uri uri, {required String token});
}

/// Production transport: an `IOWebSocketChannel` carrying the device token in the
/// `Authorization` header of the upgrade request — the same bearer shape the
/// box-owner HTTP calls use (sub=deviceId, self-signed EdDSA). dart:io supports
/// custom upgrade headers, so the token never rides in the URL/query (where it
/// would land in proxy/access logs, CLAUDE.md §7).
class IoBoxLinkTransport implements BoxLinkTransport {
  const IoBoxLinkTransport();

  @override
  Future<BoxLinkConnection> connect(Uri uri, {required String token}) async {
    final channel = IOWebSocketChannel.connect(
      uri,
      headers: <String, dynamic>{'Authorization': 'Bearer $token'},
    );
    // Surface a failed handshake as a thrown error so [BoxLink] retries.
    await channel.ready;
    return _ChannelConnection(channel);
  }
}

/// Adapts a [WebSocketChannel] to [BoxLinkConnection]: frames as strings, a clean
/// close. Non-string frames (unexpected binary) are mapped to their UTF-8 text.
class _ChannelConnection implements BoxLinkConnection {
  _ChannelConnection(this._channel);

  final WebSocketChannel _channel;

  @override
  Stream<String> get stream => _channel.stream.map((event) {
        if (event is String) return event;
        if (event is List<int>) return utf8.decode(event, allowMalformed: true);
        return event.toString();
      });

  @override
  void send(String frame) => _channel.sink.add(frame);

  @override
  Future<void> close() async {
    await _channel.sink.close();
  }
}

/// The box receive link: a self-healing WebSocket to the Router's
/// `/v1/agent-link` that registers this device to receive pushes and surfaces
/// `box.ping` frames as a broadcast [pings] stream (FROZEN contract).
///
/// Lifecycle (CLAUDE.md §3 DI, §12 observability):
///   - [open] connects with the device token, listens for frames, and parses
///     pings onto [pings]. Idempotent — a second [open] is a no-op while live.
///   - On a drop (stream done/error) it reconnects with exponential backoff
///     ([_initialBackoff] doubling to [_maxBackoff]); a clean [close] stops the
///     loop so leaving a box tears the socket down deterministically.
///
/// The token is read fresh per (re)connect via [tokenProvider] so a short-lived
/// EdDSA JWT is never reused stale across a long-lived/ reconnecting link — the
/// same minting seam the HTTP api uses (ADR-0016 §4). Collaborators injected:
/// [transport] opens sockets, [tokenProvider] mints the bearer, [delay] schedules
/// backoff (overridable in tests to avoid real waits).
class BoxLink {
  BoxLink({
    required Uri routerWsUri,
    required Future<String?> Function() tokenProvider,
    BoxLinkTransport transport = const IoBoxLinkTransport(),
    Future<void> Function(Duration)? delay,
    Duration initialBackoff = const Duration(seconds: 1),
    Duration maxBackoff = const Duration(seconds: 30),
  })  : _routerWsUri = routerWsUri,
        _tokenProvider = tokenProvider,
        _transport = transport,
        _delay = delay ?? Future<void>.delayed,
        _initialBackoff = initialBackoff,
        _maxBackoff = maxBackoff;

  // ignore_for_file: prefer_initializing_formals — the public named params map
  // to private fields; an initializing formal can't be a private named param.
  final Uri _routerWsUri;
  final Future<String?> Function() _tokenProvider;
  final BoxLinkTransport _transport;
  final Future<void> Function(Duration) _delay;
  final Duration _initialBackoff;
  final Duration _maxBackoff;

  final StreamController<BoxPing> _pings = StreamController<BoxPing>.broadcast();

  BoxLinkConnection? _connection;
  StreamSubscription<String>? _subscription;
  bool _open = false;
  bool _connecting = false;
  Duration _backoff = const Duration(seconds: 1);

  /// Broadcast stream of parsed pings received over the link. The UI subscribes
  /// while a box is in view and shows `Ping from <from>` per event.
  Stream<BoxPing> get pings => _pings.stream;

  /// True between [open] and [close] (the link should be live or reconnecting).
  bool get isOpen => _open;

  /// Build the `/v1/agent-link` WS URI from an http(s) Router base — `http`→`ws`,
  /// `https`→`wss` — preserving host/port. Static so the derivation is unit-
  /// testable and used identically by production wiring.
  static Uri agentLinkUri(String routerBaseUrl) {
    final base = Uri.parse(routerBaseUrl);
    final scheme = base.scheme == 'https' ? 'wss' : 'ws';
    return base.replace(scheme: scheme, path: '/v1/agent-link');
  }

  /// Open the link and start the connect/reconnect loop. Idempotent: a second
  /// call while already open is a no-op. Returns immediately; the first
  /// connection is established asynchronously (failures retry with backoff).
  void open() {
    if (_open) return;
    _open = true;
    _backoff = _initialBackoff;
    unawaited(_connect());
  }

  /// Connect once and wire the frame listener. On any failure (handshake throw,
  /// missing token) schedule a backoff retry. Guarded so overlapping calls
  /// (a manual open racing a reconnect) don't open two sockets.
  Future<void> _connect() async {
    if (!_open || _connecting || _connection != null) return;
    _connecting = true;
    try {
      final token = await _tokenProvider();
      if (token == null || token.isEmpty) {
        // No identity yet — can't authenticate. Retry; the device provisions
        // its key on first launch and the token becomes available shortly.
        _connecting = false;
        _scheduleReconnect();
        return;
      }
      final connection = await _transport.connect(_routerWsUri, token: token);
      if (!_open) {
        // Closed while the handshake was in flight — tear the new socket down.
        await connection.close();
        _connecting = false;
        return;
      }
      _connection = connection;
      // Register the device with the Router as the FIRST frame on the wire. The
      // backend's handle_agent_link does `accept()` then blocks on
      // `receive_json()` for this hello and reads the identity from it (the
      // upgrade Authorization header is ignored), then requires
      // `claims.sub == agentId` (bug #54). So the agentId MUST be the token's own
      // `sub` claim — which this client minted (device_auth.dart §sub=deviceId).
      // A token we can't decode to a sub can't form a valid hello: treat it as a
      // failed connect and back off rather than send a hello the Router rejects.
      final deviceId = _deviceIdFromToken(token);
      if (deviceId == null) {
        _teardownConnection();
        _scheduleReconnect();
        return;
      }
      connection.send(
        jsonEncode(<String, String>{
          'type': 'hello',
          'agentId': deviceId,
          'authToken': token,
        }),
      );
      // NB: the backoff is NOT reset here. A handshake that succeeds and then
      // immediately drops is flapping, and resetting on mere connect would peg
      // the retry interval at the floor forever. The backoff resets only once
      // the link proves it actually delivers — on the first frame ([_onFrame]).
      _subscription = connection.stream.listen(
        _onFrame,
        onError: (_) => _onDrop(),
        onDone: _onDrop,
        cancelOnError: false,
      );
    } on Object {
      // Handshake or transport failure — retry with backoff.
      _connection = null;
      _scheduleReconnect();
    } finally {
      _connecting = false;
    }
  }

  /// Read the deviceId from [token]'s `sub` claim — the agentId the hello must
  /// carry (the Router requires `claims.sub == agentId`, broker.py #54). The
  /// token is a JWT this client self-minted (device_auth.dart, `sub=deviceId`),
  /// so [JWT.decode] parses the payload WITHOUT a signature check — we are
  /// reading our own claim, not trusting a third party. Returns null when the
  /// token is not a decodable JWT or carries no `sub`, in which case no valid
  /// hello can be formed and the caller backs off instead.
  static String? _deviceIdFromToken(String token) {
    try {
      final sub = JWT.decode(token).subject;
      if (sub == null || sub.isEmpty) return null;
      return sub;
    } on JWTException {
      return null;
    }
  }

  /// A frame arrived: the link is proven healthy, so reset the backoff floor;
  /// then surface the frame as a [BoxPing] when it parses, else ignore it
  /// (unmodeled peer frame — not an error, see [BoxPing.tryParse]).
  void _onFrame(String frame) {
    _backoff = _initialBackoff;
    final ping = BoxPing.tryParse(frame);
    if (ping != null && !_pings.isClosed) _pings.add(ping);
  }

  /// The socket dropped (remote close or stream error). Drop the dead
  /// connection and reconnect with backoff while still open.
  void _onDrop() {
    _teardownConnection();
    if (_open) _scheduleReconnect();
  }

  /// Schedule the next reconnect after the current backoff, then double it up to
  /// [_maxBackoff]. No-op once [close]d.
  void _scheduleReconnect() {
    if (!_open) return;
    final wait = _backoff;
    _backoff = _nextBackoff(wait);
    unawaited(_delay(wait).then((_) {
      if (_open) unawaited(_connect());
    }));
  }

  /// Double [current], clamped to [_maxBackoff].
  Duration _nextBackoff(Duration current) {
    final doubled = current * 2;
    return doubled > _maxBackoff ? _maxBackoff : doubled;
  }

  /// Cancel the listener and forget the connection (without flipping [_open]),
  /// so a reconnect can replace it. Fire-and-forget close on the old socket.
  void _teardownConnection() {
    final sub = _subscription;
    final conn = _connection;
    _subscription = null;
    _connection = null;
    unawaited(sub?.cancel());
    unawaited(conn?.close());
  }

  /// Close the link cleanly when leaving a box: stop the reconnect loop, cancel
  /// the listener, and shut the socket. Safe to call when never opened or twice.
  /// Does NOT close [pings] — call [dispose] to release the controller when the
  /// link object is being discarded for good.
  Future<void> close() async {
    _open = false;
    final sub = _subscription;
    final conn = _connection;
    _subscription = null;
    _connection = null;
    await sub?.cancel();
    await conn?.close();
  }

  /// Tear down and release the broadcast controller. After [dispose] the link is
  /// unusable; build a new one to reconnect.
  Future<void> dispose() async {
    await close();
    if (!_pings.isClosed) await _pings.close();
  }
}
