import 'package:bard_pro/secure_store.dart';

/// In-memory [SecretStore] for tests — no platform channel (CLAUDE.md §9).
/// Mirrors the namespacing of the real store via [devicePrivateKeyName] so tests
/// exercise the same key shape the production store uses.
class FakeSecretStore implements SecretStore {
  final Map<String, String> values = {};

  @override
  Future<void> writeDevicePrivateKey({
    required String channelId,
    required String deviceId,
    required String privateKey,
  }) async {
    values[devicePrivateKeyName(channelId, deviceId)] = privateKey;
  }

  @override
  Future<String?> readDevicePrivateKey({
    required String channelId,
    required String deviceId,
  }) async {
    return values[devicePrivateKeyName(channelId, deviceId)];
  }

  @override
  Future<void> deleteDevicePrivateKey({
    required String channelId,
    required String deviceId,
  }) async {
    values.remove(devicePrivateKeyName(channelId, deviceId));
  }
}
