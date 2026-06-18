import 'dart:convert';
import 'dart:isolate';
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
/// **Off the UI isolate (bug #board-freeze).** Argon2id is deliberately
/// expensive; running it on the main isolate freezes the whole screen — queued
/// taps (Share/Copy) never fire and the escrow POST never goes out. The
/// `package:cryptography` Argon2id does NOT reliably offload on mobile (its
/// internal isolate path falls back to inline computation when the FFI buffer
/// is unavailable, and is single-lane at `parallelism: 1`), so [SeedWrapper]
/// runs the ENTIRE derive+cipher on a background isolate via [Isolate.run]
/// (the injectable [IsolateRunner] seam, defaulting to [defaultRunner]). Tests
/// bind an inline runner so the work is deterministic without spawning.
///
/// The cipher + KDF parameters are centralized in [Argon2Params] (CLAUDE.md §2:
/// config over hardcoding) so the work factor is one place and tests can dial
/// it down for speed without changing the wire format.
/// The wrap/unwrap contract (CLAUDE.md §3: swappable behind an interface). The
/// production implementation is [SeedWrapper] (isolate-offloaded Argon2id +
/// AES-GCM); widget tests bind a trivial fake so the UI flow runs without the
/// isolate-backed Argon2id, which does not complete inside the widget-test
/// fake-async zone.
abstract class SeedWrapping {
  /// Wrap [seed] under [secret], returning the base64 escrow blob.
  Future<String> wrap({required List<int> seed, required String secret});

  /// Unwrap a base64 [blob] under [secret], or throw [SeedUnwrapException].
  Future<Uint8List> unwrap({required String blob, required String secret});
}

/// Runs a top-level [computation] off the calling isolate. Defaults to
/// [Isolate.run] in production; tests inject [inlineRunner] to run it on the
/// current isolate (deterministic, no spawn) (CLAUDE.md §3: swappable seam).
typedef IsolateRunner = Future<R> Function<R>(Future<R> Function() computation);

/// Production runner: spawn a short-lived isolate so heavy crypto never blocks
/// the UI isolate (CLAUDE.md §0.12 — keep the thread responsive).
Future<R> defaultRunner<R>(Future<R> Function() computation) =>
    Isolate.run(computation);

/// Test/synchronous runner: execute [computation] on the current isolate. Used
/// by unit tests so the Argon2id work is deterministic and needs no spawn (and
/// so it completes inside a `flutter_test` zone).
Future<R> inlineRunner<R>(Future<R> Function() computation) => computation();

/// Argon2id work factor + key/salt sizing (ADR-0016 §5). Centralized so the
/// cost is one constant block, not literals scattered across the wrap/unwrap
/// paths — and so the value sent into the isolate is a plain, serializable DTO.
class Argon2Params {
  const Argon2Params({
    required this.parallelism,
    required this.memory,
    required this.iterations,
    this.hashLength = SeedWrapper.keyLength,
  });

  /// Mobile-tuned default (bug #board-freeze): the RFC 9106 "second recommended"
  /// low-memory profile — 19 MiB, 2 passes, single lane. On a modern phone this
  /// completes in well under a second (target ≤ ~1 s/derivation) yet stays at or
  /// above OWASP's Argon2id floor (≥ 19 MiB / ≥ 2 iterations / parallelism 1).
  /// Crucially it now runs OFF the UI isolate, so even the worst-case cost never
  /// freezes the screen.
  static const Argon2Params mobile = Argon2Params(
    parallelism: 1,
    memory: 19 * 1024, // 1 kB blocks → 19 MiB
    iterations: 2,
  );

  /// Maximum number of processors an attacker can use per attempt (Argon2 lanes).
  final int parallelism;

  /// Minimum number of 1 kB blocks of memory the derivation must touch.
  final int memory;

  /// Number of Argon2 passes over memory.
  final int iterations;

  /// Derived-key length in bytes (the AES-256 key → 32).
  final int hashLength;

  Argon2id toKdf() => Argon2id(
        parallelism: parallelism,
        memory: memory,
        iterations: iterations,
        hashLength: hashLength,
      );
}

class SeedWrapper implements SeedWrapping {
  SeedWrapper({Argon2Params? params, IsolateRunner? runner})
      : _params = params ?? Argon2Params.mobile,
        _runner = runner ?? defaultRunner;

  /// Salt length (Argon2id nonce), in bytes. 16 bytes = 128 bits, the standard
  /// salt size; random per wrap so the same secret yields a different blob each
  /// time (CLAUDE.md §2: named, not a magic number).
  static const saltLength = 16;

  /// The derived AES key length, in bytes (256-bit AES-GCM).
  static const keyLength = 32;

  /// AES-256-GCM nonce length, in bytes (the cipher's standard 96-bit nonce).
  /// Pinned as a constant so the wire-format header geometry is computable
  /// without constructing an [AesGcm] just to read it.
  static const aesNonceLength = 12;

  /// AES-256-GCM authentication-tag length, in bytes (128-bit GCM tag).
  static const aesMacLength = 16;

  final Argon2Params _params;
  final IsolateRunner _runner;

  /// Wrap [seed] under [secret] (the app password or the OMG code), returning the
  /// base64 `salt ++ nonce ++ cipherText ++ mac` blob to escrow. A fresh random
  /// salt and nonce are drawn per call, so wrapping the same seed twice (once per
  /// secret, or even the same secret twice) never produces the same ciphertext.
  ///
  /// The Argon2id + AES-GCM runs on a background isolate ([_runner]) so the heavy
  /// derivation never blocks the UI isolate (bug #board-freeze).
  @override
  Future<String> wrap({required List<int> seed, required String secret}) {
    final req = _WrapRequest(
      seed: Uint8List.fromList(seed),
      secret: secret,
      params: _params,
    );
    return _runner<String>(() => _wrapInIsolate(req));
  }

