# Bard Software — Independent Security Evaluation

Status: Desk audit (read-only, one reviewer), 2026-06-10. **NOT a substitute for a
professional external pentest + independent cryptographer review** — input to scoping
that engagement, not a clean bill of health. Scope: Bard fabric (Router +
Registry + agents + LokNet broker), Maude/claudeTalk client + current relay, and the
planned hosted/E2EE/multi-tenant/plugin tiers.

## Headline
The shipped fabric is **honestly documented and structurally sound for Profile A**
(single owner, trusted devices): TLS-default + fail-fast cleartext gate, verified JWT on
every hop, no `verify=False` anywhere, secrets via Secret Manager/Keychain never
committed, a real swappable auth seam, rootless cap-dropped UBI-9 containers. Risk
concentrates in three places: (1) the single shared HMAC secret + bug #54 (real
link-hijack), (2) the **Maude relay today has no auth and sees plaintext — E2EE is
paper-only**, (3) everything gating the hosted/multi-tenant future is unbuilt and must
not ship before external audit.

## Findings by severity

**CRITICAL**
- **C-1 — Maude relay `/ws/voice`: no auth + plaintext peer broadcast.** Trusts a
  `?session=` param as identity; fans every utterance to all other sessions; handles
  cleartext. Contained TODAY (binds 127.0.0.1 / Tailnet-private) — **critical as a
  launch-gate**, not a live exposure. Must not be exposed publicly under any
  "private/E2EE" branding until wss + account-bound auth + real per-recipient E2EE land.
  Add a guard refusing non-loopback bind without auth.
  - **Update 2026-06-12 (Sprint B4, v1.5.4) — fabric side closed; DOWNGRADED to
    High pending client adoption.** Bug #56's auth mechanism now exists and is
    enforced on the Bard fabric's relay/data path: with
    `BARDPRO_DEVICE_IDENTITY_ENABLED=true` the Router's `/v1/message` and the
    broker `/v1/agent-link` hello verify per-device credentials
    (`FleetOrDeviceVerifier` → `PerDeviceVerifier`): unknown, pending, revoked,
    and cross-device (A's key claiming B) tokens are rejected before anything is
    relayed, and a Registry-side revoke takes effect on the Router's next
    request (`DeviceStore(reload_on_read=True)`). The legacy fleet JWT coexists
    opt-in so migration is per-device, not flag-day. Pinned by
    `tests/test_security_pentest.py` §7. **Still open (tracked in bug #56): the
    Maude/claudeTalk voice WS transport itself must present per-device tokens
    and the relay must verify them** — that client/relay adoption lives in the
    claudeTalk codebase, plus wss + the non-loopback-bind guard + E2EE before
    any public exposure. The launch gate stands until then.

**HIGH**
- **H-1 — Bug #54 confirmed (`router/broker.py:301-308`): broker `hello` verifies the
  JWT but never checks `sub == agentId`.** With one shared secret, any valid token can
  claim any agentId; the new link evicts the old and steals all dispatched inferences
  (confidentiality + integrity break). The register-side mitigation does NOT protect
  dispatch. **~3-line fix; launch-gating before any broker link leaves the owner's boxes.**
- **H-2 — Single shared fleet HMAC secret.** No per-entity identity; one leaked token =
  full fleet access + (with H-1) impersonate any agent; authz is binary "valid JWT?";
  no revocation short of fleet-wide rotation. Honestly documented; fine for single owner;
  **structural blocker for Profile B / hosted** — needs per-entity asymmetric short-lived
  tokens + real authorization.
  - **Update 2026-06-12 (B2+B4, v1.5.3–1.5.4) — substantially mitigated, opt-in.**
    Per-device identity shipped (ADR-0010, `contracts/enrollment.schema.json`):
    each device holds its own HMAC key issued via enroll→approve (or B3 invite
    redemption), individually revocable, and the Router's data path enforces it
    (see C-1 update). Still HMAC (symmetric, server-held keys), still opt-in
    with fleet-JWT coexistence — the asymmetric/PQ per-entity credential and
    real authorization remain the v3 bar for Profile B / hosted.
- **H-3 — E2EE entirely unimplemented; "private/E2EE" is a roadmap claim.** On-device
  keys/sealing not present; relay sees plaintext (C-1). Gap is currently *total*. BUT
  POSITIONING explicitly says so and gates the public rendezvous on E2EE — the risk is
  **shipping order, not deception**. Keep the gate absolute; independently review M0–M3.

**MEDIUM**
- **M-1 — `JwtVerifier` doesn't *require* `exp`/`iss`/`sub`** (`common/auth.py:43-50`): a
  token minted without `exp` never expires. Shipped minter always sets exp, but the
  verifier doesn't enforce it. **~1-line fix:** `options={"require":["exp","iss","sub"],
  "verify_exp":True}` + leeway. Also makes `sub` mandatory for the H-1 fix.
- **M-2 — Server-blind escrow KDF unpinned:** Argon2 params/salt/passphrase-floor not
  specified; weak passphrase + stored blob = offline brute force. Pin Argon2id params,
  prefer a high-entropy generated recovery code, cryptographer review before escrow ships.
- **M-3 — Metadata leakage + no forward secrecy:** plane-1 relay learns the social graph
  / who-talks-to-whom; v1 sealed-box (`crypto_box_seal`) has no FS/PCS (stolen long-term
  key decrypts all past/future). Disclose metadata exposure (à la Signal); decide
  sealed-box vs ratchet/MLS before charging for "private."
- **M-4 — Body-token vs Bearer-header split:** Router checks body `authToken` only,
  Registry checks header only, never cross-checked. Confused-deputy smell + body token is
  harder to keep out of logs. Pick one canonical location per hop; assert equality if both.
- **M-5 — No biometric Keychain ACL:** `KeychainStore` uses
  `WhenUnlockedThisDeviceOnly` (good: no iCloud/restore) but not the FR-S3-mandated
  `.biometryCurrentSet` ACL. When private keys land, use `SecAccessControl`.
- **M-6 — Plaintext secrets on disk (hygiene):** `authkey.txt` (Tailscale auth key) +
  `claudeTalk/eleven.txt` (live-format ElevenLabs `sk_…`). **Gitignored + never committed
  (verified)** — leak-prevention worked — but two real creds sit readable at repo roots.
  Move to keychain/secret-manager + delete; **rotate the ElevenLabs key** (it's been
  readable on disk).
- **M-7 — Single-instance in-memory state** (broker link map + JSON registry, `min=max=1`):
  no HA/scale; SPOF + overload. Fine for Profile A; disqualifying for hosted until Valkey
  (ADR-0010). Add edge rate-limiting regardless (no rate limit on `/v1/message` or
  `/v1/agent-link` today).

**LOW**
- **L-1** `--allow-unauthenticated` Cloud Run edge: correct (JWT is the gate) but any
  future route added without the verifier is world-open; `/version`+`/metrics` aid
  fingerprinting. Add a test asserting every non-health route requires auth; consider
  authing `/metrics`.
- **L-2** TLS terminates at Cloud Run; Router↔Registry loopback plaintext inside the
  instance (JWT still gates) — acceptable; document it.
- **L-3** SELinux `container_t` claim host-dependent and correctly hedged; ship the
  cap-drop/no-new-priv flags in the canonical run recipe (image doesn't enforce
  runtime-flag protections).
- **L-4** Plugin platform + cloud connectors (roadmap): untrusted-plugin execution needs
  a real sandbox (no ambient fleet credential); Drive/cloud-agents egress data (keep
  labeled opt-in, never "private"); supply chain (Quay+cosign+Clair #69) is right shape —
  verify signatures at pull; gate image-gen on the #71 legal/safety review. Give the
  plugin trust boundary its own ADR + external review.

## Solid — don't regress
No `verify=False` anywhere; cleartext is a fail-fast logged opt-in (no silent downgrade);
auth behind a real `TokenVerifier` seam (PQ drops in cleanly); secrets never committed /
never baked into images (`--set-secrets` from Secret Manager, fails loud if absent; iOS
JWT in Keychain); rootless UBI-9 non-root containers, sshd installed-but-off, no baked
host keys; registration can't impersonate over the link (`build_relay_body` ignores
frame agentId). **The documentation honesty (`[shipped]`/`[roadmap]` tags, self-disclosed
#54 and E2EE gap) is itself a meaningful security control — preserve it.**

## Fix-before-launch (prioritized)
**Before any broker link leaves the owner's boxes:** (1) bug #54 — bind `sub==agentId`
at hello (H-1, ~3 lines); (2) require `exp`/`iss`/`sub` in JwtVerifier (M-1, ~1 line).
**Before any public Maude rendezvous / "private" P2P marketing:** (3) no unauth public
relay — wss + account-bound bearer + non-loopback-without-auth guard (C-1); (4) ship +
independently review E2EE crypto (H-3, M-3 FS/PCS decision); (5) escrow Argon2id params +
recovery-code entropy + cryptographer review (M-2); (6) biometric Keychain ACL (M-5).
**Before any multi-tenant hosted tier:** (7) retire single shared secret → per-entity
identity + authorization (H-2; per-device HMAC identity + Router relay enforcement
shipped opt-in 2026-06-12, B2+B4 — asymmetric/PQ + authz still open); (8) Valkey + per-tenant isolation + edge rate-limiting
(M-7, L-1). **Hygiene now:** (9) move/rotate `authkey.txt`/`eleven.txt` (M-6); (10)
reconcile VERSION vs doc.

## External-audit gates (engage an independent firm + cryptographer)
- **Gate 1 — before broker leaves owner's boxes:** focused review of JWT model, #54 fix,
  broker WS handshake, cleartext-opt-in gates, body-credential logging (M-4), the
  unauthenticated edge (L-1). Small engagement.
- **Gate 2 — before public rendezvous / P2P "private" (non-negotiable):** full E2EE
  protocol review by a cryptographer (keygen, sealed-box vs ratchet/FS, signature verify,
  the relay's actual blindness, metadata, escrow KDF) + black-box pentest of the public
  relay (auth, session isolation, inject/eavesdrop per C-1, abuse/rate-limit). **Do not
  launch on the single-shared-secret model.**
- **Gate 3 — before multi-tenant scale / EU:** tenant-isolation + plugin-sandbox review;
  data-egress/DPA for cloud connectors+agents; GDPR/data-residency + DPIA (the relay's
  social-graph metadata is personal data even with content E2EE). Pair with #71 legal
  counsel + written AUP, before hosted tier and before the image-gen plugin.
