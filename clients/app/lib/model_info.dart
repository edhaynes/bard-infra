/// A model/agent row shown in the professional list (no album art, by design).
class ModelInfo {
  const ModelInfo({
    required this.id,
    required this.name,
    required this.provider,
    required this.params,
    required this.quant,
    required this.sizeGb,
    required this.status,
  });

  final String id;
  final String name;
  final String provider;
  final String params;
  final String quant;
  final double sizeGb;
  final String status; // ready | loading | offline

  factory ModelInfo.fromAgentJson(Map<String, dynamic> json) {
    final caps = (json['capabilities'] as List?)?.cast<String>() ?? const [];
    return ModelInfo(
      id: json['agentId'] as String? ?? '?',
      name: json['agentId'] as String? ?? 'unknown',
      provider: caps.contains('gpu') ? 'GPU agent' : 'agent',
      params: '—',
      quant: '—',
      sizeGb: 0,
      status: 'ready',
    );
  }
}

/// Fallback sample data so the list renders before a backend is configured.
const sampleModels = <ModelInfo>[
  ModelInfo(
    id: 'gemma-3-4b',
    name: 'Gemma 3 4B',
    provider: 'Google',
    params: '4B',
    quant: 'Q4_K_M',
    sizeGb: 2.4,
    status: 'ready',
  ),
  ModelInfo(
    id: 'llama-3.1-8b',
    name: 'Llama 3.1 8B',
    provider: 'Meta',
    params: '8B',
    quant: 'Q5_K_M',
    sizeGb: 5.7,
    status: 'ready',
  ),
  ModelInfo(
    id: 'qwen2.5-14b',
    name: 'Qwen 2.5 14B',
    provider: 'Alibaba',
    params: '14B',
    quant: 'Q4_K_M',
    sizeGb: 8.9,
    status: 'offline',
  ),
];
