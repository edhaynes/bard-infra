import 'dart:convert';

import 'package:bard_pro/app_state.dart';
import 'package:bard_pro/chat_screen.dart';
import 'package:bard_pro/connection.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Widget tests for the Chat tab against the contract, driven through an injected
/// `MockClient` (no network). Covers the success render and the error-envelope
/// render (retryable 502 agent_unavailable), plus the offline gate.
void main() {
  List<Connection> oneConnection() => const [
        Connection(
          id: 'c1',
          name: 'test',
          routerBaseUrl: 'https://router.test',
          registryBaseUrl: 'https://registry.test',
          agentHost: 'router.test',
          token: 'tok',
        ),
      ];

  AppState stateWith(MockClient client) => AppState(
        connections: oneConnection(),
        httpClient: client,
      );

  Widget wrap(AppState state) => MaterialApp(home: ChatScreen(state: state));

  testWidgets('renders the agent reply on a 200 Response', (tester) async {
    final client = MockClient((req) async {
      if (req.url.path.endsWith('/agents')) {
        return http.Response(
          jsonEncode([
            {'agentId': 'gpu-1', 'address': '10.0.0.5:8444'},
          ]),
          200,
        );
      }
      return http.Response(
        jsonEncode({
          'id': (jsonDecode(req.body) as Map)['id'],
          'type': 'text',
          'content': 'pong',
          'metadata': {'agentId': 'gpu-1'},
        }),
        200,
      );
    });
    final state = stateWith(client);
    await state.refreshModels();
    await tester.pumpWidget(wrap(state));
    await tester.pump();

    await tester.enterText(find.byType(TextField), 'ping');
    await tester.pump();
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump(); // user bubble + sending
    await tester.pump(); // reply settles

    expect(find.text('ping'), findsOneWidget);
    expect(find.text('pong'), findsOneWidget);
  });

  testWidgets('renders a retryable error on 502 agent_unavailable', (tester) async {
    final client = MockClient((req) async {
      if (req.url.path.endsWith('/agents')) {
        return http.Response(
          jsonEncode([
            {'agentId': 'gpu-1', 'address': '10.0.0.5:8444'},
          ]),
          200,
        );
      }
      return http.Response(
        jsonEncode({'error': 'agent_unavailable', 'retry': true, 'detail': 'offline'}),
        502,
      );
    });
    final state = stateWith(client);
    await state.refreshModels();
    await tester.pumpWidget(wrap(state));
    await tester.pump();

    await tester.enterText(find.byType(TextField), 'ping');
    await tester.pump();
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
    await tester.pump();

    expect(find.textContaining('agent_unavailable'), findsOneWidget);
    expect(find.textContaining('retryable'), findsOneWidget);
  });

  testWidgets('offline state gates the composer behind a prompt', (tester) async {
    final state = AppState(connections: const []);
    await tester.pumpWidget(wrap(state));
    await tester.pump();
    expect(find.textContaining('No active connection'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
  });
}
