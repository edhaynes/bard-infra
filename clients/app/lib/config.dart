import 'dart:io' show Platform;

/// Configuration layer for the client's backend endpoints and auth token.
///
/// CLAUDE.md §1 (config over hardcoding): the Router/Registry URLs and the
/// bearer token flow through one place, sourced from environment variables with
/// localhost defaults so the app runs locally with no setup. The Settings/
/// Connections UI layers on top of this — a [Connection] may override these
/// per-backend, but the seed values come from here, never from literals
/// scattered across widgets.
///
/// The environment map is injected (not read from `Platform.environment` deep in
/// a method) so config resolution is unit-testable without real env vars
/// (CLAUDE.md §2: dependency injection, no `os.environ` inside methods).
class AppConfig {
  const AppConfig({
    required this.routerBaseUrl,
    required this.registryBaseUrl,
    required this.authToken,
  });

  /// Env var names — the single source of truth for the config keys, mirrored in
  /// `bardLLMPro/.env.example`.
  static const routerUrlKey = 'BARD_ROUTER_URL';
  static const registryUrlKey = 'BARD_REGISTRY_URL';
  static const tokenKey = 'BARD_AUTH_TOKEN';

  /// Defaults match the MVP local ports (Router 8080, Registry 8081) so a fresh
  /// checkout runs against a localhost stack without configuration.
  static const defaultRouterBaseUrl = 'http://127.0.0.1:8080';
  static const defaultRegistryBaseUrl = 'http://127.0.0.1:8081';

  /// Compile-time `--dart-define` overrides. Flutter bakes these into the binary
  /// and they are read with `String.fromEnvironment` — crucially they are NOT
  /// visible via `Platform.environment`, so `--dart-define=BARD_ROUTER_URL=...`
  /// is ignored unless read here (bug: an Android build picked up neither the
  /// URL nor the token and fell back to localhost:8080/8081). Empty when unset.
  static const _routerDefine = String.fromEnvironment(routerUrlKey);
  static const _registryDefine = String.fromEnvironment(registryUrlKey);
  static const _tokenDefine = String.fromEnvironment(tokenKey);

  final String routerBaseUrl;
  final String registryBaseUrl;

  /// Bearer token for the Router/Registry. Empty when unset — the UI treats an
  /// empty token as "needs configuration" rather than sending `Bearer `.
  final String authToken;

  /// Build config from an environment map (defaults to the process environment).
  /// Blank/whitespace values fall back to the defaults so an exported-but-empty
  /// variable doesn't blank out the endpoint.
  factory AppConfig.fromEnvironment([Map<String, String>? environment]) {
    final env = environment ?? Platform.environment;
    return AppConfig(
      routerBaseUrl: resolve(env[routerUrlKey], _routerDefine, defaultRouterBaseUrl),
      registryBaseUrl: resolve(env[registryUrlKey], _registryDefine, defaultRegistryBaseUrl),
      authToken: resolve(env[tokenKey], _tokenDefine, ''),
    );
  }

  AppConfig copyWith({
    String? routerBaseUrl,
    String? registryBaseUrl,
    String? authToken,
  }) {
    return AppConfig(
      routerBaseUrl: routerBaseUrl ?? this.routerBaseUrl,
      registryBaseUrl: registryBaseUrl ?? this.registryBaseUrl,
      authToken: authToken ?? this.authToken,
    );
  }

  /// Resolution precedence, highest first: a non-blank runtime value (injected
  /// map / `Platform.environment`), then a non-blank compile-time
  /// `--dart-define`, then [fallback]. Blank/whitespace-only values are treated
  /// as unset at each layer. Public so the precedence branches are unit-testable
  /// — `--dart-define` values are compile-time and can't be injected at runtime.
  static String resolve(String? envValue, String define, String fallback) {
    final fromEnv = envValue?.trim() ?? '';
    if (fromEnv.isNotEmpty) return fromEnv;
    final fromDefine = define.trim();
    if (fromDefine.isNotEmpty) return fromDefine;
    return fallback;
  }
}
