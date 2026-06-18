import 'dart:convert';
import 'dart:typed_data';

import 'package:ed25519_edwards/ed25519_edwards.dart' as ed;

import '../api.dart';
import '../device_auth.dart';
import '../secure_store.dart';
import 'crockford.dart';

/// Supplies the 32-byte RFC 8032 seed for a freshly-provisioned identity. The
/// production default draws a CSPRNG seed (via [DeviceAuth.generateKeyPair]);
/// tests inject a fixed seed so the derived deviceId is deterministic — the id
/// is `deriveDeviceId(publicKey)`, so pinning the seed pins the id (ADR-0016 §5).
typedef SeedFactory = Uint8List Function();

/// The device's SINGLE identity (ADR-0016 §1: "one key per device").
///
/// Owns the one Ed25519 keypair generated on first launch and persisted under
/// the device-level namespace ([SecretStore.writeDeviceIdentity]). This same
/// identity is used to:
///   - self-register the device (`POST /devices/self-register`),
///   - create + manage boxes it owns (device-token bearer on `POST /channels`,
///     `POST /invites`, members management) — closing bug #67, which was the
///     baked `BARD_AUTH_TOKEN` expiring,
///   - join boxes (redeem sends THIS device's public key).
///
/// There is no longer a per-(channel,device) key for the fabric identity: the
/// device presents the same public key to every box, and the registry verifies
/// the same self-signed token everywhere.
///
/// **Stable deviceId (ADR-0016 §5 prerequisite refactor).** The deviceId is
/// DERIVED from the public key (`deriveDeviceId`), not random/time-seeded, so
/// recovering the seed on a new device reproduces the SAME keypair → the SAME
/// public key → the SAME deviceId, which keeps box memberships intact across a
/// recovery.
///
/// Collaborators are injected (CLAUDE.md §2 DI): [secretStore] persists the
/// private key, [deviceAuth] mints the EdDSA tokens, and [seedFactory] supplies
/// the seed for a first-launch keypair (overridable in tests for a deterministic
/// id).
class DeviceIdentity {
  DeviceIdentity({
    required SecretStore secretStore,
    DeviceAuth deviceAuth = const DeviceAuth(),
    SeedFactory? seedFactory,
  })  : _secretStore = secretStore,
        _deviceAuth = deviceAuth,
        _seedFactory = seedFactory;

  // ignore_for_file: prefer_initializing_formals — the public named params map
  // to private fields; an initializing formal can't be a private named param.
  final SecretStore _secretStore;
  final DeviceAuth _deviceAuth;

  /// Optional injected seed source. Null in production (a random keypair is
  /// generated); tests pass a fixed seed so the derived deviceId is stable.
  final SeedFactory? _seedFactory;

  /// Ensure the device has its single identity provisioned and is self-registered
  /// with [api]. Idempotent and safe on every relaunch:
  ///   1. If no identity is stored, generate ONE keypair, DERIVE its deviceId from
  ///      the public key, and persist them (the private key is stored BEFORE the
  ///      network call, so the device never registers a key it cannot self-sign
  ///      for).
  ///   2. Self-register the public key (`POST /devices/self-register`). The
  ///      backend contract makes this idempotent — re-registering the same
  ///      (deviceId, publicKey) re-affirms ACTIVE rather than failing.
  ///
  /// Returns the provisioned identity. Self-register failures propagate as
  /// [BardApiException] (fail-fast, CLAUDE.md §0.11) so the caller surfaces them;
  /// the stored identity is left intact for the next attempt.
  Future<ProvisionedIdentity> ensureProvisioned(BardApi api) async {
    final identity = await _loadOrGenerate();
    await api.selfRegister(
      deviceId: identity.deviceId,
      publicKey: identity.publicKeyBase64,
    );
    return identity;
  }

  /// Load the stored identity, generating + persisting a fresh one on first
  /// launch. Does NOT touch the network — pure local provisioning, so callers
  /// that only need the keypair (redeem encoding) avoid a self-register round
  /// trip when one is not required.
  Future<ProvisionedIdentity> _loadOrGenerate() async {
    final stored = await _secretStore.readDeviceIdentity();
    if (stored != null) {
      return ProvisionedIdentity(
        deviceId: stored.deviceId,
        privateKeyBase64: stored.privateKey,
      );
    }
    final seedFactory = _seedFactory;
    final keyPair = seedFactory == null
        ? DeviceAuth.generateKeyPair()
        : DeviceAuth.keyPairFromSeed(seedFactory());
    return _persist(keyPair);
  }

