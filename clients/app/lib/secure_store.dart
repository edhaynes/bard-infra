import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persistence seam for the per-device Ed25519 PRIVATE key (ADR-0016 §1).
///
/// The device generates its own keypair at first launch; the private half is the
/// device's identity and MUST NOT leave the device. It is stored the moment it
/// is generated and is never transmitted — only the public key goes to the
/// registry (lib/box/box_controller.dart). It is a credential — kept in the OS
/// keystore (Keychain on iOS/macOS, Keystore-backed EncryptedSharedPreferences
/// on Android), never in plain prefs and never logged (CLAUDE.md §0.2 / §7), and
/// pinned `first_unlock_this_device` so it is NOT included in any backup/restore.
///
/// [SecretStore] is the injectable interface so widget/unit tests bind an
/// in-memory fake with no platform channel (CLAUDE.md §2 DI, §9 no native calls
/// in unit tests); [FlutterSecretStore] is the production implementation.
abstract class SecretStore {
  /// Persist the device [privateKey] under a key derived from [deviceId] within
  /// [channelId].
  Future<void> writeDevicePrivateKey({
    required String channelId,
    required String deviceId,
    required String privateKey,
  });

  /// Read a previously stored private key, or null when none exists.
  Future<String?> readDevicePrivateKey({
    required String channelId,
    required String deviceId,
  });

  /// Remove a stored private key (e.g. on leaving a box / device reset).
  Future<void> deleteDevicePrivateKey({
    required String channelId,
    required String deviceId,
  });
}

/// Namespaced key so a device that joins multiple boxes keeps one identity key
/// each.
String devicePrivateKeyName(String channelId, String deviceId) =>
    'bard.device-privkey.$channelId.$deviceId';

/// [SecretStore] backed by `flutter_secure_storage` (OS keystore).
class FlutterSecretStore implements SecretStore {
  FlutterSecretStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              // The device private key MUST NOT survive backup/restore (ADR-0016
              // §1: no iCloud backup). first_unlock_this_device keeps it on this
              // device only and available post-first-unlock.
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock_this_device,
              ),
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage _storage;

  @override
  Future<void> writeDevicePrivateKey({
    required String channelId,
    required String deviceId,
    required String privateKey,
  }) {
    return _storage.write(
      key: devicePrivateKeyName(channelId, deviceId),
      value: privateKey,
    );
  }

  @override
  Future<String?> readDevicePrivateKey({
    required String channelId,
    required String deviceId,
  }) {
    return _storage.read(key: devicePrivateKeyName(channelId, deviceId));
  }

  @override
  Future<void> deleteDevicePrivateKey({
    required String channelId,
    required String deviceId,
  }) {
    return _storage.delete(key: devicePrivateKeyName(channelId, deviceId));
  }
}
