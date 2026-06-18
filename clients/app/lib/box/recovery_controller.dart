import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api.dart';
import 'box_controller.dart';
import 'crockford.dart';
import 'device_identity.dart';
import 'seed_recovery.dart';

/// Outcome of the first-run escrow setup: the one-time OMG code to show the user
/// ONCE (ADR-0016 §5). Held only long enough for the OMG screen to display +
/// confirm, then wiped from memory by the controller.
class EscrowSetupResult {
  const EscrowSetupResult({required this.omgCode, required this.handle});

  /// The one-time recovery code, formatted `XXXXX-XXXXX-XXXXX`. Shown ONCE on the
  /// OMG screen; the controller does not retain it — the UI wipes its copy after
  /// the user confirms they saved it (ADR-0016 §5).
  final String omgCode;

  /// The account handle the seed was escrowed under (echoed for the confirm UI).
  final String handle;
}

/// Orchestrates the two-tier seed-escrow recovery (ADR-0016 §5) for the UI
/// (CLAUDE.md §2: logic out of widgets). Two flows:
///
///   1. **First-run escrow setup** ([setUpEscrow]) — after the device has its
///      identity, capture a handle + app password, generate a one-time OMG code,
///      wrap the 32-byte seed twice (under the password and under the OMG code),
///      and `POST /recovery/escrow`. The OMG code is returned for the one-screen
///      show-once display; the controller does not retain it.
///   2. **Recovery** ([recover]) — a fresh install enters a handle + EITHER the
///      password OR the OMG code; `GET /recovery/escrow/{handle}` returns the
///      wraps; the matching wrap is decrypted locally to the seed; the identity
///      (and its DERIVED, stable deviceId) is rebuilt from the seed and
///      self-registered, restoring box memberships.
///
/// The seed, password, and OMG plaintext NEVER leave the device and are never
/// logged (CLAUDE.md §0.2 / §7). Collaborators are injected (DI seam):
/// [apiFactory] builds the [BardApi] (device-token mode for escrow, no-auth for
/// fetch), [identity] is the SAME [DeviceIdentity] the box flows use (so a
/// recovered identity is the live one), [wrapper] does the crypto, and
/// [omgGenerator] yields the code (overridable so tests pin it).
class RecoveryController extends ChangeNotifier {
  RecoveryController({
    required BoxApiFactory apiFactory,
    required DeviceIdentity identity,
    SeedWrapping? wrapper,
    String Function()? omgGenerator,
  })  : _apiFactory = apiFactory,
        _identity = identity,
        _wrapper = wrapper ?? SeedWrapper(),
        _omgGenerator = omgGenerator ?? Crockford.generateOmgCode;

  // ignore_for_file: prefer_initializing_formals — public named params map to
  // private fields.
  final BoxApiFactory _apiFactory;
  final DeviceIdentity _identity;
  final SeedWrapping _wrapper;
  final String Function() _omgGenerator;

  bool _busy = false;
  String? _error;
  ProvisionedIdentity? _activeIdentity;

  /// True while an escrow/recovery call is in flight (drives spinners).
  bool get busy => _busy;

  /// Last user-facing error, or null when the last action succeeded.
  String? get error => _error;

  /// Build a device-token [BardApi] for the escrow POST (the device signs with
  /// its own key, ADR-0016 §5). Mirrors [BoxController]'s device-mode api.
  BardApi _deviceApi() => _apiFactory(
        tokenProvider: () {
          final id = _activeIdentity;
          return id == null ? '' : _identity.mintTokenFor(id);
        },
      );

