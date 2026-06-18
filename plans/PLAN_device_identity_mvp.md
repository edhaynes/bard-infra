Status: In Progress — S1–S5 done (S5 2026-06-18, branch `feat/s5-flutter-owner`: single device identity unified for self-register/create/join; create-box + owner management use the device-signed token, not BARD_AUTH_TOKEN — closes #67; 170 Flutter tests, analyze clean). Remaining: S6 (ping), S7 (recovery), S8 (sign-off).

# PLAN — MVP device identity, keys, box & ping

## Progress — 2026-06-18 (parallel fan-out, merged to main)
- **S1** ADR-0016 accepted; contracts frozen.
- **S2** EdDSA interop spike: **GO** (Dart EdDSA JWT verifies under PyJWT). Throwaway deleted.
- **S3** backend (`f8ef0f0`): registry stores device `publicKey`, `PerDeviceVerifier` verifies EdDSA, revoke wipes the key; deviceSecret removed from enroll/redeem/approve. **553 tests, 100%.**
- **S4** Flutter (`1cbd82c`): Ed25519 keygen, private key in Keychain (no backup), self-signed EdDSA tokens, redeem sends `publicKey`. **148 tests, analyze clean.**
- Integration green gate: Python 553 + Flutter 148, both green. Merged to `main` (a983d6b), pushed.

### Follow-ups surfaced
- **Headless-agent tier still HS256** (`agent/register.py`): won't verify against the new EdDSA `PerDeviceVerifier`. Out of MVP (client) scope; migrate the gx10/compute agent credential separately.
- **bard-llm has no pre-commit hooks** (§7.1) — small follow-up to install them.

Author: Jason-bard
Decision record: `docs/adr/ADR-0016-mvp-per-device-identity-and-recovery.md`
North star (deferred v3): `docs/adr/ADR-0009-three-tier-identity-keys-and-membership.md`

## MVP acceptance (Eddie, 2026-06-18)

1. **One Flutter client on all three consumer devices** — iPhone, Mac, Android.
2. **Create / revoke keys** — per-device Ed25519 identity; create on first launch, revoke a member.
3. **Create a box** — owner makes a public-LokNet channel.
4. **"Ping" each other over the box** — cross-device, cross-network signal over the existing
   fabric data path. **Voice / LiveKit is OUT** of this MVP.

## De-risked already

- `dart_jsonwebtoken` 2.17 ships **native EdDSA** (`EdDSAPrivateKey` via `ed25519_edwards`);
  PyJWT verifies EdDSA → the Dart↔Python crypto interop is a 1-hour confirmation, not an unknown.
- The auth layer has **explicit seams** for the symmetric→asymmetric swap (`device_auth.py:10`,
  `device_store.py:5`, `enrollment.schema.json:4`) → extension, not rebuild.

## The ladder (sized per §18.5; crypto-spike de-risks the one unknown first)

### S1 — ADR-0016 + contract freeze · ~0.5 d · drafted
- ADR-0016 written (status Proposed). Freeze contracts: `enrollment.schema.json` +
  redeem/enroll requests gain `publicKey`; the device token claim shape; the ping message shape.
- Done: ADR accepted (after Eddie's blessing); schemas updated; 0009 conflict reconciled in-ADR.

### S2 — Crypto interop spike · ~0.5 d · GO/NO-GO · de-risk
- Dart: generate Ed25519, mint an EdDSA JWT (sub/iss/exp). Python/PyJWT: verify against the
  public key; reject a tampered token. Hardcoded keys, no UI.
- Done: a Dart-minted EdDSA token verifies in PyJWT and fails when tampered.

### S3 — Backend: public-key registration + EdDSA verify + revoke · ~1–1.5 d · backend
- `device_store.py`: add `publicKey`; `admit`/`enroll` accept a client public key (stop minting
  `secret`); `device_secret()` → `device_public_key()`.
- `device_auth.py`: `PerDeviceVerifier` verifies EdDSA against the stored public key (algo param).
- `registry/app.py` + `channel_store.py`: redeem/enroll request takes `publicKey`; response drops
  `deviceSecret`. Confirm revoke removes the key.
- Tests: 100% line+branch — pubkey device self-signs → 200; HS256 / unknown / revoked → 401.
- Done: backend suite green; a registered-pubkey device reaches the data path; revoke cuts it.

### S4 — Flutter: keygen + secure store + self-signed tokens + auto-provision · ~1.5–2 d · all platforms
- Add the Ed25519 path (`dart_jsonwebtoken` EdDSA + a keygen source); ARM-build note in the dep entry.
- `device_auth.dart`: hold the private key, sign EdDSA. `secure_store.dart`: persist the **private
  key** (Keychain/Keystore, no backup). First-launch: silent auto-provision (seed → keypair →
  store → register public key).
- Done on iPhone/Mac/Android: a fresh install auto-provisions, registers, self-signs, reaches the fabric.

### S5 — Create box + create/revoke-keys UI on the device identity · ~1–1.5 d
- create-box + redeem use the device's **self-signed** token (retire the baked manager token →
  **closes #67**).
- Owner UI: list members; **revoke** a member (reuse the revoke endpoint); show own identity + QR.
- Done: iPhone auto-provisions → creates a box (no baked token) → Mac/Android auto-provision →
  redeem → members; owner revokes one → it drops.

### S6 — Ping over box · ~1 d · **the cross-device payoff**
- A "ping" = a small message to box members over Router `/v1/message` (per-device authed; #63).
  Recipients get a local notification/badge.
- Done: from the iPhone box, tap ping → Mac + Android (different networks) receive it. **The demo.**

### S7 — Recovery: seed escrow + app-password + OMG code + account handle · ~2–3 d · completes "the right way"
- Client: seed gen, Argon2id KDF (password), OMG code (Crockford 3×5), wrap seed under each →
  upload ciphertext. Backend: zero-knowledge blob store keyed by account handle (store ciphertext,
  never decrypt). Account handle captured first-run (the lightweight account). Recovery flow + the
  OMG one-screen (show once → save → wipe).
- Done: wipe+reinstall → recover via password; recover via OMG code; both restore the same
  identity + box memberships.

### S8 — All-device §14 sign-off · ~0.5 d
- On-device visual verification: iPhone, Mac, Android.

## Sequencing / parallelism

- **S2 gates S3 + S4.** After the spike, **S3 (backend) and S4 (Flutter) run in parallel** —
  disjoint dirs (`registry`/`common`/`router` vs `clients/app`), no shared write target.
- S5 needs S3 + S4. **S6 needs S5** → first demoable milestone.
- **S7** client-crypto (seed/KDF/OMG) is independent and can start in parallel with S5; its
  integration needs S5.

## First demoable milestone

After **S6**: identity (create/revoke keys) + box + **ping across all three devices on different
networks** — authed by each device's own keypair, no shared secret, no baked token.
