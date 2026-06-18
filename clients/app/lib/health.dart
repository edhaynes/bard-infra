import 'dart:convert';

import 'package:http/http.dart' as http;

/// Result of probing a service's `/healthz` (+ optional `/version`) endpoint,
/// per the Router/Registry/Agent OpenAPI contracts.
class HealthResult {
  const HealthResult({required this.label, required this.ok, this.detail = ''});

  final String label;
  final bool ok;
  final String detail; // version string when available, else an error summary.
}

/// Probes a single service. Never throws — a failure becomes `ok:false` with the
/// error summarised in [HealthResult.detail], so callers can render it inline.
Future<HealthResult> probe({
  required String label,
  required String baseUrl,
  required String token,
  Duration timeout = const Duration(seconds: 5),
}) async {
  final headers = token.isEmpty ? <String, String>{} : {'Authorization': 'Bearer $token'};
  try {
    final health = await http
        .get(Uri.parse('$baseUrl/healthz'), headers: headers)
        .timeout(timeout);
    if (health.statusCode != 200) {
      return HealthResult(label: label, ok: false, detail: 'HTTP ${health.statusCode}');
    }
    final version = await _version(baseUrl, headers, timeout);
    return HealthResult(label: label, ok: true, detail: version);
  } catch (e) {
    return HealthResult(label: label, ok: false, detail: _summarise(e));
  }
}

Future<String> _version(String baseUrl, Map<String, String> headers, Duration timeout) async {
  try {
    final resp = await http
        .get(Uri.parse('$baseUrl/version'), headers: headers)
        .timeout(timeout);
    if (resp.statusCode != 200) return '';
    final json = jsonDecode(resp.body) as Map<String, dynamic>;
    return json['version']?.toString() ?? '';
  } catch (_) {
    return ''; // /version is optional; absence is not a health failure.
  }
}

String _summarise(Object e) {
  final s = e.toString();
  return s.length > 80 ? '${s.substring(0, 77)}…' : s;
}