  /// Persist [keyPair] under its DERIVED deviceId and return the in-memory
  /// identity. Shared by first-launch provisioning and recovery so both produce
  /// the same (deterministic) deviceId from the same public key.
  Future<ProvisionedIdentity> _persist(DeviceKeyPair keyPair) async {
    final deviceId = deriveDeviceId(base64.decode(keyPair.publicKeyBase64));
    // Persist before anything else can drop it — it is the device's only
    // credential and is never recoverable from the server (ADR-0016 §1).
    await _secretStore.writeDeviceIdentity(
      deviceId: deviceId,
      privateKey: keyPair.privateKeyBase64,
    );
    return ProvisionedIdentity(
      deviceId: deviceId,
      privateKeyBase64: keyPair.privateKeyBase64,
    );
  }

  /// Rebuild and persist the device identity from a recovered 32-byte [seed]
  /// (ADR-0016 §5 recovery). The seed deterministically regenerates the keypair
  /// and therefore the SAME deviceId the device originally had, so membership is
  /// preserved. Overwrites any existing stored identity — recovery is an explicit
  /// "this is now my identity" action. Returns the restored identity.
  Future<ProvisionedIdentity> restoreFromSeed(List<int> seed) async {
    return _persist(DeviceAuth.keyPairFromSeed(seed));
  }

  /// The stored/generated identity without any network call — used by the join
  /// flow (which sends the public key to redeem) and anywhere the keypair is
  /// needed without re-asserting registration.
  Future<ProvisionedIdentity> provisionLocal() => _loadOrGenerate();

  /// The currently stored identity, or null on a fresh install. Read-only — does
  /// NOT generate one (use [provisionLocal]/[ensureProvisioned] to create).
  Future<ProvisionedIdentity?> current() async {
    final stored = await _secretStore.readDeviceIdentity();
    if (stored == null) return null;
    return ProvisionedIdentity(
      deviceId: stored.deviceId,
      privateKeyBase64: stored.privateKey,
    );
  }

  /// Self-sign a fresh device fabric token for the stored identity, or null when
  /// no identity is provisioned yet. This is the bearer the device presents for
  /// owner actions (create channel/invite, members management) and fabric calls
  /// — never the baked `BARD_AUTH_TOKEN` (closes #67).
  Future<String?> mintToken() async {
    final identity = await current();
    if (identity == null) return null;
    return mintTokenFor(identity);
  }

  /// Self-sign a fresh token for an already-loaded [identity] — synchronous,
  /// since minting is pure once the private key is in hand. Used by the api's
  /// `tokenProvider` seam to re-mint per request without an async store read.
  String mintTokenFor(ProvisionedIdentity identity) => _deviceAuth.mintToken(
        deviceId: identity.deviceId,
        privateKeyBase64: identity.privateKeyBase64,
      );
}

/// The device's single provisioned identity in memory: its stable [deviceId] and
/// the base64 Ed25519 [privateKeyBase64]. [publicKeyBase64] is derived from the
/// trailing 32 bytes of the private representation (the value sent to the
/// registry), so it is never persisted separately.
class ProvisionedIdentity {
  ProvisionedIdentity({
    required this.deviceId,
    required this.privateKeyBase64,
  });

  final String deviceId;
  final String privateKeyBase64;

  /// The raw 32-byte Ed25519 public key (base64) — the value sent to
  /// self-register and redeem. ed25519_edwards stores seed(32) ++ pubkey(32);
  /// the public half is exactly the trailing 32 bytes.
  String get publicKeyBase64 {
    final bytes = base64.decode(privateKeyBase64);
    return base64.encode(bytes.sublist(ed.PublicKeySize, ed.PrivateKeySize));
  }

  /// The 32-byte RFC 8032 seed — the leading half of the private representation,
  /// and the value the recovery flow wraps + escrows (ADR-0016 §5). Secret keying
  /// material: never logged, never sent in the clear.
  Uint8List get seed => DeviceAuth.seedFromPrivateKey(privateKeyBase64);
}