  /// First-run escrow setup. Provisions/loads the device identity, wraps its
  /// seed under [password] and a fresh OMG code, and escrows both ciphertexts for
  /// [handle]. Returns the [EscrowSetupResult] (carrying the OMG code to show
  /// ONCE) on success, or null on failure (message in [error]).
  ///
  /// [handle] and [password] are validated non-empty (fail fast, CLAUDE.md
  /// §0.11). The seed plaintext is wrapped in-memory and never escrowed or
  /// logged; only the two ciphertext blobs are sent.
  Future<EscrowSetupResult?> setUpEscrow({
    required String handle,
    required String password,
  }) async {
    if (handle.trim().isEmpty || password.isEmpty) {
      _error = 'Enter both an account handle and a password.';
      notifyListeners();
      return null;
    }
    return _run(() async {
      final id = await _identity.provisionLocal();
      _activeIdentity = id;
      final omgCode = _omgGenerator();
      final seed = id.seed;
      final wraps = EscrowWraps(
        password: await _wrapper.wrap(seed: seed, secret: password),
        // The OMG secret is the normalized code (separators stripped) so the same
        // canonical bytes wrap and later unwrap regardless of how it is typed.
        omg: await _wrapper.wrap(
          seed: seed,
          secret: Crockford.normalizeOmgCode(omgCode) ?? omgCode,
        ),
      );
      final api = _deviceApi();
      try {
        await api.escrowSeed(
          handle: handle.trim(),
          publicKey: id.publicKeyBase64,
          wraps: wraps,
        );
      } finally {
        api.close();
      }
      return EscrowSetupResult(omgCode: omgCode, handle: handle.trim());
    });
  }

  /// Recover the device identity on a fresh install. Fetches the escrow for
  /// [handle], decrypts the wrap that matches [secret] (the app password OR the
  /// OMG code — [usingOmgCode] selects which wrap to attempt), rebuilds the
  /// identity + its stable deviceId from the recovered seed, and self-registers
  /// it so the same identity (and therefore its box memberships) is restored.
  ///
  /// Returns the restored [ProvisionedIdentity] on success, or null on failure
  /// (wrong secret, unknown handle, offline — message in [error]). An OMG code is
  /// normalized (case/separators) before the unwrap so a code typed loosely still
  /// resolves.
  Future<ProvisionedIdentity?> recover({
    required String handle,
    required String secret,
    required bool usingOmgCode,
  }) async {
    if (handle.trim().isEmpty || secret.trim().isEmpty) {
      _error = usingOmgCode
          ? 'Enter your account handle and recovery code.'
          : 'Enter your account handle and password.';
      notifyListeners();
      return null;
    }
    return _run<ProvisionedIdentity?>(() async {
      final api = _plainApi();
      EscrowRecord record;
      try {
        record = await api.fetchEscrow(handle.trim());
      } finally {
        api.close();
      }
      final String unwrapSecret;
      final String blob;
      if (usingOmgCode) {
        final normalized = Crockford.normalizeOmgCode(secret);
        if (normalized == null) {
          _error = "That recovery code doesn't look right. "
              'It has 15 letters and numbers, like 7K3P9-R2M4X-WQ8TB.';
          return null;
        }
        unwrapSecret = normalized;
        blob = record.wraps.omg;
      } else {
        unwrapSecret = secret;
        blob = record.wraps.password;
      }
      final List<int> seed;
      try {
        seed = await _wrapper.unwrap(blob: blob, secret: unwrapSecret);
      } on SeedUnwrapException {
        _error = usingOmgCode
            ? "That recovery code didn't match this account."
            : "That password didn't match this account.";
        return null;
      }
      final restored = await _identity.restoreFromSeed(seed);
      _activeIdentity = restored;
      // Self-register the restored public key so the device's self-signed tokens
      // verify server-side again (the deviceId is unchanged, so memberships hold).
      final regApi = _deviceApi();
      try {
        await _identity.ensureProvisioned(regApi);
      } finally {
        regApi.close();
      }
      return restored;
    });
  }

  /// Build a no-auth [BardApi] for the escrow FETCH (the recovering device has no
  /// credential yet — the handle is the lookup key).
  BardApi _plainApi() => _apiFactory();

  /// Run [action] with busy/error bookkeeping, returning null when it throws a
  /// [BardApiException] (surfaced via [error]) and rethrowing nothing else.
  Future<T?> _run<T>(Future<T> Function() action) async {
    _busy = true;
    _error = null;
    notifyListeners();
    try {
      return await action();
    } on BardApiException catch (e) {
      _error = e.message;
      return null;
    } finally {
      _busy = false;
      notifyListeners();
    }
  }
}
