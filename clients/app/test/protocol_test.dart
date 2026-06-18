import 'package:bard_pro/protocol.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for the Dart domain model derived from
/// `contracts/protocol.schema.json`. Covers every parse branch (happy path,
/// missing/wrong-typed required fields, optional fields, tool transcript) so the
/// client fails loudly on a contract violation rather than silently mis-rendering.
void main() {
  group('MessageType', () {
    test('round-trips text and voice', () {
      expect(MessageType.fromWire('text'), MessageType.text);
      expect(MessageType.fromWire('voice'), MessageType.voice);
      expect(MessageType.text.wire, 'text');
      expect(MessageType.voice.wire, 'voice');
    });

    test('throws on an unknown type', () {
      expect(() => MessageType.fromWire('image'), throwsA(isA<ProtocolFormatException>()));
    });
  });

  group('BardRequest.toJson', () {
    test('serialises required fields and omits absent optionals', () {
      final req = BardRequest(
        id: '11111111-1111-1111-1111-111111111111',
        type: MessageType.text,
        content: 'hello',
        metadata: const RequestMetadata(targetAgent: 'agent-1', authToken: 'tok'),
      );
      final json = req.toJson();
      expect(json['id'], '11111111-1111-1111-1111-111111111111');
      expect(json['type'], 'text');
      expect(json['content'], 'hello');
      expect(json['metadata'], {'targetAgent': 'agent-1', 'authToken': 'tok'});
      expect((json['metadata'] as Map).containsKey('sessionId'), isFalse);
      expect((json['metadata'] as Map).containsKey('timestamp'), isFalse);
    });

    test('includes sessionId and ISO-8601 UTC timestamp when present', () {
      final ts = DateTime.utc(2026, 6, 7, 13);
      final req = BardRequest(
        id: '22222222-2222-2222-2222-222222222222',
        type: MessageType.text,
        content: 'hi',
        metadata: RequestMetadata(
          targetAgent: 'a',
          authToken: 't',
          sessionId: 'sess-9',
          timestamp: ts,
        ),
      );
      final meta = req.toJson()['metadata'] as Map<String, dynamic>;
      expect(meta['sessionId'], 'sess-9');
      expect(meta['timestamp'], '2026-06-07T13:00:00.000Z');
    });
  });

  group('BardResponse.fromJson', () {
    Map<String, dynamic> validResponse() => {
          'id': '33333333-3333-3333-3333-333333333333',
          'type': 'text',
          'content': 'the answer',
          'metadata': {'agentId': 'agent-1'},
        };

    test('parses a minimal valid response', () {
      final resp = BardResponse.fromJson(validResponse());
      expect(resp.id, '33333333-3333-3333-3333-333333333333');
      expect(resp.type, MessageType.text);
      expect(resp.content, 'the answer');
      expect(resp.metadata.agentId, 'agent-1');
      expect(resp.metadata.toolCalls, isEmpty);
      expect(resp.metadata.toolResults, isEmpty);
    });

    test('parses tool calls and results', () {
      final json = validResponse()
        ..['metadata'] = {
          'agentId': 'agent-1',
          'sessionId': 'sess-1',
          'timestamp': '2026-06-07T13:00:00Z',
          'toolCalls': [
            {'name': 'search', 'arguments': {'q': 'cats'}},
          ],
          'toolResults': [
            {'name': 'search', 'output': '10 results'},
          ],
        };
      final resp = BardResponse.fromJson(json);
      expect(resp.metadata.sessionId, 'sess-1');
      expect(resp.metadata.timestamp, DateTime.utc(2026, 6, 7, 13));
      expect(resp.metadata.toolCalls.single.name, 'search');
      expect(resp.metadata.toolCalls.single.arguments['q'], 'cats');
      expect(resp.metadata.toolResults.single.output, '10 results');
    });

    test('ignores an unparseable timestamp (treated as absent)', () {
      final json = validResponse()
        ..['metadata'] = {'agentId': 'a', 'timestamp': 'not-a-date'};
      expect(BardResponse.fromJson(json).metadata.timestamp, isNull);
    });

    test('throws when id is missing', () {
      final json = validResponse()..remove('id');
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when id is empty', () {
      final json = validResponse()..['id'] = '';
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when type is missing', () {
      final json = validResponse()..remove('type');
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when type is unknown', () {
      final json = validResponse()..['type'] = 'hologram';
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when content is missing', () {
      final json = validResponse()..remove('content');
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when content is not a string', () {
      final json = validResponse()..['content'] = 42;
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when metadata is missing', () {
      final json = validResponse()..remove('metadata');
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when metadata is not an object', () {
      final json = validResponse()..['metadata'] = 'oops';
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when metadata.agentId is missing', () {
      final json = validResponse()..['metadata'] = <String, dynamic>{};
      expect(() => BardResponse.fromJson(json), throwsA(isA<ProtocolFormatException>()));
    });
  });

  group('tool transcript parse failures', () {
    BardResponse parseWithToolCalls(Object toolCalls) => BardResponse.fromJson({
          'id': '44444444-4444-4444-4444-444444444444',
          'type': 'text',
          'content': 'c',
          'metadata': {'agentId': 'a', 'toolCalls': toolCalls},
        });

    test('throws when toolCalls is not an array', () {
      expect(() => parseWithToolCalls('nope'), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when a toolCall element is not an object', () {
      expect(() => parseWithToolCalls(['nope']), throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when toolCall.name is empty', () {
      expect(
        () => parseWithToolCalls([{'name': '', 'arguments': <String, dynamic>{}}]),
        throwsA(isA<ProtocolFormatException>()),
      );
    });

    test('throws when toolCall.arguments is not an object', () {
      expect(
        () => parseWithToolCalls([{'name': 'x', 'arguments': 'no'}]),
        throwsA(isA<ProtocolFormatException>()),
      );
    });
  });

  group('ToolResult.fromJson', () {
    test('throws when name is empty', () {
      expect(
        () => ToolResult.fromJson({'name': '', 'output': 'o'}),
        throwsA(isA<ProtocolFormatException>()),
      );
    });

    test('throws when output is not a string', () {
      expect(
        () => ToolResult.fromJson({'name': 'x', 'output': 5}),
        throwsA(isA<ProtocolFormatException>()),
      );
    });
  });

  group('BardError.fromJson', () {
    test('parses agent_unavailable with retry=true', () {
      final err = BardError.fromJson({
        'error': 'agent_unavailable',
        'retry': true,
        'detail': 'connection refused',
      });
      expect(err.code, 'agent_unavailable');
      expect(err.retry, isTrue);
      expect(err.detail, 'connection refused');
    });

    test('defaults retry to false and detail to null', () {
      final err = BardError.fromJson({'error': 'not_found'});
      expect(err.retry, isFalse);
      expect(err.detail, isNull);
    });

    test('throws when error code is missing', () {
      expect(() => BardError.fromJson(<String, dynamic>{}),
          throwsA(isA<ProtocolFormatException>()));
    });

    test('throws when error code is empty', () {
      expect(() => BardError.fromJson({'error': ''}),
          throwsA(isA<ProtocolFormatException>()));
    });
  });

  test('ProtocolFormatException toString includes the message', () {
    expect(ProtocolFormatException('boom').toString(), contains('boom'));
  });
}
