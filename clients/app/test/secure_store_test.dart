import 'package:bard_pro/secure_store.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fake_secret_store.dart';

/// Tests the secure-store key derivation and the [SecretStore] contract via the
/// in-memory fake (the production `FlutterSecretStore` is the same contract over
/// the OS keystore; its platform channel is out of scope for a unit test —
/// CLAUDE.md §9).
void main() {
  group('deviceSecretKey', () {
    test('namespaces by channel and device', () {
      expect(deviceSecretKey('chan', 'dev'), 'bard.device-secret.chan.dev');
    });

    test('different channels for the same device get different keys', () {
      expect(
        deviceSecretKey('chan-a', 'dev'),
        isNot(deviceSecretKey('chan-b', 'dev')),
      );
    });

    test('different devices in the same channel get different keys', () {
      expect(
        deviceSecretKey('chan', 'dev-a'),
        isNot(deviceSecretKey('chan', 'dev-b')),
      );
    });
  });

  group('SecretStore round-trip (fake)', () {
    test('write then read returns the stored secret', () async {
      final store = FakeSecretStore();
      await store.writeDeviceSecret(channelId: 'c', deviceId: 'd', secret: 's3cr3t');
      expect(
        await store.readDeviceSecret(channelId: 'c', deviceId: 'd'),
        's3cr3t',
      );
    });

    test('read returns null for an unknown device', () async {
      final store = FakeSecretStore();
      expect(
        await store.readDeviceSecret(channelId: 'c', deviceId: 'missing'),
        isNull,
      );
    });

    test('delete removes the secret', () async {
      final store = FakeSecretStore();
      await store.writeDeviceSecret(channelId: 'c', deviceId: 'd', secret: 's');
      await store.deleteDeviceSecret(channelId: 'c', deviceId: 'd');
      expect(await store.readDeviceSecret(channelId: 'c', deviceId: 'd'), isNull);
    });

    test('secrets for two boxes are isolated', () async {
      final store = FakeSecretStore();
      await store.writeDeviceSecret(channelId: 'box-1', deviceId: 'd', secret: 'one');
      await store.writeDeviceSecret(channelId: 'box-2', deviceId: 'd', secret: 'two');
      expect(await store.readDeviceSecret(channelId: 'box-1', deviceId: 'd'), 'one');
      expect(await store.readDeviceSecret(channelId: 'box-2', deviceId: 'd'), 'two');
    });
  });
}
