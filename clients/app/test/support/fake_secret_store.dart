import 'package:bard_pro/secure_store.dart';

/// In-memory [SecretStore] for tests — no platform channel (CLAUDE.md §9).
/// Mirrors the namespacing of the real store via [deviceSecretKey] so tests
/// exercise the same key shape the production store uses.
class FakeSecretStore implements SecretStore {
  final Map<String, String> values = {};

  @override
  Future<void> writeDeviceSecret({
    required String channelId,
    required String deviceId,
    required String secret,
  }) async {
    values[deviceSecretKey(channelId, deviceId)] = secret;
  }

  @override
  Future<String?> readDeviceSecret({
    required String channelId,
    required String deviceId,
  }) async {
    return values[deviceSecretKey(channelId, deviceId)];
  }

  @override
  Future<void> deleteDeviceSecret({
    required String channelId,
    required String deviceId,
  }) async {
    values.remove(deviceSecretKey(channelId, deviceId));
  }
}
