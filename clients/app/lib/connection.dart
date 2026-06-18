import 'config.dart';

/// A named backend the client talks to: the Router + Registry HTTP endpoints and
/// the Agent's ssh endpoint for the Terminal tab. One [Connection] is "active" at
/// a time (see [AppState]); Dashboard/Chat/Terminal/Models all read the active one.
///
/// In-memory only this pass — persistence (shared_preferences) is a flagged
/// follow-up (see plans/PLAN_client_tabs.md §6). The [token] is the auth seam: a
/// future PQ-identity verifier replaces it without touching the screens.
class Connection {
  const Connection({
    required this.id,
    required this.name,
    required this.routerBaseUrl,
    required this.registryBaseUrl,
    required this.agentHost,
    this.sshPort = 2222,
    this.sshUser = 'bard',
    this.sshPassword = '',
    this.token = '',
    this.useTls = false,
  });

  final String id;
  final String name;
  final String routerBaseUrl;
  final String registryBaseUrl;

  /// Agent ssh endpoint for the Terminal tab (the UBI-9 container's sshd).
  final String agentHost;
  final int sshPort;
  final String sshUser;

  /// Dev-only convenience; key-based auth is the production path (DESIGN §6, Lane C).
  final String sshPassword;

  /// Bearer token for Router/Registry. Auth seam for the future trust layer (#42).
  final String token;
  final bool useTls;

  Connection copyWith({
    String? name,
    String? routerBaseUrl,
    String? registryBaseUrl,
    String? agentHost,
    int? sshPort,
    String? sshUser,
    String? sshPassword,
    String? token,
    bool? useTls,
  }) {
    return Connection(
      id: id,
      name: name ?? this.name,
      routerBaseUrl: routerBaseUrl ?? this.routerBaseUrl,
      registryBaseUrl: registryBaseUrl ?? this.registryBaseUrl,
      agentHost: agentHost ?? this.agentHost,
      sshPort: sshPort ?? this.sshPort,
      sshUser: sshUser ?? this.sshUser,
      sshPassword: sshPassword ?? this.sshPassword,
      token: token ?? this.token,
      useTls: useTls ?? this.useTls,
    );
  }
}

/// Seeded so the app runs locally with no setup (CLAUDE.md §1): a default backend
/// whose Router/Registry URLs and token come from the config layer ([AppConfig],
/// env-sourced) rather than literals, falling back to the MVP localhost ports
/// (Router 8080, Registry 8081, agent sshd 2222). Reset on relaunch until
/// persistence lands (§6 of the plan).
List<Connection> defaultConnections([AppConfig? config]) {
  final cfg = config ?? AppConfig.fromEnvironment();
  return [
    Connection(
      id: 'default',
      name: 'localhost',
      routerBaseUrl: cfg.routerBaseUrl,
      registryBaseUrl: cfg.registryBaseUrl,
      agentHost: Uri.tryParse(cfg.registryBaseUrl)?.host.isNotEmpty == true
          ? Uri.parse(cfg.registryBaseUrl).host
          : '127.0.0.1',
      token: cfg.authToken,
    ),
  ];
}