  /// Unwrap a base64 [blob] produced by [wrap] using [secret], returning the
  /// recovered seed bytes — or throwing [SeedUnwrapException] when the secret is
  /// wrong, the blob is malformed, or the GCM authentication tag does not verify.
  /// The exception carries NO plaintext (CLAUDE.md §7); the caller surfaces a
  /// friendly "that password/code didn't work" message.
  ///
  /// The base64 decode + length checks happen on the calling isolate (cheap,
  /// fail-fast); only the Argon2id + AES-GCM decrypt is offloaded.
  @override
  Future<Uint8List> unwrap({required String blob, required String secret}) async {
    final Uint8List bytes;
    try {
      bytes = base64.decode(blob);
    } on FormatException {
      throw const SeedUnwrapException('escrow blob is not valid base64');
    }
    const headerLength = saltLength + aesNonceLength + aesMacLength;
    if (bytes.length <= headerLength) {
      throw const SeedUnwrapException('escrow blob is too short to be a wrap');
    }
    final req = _UnwrapRequest(bytes: bytes, secret: secret, params: _params);
    final result = await _runner<_UnwrapOutcome>(() => _unwrapInIsolate(req));
    if (!result.ok) {
      throw SeedUnwrapException(
          result.reason ?? 'the password or code did not match');
    }
    return result.seed!;
  }
}

// --- Isolate entry points -------------------------------------------------
//
// Top-level (closure-free) functions so they are safe to run on a background
// isolate. They take a plain serializable request and return a plain
// serializable result; all crypto runs here, off the UI isolate.

/// The wrap computation: derive an AES key from [req.secret] via Argon2id, then
/// AES-256-GCM encrypt the seed. Returns the base64 `salt ++ nonce ++ ct ++ mac`.
Future<String> _wrapInIsolate(_WrapRequest req) async {
  final cipher = AesGcm.with256bits();
  final salt = _randomBytes(SeedWrapper.saltLength);
  final key = await req.params.toKdf().deriveKeyFromPassword(
        password: req.secret,
        nonce: salt,
      );
  final box = await cipher.encrypt(
    req.seed,
    secretKey: key,
    nonce: cipher.newNonce(),
  );
  final blob = BytesBuilder()
    ..add(salt)
    ..add(box.nonce)
    ..add(box.cipherText)
    ..add(box.mac.bytes);
  return base64.encode(blob.toBytes());
}

/// The unwrap computation: split the blob, derive the key, AES-256-GCM decrypt.
/// Returns an [_UnwrapOutcome] (never throws across the isolate boundary for the
/// expected "wrong secret" case — a thrown error would surface as a generic
/// isolate error; an outcome flag keeps the caller's clean exception mapping).
Future<_UnwrapOutcome> _unwrapInIsolate(_UnwrapRequest req) async {
  final cipher = AesGcm.with256bits();
  final bytes = req.bytes;
  final nonceLength = cipher.nonceLength;
  final macLength = cipher.macAlgorithm.macLength;
  final salt = bytes.sublist(0, SeedWrapper.saltLength);
  final nonce = bytes.sublist(
      SeedWrapper.saltLength, SeedWrapper.saltLength + nonceLength);
  final cipherText = bytes.sublist(
      SeedWrapper.saltLength + nonceLength, bytes.length - macLength);
  final mac = Mac(bytes.sublist(bytes.length - macLength));
  final key = await req.params.toKdf().deriveKeyFromPassword(
        password: req.secret,
        nonce: salt,
      );
  try {
    final seed = await cipher.decrypt(
      SecretBox(cipherText, nonce: nonce, mac: mac),
      secretKey: key,
    );
    return _UnwrapOutcome.success(Uint8List.fromList(seed));
  } on SecretBoxAuthenticationError {
    // Wrong secret (or tampered blob): the GCM tag failed to verify.
    return const _UnwrapOutcome.failure('the password or code did not match');
  }
}

Uint8List _randomBytes(int n) {
  final rnd = SecureRandom.fast;
  final out = Uint8List(n);
  for (var i = 0; i < n; i++) {
    out[i] = rnd.nextUint32() & 0xff;
  }
  return out;
}

/// Serializable request for [_wrapInIsolate] (only plain bytes/strings/ints
/// cross the isolate boundary).
class _WrapRequest {
  const _WrapRequest({
    required this.seed,
    required this.secret,
    required this.params,
  });

  final Uint8List seed;
  final String secret;
  final Argon2Params params;
}

/// Serializable request for [_unwrapInIsolate].
class _UnwrapRequest {
  const _UnwrapRequest({
    required this.bytes,
    required this.secret,
    required this.params,
  });

  final Uint8List bytes;
  final String secret;
  final Argon2Params params;
}

/// Serializable result of [_unwrapInIsolate]: the recovered seed on success, or
/// a clean reason on the expected wrong-secret failure.
class _UnwrapOutcome {
  const _UnwrapOutcome.success(this.seed)
      : ok = true,
        reason = null;
  const _UnwrapOutcome.failure(this.reason)
      : ok = false,
        seed = null;

  final bool ok;
  final Uint8List? seed;
  final String? reason;
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
