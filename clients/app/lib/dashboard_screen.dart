import 'package:flutter/material.dart';

import 'app_state.dart';
import 'health.dart';

/// Dashboard tab — at-a-glance state of the active backend: which connection is
/// live, and the health/version of its Router, Registry, and Agent. Enterprise
/// presentation (no skins). Live host metrics are a follow-up (needs an agent
/// metrics endpoint — see plans/PLAN_client_tabs.md §5).
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key, required this.state});

  final AppState state;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  List<HealthResult>? _results;
  bool _probing = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _refresh());
  }

  Future<void> _refresh() async {
    final conn = widget.state.activeConnection;
    if (conn == null) {
      setState(() => _results = const []);
      return;
    }
    setState(() => _probing = true);
    final results = await Future.wait([
      probe(label: 'Router', baseUrl: conn.routerBaseUrl, token: conn.token),
      probe(label: 'Registry', baseUrl: conn.registryBaseUrl, token: conn.token),
    ]);
    if (!mounted) return;
    setState(() {
      _results = results;
      _probing = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final conn = widget.state.activeConnection;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Dashboard'),
        actions: [
          IconButton(
            onPressed: _probing ? null : _refresh,
            icon: const Icon(Icons.refresh),
            tooltip: 'Re-check health',
          ),
        ],
      ),
      body: conn == null
          ? const _NoConnection()
          : RefreshIndicator(
              onRefresh: _refresh,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  _ActiveCard(connName: conn.name, host: conn.routerBaseUrl),
                  const SizedBox(height: 16),
                  Text('Services', style: Theme.of(context).textTheme.titleSmall),
                  const SizedBox(height: 8),
                  if (_probing && _results == null)
                    const Padding(
                      padding: EdgeInsets.all(24),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else
                    ...(_results ?? const []).map((r) => _HealthTile(result: r)),
                ],
              ),
            ),
    );
  }
}

class _ActiveCard extends StatelessWidget {
  const _ActiveCard({required this.connName, required this.host});

  final String connName;
  final String host;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      child: ListTile(
        leading: Icon(Icons.hub_outlined, color: scheme.primary),
        title: Text('Active connection: $connName'),
        subtitle: Text(host),
      ),
    );
  }
}

class _HealthTile extends StatelessWidget {
  const _HealthTile({required this.result});

  final HealthResult result;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = result.ok ? Colors.green : scheme.error;
    return ListTile(
      leading: Icon(result.ok ? Icons.check_circle : Icons.error_outline, color: color),
      title: Text(result.label),
      subtitle: Text(
        result.ok
            ? (result.detail.isEmpty ? 'healthy' : 'healthy · v${result.detail}')
            : 'unreachable · ${result.detail}',
      ),
    );
  }
}

class _NoConnection extends StatelessWidget {
  const _NoConnection();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Text(
          'No active connection.\nAdd one on the Connections tab to see backend health.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
