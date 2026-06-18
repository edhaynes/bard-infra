import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persistence seam for the one-time per-device secret minted at box redemption.
///
/// The secret is the device's HMAC signing key; it is disclosed EXACTLY ONCE by
/// the registry (`RedeemResponse.deviceSecret`) and is never recoverable, so it
/// MUST be stored the moment it arrives (lib/box/redeem.dart). It is a
/// credential — kept in the OS keystore (Keychain on iOS/macOS, Keystore-backed
/// EncryptedSharedPreferences on Android), never in plain prefs and never logged
/// (CLAUDE.md §0.2 / §7).
///
/// [SecretStore] is the injectable interface so widget/unit tests bind an
/// in-memory fake with no platform channel (CLAUDE.md §2 DI, §9 no native calls
/// in unit tests); [FlutterSecretStore] is the production implementation.
abstract class SecretStore {
  /// Persist [secret] under a key derived from [deviceId] within [channelId].
  Future<void> writeDeviceSecret({
    required String channelId,
    required String deviceId,
    required String secret,
  });

  /// Read a previously stored secret, or null when none exists.
  Future<String?> readDeviceSecret({
    required String channelId,
    required String deviceId,
  });

  /// Remove a stored secret (e.g. on leaving a box / device reset).
  Future<void> deleteDeviceSecret({
    required String channelId,
    required String deviceId,
  });
}

/// Namespaced key so a device that joins multiple boxes keeps one secret each.
String deviceSecretKey(String channelId, String deviceId) =>
    'bard.device-secret.$channelId.$deviceId';

/// [SecretStore] backed by `flutter_secure_storage` (OS keystore).
class FlutterSecretStore implements SecretStore {
  FlutterSecretStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              // Survive backup/restore is undesirable for a device credential:
              // first_unlock_this_device keeps it on-device and post-first-unlock.
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock_this_device,
              ),
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage _storage;

  @override
  Future<void> writeDeviceSecret({
    required String channelId,
    required String deviceId,
    required String secret,
  }) {
    return _storage.write(
      key: deviceSecretKey(channelId, deviceId),
      value: secret,
    );
  }

  @override
  Future<String?> readDeviceSecret({
    required String channelId,
    required String deviceId,
  }) {
    return _storage.read(key: deviceSecretKey(channelId, deviceId));
  }

  @override
  Future<void> deleteDeviceSecret({
    required String channelId,
    required String deviceId,
  }) {
    return _storage.delete(key: deviceSecretKey(channelId, deviceId));
  }
}
