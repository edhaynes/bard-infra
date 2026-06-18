import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'api.dart';
import 'box/box_controller.dart';
import 'box/box_link.dart';
import 'config.dart';
import 'connection.dart';
import 'model_info.dart';
import 'secure_store.dart';

/// Single source of truth for the client shell: the list of [Connection]s, which
/// one is active, and the cached model list. Screens are constructed with this
/// and rebuild via `ListenableBuilder` — no third-party state-management dep
/// (CLAUDE.md §13: prefer stdlib/framework over extra deps).
class AppState extends ChangeNotifier {
  /// [config] seeds the default connection's endpoints/token from the config
  /// layer (env vars). [httpClient] is injected so tests bind a `MockClient`;
  /// production builds let each [BardApi] own its own client.
  AppState({
    List<Connection>? connections,
    AppConfig? config,
    this.httpClient,
    SecretStore? secretStore,
  })  : _connections = connections ?? defaultConnections(config),
        _secretStore = secretStore ?? FlutterSecretStore() {
    _activeId = _connections.isEmpty ? null : _connections.first.id;
  }

  /// Persistence seam for the per-device secret; injected so tests bind a fake.
  final SecretStore _secretStore;

  /// Box onboarding controller, bound to the active connection's manager token.
  /// Lazily built and rebound when the active connection changes so create/
  /// members calls always use the current backend.
  BoxController? _boxController;
  String? _boxControllerForId;

  /// The [BoxController] for the active connection, or null when none is active.
  BoxController? get boxController {
    final c = activeConnection;
    if (c == null) return null;
    if (_boxController == null || _boxControllerForId != c.id) {
      _boxController?.dispose();
      _boxController = BoxController(
        apiFactory: ({tokenProvider}) => BardApi(
          routerBaseUrl: c.routerBaseUrl,
          registryBaseUrl: c.registryBaseUrl,
          token: c.token,
          httpClient: httpClient,
          tokenProvider: tokenProvider,
        ),
        secretStore: _secretStore,
        // The receive link (S6): a self-healing WS to the active connection's
        // Router `/v1/agent-link`, authed by the device's EdDSA token. Suppressed
        // in tests (httpClient injected) so no real socket is opened — widget
        // tests drive the box screens without the platform networking stack.
        linkFactory: httpClient != null
            ? null
            : ({required tokenProvider}) => BoxLink(
                  routerWsUri: BoxLink.agentLinkUri(c.routerBaseUrl),
                  tokenProvider: tokenProvider,
                ),
      );
      _boxControllerForId = c.id;
    }
    return _boxController;
  }

  @override
  void dispose() {
    _boxController?.dispose();
    super.dispose();
  }

  /// Injected so tests bind a `MockClient`; null in production (each [BardApi]
  /// owns its own client). Exposed read-only for the same DI seam in widget tests.
  final http.Client? httpClient;
  final List<Connection> _connections;
  String? _activeId;
  List<ModelInfo> _models = sampleModels;

  List<Connection> get connections => List.unmodifiable(_connections);
  List<ModelInfo> get models => List.unmodifiable(_models);

  Connection? get activeConnection {
    if (_activeId == null) return null;
    for (final c in _connections) {
      if (c.id == _activeId) return c;
    }
    return null;
  }

  /// A [BardApi] bound to the active connection, or null when none is selected.
  /// Replaces the old hardcoded `_api => null` that left the client unable to
  /// run a model (bugs.md #50).
  BardApi? get api {
    final c = activeConnection;
    if (c == null) return null;
    return BardApi(
      routerBaseUrl: c.routerBaseUrl,
      registryBaseUrl: c.registryBaseUrl,
      token: c.token,
      httpClient: httpClient,
    );
  }

  void setActive(String id) {
    if (_activeId == id) return;
    _activeId = id;
    notifyListeners();
  }

  /// Insert or replace by id.
  void upsert(Connection connection) {
    final i = _connections.indexWhere((c) => c.id == connection.id);
    if (i >= 0) {
      _connections[i] = connection;
    } else {
      _connections.add(connection);
    }
    _activeId ??= connection.id;
    notifyListeners();
  }

  void remove(String id) {
    _connections.removeWhere((c) => c.id == id);
    if (_activeId == id) {
      _activeId = _connections.isEmpty ? null : _connections.first.id;
    }
    notifyListeners();
  }

  /// Pull the live agent list from the active connection's Registry. Keeps the
  /// last good list (falls back to samples) when offline so the UI never blanks.
  Future<void> refreshModels() async {
    final api = this.api;
    if (api == null) return;
    try {
      final agents = await api.listAgents();
      _models = agents.isEmpty ? sampleModels : agents;
      notifyListeners();
    } on BardApiException {
      // Surface errors via Dashboard health, not by clearing the list.
    }
  }
}
