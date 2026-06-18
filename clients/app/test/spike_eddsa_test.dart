// S2 spike (throwaway) — prove a Dart-minted EdDSA JWT verifies under PyJWT.
// Generates an Ed25519 keypair, self-signs a JWT (sub/iss/exp), and writes the
// token + raw public key to /tmp for the Python verifier. Delete after S2.
import 'dart:convert';
import 'dart:io';

import 'package:dart_jsonwebtoken/dart_jsonwebtoken.dart';
import 'package:ed25519_edwards/ed25519_edwards.dart' as ed;
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('S2 spike: device generates Ed25519, self-signs an EdDSA JWT', () {
    final kp = ed.generateKey();

    final token = JWT(
      <String, dynamic>{},
      issuer: 'bardllm-pro',
      subject: 'spike-device',
    ).sign(
      EdDSAPrivateKey(kp.privateKey.bytes),
      algorithm: JWTAlgorithm.EdDSA,
      expiresIn: const Duration(hours: 1),
    );

    File('/tmp/eddsa_spike.json').writeAsStringSync(jsonEncode(<String, String>{
      'token': token,
      'pub_b64': base64.encode(kp.publicKey.bytes),
    }));

    expect(token.split('.').length, 3);
    // ignore: avoid_print
    print('SPIKE: wrote /tmp/eddsa_spike.json (pub=${kp.publicKey.bytes.length}B)');
  });
}
