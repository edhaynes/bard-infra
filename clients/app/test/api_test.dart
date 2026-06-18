import 'dart:convert';

import 'package:bard_pro/api.dart';
import 'package:bard_pro/protocol.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Contract-level tests for [BardApi] against the FROZEN Router/Registry shapes.
/// All requests go through a `MockClient` — no real network (CLAUDE.md §9).
/// Covers the success path and every failure branch: status codes, the error
/// envelope (incl. retryable 502 agent_unavailable), timeouts, transport
/// errors, and malformed bodies.
void main() {
  const router = 'https://router.test:8443';
  const registry = 'https://registry.test:8081';
  const token = 'jwt-token';

  BardApi apiWith(MockClient client, {String Function()? idFactory}) => BardApi(
        routerBaseUrl: router,
        registryBaseUrl: registry,
        token: token,
        httpClient: client,
        idFactory: idFactory ?? () => '00000000-0000-0000-0000-000000000001',
        listTimeout: const Duration(milliseconds: 50),
        messageTimeout: const Duration(milliseconds: 50),
      );

  group('listAgents (GET /agents)', () {
    test('parses an agent list into ModelInfo', () async {
      final client = MockClient((req) async {
        expect(req.method, 'GET');
        expect(req.url.toString(), '$registry/agents');
        expect(req.headers['Authorization'], 'Bearer $token');
        return http.Response(
          jsonEncode([
            {'agentId': 'gpu-1', 'address': '10.0.0.5:8444', 'capabilities': ['gpu', 'llm']},
            {'agentId': 'cpu-1', 'address': '10.0.0.6:8444'},
          ]),
          200,
          headers: {'content-type': 'application/json'},
        );
      });
      final models = await apiWith(client).listAgents();
      expect(models, hasLength(2));
      expect(models.first.id, 'gpu-1');
      expect(models.first.provider, 'GPU agent');
      expect(models[1].provider, 'agent');
    });

    test('returns an empty list for an empty array (empty model list)', () async {
      final client = MockClient((_) async => http.Response('[]', 200));
      expect(await apiWith(client).listAgents(), isEmpty);
    });

    test('omits the Authorization header when token is empty', () async {
      String? auth;
      final client = MockClient((req) async {
        auth = req.headers['Authorization'];
        return http.Response('[]', 200);
      });
      final api = BardApi(
        routerBaseUrl: router,
        registryBaseUrl: registry,
        token: '',
        httpClient: client,
      );
      await api.listAgents();
      expect(auth, isNull);
    });

    test('throws on a 401 error envelope', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({'error': 'unauthorized'}),
            401,
          ));
      await expectLater(
        apiWith(client).listAgents(),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.errorEnvelope && e.error?.code == 'unauthorized',
        )),
      );
    });

    test('throws on a non-200 with a non-envelope body (status only)', () async {
      final client = MockClient((_) async => http.Response('<html>500</html>', 500));
      await expectLater(
        apiWith(client).listAgents(),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.httpStatus && e.statusCode == 500 && e.retryable,
        )),
      );
    });

    test('throws malformed when the body is not a JSON array', () async {
      final client = MockClient((_) async => http.Response('{"not":"array"}', 200));
      await expectLater(
        apiWith(client).listAgents(),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });

    test('throws malformed when an element is not an object', () async {
      final client = MockClient((_) async => http.Response('[1,2,3]', 200));
      await expectLater(
        apiWith(client).listAgents(),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });

    test('throws malformed when the 200 body is invalid JSON', () async {
      final client = MockClient((_) async => http.Response('not json{', 200));
      await expectLater(
        apiWith(client).listAgents(),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });
  });

  group('sendMessage (POST /v1/message)', () {
    String successBody(String id) => jsonEncode({
          'id': id,
          'type': 'text',
          'content': 'hello back',
          'metadata': {'agentId': 'gpu-1'},
        });

    test('sends a conformant Request envelope and parses the Response', () async {
      Map<String, dynamic>? sent;
      final client = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.toString(), '$router/v1/message');
        sent = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(successBody('00000000-0000-0000-0000-000000000001'), 200);
      });
      final resp = await apiWith(client).sendMessage(
        targetAgent: 'gpu-1',
        content: 'hello',
        sessionId: 'sess-1',
      );
      expect(resp.content, 'hello back');
      expect(resp.metadata.agentId, 'gpu-1');
      // Request envelope conforms to protocol.schema.json.
      expect(sent!['id'], '00000000-0000-0000-0000-000000000001');
      expect(sent!['type'], 'text');
      expect(sent!['content'], 'hello');
      final meta = sent!['metadata'] as Map<String, dynamic>;
      expect(meta['targetAgent'], 'gpu-1');
      expect(meta['authToken'], token);
      expect(meta['sessionId'], 'sess-1');
    });

    test('throws a retryable error on 502 agent_unavailable retry=true', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({
              'error': 'agent_unavailable',
              'retry': true,
              'detail': 'agent offline',
            }),
            502,
          ));
      await expectLater(
        apiWith(client).sendMessage(targetAgent: 'a', content: 'x'),
        throwsA(predicate<BardApiException>(
          (e) =>
              e.kind == ApiFailureKind.errorEnvelope &&
              e.statusCode == 502 &&
              e.error?.code == 'agent_unavailable' &&
              e.retryable &&
              e.message.contains('agent offline'),
        )),
      );
    });

    test('throws not_found (non-retryable) on 404', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({'error': 'not_found'}),
            404,
          ));
      await expectLater(
        apiWith(client).sendMessage(targetAgent: 'ghost', content: 'x'),
        throwsA(predicate<BardApiException>(
          (e) => e.error?.code == 'not_found' && !e.retryable,
        )),
      );
    });

    test('throws unsupported_type on 501', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({'error': 'unsupported_type'}),
            501,
          ));
      await expectLater(
        apiWith(client).sendMessage(targetAgent: 'a', content: 'x'),
        throwsA(predicate<BardApiException>((e) => e.error?.code == 'unsupported_type')),
      );
    });

    test('falls back to status-only when the error code is an empty string', () async {
      // Passes the `error is String` guard but fails BardError.fromJson, hitting
      // the ProtocolFormatException fall-through.
      final client = MockClient((_) async => http.Response(
            jsonEncode({'error': ''}),
            400,
          ));
      await expectLater(
        apiWith(client).sendMessage(targetAgent: 'a', content: 'x'),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.httpStatus && e.statusCode == 400,
        )),
      );
    });

    test('falls back to status-only when the error body lacks a code', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({'detail': 'no code here'}),
            400,
          ));
      await expectLater(
        apiWith(client).sendMessage(targetAgent: 'a', content: 'x'),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.httpStatus && e.statusCode == 400 && !e.retryable,
        )),
      );
    });

    test('throws malformed when the 200 body violates the Response schema', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({'id': 'x', 'type': 'text', 'content': 'c'}), // no metadata
            200,
          ));
      await expectLater(
        apiWith(client).sendMessage(targetAgent: 'a', content: 'x'),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });

    test('throws malformed when the 200 body is a JSON array, not an object', () async {
      final client = MockClient((_) async => http.Response('[]', 200));
      await expectLater(
        apiWith(client).sendMessage(targetAgent: 'a', content: 'x'),
        throwsA(predicate<BardApiException>((e) => e.kind == ApiFailureKind.malformed)),
      );
    });
  });

  group('transport failures', () {
    test('maps a timeout to a retryable timeout exception', () async {
      final client = MockClient((_) async {
        await Future<void>.delayed(const Duration(seconds: 1));
        return http.Response('[]', 200);
      });
      await expectLater(
        apiWith(client).listAgents(),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.timeout && e.retryable,
        )),
      );
    });

    test('maps a ClientException to a retryable network exception', () async {
      final client = MockClient((_) async => throw http.ClientException('connection reset'));
      await expectLater(
        apiWith(client).sendMessage(targetAgent: 'a', content: 'x'),
        throwsA(predicate<BardApiException>(
          (e) => e.kind == ApiFailureKind.network && e.retryable,
        )),
      );
    });
  });

  group('BardApiException', () {
    test('toString returns the human message', () {
      final e = BardApiException.status(503);
      expect(e.toString(), 'HTTP 503');
    });

    test('envelope message omits detail when absent', () {
      final e = BardApiException.fromEnvelope(404, const BardError(code: 'not_found'));
      expect(e.message, 'not_found');
    });

    test('default idFactory produces a UUID-shaped id', () async {
      // Exercise the production id path (no injected idFactory).
      String? sentId;
      final client = MockClient((req) async {
        sentId = (jsonDecode(req.body) as Map)['id'] as String;
        return http.Response(
          jsonEncode({
            'id': sentId,
            'type': 'text',
            'content': 'c',
            'metadata': {'agentId': 'a'},
          }),
          200,
        );
      });
      final api = BardApi(
        routerBaseUrl: router,
        registryBaseUrl: registry,
        token: token,
        httpClient: client,
      );
      await api.sendMessage(targetAgent: 'a', content: 'hi');
      expect(
        RegExp(r'^[0-9a-fA-F-]{36}$').hasMatch(sentId!),
        isTrue,
        reason: 'id "$sentId" should be UUID-shaped',
      );
    });

    test('close() is a no-op when the client was injected', () {
      final client = MockClient((_) async => http.Response('[]', 200));
      // Should not close the injected client (no throw, client stays usable).
      apiWith(client).close();
      expect(() => client, returnsNormally);
    });
  });
}
