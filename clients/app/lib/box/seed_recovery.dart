import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

/// Two-tier seed-escrow crypto (ADR-0016 §5).
///
/// The device's 32-byte identity seed is WRAPPED — once under the app password
/// and once under a one-time OMG code — and both ciphertexts are escrowed
/// server-side, keyed by an account handle. The server stores ciphertext only
/// and can never read the seed (zero-knowledge escrow).
///
/// A wrap is `AES-256-GCM(seed)` under an Argon2id-derived key, with a random
/// salt (the Argon2id nonce) and a random AES nonce per wrap. The serialized
/// blob is `salt ++ nonce ++ cipherText ++ mac`, base64. The seed, password and
/// OMG code plaintext NEVER leave the device and are never logged (CLAUDE.md
/// §0.2 / §7).
///
/// The cipher + KDF are injectable so the parameters live in one place
/// (CLAUDE.md §2: config over hardcoding) and tests can dial the Argon2id work
/// factor down for speed without changing the wire format.
/// The wrap/unwrap contract (CLAUDE.md §3: swappable behind an interface). The
/// production implementation is [SeedWrapper] (Argon2id + AES-GCM); widget tests
/// bind a trivial fake so the UI flow runs without the isolate-backed Argon2id,
/// which does not complete inside the widget-test fake-async zone.
abstract class SeedWrapping {
  /// Wrap [seed] under [secret], returning the base64 escrow blob.
  Future<String> wrap({required List<int> seed, required String secret});

  /// Unwrap a base64 [blob] under [secret], or throw [SeedUnwrapException].
  Future<Uint8List> unwrap({required String blob, required String secret});
}

class SeedWrapper implements SeedWrapping {
  SeedWrapper({Argon2id? kdf, AesGcm? cipher})
      : _kdf = kdf ?? defaultKdf(),
        _cipher = cipher ?? AesGcm.with256bits();

  /// Salt length (Argon2id nonce), in bytes. 16 bytes = 128 bits, the standard
  /// salt size; random per wrap so the same secret yields a different blob each
  /// time (CLAUDE.md §2: named, not a magic number).
  static const saltLength = 16;

  /// The derived AES key length, in bytes (256-bit AES-GCM).
  static const keyLength = 32;

  /// Default Argon2id parameters. Tuned for an interactive client unlock:
  /// `memory` is in 1 kB blocks → 19 MiB, the RFC 9106 "second recommended"
  /// low-memory profile, with 2 iterations and single-lane parallelism so it
  /// runs on a phone without a multi-second stall. Centralized here so the
  /// work factor is one constant, not scattered literals.
  static Argon2id defaultKdf() => Argon2id(
        parallelism: 1,
        memory: 19 * 1024,
        iterations: 2,
        hashLength: keyLength,
      );

  final Argon2id _kdf;
  final AesGcm _cipher;

  /// Wrap [seed] under [secret] (the app password or the OMG code), returning the
  /// base64 `salt ++ nonce ++ cipherText ++ mac` blob to escrow. A fresh random
  /// salt and nonce are drawn per call, so wrapping the same seed twice (once per
  /// secret, or even the same secret twice) never produces the same ciphertext.
  @override
  Future<String> wrap({required List<int> seed, required String secret}) async {
    final salt = _randomBytes(saltLength);
    final key = await _deriveKey(secret, salt);
    final box = await _cipher.encrypt(seed, secretKey: key, nonce: _cipher.newNonce());
    final blob = BytesBuilder()
      ..add(salt)
      ..add(box.nonce)
      ..add(box.cipherText)
      ..add(box.mac.bytes);
    return base64.encode(blob.toBytes());
  }

