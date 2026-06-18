import 'dart:math';

import 'package:cryptography/dart.dart' show DartSha256;

/// Crockford base32 encoding + the one-time OMG recovery code (ADR-0016 §5).
///
/// Crockford's alphabet excludes the ambiguous letters I, L, O and U so a human
/// can read a code off a screen or a printout and type it back without
/// confusing `0`/`O` or `1`/`I`/`L`. It is used in two places:
///   - the stable deviceId (a slice of `sha256(publicKey)` rendered as
///     Crockford base32, [encodeBytes]), and
///   - the one-time OMG code ([generateOmgCode]) that wraps the device seed.
///
/// Pure Dart, no platform channel — runs on every target (CLAUDE.md §5).
class Crockford {
  Crockford._();

  /// Crockford base32 symbol alphabet (RFC-less de-facto standard): the digits
  /// `0-9` then `A-Z` with `I`, `L`, `O`, `U` removed. 32 symbols exactly.
  static const alphabet =
      '0123456789ABCDEFGHJKMNPQRSTVWXYZ'; // pragma: allowlist secret — public alphabet, not a secret

  /// The number of symbols in one OMG group and the number of groups, so the
  /// shape (`XXXXX-XXXXX-XXXXX`) lives in one place (CLAUDE.md §2: no magic
  /// numbers). 3 groups × 5 chars = 15 symbols = 75 bits of entropy.
  static const omgGroupCount = 3;
  static const omgGroupLength = 5;

  /// The character that joins OMG groups for readability.
  static const omgSeparator = '-';

  /// Encode [bytes] as Crockford base32 (5 bits per symbol, most-significant
  /// bit first), with no padding. Deterministic — the same bytes always yield
  /// the same string, which is what makes the derived deviceId stable across a
  /// recovery (ADR-0016 §5: recovering the seed reproduces the same deviceId).
  static String encodeBytes(List<int> bytes) {
    final out = StringBuffer();
    var buffer = 0;
    var bitsInBuffer = 0;
    for (final byte in bytes) {
      buffer = (buffer << 8) | (byte & 0xff);
      bitsInBuffer += 8;
      while (bitsInBuffer >= 5) {
        bitsInBuffer -= 5;
        out.write(alphabet[(buffer >> bitsInBuffer) & 0x1f]);
      }
    }
    if (bitsInBuffer > 0) {
      // Left-align the remaining bits into a final 5-bit symbol.
      out.write(alphabet[(buffer << (5 - bitsInBuffer)) & 0x1f]);
    }
    return out.toString();
  }

  /// Generate a fresh one-time OMG code (e.g. `7K3P9-R2M4X-WQ8TB`) from a CSPRNG
  /// ([random], defaults to [Random.secure]). The code is the human-presented
  /// recovery secret: it is shown once, used to wrap the device seed, then wiped
  /// from memory. Drawn symbol-by-symbol from [alphabet] so every character is a
  /// valid Crockford symbol (no normalization needed on the way out).
  static String generateOmgCode({Random? random}) {
    final rng = random ?? Random.secure();
    final groups = <String>[];
    for (var g = 0; g < omgGroupCount; g++) {
      final group = StringBuffer();
      for (var i = 0; i < omgGroupLength; i++) {
        group.write(alphabet[rng.nextInt(alphabet.length)]);
      }
      groups.add(group.toString());
    }
    return groups.join(omgSeparator);
  }

  /// Normalize a user-typed OMG code into the exact secret bytes the wrap was
  /// keyed with: uppercase, strip separators/spaces, and apply Crockford's
  /// canonical letter substitutions (`I`/`L` → `1`, `O` → `0`) so a code typed
  /// with a confusable still resolves. Returns the cleaned symbol string (the
  /// value used as the Argon2id secret), or null when the input is not a
  /// well-formed code (wrong length or an out-of-alphabet symbol) so the caller
  /// fails fast rather than deriving a key from garbage (CLAUDE.md §0.11).
  static String? normalizeOmgCode(String input) {
    final cleaned = StringBuffer();
    for (final rune in input.toUpperCase().runes) {
      var ch = String.fromCharCode(rune);
      if (ch == omgSeparator || ch == ' ') continue;
      // Crockford canonical substitutions for the confusable inputs.
      if (ch == 'I' || ch == 'L') ch = '1';
      if (ch == 'O') ch = '0';
      if (!alphabet.contains(ch)) return null;
      cleaned.write(ch);
    }
    final symbols = cleaned.toString();
    if (symbols.length != omgGroupCount * omgGroupLength) return null;
    return symbols;
  }
}

/// The number of `sha256(publicKey)` bytes folded into the deviceId. 10 bytes =
/// 80 bits → 16 Crockford symbols, comfortably collision-safe for the MVP fleet
/// size (CLAUDE.md §2: no magic number — named here, used in [deriveDeviceId]).
const deviceIdHashBytes = 10;

/// The `dev-` prefix kept from the legacy id shape so existing log/UI scanning
/// and the backend's id handling see the same family of values; only the suffix
/// changes from time-seeded to key-derived.
const deviceIdPrefix = 'dev-';

/// Derive the STABLE deviceId from the raw 32-byte Ed25519 [publicKeyBytes]
/// (ADR-0016 §5 prerequisite refactor).
///
/// `deviceId = "dev-" + crockford(sha256(publicKey)[:deviceIdHashBytes])`. This
/// is DETERMINISTIC: recovering the seed reproduces the same keypair → the same
/// public key → the same deviceId, which is exactly what keeps box memberships
/// intact across a recovery. The deviceId carries no secret — the public key is
/// already public — so a hash prefix is safe to expose. Synchronous SHA-256
/// ([DartSha256.hashSync]) keeps the call non-async so it slots into the
/// existing identity-load path without forcing an await.
String deriveDeviceId(List<int> publicKeyBytes) {
  final digest = const DartSha256().hashSync(publicKeyBytes).bytes;
  final slice = digest.sublist(0, deviceIdHashBytes);
  return '$deviceIdPrefix${Crockford.encodeBytes(slice)}';
}
