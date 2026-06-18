import 'dart:convert';

import 'package:bard_pro/app_state.dart';
import 'package:bard_pro/config.dart';
import 'package:bard_pro/connection.dart';
import 'package:bard_pro/model_info.dart';
import 'package:bard_pro/models_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Tests for the model-list flow: AppState.refreshModels against the Registry
/// (success / empty-falls-back / error-keeps-list) and the Models screen render.
void main() {
  List<Connection> oneConnection() => const [
        Connection(
          id: 'c1',
          name: 'test',
          routerBaseUrl: 'https://router.test',
          registryBaseUrl: 'https://registry.test',
          agentHost: 'registry.test',
          token: 'tok',
        ),
      ];

  group('AppState.refreshModels', () {
    test('replaces the list with live agents', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode([
              {'agentId': 'gpu-1', 'address': '10.0.0.5:8444', 'capabilities': ['gpu']},
            ]),
            200,
          ));
      final state = AppState(connections: oneConnection(), httpClient: client);
      await state.refreshModels();
      expect(state.models, hasLength(1));
      expect(state.models.single.id, 'gpu-1');
    });

    test('falls back to sample models on an empty list (UI never blanks)', () async {
      final client = MockClient((_) async => http.Response('[]', 200));
      final state = AppState(connections: oneConnection(), httpClient: client);
      await state.refreshModels();
      expect(state.models, equals(sampleModels));
    });

    test('keeps the last good list when the Registry errors', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({'error': 'unauthorized'}),
            401,
          ));
      final state = AppState(connections: oneConnection(), httpClient: client);
      final before = state.models;
      await state.refreshModels();
      expect(state.models, equals(before)); // unchanged, not cleared
    });

    test('is a no-op with no active connection', () async {
      final state = AppState(connections: const []);
      await state.refreshModels();
      expect(state.models, equals(sampleModels));
    });
  });

  group('AppState wiring', () {
    test('seeds the default connection from config', () {
      const cfg = AppConfig(
        routerBaseUrl: 'https://r.example',
        registryBaseUrl: 'https://g.example',
        authToken: 'seed-tok',
      );
      final state = AppState(config: cfg);
      final c = state.activeConnection!;
      expect(c.routerBaseUrl, 'https://r.example');
      expect(c.registryBaseUrl, 'https://g.example');
      expect(c.token, 'seed-tok');
      expect(state.api, isNotNull);
    });

    test('exposes a null api when no connection is active', () {
      expect(AppState(connections: const []).api, isNull);
    });
  });

  testWidgets('ModelsScreen renders rows with a status chip', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: ModelsScreen(models: sampleModels),
    ));
    await tester.pump();
    expect(find.text('Gemma 3 4B'), findsOneWidget);
    expect(find.text('ready'), findsWidgets);
    expect(find.text('offline'), findsOneWidget);
  });
}