  /// Unwrap a base64 [blob] produced by [wrap] using [secret], returning the
  /// recovered seed bytes — or throwing [SeedUnwrapException] when the secret is
  /// wrong, the blob is malformed, or the GCM authentication tag does not verify.
  /// The exception carries NO plaintext (CLAUDE.md §7); the caller surfaces a
  /// friendly "that password/code didn't work" message.
  @override
  Future<Uint8List> unwrap({required String blob, required String secret}) async {
    final Uint8List bytes;
    try {
      bytes = base64.decode(blob);
    } on FormatException {
      throw const SeedUnwrapException('escrow blob is not valid base64');
    }
    final nonceLength = _cipher.nonceLength;
    final macLength = _cipher.macAlgorithm.macLength;
    final headerLength = saltLength + nonceLength + macLength;
    if (bytes.length <= headerLength) {
      throw const SeedUnwrapException('escrow blob is too short to be a wrap');
    }
    final salt = bytes.sublist(0, saltLength);
    final nonce = bytes.sublist(saltLength, saltLength + nonceLength);
    final cipherText = bytes.sublist(saltLength + nonceLength, bytes.length - macLength);
    final mac = Mac(bytes.sublist(bytes.length - macLength));
    final key = await _deriveKey(secret, salt);
    try {
      final seed = await _cipher.decrypt(
        SecretBox(cipherText, nonce: nonce, mac: mac),
        secretKey: key,
      );
      return Uint8List.fromList(seed);
    } on SecretBoxAuthenticationError {
      // Wrong secret (or tampered blob): the GCM tag failed to verify.
      throw const SeedUnwrapException('the password or code did not match');
    }
  }

  Future<SecretKey> _deriveKey(String secret, List<int> salt) =>
      _kdf.deriveKeyFromPassword(password: secret, nonce: salt);

  static Uint8List _randomBytes(int n) {
    final rnd = SecureRandom.fast;
    final out = Uint8List(n);
    for (var i = 0; i < n; i++) {
      out[i] = rnd.nextUint32() & 0xff;
    }
    return out;
  }
}

/// Thrown when an escrow blob cannot be unwrapped — a wrong secret, a malformed
/// blob, or a failed authentication tag. Deliberately carries no key/seed
/// material so it is safe to log and surface (CLAUDE.md §7, §12).
class SeedUnwrapException implements Exception {
  const SeedUnwrapException(this.reason);

  final String reason;

  @override
  String toString() => 'SeedUnwrapException: $reason';
}

/// The two ciphertext wraps escrowed for an account handle (ADR-0016 §5 frozen
/// contract): one keyed by the app password, one by the one-time OMG code. Both
/// wrap the SAME seed, so either path recovers the same identity.
class EscrowWraps {
  const EscrowWraps({required this.password, required this.omg});

  /// Base64 `salt ++ nonce ++ ct ++ mac` of the seed wrapped under the password.
  final String password;

  /// Base64 `salt ++ nonce ++ ct ++ mac` of the seed wrapped under the OMG code.
  final String omg;

  /// The `wraps` object body for the escrow POST / GET contract.
  Map<String, dynamic> toJson() => {'password': password, 'omg': omg};

  /// Parse the `wraps` object from a `GET /recovery/escrow/{handle}` response.
  /// Throws [FormatException] when either wrap is missing or not a string so the
  /// caller fails fast rather than passing a null into the unwrap path.
  factory EscrowWraps.fromJson(Map<String, dynamic> json) {
    final password = json['password'];
    final omg = json['omg'];
    if (password is! String || password.isEmpty) {
      throw const FormatException('escrow: missing wraps.password');
    }
    if (omg is! String || omg.isEmpty) {
      throw const FormatException('escrow: missing wraps.omg');
    }
    return EscrowWraps(password: password, omg: omg);
  }
}

/// A fetched escrow record (`GET /recovery/escrow/{handle}` 200 body): the
/// device's public key (informational — the recovered seed re-derives it) and
/// the two wraps to attempt a decrypt against.
class EscrowRecord {
  const EscrowRecord({required this.publicKey, required this.wraps});

  /// Base64 32-byte Ed25519 public key the handle was escrowed with.
  final String publicKey;

  /// The password + OMG ciphertext wraps.
  final EscrowWraps wraps;

  factory EscrowRecord.fromJson(Map<String, dynamic> json) {
    final publicKey = json['publicKey'];
    final wraps = json['wraps'];
    if (publicKey is! String || publicKey.isEmpty) {
      throw const FormatException('escrow: missing publicKey');
    }
    if (wraps is! Map) {
      throw const FormatException('escrow: "wraps" is not an object');
    }
    return EscrowRecord(
      publicKey: publicKey,
      wraps: EscrowWraps.fromJson(Map<String, dynamic>.from(wraps)),
    );
  }
}
