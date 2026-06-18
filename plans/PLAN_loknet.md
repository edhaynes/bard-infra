Status: Implemented, 2026-06-10 — slice 1 DONE (ADR-0013, v1.1.0); slice 2 DONE (v1.2.0); slice 3 DONE — real-socket mesh-free smoke (v1.2.1) + Cloud Run deploy recipe authored (v1.3.0). Public deploy is Eddie's to run; demo NOT rewired (decision 3).

# PLAN — LokNet: mesh-free transport (drop the Tailscale dependency)

> Feature #59. Internal codename **LokNet** (Eddie 2026-06-10; external name needs
> separate sign-off — see #59 note). First v2-Walk feature after bardpro-v1.0.0.

## Decisions (Eddie, 2026-06-10)
1. **Single front door** — the Router is the only public endpoint. Registration and
   heartbeat move onto the broker link; the Registry becomes fully private behind the
   Router. (Converges with ADR-0010's control-plane front door.)
2. **Public endpoint = Cloud Run *as one option*.** Per ADR-0014, cloud is never a hard
   dependency — Cloud Run is a rendezvous *option* with self-hostable equivalents (home
   box Router, LAN-direct, self-hosted Headscale) that Profile A (home hobbyist) uses
   instead. Where used: automatic TLS, proven by the cloud node. Pin
   `min-instances=1 max-instances=1` while the link registry is in-memory (Valkey in
   later v2 lifts this). Cloud Run's 60-min WebSocket cap makes the agent reconnect
   loop load-bearing — test it explicitly.
3. **The Chris demo is untouched.** It stays on the verified Tailscale path. LokNet may
   appear as an *optional* sixth beat only after a boringly-stable dry run.
4. **Transport only.** Identity stays JWT behind the existing `TokenVerifier` seam. No
   PQ / MLS / key-management pull-forward; the trust fabric remains v3.

## Slices
- **Slice 1 (DONE 2026-06-10, v1.1.0)** — ADR-0013 + opt-in outbound WS agent-link: Router
  dispatches `/infer` down the open pipe with frameId correlation + timeout; falls back to
  direct dial. Default off, additive, no new deps. 208 tests/100% cov. Link-first dispatch
  skips the registry lookup (the Cloud-Run fix). Follow-up: bug #54 (sub↔agentId binding).
- **Slice 2 (DONE 2026-06-10, v1.2.0)** — single front door: `register`/`heartbeat`/
  `registered` frames added (additive); the Router relays register/heartbeat to the
  Registry's existing `/register` via the `RegistryClient` seam, bound to the link's
  authenticated `agentId` (frame-supplied id ignored — bug #54 boundary). Agent in
  broker mode registers/heartbeats over the link; HTTP `/register` path suppressed.
  `advertisedAddress` sentinel `broker://<agentId>`; dropped link → stale via normal
  TTL (no 2nd liveness path). Registry needs no public bind in LokNet mode (loopback
  shape documented in ADR-0013 follow-up + README). Direct mode unchanged. 228 tests/
  100% cov, no new deps.
- **Slice 3 (DONE 2026-06-10)** — two parts:
  - **v1.2.1** — `scripts/smoke_broker.py`: real-socket (localhost TLS/WSS, not
    TestClient) mesh-free proof. Private loopback Registry + public-facing Router +
    one broker-mode agent with NO usable direct Registry route (blackhole port);
    asserts register-over-link (`broker://` sentinel in /pool + /schedule) and an echo
    completion dispatched down the link. Wired into CI. No slice-1/2 bug surfaced under
    real sockets — the code worked as designed; closes the "no real sockets" gap.
  - **v1.3.0** — Cloud Run deploy recipe **authored, not executed** (public deploy is
    Eddie's): `router/Containerfile.cloud` (UBI9, non-root, `uvicorn router.main:app` on
    `$PORT`, TLS by Cloud Run), `scripts/deploy_loknet_router.sh` (idempotent,
    parameterized, min/max=1, JWT via `--set-secrets`, `--allow-unauthenticated`,
    `--timeout=3600`; `bash -n` + shellcheck clean), and `docs/demo/LOKNET_CLOUDRUN.md`
    (60-min WS cap covered by the slice-1 reconnect loop, single-instance constraint,
    how to point a remote agent at the public Router). Demo NOT rewired (decision 3).

## Transport: build vs integrate (Eddie 2026-06-10)
LokNet should be a **thin interface + policy layer over a PLUGGABLE transport**, not a
transport we own (coding-rules §2, swappable backend — same pattern as the engine/verifier).
Mature open-source interconnects already do outbound-only, no-inbound, mTLS tunneling:
- **Skupper** (Red Hat L7 service interconnect — skupper.io): same shape as our broker;
  building ON it is on-brand for the Red Hat / Chris Wright pitch. Best fit for **Profile B**.
- **Submariner** (Red Hat/CNCF cross-cluster networking) — k8s-weighted alternative.
- Lighter options for **Profile A** (home, no k8s): the shipped WS broker, WireGuard/Headscale,
  zrok/OpenZiti, sshuttle.
**Decision (feature #64, §13 review + spike):** evaluate Skupper as the Profile-B transport;
keep the lightweight broker for Profile A; pick the tunnel per profile behind the LokNet
interface. The shipped broker (slices 1-3) is the Profile-A option and proved the model — not
wasted, but the enterprise transport likely shouldn't be ours to maintain.

## Non-goals
Mesh client, multi-instance router HA (Valkey, later v2), PQ identity (v3), external
naming (open on #59), demo rewire (decision 3).
