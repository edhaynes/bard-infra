import 'dart:convert';
import 'dart:isolate';
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
  // [inlineRunner] keeps the crypto on the test isolate (no real spawn) so the
  // round-trips are deterministic and fast.
  SeedWrapper fastWrapper() => SeedWrapper(
        params: const Argon2Params(parallelism: 1, memory: 1024, iterations: 1),
        runner: inlineRunner,
      );

  final seed = fixtureSeed; // 32-byte deterministic test seed.
  const password = fixtureSecretString;
  const omgSecret = fixtureOmgSecret; // a normalized OMG code (15 symbols)

  group('offload contract (bug #board-freeze root cause)', () {
    // The freeze was Argon2id running ON the UI isolate. These tests pin the
    // fix: the wrapper hands ALL heavy crypto to the injected runner — it never
    // runs the derivation inline on the calling isolate — and the production
    // default runner is the real off-isolate [Isolate.run].

    test('wrap does not run the crypto on the calling isolate', () async {
      // A runner that records whether it was asked to defer the work, but runs
      // it inline so the test stays deterministic. The point: wrap() routes the
      // heavy work THROUGH the runner rather than doing it before returning.
      var routedThroughRunner = false;
      Future<R> spyRunner<R>(Future<R> Function() computation) {
        routedThroughRunner = true;
        return computation();
      }

      final w = SeedWrapper(
        params: const Argon2Params(parallelism: 1, memory: 1024, iterations: 1),
        runner: spyRunner,
      );
      await w.wrap(seed: seed, secret: password);
      expect(routedThroughRunner, isTrue,
          reason: 'the Argon2id work must go through the offload runner, not '
              'run inline on the UI isolate');
    });

    test('the default runner runs the work on ANOTHER isolate', () async {
      // [Isolate.run] copies the closure to a fresh isolate, so the computation
      // sees a DIFFERENT isolate identity than the caller. This is the concrete
      // proof the heavy crypto is off the UI isolate (not just "async on the
      // same thread"): if it ran inline, the hash codes would match.
      final callerIsolate = Isolate.current.hashCode;
      final workerIsolate =
          await defaultRunner<int>(() async => Isolate.current.hashCode);
      expect(workerIsolate, isNot(callerIsolate),
          reason: 'the wrap computation must run on a separate isolate, off '
              'the UI thread (bug #board-freeze)');
    });
  });

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
      // The real mobile work factor (19 MiB / 2 iterations), pinned to the
      // inline runner so the round-trip is exercised without spawning a real
      // isolate (production uses [defaultRunner]; the crypto is identical).
      final w = SeedWrapper(runner: inlineRunner);
      final blob = await w.wrap(seed: seed, secret: password);
      expect(await w.unwrap(blob: blob, secret: password), seed);
    });

    test('defaults to the mobile work factor and the real isolate runner', () {
      // The mobile profile is the OWASP-floor low-memory Argon2id (bug
      // #board-freeze): 19 MiB, 2 passes, single lane — run off the UI isolate.
      expect(Argon2Params.mobile.memory, 19 * 1024);
      expect(Argon2Params.mobile.iterations, 2);
      expect(Argon2Params.mobile.parallelism, 1);
      expect(Argon2Params.mobile.hashLength, SeedWrapper.keyLength);
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
