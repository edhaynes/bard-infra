import 'package:bard_pro/secure_store.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_secret_store.dart';

/// Tests the secure-store key derivation and the [SecretStore] contract via the
/// in-memory fake (the production `FlutterSecretStore` is the same contract over
/// the OS keystore; its platform channel is out of scope for a unit test —
/// CLAUDE.md §9). The stored value is now the device PRIVATE key (ADR-0016).
void main() {
  group('devicePrivateKeyName', () {
    test('namespaces by channel and device', () {
      expect(devicePrivateKeyName('chan', 'dev'), 'bard.device-privkey.chan.dev');
    });

    test('different channels for the same device get different keys', () {
      expect(
        devicePrivateKeyName('chan-a', 'dev'),
        isNot(devicePrivateKeyName('chan-b', 'dev')),
      );
    });

    test('different devices in the same channel get different keys', () {
      expect(
        devicePrivateKeyName('chan', 'dev-a'),
        isNot(devicePrivateKeyName('chan', 'dev-b')),
      );
    });
  });

  group('SecretStore round-trip (fake)', () {
    test('write then read returns the stored private key', () async {
      final store = FakeSecretStore();
      await store.writeDevicePrivateKey(
          channelId: 'c',
          deviceId: 'd',
          privateKey: 'priv-key'); // pragma: allowlist secret — fake test value
      expect(
        await store.readDevicePrivateKey(channelId: 'c', deviceId: 'd'),
        'priv-key',
      );
    });

    test('read returns null for an unknown device', () async {
      final store = FakeSecretStore();
      expect(
        await store.readDevicePrivateKey(channelId: 'c', deviceId: 'missing'),
        isNull,
      );
    });

    test('delete removes the private key', () async {
      final store = FakeSecretStore();
      await store.writeDevicePrivateKey(
          channelId: 'c', deviceId: 'd', privateKey: 'k');
      await store.deleteDevicePrivateKey(channelId: 'c', deviceId: 'd');
      expect(
          await store.readDevicePrivateKey(channelId: 'c', deviceId: 'd'), isNull);
    });

    test('keys for two boxes are isolated', () async {
      final store = FakeSecretStore();
      await store.writeDevicePrivateKey(
          channelId: 'box-1', deviceId: 'd', privateKey: 'one');
      await store.writeDevicePrivateKey(
          channelId: 'box-2', deviceId: 'd', privateKey: 'two');
      expect(
          await store.readDevicePrivateKey(channelId: 'box-1', deviceId: 'd'),
          'one');
      expect(
          await store.readDevicePrivateKey(channelId: 'box-2', deviceId: 'd'),
          'two');
    });
  });
}
