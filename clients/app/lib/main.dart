import 'dart:io' show Platform;

import 'package:flutter/material.dart';

import 'app_state.dart';
import 'box/box_screen.dart';
import 'box/redeem.dart';
import 'chat_screen.dart';
import 'connections_screen.dart';
import 'dashboard_screen.dart';
import 'deep_link.dart';
import 'models_screen.dart';
import 'terminal_screen.dart';

void main() => runApp(const BardProApp());

/// Number of bottom-nav tabs in the shell.
const _tabCount = 6;

/// Initial tab index, overridable via the BARD_INITIAL_TAB env var (0-5) so the
/// shell can be launched directly onto a given tab for screenshot capture.
int _initialTab() {
  final v = int.tryParse(Platform.environment['BARD_INITIAL_TAB'] ?? '');
  return (v != null && v >= 0 && v < _tabCount) ? v : 0;
}

class BardProApp extends StatelessWidget {
  const BardProApp({super.key, this.state, this.deepLinks});

  /// Optional injected state (tests pass a connection-less [AppState] to keep the
  /// shell offline). Production builds let [HomeShell] seed the default.
  final AppState? state;

  /// Optional injected deep-link service. Null in tests so the shell never
  /// touches the `app_links` platform channel (CLAUDE.md §9); production builds
  /// let [HomeShell] construct the real one.
  final DeepLinkService? deepLinks;

  @override
  Widget build(BuildContext context) {
    final navigatorKey = GlobalKey<NavigatorState>();
    return MaterialApp(
      title: 'Bard',
      debugShowCheckedModeBanner: false,
      navigatorKey: navigatorKey,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF35506B)),
        useMaterial3: true,
      ),
      home: HomeShell(state: state, deepLinks: deepLinks, navigatorKey: navigatorKey),
    );
  }
}

/// Five-tab shell: Dashboard · Connections · Terminal · Chat · Models. Mirrors the
/// consumer app's persisted-tab `TabView` shape (LlamaServerApp.swift) but in
/// Flutter with a bottom `NavigationBar`. An [IndexedStack] keeps every tab's
/// state alive across switches (Chat history, Terminal session) while the nav bar
/// stays reachable — avoiding the consumer app's terminal/chat-trap bugs.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.state, this.deepLinks, this.navigatorKey});

  final AppState? state;

  /// Deep-link receiver (null in tests / when unavailable). Production builds it.
  final DeepLinkService? deepLinks;

  /// Used to push the redeem screen when a deep link arrives.
  final GlobalKey<NavigatorState>? navigatorKey;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  // In-memory this pass; persisting the index (and connections) is a flagged
  // follow-up requiring shared_preferences sign-off (plan §6). The initial tab
  // can be overridden via BARD_INITIAL_TAB (0-4) for CLI-driven screenshot
  // capture — mirrors the consumer app's @AppStorage("selectedTab") affordance.
  int _index = _initialTab();
  late final AppState _state;
  late final bool _ownsState;
  DeepLinkService? _deepLinks;
  bool _ownsDeepLinks = false;

  @override
  void initState() {
    super.initState();
    _ownsState = widget.state == null;
    _state = widget.state ?? AppState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _state.refreshModels();
      _selfRegister();
      _startDeepLinks();
    });
  }

  /// Wire the deep-link receiver: an injected one (tests) or, in production,
  /// the real [DeepLinkService]. A received invite token pushes the redeem
  /// screen onto the app navigator.
  void _startDeepLinks() {
    final service = widget.deepLinks ?? (widget.state == null ? DeepLinkService() : null);
    if (service == null) return;
    _ownsDeepLinks = widget.deepLinks == null;
    _deepLinks = service;
    service.start(_onInviteToken);
  }

  /// First-launch (and every-relaunch, idempotent) device self-register
  /// (ADR-0016 §3): generate the single device identity if needed and register
  /// its public key so the device's self-signed tokens verify server-side.
  /// Best-effort and silent — a backend that is offline at launch surfaces via
  /// the Box screen's error on the first owner action, not a startup crash.
  void _selfRegister() {
    _state.boxController?.selfRegister();
  }

  void _onInviteToken(String token) {
    final navigator = widget.navigatorKey?.currentState;
    final controller = _state.boxController;
    if (navigator == null || controller == null) return;
    navigator.push(
      MaterialPageRoute<void>(
        builder: (_) => RedeemScreen(controller: controller, token: token),
      ),
    );
  }

  @override
  void dispose() {
    if (_ownsDeepLinks) _deepLinks?.dispose();
    if (_ownsState) _state.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _state,
      builder: (context, _) {
        final boxController = _state.boxController;
        final pages = [
          DashboardScreen(state: _state),
          ConnectionsScreen(state: _state),
          TerminalScreen(state: _state),
          ChatScreen(state: _state),
          ModelsScreen(
            models: _state.models,
            onRefresh: _state.api == null ? null : _state.refreshModels,
          ),
          boxController == null
              ? const _NoBoxBackend()
              : BoxScreen(
                  controller: boxController,
                  recoveryController: _state.recoveryController,
                ),
        ];
        return Scaffold(
          body: IndexedStack(index: _index, children: pages),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            destinations: const [
              NavigationDestination(icon: Icon(Icons.dashboard_outlined), label: 'Dashboard'),
              NavigationDestination(icon: Icon(Icons.hub_outlined), label: 'Connections'),
              NavigationDestination(icon: Icon(Icons.terminal_outlined), label: 'Terminal'),
              NavigationDestination(icon: Icon(Icons.chat_outlined), label: 'Chat'),
              NavigationDestination(icon: Icon(Icons.view_list_outlined), label: 'Models'),
              NavigationDestination(icon: Icon(Icons.inbox_outlined), label: 'Box'),
            ],
          ),
        );
      },
    );
  }
}

/// Fallback for the Box tab when no connection is active (no backend to create
/// or join a box against).
class _NoBoxBackend extends StatelessWidget {
  const _NoBoxBackend();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Box')),
      body: const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'Add a connection first, then you can create or join a box.',
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}
