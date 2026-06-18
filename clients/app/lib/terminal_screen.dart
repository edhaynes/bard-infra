import 'dart:convert';

import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';

import 'app_state.dart';
import 'connection.dart';

/// Terminal tab — an ssh-backed shell into the active connection's UBI-9 agent
/// (feature #38). Auto-connects on open using the active [Connection]'s
/// host/port/user (no manual form); lands at the container's `[bard@ubi9 ~]$`
/// prompt. Key-based auth is the production path; the connection's password
/// field is a dev convenience. Reconnect re-reads the active connection.
class TerminalScreen extends StatefulWidget {
  const TerminalScreen({super.key, required this.state});

  final AppState state;

  @override
  State<TerminalScreen> createState() => _TerminalScreenState();
}

class _TerminalScreenState extends State<TerminalScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();

  SSHClient? _client;
  SSHSession? _session;
  final _buffer = StringBuffer();
  String _status = 'disconnected';
  String? _connectedTo; // connection id we attached to, to detect changes.

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeAutoConnect());
  }

  @override
  void didUpdateWidget(TerminalScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    _maybeAutoConnect();
  }

  @override
  void dispose() {
    _session?.close();
    _client?.close();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _maybeAutoConnect() {
    final conn = widget.state.activeConnection;
    if (conn == null || _session != null) return;
    if (_connectedTo == conn.id && _status == 'connecting…') return;
    _connect(conn);
  }

  void _append(String text) {
    setState(() => _buffer.write(text));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  Future<void> _connect(Connection conn) async {
    setState(() {
      _status = 'connecting…';
      _connectedTo = conn.id;
    });
    _append('Connecting to ${conn.sshUser}@${conn.agentHost}:${conn.sshPort}…\n');
    try {
      final socket = await SSHSocket.connect(conn.agentHost, conn.sshPort);
      final client = SSHClient(
        socket,
        username: conn.sshUser,
        onPasswordRequest: () => conn.sshPassword,
      );
      final session = await client.shell(pty: const SSHPtyConfig(width: 80, height: 25));
      session.stdout.listen((d) => _append(utf8.decode(d, allowMalformed: true)));
      session.stderr.listen((d) => _append(utf8.decode(d, allowMalformed: true)));
      if (!mounted) return;
      setState(() {
        _client = client;
        _session = session;
        _status = 'connected';
      });
    } catch (e) {
      _append('\n[connect failed: $e]\n');
      if (mounted) setState(() => _status = 'error');
    }
  }

  void _send() {
    final session = _session;
    if (session == null) return;
    session.write(utf8.encode('${_input.text}\n'));
    _input.clear();
  }

  void _disconnect() {
    _session?.close();
    _client?.close();
    setState(() {
      _session = null;
      _client = null;
      _status = 'disconnected';
    });
  }

  void _reconnect() {
    _disconnect();
    final conn = widget.state.activeConnection;
    if (conn != null) _connect(conn);
  }

  @override
  Widget build(BuildContext context) {
    final conn = widget.state.activeConnection;
    final connected = _session != null;
    return Scaffold(
      appBar: AppBar(
        title: Text(conn == null ? 'Terminal' : 'Terminal · ${conn.name}'),
        actions: [
          Center(child: Text(_status, style: const TextStyle(fontSize: 12))),
          IconButton(
            tooltip: 'Reconnect',
            onPressed: conn == null ? null : _reconnect,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: conn == null
          ? const _NoConnection()
          : Column(
              children: [
                Expanded(child: _console()),
                if (connected) _inputBar(),
              ],
            ),
    );
  }

  Widget _console() => Container(
        width: double.infinity,
        color: const Color(0xFF101418),
        padding: const EdgeInsets.all(12),
        child: SingleChildScrollView(
          controller: _scroll,
          child: SelectableText(
            _buffer.isEmpty ? 'Not connected.' : _buffer.toString(),
            style: const TextStyle(
              fontFamily: 'monospace',
              color: Color(0xFFD6E2EE),
              fontSize: 13,
            ),
          ),
        ),
      );

  Widget _inputBar() => SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(
                      hintText: r'$ command', isDense: true, prefixText: '> '),
                ),
              ),
              IconButton(onPressed: _send, icon: const Icon(Icons.keyboard_return)),
              IconButton(onPressed: _disconnect, icon: const Icon(Icons.link_off)),
            ],
          ),
        ),
      );
}

class _NoConnection extends StatelessWidget {
  const _NoConnection();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Text(
          'No active connection.\nAdd one on the Connections tab to open a terminal.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
