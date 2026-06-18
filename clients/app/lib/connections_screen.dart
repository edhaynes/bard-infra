import 'package:flutter/material.dart';

import 'app_state.dart';
import 'connection.dart';
import 'health.dart';

/// Connections tab — define/select the backend the rest of the app talks to.
/// One connection is active (radio); Dashboard, Terminal, Chat, and Models all
/// read it. CRUD is in-memory this pass (persistence is a flagged follow-up).
class ConnectionsScreen extends StatelessWidget {
  const ConnectionsScreen({super.key, required this.state});

  final AppState state;

  Future<void> _edit(BuildContext context, Connection? existing) async {
    final result = await showDialog<Connection>(
      context: context,
      builder: (_) => _ConnectionDialog(existing: existing),
    );
    if (result != null) state.upsert(result);
  }

  @override
  Widget build(BuildContext context) {
    final active = state.activeConnection;
    return Scaffold(
      appBar: AppBar(title: const Text('Connections')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _edit(context, null),
        icon: const Icon(Icons.add),
        label: const Text('Add'),
      ),
      body: state.connections.isEmpty
          ? const Center(child: Text('No connections. Add one to get started.'))
          : ListView(
              children: [
                for (final c in state.connections)
                  _ConnectionTile(
                    connection: c,
                    active: c.id == active?.id,
                    onSelect: () => state.setActive(c.id),
                    onEdit: () => _edit(context, c),
                    onDelete: () => state.remove(c.id),
                  ),
              ],
            ),
    );
  }
}

class _ConnectionTile extends StatelessWidget {
  const _ConnectionTile({
    required this.connection,
    required this.active,
    required this.onSelect,
    required this.onEdit,
    required this.onDelete,
  });

  final Connection connection;
  final bool active;
  final VoidCallback onSelect;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ListTile(
      leading: IconButton(
        tooltip: active ? 'Active' : 'Set active',
        onPressed: onSelect,
        icon: Icon(
          active ? Icons.radio_button_checked : Icons.radio_button_unchecked,
          color: active ? scheme.primary : null,
        ),
      ),
      title: Text(connection.name + (active ? '  ·  active' : '')),
      subtitle: Text(
        'router ${connection.routerBaseUrl}\n'
        'agent ${connection.agentHost}:${connection.sshPort} (${connection.sshUser})',
      ),
      isThreeLine: true,
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _TestButton(connection: connection),
          IconButton(onPressed: onEdit, icon: const Icon(Icons.edit_outlined)),
          IconButton(onPressed: onDelete, icon: const Icon(Icons.delete_outline)),
        ],
      ),
      onTap: onSelect,
    );
  }
}

class _TestButton extends StatefulWidget {
  const _TestButton({required this.connection});

  final Connection connection;

  @override
  State<_TestButton> createState() => _TestButtonState();
}

class _TestButtonState extends State<_TestButton> {
  bool _busy = false;

  Future<void> _test() async {
    setState(() => _busy = true);
    final r = await probe(
      label: 'Router',
      baseUrl: widget.connection.routerBaseUrl,
      token: widget.connection.token,
    );
    if (!mounted) return;
    setState(() => _busy = false);
    final msg = r.ok ? 'Router healthy' : 'Router unreachable · ${r.detail}';
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: 'Test connection',
      onPressed: _busy ? null : _test,
      icon: _busy
          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
          : const Icon(Icons.network_check),
    );
  }
}

/// Add/edit form. Returns a [Connection] (new id for new entries) or null on cancel.
class _ConnectionDialog extends StatefulWidget {
  const _ConnectionDialog({this.existing});

  final Connection? existing;

  @override
  State<_ConnectionDialog> createState() => _ConnectionDialogState();
}

class _ConnectionDialogState extends State<_ConnectionDialog> {
  late final TextEditingController _name;
  late final TextEditingController _router;
  late final TextEditingController _registry;
  late final TextEditingController _agentHost;
  late final TextEditingController _sshPort;
  late final TextEditingController _sshUser;
  late final TextEditingController _sshPassword;
  late final TextEditingController _token;

  @override
  void initState() {
    super.initState();
    final e = widget.existing;
    _name = TextEditingController(text: e?.name ?? '');
    _router = TextEditingController(text: e?.routerBaseUrl ?? 'http://127.0.0.1:8080');
    _registry = TextEditingController(text: e?.registryBaseUrl ?? 'http://127.0.0.1:8081');
    _agentHost = TextEditingController(text: e?.agentHost ?? '127.0.0.1');
    _sshPort = TextEditingController(text: '${e?.sshPort ?? 2222}');
    _sshUser = TextEditingController(text: e?.sshUser ?? 'bard');
    _sshPassword = TextEditingController(text: e?.sshPassword ?? '');
    _token = TextEditingController(text: e?.token ?? '');
  }

  @override
  void dispose() {
    for (final c in [_name, _router, _registry, _agentHost, _sshPort, _sshUser, _sshPassword, _token]) {
      c.dispose();
    }
    super.dispose();
  }

  void _save() {
    final id = widget.existing?.id ??
        _name.text.trim().toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '-');
    final conn = Connection(
      id: id.isEmpty ? 'conn-${DateTime.now().microsecondsSinceEpoch}' : id,
      name: _name.text.trim().isEmpty ? 'unnamed' : _name.text.trim(),
      routerBaseUrl: _router.text.trim(),
      registryBaseUrl: _registry.text.trim(),
      agentHost: _agentHost.text.trim(),
      sshPort: int.tryParse(_sshPort.text.trim()) ?? 2222,
      sshUser: _sshUser.text.trim(),
      sshPassword: _sshPassword.text,
      token: _token.text.trim(),
      useTls: _router.text.trim().startsWith('https'),
    );
    Navigator.of(context).pop(conn);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.existing == null ? 'Add connection' : 'Edit connection'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _field(_name, 'Name'),
              _field(_router, 'Router base URL'),
              _field(_registry, 'Registry base URL'),
              _field(_agentHost, 'Agent host (ssh)'),
              Row(children: [
                Expanded(child: _field(_sshPort, 'ssh port')),
                const SizedBox(width: 8),
                Expanded(flex: 2, child: _field(_sshUser, 'ssh user')),
              ]),
              _field(_sshPassword, 'ssh password (dev)', obscure: true),
              _field(_token, 'Bearer token', obscure: true),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _save, child: const Text('Save')),
      ],
    );
  }

  Widget _field(TextEditingController c, String label, {bool obscure = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: TextField(
          controller: c,
          obscureText: obscure,
          decoration: InputDecoration(labelText: label, isDense: true),
        ),
      );
}
