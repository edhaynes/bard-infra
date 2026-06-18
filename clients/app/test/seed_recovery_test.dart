import 'dart:convert';
import 'dart:typed_data';

import 'package:bard_pro/box/seed_recovery.dart';
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fixed_identity.dart';

/// Unit tests for the two-tier seed-escrow crypto (ADR-0016 §5): Argon2id +
/// AES-GCM wrap/unwrap of the device seed under the app password and the OMG
/// code, plus the escrow wire-format models. All dummy secrets reuse the fixture
/// string the rules mandate.
void main() {
  // A fast KDF for the tests (1 iteration, low memory) — the wire format and the
  // round-trip behaviour are identical to production; only the work factor
  // differs, kept low so the suite stays quick (CLAUDE.md §2: parameter is config).
  SeedWrapper fastWrapper() => SeedWrapper(
        kdf: Argon2id(parallelism: 1, memory: 1024, iterations: 1, hashLength: 32),
      );

  final seed = fixtureSeed; // 32-byte deterministic test seed.
  const password = fixtureSecretString;
  const omgSecret = fixtureOmgSecret; // a normalized OMG code (15 symbols)

  group('wrap / unwrap round-trip', () {
    test('a password wrap unwraps back to the exact seed', () async {
      final w = fastWrapper();
      final blob = await w.wrap(seed: seed, secret: password);
      final recovered = await w.unwrap(blob: blob, secret: password);
      expect(recovered, seed);
    });

    test('an OMG-code wrap unwraps back to the exact seed', () async {
      final w = fastWrapper();
      final blob = await w.wrap(seed: seed, secret: omgSecret);
      final recovered = await w.unwrap(blob: blob, secret: omgSecret);
      expect(recovered, seed);
    });

    test('two wraps of the same seed+secret differ (random salt + nonce)',
        () async {
      final w = fastWrapper();
      final a = await w.wrap(seed: seed, secret: password);
      final b = await w.wrap(seed: seed, secret: password);
      expect(a, isNot(b), reason: 'fresh salt/nonce per wrap');
      // …yet both decrypt to the same seed.
      expect(await w.unwrap(blob: a, secret: password), seed);
      expect(await w.unwrap(blob: b, secret: password), seed);
    });

    test('the blob is salt ++ nonce ++ ciphertext ++ mac', () async {
      final w = fastWrapper();
      final blob = await w.wrap(seed: seed, secret: password);
      final bytes = base64.decode(blob);
      final cipher = AesGcm.with256bits();
      final overhead =
          SeedWrapper.saltLength + cipher.nonceLength + cipher.macAlgorithm.macLength;
      // Seed is 32 bytes; AES-GCM cipherText is the same length as the plaintext.
      expect(bytes.length, overhead + seed.length);
    });
  });

  group('unwrap failure modes (no plaintext leak)', () {
    test('the wrong password is rejected with a clean exception', () async {
      final w = fastWrapper();
      final blob = await w.wrap(seed: seed, secret: password);
      await expectLater(
        w.unwrap(blob: blob, secret: 'not-the-password'), // pragma: allowlist secret
        throwsA(isA<SeedUnwrapException>()),
      );
    });

    test('the OMG wrap does NOT open with the password (tier isolation)', () async {
      final w = fastWrapper();
      final omgBlob = await w.wrap(seed: seed, secret: omgSecret);
      await expectLater(
        w.unwrap(blob: omgBlob, secret: password),
        throwsA(isA<SeedUnwrapException>()),
      );
    });

    test('a non-base64 blob fails fast', () async {
      await expectLater(
        fastWrapper().unwrap(blob: 'not base64 !!!', secret: password),
        throwsA(isA<SeedUnwrapException>()),
      );
    });

    test('a too-short blob (no room for salt+nonce+mac) fails fast', () async {
      final tiny = base64.encode(Uint8List(4));
      await expectLater(
        fastWrapper().unwrap(blob: tiny, secret: password),
        throwsA(isA<SeedUnwrapException>()),
      );
    });

    test('a tampered ciphertext fails the GCM tag', () async {
      final w = fastWrapper();
      final blob = await w.wrap(seed: seed, secret: password);
      final bytes = base64.decode(blob);
      // Flip a bit in the ciphertext region (just after salt+nonce).
      final i = SeedWrapper.saltLength + AesGcm.with256bits().nonceLength;
      bytes[i] = bytes[i] ^ 0x01;
      await expectLater(
        w.unwrap(blob: base64.encode(bytes), secret: password),
        throwsA(isA<SeedUnwrapException>()),
      );
    });

    test('SeedUnwrapException.toString carries the reason, never a secret', () {
      const e = SeedUnwrapException('the password or code did not match');
      expect(e.toString(), contains('did not match'));
      expect(e.toString(), isNot(contains(fixtureSecretString)));
    });
  });

  group('default wrapper (production Argon2id parameters)', () {
    test('round-trips with the real KDF work factor', () async {
      final w = SeedWrapper();
      final blob = await w.wrap(seed: seed, secret: password);
      expect(await w.unwrap(blob: blob, secret: password), seed);
    });
  });

  group('EscrowWraps / EscrowRecord (wire format)', () {
    test('EscrowWraps.toJson / fromJson round-trip', () {
      const wraps = EscrowWraps(password: 'PW-BLOB', omg: 'OMG-BLOB');
      final json = wraps.toJson();
      expect(json, {'password': 'PW-BLOB', 'omg': 'OMG-BLOB'}); // pragma: allowlist secret
      final back = EscrowWraps.fromJson(json);
      expect(back.password, 'PW-BLOB');
      expect(back.omg, 'OMG-BLOB');
    });

    test('EscrowWraps.fromJson rejects a missing/blank wrap', () {
      expect(() => EscrowWraps.fromJson({'omg': 'x'}), throwsFormatException);
      expect(() => EscrowWraps.fromJson({'password': '', 'omg': 'x'}),
          throwsFormatException);
      expect(() => EscrowWraps.fromJson({'password': 'x', 'omg': 42}),
          throwsFormatException);
    });

    test('EscrowRecord.fromJson parses publicKey + wraps', () {
      final record = EscrowRecord.fromJson({
        'publicKey': fixturePublicKeyBase64,
        'wraps': {'password': 'PW', 'omg': 'OMG'}, // pragma: allowlist secret
      });
      expect(record.publicKey, fixturePublicKeyBase64);
      expect(record.wraps.password, 'PW');
      expect(record.wraps.omg, 'OMG');
    });

    test('EscrowRecord.fromJson rejects a missing publicKey or wraps', () {
      expect(
        () => EscrowRecord.fromJson({'wraps': {'password': 'p', 'omg': 'o'}}),
        throwsFormatException,
      );
      expect(
        () => EscrowRecord.fromJson({'publicKey': 'k', 'wraps': 'not-an-object'}),
        throwsFormatException,
      );
    });
  });
}
