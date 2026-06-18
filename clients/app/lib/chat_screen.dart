import 'package:flutter/material.dart';

import 'api.dart';
import 'app_state.dart';

/// Chat tab — same role as the consumer app's Chat: a bubble conversation with a
/// model. In Pro it routes through the active connection's Router
/// (`POST /v1/message`, the Bard JSON envelope) targeting the agent picked
/// from the model list, rather than calling an OpenAI endpoint directly.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.state});

  final AppState state;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _Message {
  _Message(this.text, {required this.fromUser});
  final String text;
  final bool fromUser;
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<_Message> _messages = [];
  String? _targetAgent;
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _targetAgent = widget.state.models.isEmpty ? null : widget.state.models.first.id;
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  bool get _canSend =>
      !_sending &&
      widget.state.api != null &&
      _targetAgent != null &&
      _input.text.trim().isNotEmpty;

  Future<void> _send() async {
    final api = widget.state.api;
    final target = _targetAgent;
    final text = _input.text.trim();
    if (api == null || target == null || text.isEmpty || _sending) return;

    setState(() {
      _messages.add(_Message(text, fromUser: true));
      _sending = true;
      _input.clear();
    });
    _scrollToEnd();

    try {
      final reply = await api.sendMessage(targetAgent: target, content: text);
      if (!mounted) return;
      setState(() => _messages.add(_Message(reply.content, fromUser: false)));
    } on BardApiException catch (e) {
      if (!mounted) return;
      final suffix = e.retryable ? ' (retryable — try again)' : '';
      setState(() => _messages.add(_Message('[error] ${e.message}$suffix', fromUser: false)));
    } finally {
      if (mounted) setState(() => _sending = false);
      _scrollToEnd();
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  @override
  Widget build(BuildContext context) {
    final hasConnection = widget.state.api != null;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Chat'),
        actions: [if (hasConnection) _agentPicker()],
      ),
      body: !hasConnection
          ? const _NoConnection()
          : Column(
              children: [
                Expanded(child: _conversation()),
                if (_sending) const LinearProgressIndicator(minHeight: 2),
                _inputBar(),
              ],
            ),
    );
  }

  Widget _agentPicker() {
    final models = widget.state.models;
    return Padding(
      padding: const EdgeInsets.only(right: 12),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: _targetAgent,
          hint: const Text('agent'),
          items: [
            for (final m in models) DropdownMenuItem(value: m.id, child: Text(m.name)),
          ],
          onChanged: (v) => setState(() => _targetAgent = v),
        ),
      ),
    );
  }

  Widget _conversation() {
    if (_messages.isEmpty) {
      return const Center(child: Text('Send a message to the selected agent.'));
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.all(12),
      itemCount: _messages.length,
      itemBuilder: (context, i) => _Bubble(message: _messages[i]),
    );
  }

  Widget _inputBar() => SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  onChanged: (_) => setState(() {}),
                  onSubmitted: (_) => _canSend ? _send() : null,
                  decoration: const InputDecoration(
                    hintText: 'Message', isDense: true, border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                onPressed: _canSend ? _send : null,
                icon: const Icon(Icons.send),
              ),
            ],
          ),
        ),
      );
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message});

  final _Message message;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final fromUser = message.fromUser;
    return Align(
      alignment: fromUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: const BoxConstraints(maxWidth: 520),
        decoration: BoxDecoration(
          color: fromUser ? scheme.primaryContainer : scheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: SelectableText(message.text),
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
          'No active connection.\nAdd one on the Connections tab to start chatting.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
