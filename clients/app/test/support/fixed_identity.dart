import 'dart:convert';
import 'dart:typed_data';

import 'package:bard_pro/box/crockford.dart';
import 'package:bard_pro/box/device_identity.dart';
import 'package:bard_pro/device_auth.dart';

/// Shared deterministic identity fixture for the box/recovery tests.
///
/// Because the deviceId is now DERIVED from the public key (ADR-0016 §5), a test
/// that needs a stable deviceId must provision from a fixed SEED rather than
/// injecting an id. This helper centralizes that seed so every test agrees on
/// the same `(seed → keypair → publicKey → deviceId)` chain.
///
/// The seed is the first 32 bytes of the canonical fixture string the rules
/// mandate for dummy secrets (`abcdefghijklmnopqrstuvwxyz0123456789ABCDEF`) —
/// a fixed, non-sensitive value, never a real key.
const fixtureSecretString = 'abcdefghijklmnopqrstuvwxyz0123456789ABCDEF';

/// The 32-byte RFC 8032 seed used by the fixed identity.
final Uint8List fixtureSeed =
    Uint8List.fromList(utf8.encode(fixtureSecretString).sublist(0, 32));

/// The example OMG recovery code from ADR-0016 §5 — a documented, NON-secret
/// fixture used across the recovery tests (formatted, with separators), and its
/// normalized 15-symbol form (the Argon2id secret the wrap is keyed with). Not a
/// real credential; the trailing comments clear the gitleaks generic-key rule
/// and the detect-secrets keyword rule.
const fixtureOmgCode = '7K3P9-R2M4X-WQ8TB'; // pragma: allowlist secret gitleaks:allow
const fixtureOmgSecret = '7K3P9R2M4XWQ8TB'; // pragma: allowlist secret gitleaks:allow

/// A [SeedFactory] yielding [fixtureSeed] — drop into `DeviceIdentity` /
/// `BoxController` / `RecoveryController` so the provisioned identity is stable.
Uint8List fixtureSeedFactory() => fixtureSeed;

/// The deterministic keypair the fixture seed expands to.
final DeviceKeyPair fixtureKeyPair = DeviceAuth.keyPairFromSeed(fixtureSeed);

/// The base64 32-byte public key of the fixed identity (what self-register /
/// redeem send and what the server stores).
String get fixturePublicKeyBase64 => fixtureKeyPair.publicKeyBase64;

/// The base64 64-byte private representation (seed ++ pubkey) of the fixture.
String get fixturePrivateKeyBase64 => fixtureKeyPair.privateKeyBase64;

/// The DERIVED, stable deviceId the fixture identity self-registers/joins under.
/// Computed exactly as production does (`deriveDeviceId(publicKey)`), so tests
/// assert against the real derivation, not a hand-written literal.
final String fixtureDeviceId =
    deriveDeviceId(base64.decode(fixturePublicKeyBase64));
