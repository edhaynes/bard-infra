import 'dart:convert';
import 'dart:typed_data';

import 'package:bard_pro/box/seed_recovery.dart';

/// A trivial, synchronous [SeedWrapping] for WIDGET tests.
///
/// The production [SeedWrapper] uses isolate-backed Argon2id, which does not
/// complete inside the widget-test fake-async zone (it times out with
/// "Segment processing timeout"). The real crypto is covered by the pure-unit
/// `seed_recovery_test.dart` / `recovery_test.dart`; widget tests only need a
/// wrap that round-trips and rejects the wrong secret, so this fake prefixes the
/// secret to the base64 seed and checks the secret on unwrap. It is NOT
/// cryptographic and is test-only.
class FakeSeedWrapper implements SeedWrapping {
  const FakeSeedWrapper();

  static const _sep = ' ';

  @override
  Future<String> wrap({required List<int> seed, required String secret}) async {
    return base64.encode(utf8.encode('$secret$_sep${base64.encode(seed)}'));
  }

  @override
  Future<Uint8List> unwrap({required String blob, required String secret}) async {
    final String decoded;
    try {
      decoded = utf8.decode(base64.decode(blob));
    } on FormatException {
      throw const SeedUnwrapException('bad blob');
    }
    final i = decoded.indexOf(_sep);
    if (i < 0 || decoded.substring(0, i) != secret) {
      throw const SeedUnwrapException('the password or code did not match');
    }
    return Uint8List.fromList(base64.decode(decoded.substring(i + 1)));
  }
}
