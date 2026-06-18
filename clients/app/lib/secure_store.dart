import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persistence seam for the per-device Ed25519 PRIVATE key (ADR-0016 §1).
///
/// The device generates ONE keypair at first launch; the private half is the
/// device's identity and MUST NOT leave the device. It is stored the moment it
/// is generated and is never transmitted — only the public key goes to the
/// registry. It is a credential — kept in the OS keystore (Keychain on
/// iOS/macOS, Keystore-backed EncryptedSharedPreferences on Android), never in
/// plain prefs and never logged (CLAUDE.md §0.2 / §7), and pinned
/// `first_unlock_this_device` so it is NOT included in any backup/restore.
///
/// ADR-0016 §1 is "one key per device": the device-level identity
/// ([readDeviceIdentity]/[writeDeviceIdentity]) is the single source of truth,
/// stored under [deviceIdentityName]. It is used to self-register, create boxes
/// it owns, AND join boxes. The earlier per-(channel,device) key methods are
/// retained only as a lower-level seam (and for the S4 join encoding) but the
/// identity used everywhere is the one device key.
///
/// [SecretStore] is the injectable interface so widget/unit tests bind an
/// in-memory fake with no platform channel (CLAUDE.md §2 DI, §9 no native calls
/// in unit tests); [FlutterSecretStore] is the production implementation.
abstract class SecretStore {
  /// Persist the single device-level identity: its stable [deviceId] and the
  /// base64 Ed25519 [privateKey]. This is the one key per device (ADR-0016 §1)
  /// used for self-register, create, and join.
  Future<void> writeDeviceIdentity({
    required String deviceId,
    required String privateKey,
  });

  /// Read the device-level identity (deviceId + private key), or null on a fresh
  /// install where no identity has been provisioned yet.
  Future<StoredDeviceIdentity?> readDeviceIdentity();

  /// Remove the device-level identity (device reset / revoke-self).
  Future<void> deleteDeviceIdentity();

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

/// The persisted device-level identity: the stable [deviceId] the device
/// self-registered under and the base64 Ed25519 [privateKey] it self-signs with.
/// The public half is derivable from the private representation (trailing 32
/// bytes), so it is not stored separately.
class StoredDeviceIdentity {
  const StoredDeviceIdentity({required this.deviceId, required this.privateKey});

  final String deviceId;
  final String privateKey;
}

/// Storage keys for the single device identity (ADR-0016 §1). The deviceId is
/// not secret but lives alongside the key so the pair is read in one place; the
/// private key is the credential.
const deviceIdentityKeyName = 'bard.device-identity.privkey';
const deviceIdentityIdName = 'bard.device-identity.deviceId';

/// Namespaced key so a device that joins multiple boxes can keep a per-box key
/// (retained from S4; the single device identity is the primary path).
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
  Future<void> writeDeviceIdentity({
    required String deviceId,
    required String privateKey,
  }) async {
    await _storage.write(key: deviceIdentityIdName, value: deviceId);
    await _storage.write(key: deviceIdentityKeyName, value: privateKey);
  }

  @override
  Future<StoredDeviceIdentity?> readDeviceIdentity() async {
    final deviceId = await _storage.read(key: deviceIdentityIdName);
    final privateKey = await _storage.read(key: deviceIdentityKeyName);
    // Both halves are required to be a usable identity; a partial write (e.g.
    // interrupted first launch) reads as "no identity" so provisioning re-runs.
    if (deviceId == null ||
        deviceId.isEmpty ||
        privateKey == null ||
        privateKey.isEmpty) {
      return null;
    }
    return StoredDeviceIdentity(deviceId: deviceId, privateKey: privateKey);
  }

  @override
  Future<void> deleteDeviceIdentity() async {
    await _storage.delete(key: deviceIdentityIdName);
    await _storage.delete(key: deviceIdentityKeyName);
  }

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
