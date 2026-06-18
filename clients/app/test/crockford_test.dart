import 'dart:math';

import 'package:bard_pro/box/crockford.dart';
import 'package:flutter_test/flutter_test.dart';

/// Unit tests for Crockford base32 + the OMG recovery code (ADR-0016 §5).
void main() {
  group('encodeBytes', () {
    test('encodes known vectors (5-bit groups, MSB first)', () {
      // 0x00 = 8 bits → symbol 00000 = '0', then 3 leftover bits left-aligned to
      // 00000 = '0' → "00".
      expect(Crockford.encodeBytes([0x00]), '00');
      // 16 bits of zero → three full 5-bit symbols + 1 leftover bit → "0000".
      expect(Crockford.encodeBytes([0x00, 0x00]), '0000');
      // 0xff = 8 bits: 11111 = alphabet[31] = 'Z', then 111 left-aligned = 11100
      // = alphabet[28] = 'W' → "ZW".
      expect(Crockford.encodeBytes([0xff]), 'ZW');
    });

    test('only emits symbols from the Crockford alphabet', () {
      final bytes = List<int>.generate(40, (i) => (i * 37 + 11) & 0xff);
      final encoded = Crockford.encodeBytes(bytes);
      for (final ch in encoded.split('')) {
        expect(Crockford.alphabet.contains(ch), isTrue, reason: '$ch not in alphabet');
      }
    });

    test('is deterministic for the same input', () {
      final bytes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
      expect(Crockford.encodeBytes(bytes), Crockford.encodeBytes(bytes));
    });

    test('the alphabet excludes the ambiguous I, L, O, U', () {
      expect(Crockford.alphabet.length, 32);
      for (final excluded in ['I', 'L', 'O', 'U']) {
        expect(Crockford.alphabet.contains(excluded), isFalse);
      }
    });
  });

  group('generateOmgCode', () {
    test('has the XXXXX-XXXXX-XXXXX shape (3 groups × 5 Crockford symbols)', () {
      final code = Crockford.generateOmgCode();
      final groups = code.split(Crockford.omgSeparator);
      expect(groups.length, Crockford.omgGroupCount);
      for (final g in groups) {
        expect(g.length, Crockford.omgGroupLength);
        for (final ch in g.split('')) {
          expect(Crockford.alphabet.contains(ch), isTrue);
        }
      }
      // The format string the user sees, e.g. 7K3P9-R2M4X-WQ8TB.
      expect(RegExp(r'^[0-9A-Z]{5}-[0-9A-Z]{5}-[0-9A-Z]{5}$').hasMatch(code), isTrue);
    });

    test('is drawn from the injected RNG (deterministic for a seeded Random)', () {
      // A seeded (non-secure) Random makes the draw reproducible for the test.
      final a = Crockford.generateOmgCode(random: Random(42));
      final b = Crockford.generateOmgCode(random: Random(42));
      expect(a, b);
    });

    test('two fresh codes differ (entropy)', () {
      expect(Crockford.generateOmgCode(), isNot(Crockford.generateOmgCode()));
    });
  });

  group('normalizeOmgCode', () {
    test('round-trips a freshly generated code to its 15-symbol secret', () {
      final code = Crockford.generateOmgCode(random: Random(7));
      final normalized = Crockford.normalizeOmgCode(code);
      expect(normalized, isNotNull);
      expect(normalized!.length, Crockford.omgGroupCount * Crockford.omgGroupLength);
      // Normalizing the already-canonical code is the code with separators stripped.
      expect(normalized, code.replaceAll(Crockford.omgSeparator, ''));
    });

    test('lower-cases, strips spaces/dashes, and applies confusable substitutions',
        () {
      // A user types it loosely with I/L/O confusables and stray spacing.
      final typed = ' 7k3p9 r2m4x wq8tb ';
      final normalized = Crockford.normalizeOmgCode(typed);
      expect(normalized, '7K3P9R2M4XWQ8TB');
      // I/L → 1, O → 0.
      expect(Crockford.normalizeOmgCode('ILO11-22233-44455'), '11011' '22233' '44455');
    });

    test('returns null for a wrong-length code', () {
      expect(Crockford.normalizeOmgCode('7K3P9-R2M4X'), isNull); // 10 symbols
      expect(Crockford.normalizeOmgCode('7K3P9-R2M4X-WQ8TB-EXTRA'), isNull);
    });

    test('returns null for an out-of-alphabet symbol', () {
      // '!' is not a Crockford symbol (and not a substitution target).
      expect(Crockford.normalizeOmgCode('7K3P9-R2M4X-WQ8T!'), isNull);
    });
  });

  group('deriveDeviceId', () {
    test('is deterministic and shaped "dev-" + Crockford(sha256[:10])', () {
      final pub = List<int>.generate(32, (i) => i);
      final id = deriveDeviceId(pub);
      expect(id, deriveDeviceId(pub), reason: 'deterministic');
      expect(id, startsWith(deviceIdPrefix));
      final suffix = id.substring(deviceIdPrefix.length);
      // 10 bytes = 80 bits → ceil(80/5) = 16 Crockford symbols.
      expect(suffix.length, 16);
      for (final ch in suffix.split('')) {
        expect(Crockford.alphabet.contains(ch), isTrue);
      }
    });

    test('different public keys yield different ids', () {
      final a = deriveDeviceId(List<int>.generate(32, (i) => i));
      final b = deriveDeviceId(List<int>.generate(32, (i) => 31 - i));
      expect(a, isNot(b));
    });
  });
}
