/// Dart domain model for the Bard wire protocol.
///
/// Derived 1:1 from `contracts/protocol.schema.json` (FROZEN). Each type here
/// mirrors a `$defs` entry: the client serialises [BardRequest] for
/// `POST /v1/message` and parses [BardResponse] / [BardError] from the reply.
/// Keep this file in lock-step with the contract — never invent fields the
/// schema does not define (`additionalProperties: false`).
library;

/// `MessageType` — `text` is the MVP path; `voice` is accepted by the schema but
/// the Router returns 501 (`unsupported_type`).
enum MessageType {
  text,
  voice;

  String get wire => name;

  static MessageType fromWire(String value) {
    return switch (value) {
      'text' => MessageType.text,
      'voice' => MessageType.voice,
      _ => throw ProtocolFormatException('unknown message type "$value"'),
    };
  }
}

/// `ToolCall` — a tool the agent invoked while producing its response.
class ToolCall {
  const ToolCall({required this.name, required this.arguments});

  final String name;
  final Map<String, dynamic> arguments;

  factory ToolCall.fromJson(Map<String, dynamic> json) {
    final name = json['name'];
    final args = json['arguments'];
    if (name is! String || name.isEmpty) {
      throw ProtocolFormatException('toolCall.name missing or empty');
    }
    if (args is! Map) {
      throw ProtocolFormatException('toolCall.arguments missing or not an object');
    }
    return ToolCall(name: name, arguments: Map<String, dynamic>.from(args));
  }
}

/// `ToolResult` — the output the agent got back from a [ToolCall].
class ToolResult {
  const ToolResult({required this.name, required this.output});

  final String name;
  final String output;

  factory ToolResult.fromJson(Map<String, dynamic> json) {
    final name = json['name'];
    final output = json['output'];
    if (name is! String || name.isEmpty) {
      throw ProtocolFormatException('toolResult.name missing or empty');
    }
    if (output is! String) {
      throw ProtocolFormatException('toolResult.output missing or not a string');
    }
    return ToolResult(name: name, output: output);
  }
}

/// `RequestMetadata` — required `targetAgent` + `authToken`; optional session id
/// and timestamp. The [authToken] MUST NOT be logged (contract note).
class RequestMetadata {
  const RequestMetadata({
    required this.targetAgent,
    required this.authToken,
    this.sessionId,
    this.timestamp,
  });

  final String targetAgent;
  final String authToken;
  final String? sessionId;
  final DateTime? timestamp;

  Map<String, dynamic> toJson() => {
        'targetAgent': targetAgent,
        'authToken': authToken,
        if (sessionId != null) 'sessionId': sessionId,
        if (timestamp != null) 'timestamp': timestamp!.toUtc().toIso8601String(),
      };
}

/// `ResponseMetadata` — required `agentId`; optional session id, timestamp, and
/// the tool call/result transcript.
class ResponseMetadata {
  const ResponseMetadata({
    required this.agentId,
    this.sessionId,
    this.timestamp,
    this.toolCalls = const [],
    this.toolResults = const [],
  });

  final String agentId;
  final String? sessionId;
  final DateTime? timestamp;
  final List<ToolCall> toolCalls;
  final List<ToolResult> toolResults;

  factory ResponseMetadata.fromJson(Map<String, dynamic> json) {
    final agentId = json['agentId'];
    if (agentId is! String || agentId.isEmpty) {
      throw ProtocolFormatException('response metadata.agentId missing or empty');
    }
    return ResponseMetadata(
      agentId: agentId,
      sessionId: json['sessionId'] as String?,
      timestamp: _parseTimestamp(json['timestamp']),
      toolCalls: _list(json['toolCalls'], ToolCall.fromJson),
      toolResults: _list(json['toolResults'], ToolResult.fromJson),
    );
  }
}

/// `Request` — the envelope POSTed to `/v1/message`.
class BardRequest {
  const BardRequest({
    required this.id,
    required this.type,
    required this.content,
    required this.metadata,
  });

  final String id;
  final MessageType type;
  final String content;
  final RequestMetadata metadata;

  Map<String, dynamic> toJson() => {
        'id': id,
        'type': type.wire,
        'content': content,
        'metadata': metadata.toJson(),
      };
}

/// `Response` — the envelope returned on HTTP 200. [id] echoes the request id.
class BardResponse {
  const BardResponse({
    required this.id,
    required this.type,
    required this.content,
    required this.metadata,
  });

  final String id;
  final MessageType type;
  final String content;
  final ResponseMetadata metadata;

  factory BardResponse.fromJson(Map<String, dynamic> json) {
    final id = json['id'];
    final type = json['type'];
    final content = json['content'];
    final metadata = json['metadata'];
    if (id is! String || id.isEmpty) {
      throw ProtocolFormatException('response.id missing or empty');
    }
    if (type is! String) {
      throw ProtocolFormatException('response.type missing');
    }
    if (content is! String) {
      throw ProtocolFormatException('response.content missing or not a string');
    }
    if (metadata is! Map) {
      throw ProtocolFormatException('response.metadata missing or not an object');
    }
    return BardResponse(
      id: id,
      type: MessageType.fromWire(type),
      content: content,
      metadata: ResponseMetadata.fromJson(Map<String, dynamic>.from(metadata)),
    );
  }
}

/// `Error` — the error envelope returned on 401/404/501/502 (and 400). The
/// machine-readable [code] is one of: `agent_unavailable`, `unauthorized`,
/// `unsupported_type`, `not_found`, `bad_request`. [retry] defaults to false.
class BardError {
  const BardError({required this.code, this.retry = false, this.detail});

  final String code;
  final bool retry;
  final String? detail;

  factory BardError.fromJson(Map<String, dynamic> json) {
    final code = json['error'];
    if (code is! String || code.isEmpty) {
      throw ProtocolFormatException('error.error code missing or empty');
    }
    return BardError(
      code: code,
      retry: json['retry'] == true,
      detail: json['detail'] as String?,
    );
  }
}

/// Thrown when a payload that should conform to the frozen protocol does not.
/// Distinct from a transport/HTTP failure — this is a contract violation.
class ProtocolFormatException implements Exception {
  ProtocolFormatException(this.message);
  final String message;
  @override
  String toString() => 'ProtocolFormatException: $message';
}

DateTime? _parseTimestamp(Object? raw) {
  if (raw is! String || raw.isEmpty) return null;
  return DateTime.tryParse(raw);
}

List<T> _list<T>(Object? raw, T Function(Map<String, dynamic>) parse) {
  if (raw == null) return const [];
  if (raw is! List) {
    throw ProtocolFormatException('expected a JSON array');
  }
  return raw.map((e) {
    if (e is! Map) throw ProtocolFormatException('array element is not an object');
    return parse(Map<String, dynamic>.from(e));
  }).toList(growable: false);
}
