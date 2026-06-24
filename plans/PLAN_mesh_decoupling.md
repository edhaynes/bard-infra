Status: Partial — Remaining: Phases 1–5 (Phase 0 done 2026-06-24)

# PLAN — Decouple from Tailscale; pluggable OSS mesh (Nebula) under INFRA-2

**Author:** Jason-bard
**Date:** 2026-06-24
**Implements:** INFRA-2 (self-hosted fabric DNS / mesh-independent resolver)
**Depends on:** INFRA-1 (frozen `Resolver` seam), INFRA-3 (LokNet, already mesh-free)
**Related research:** Linda OSS-mesh competitive scan, 2026-06-24 (this session)

---

## 1. Why (the finding that shapes this plan)

A code trace of the live transport path establishes that **Tailscale coupling in
bard-infra is shallow and confined to two functions**, not woven through the
product:

| Tailscale job | Where it lives | Coupling depth |
|---|---|---|
| **Name → address** | `SystemResolver.resolve()` → `socket.getaddrinfo()` (`bard_infra/nameres/resolver.py`) | Behind the `Resolver` ABC swap seam (INFRA-1). One class to replace. |
| **L3 reachability** | The `100.x` overlay IPs that `wss://`/`httpx` dial are routable only because hosts share a tailnet | Below Bard. Bard never imports Tailscale; it dials whatever address the resolver returns. |

**Bard's own transport is application-layer:** `wss://` (`agent/broker.py`,
`websockets`) and HTTPS (`agent/engine.py`, `register.py`, `httpx`). It does
**not** speak WireGuard or Noise. Therefore the mesh's on-the-wire protocol is
**irrelevant to Bard** — Nebula's Noise vs. WireGuard is a non-issue. Any mesh
that hands each host a stable overlay IP + transparent L3 encryption is a valid
substrate; Bard rides on top unchanged.

Two independent decoupling vectors exist, and they compose:

- **Vector A — LokNet (INFRA-3), already mesh-free.** Agents hold an *outbound*
  `wss://` to a single public Router front door. No mesh, no inbound ports. On
  this path Tailscale is already absent. Hardening/adopting LokNet as the
  *default* agent transport removes Tailscale from the agent fleet with **no new
  mesh at all**.
- **Vector B — direct fleet path (gx10 ↔ macbook ↔ frogstation).** For
  node-to-node traffic that isn't via the Router, swap the L3 substrate
  Tailscale → **Nebula**, and swap MagicDNS → a **registry-backed resolver**
  (INFRA-2) that returns Nebula overlay IPs. The Registry already holds the
  authoritative node list, so it is the natural name source.

**Chosen mesh: Nebula (slackhq, MIT).** Rationale (Linda's scan): no control
plane to host or trust — just a self-managed CA + dumb "lighthouse" discovery
nodes, which maps onto Bard already owning identity; MIT end-to-end (no AGPL
server carve-out like NetBird, no BSL "no government use" clause like ZeroTier);
native ARM64 for gx10; genuinely air-gappable. Runner-up Headscale was rejected
for the structural risk of perpetually chasing Tailscale's proprietary protocol
— the wrong dependency for a determinism-first, sometimes-air-gapped fabric.

---

## 2. Contract first (freeze before code)

INFRA-1 already froze the `Resolver` ABC. This plan adds **one** new contract
and changes **no** existing one:

- **`MeshResolver` is a `Resolver` subclass**, not a new interface. `resolve(host) -> list[str]`
  is unchanged. Callers (`validate_endpoint`, `common/config.py`) see no diff.
- **New config contract:** a `RESOLVER_BACKEND` selector (`system` | `registry`)
  wired through `common/config.py`, defaulting to `system` (today's behaviour).
  Fail-fast on unknown value (§0.11).
- **Registry name endpoint** (Vector B): the Registry exposes the node list it
  already holds as a name→address lookup the `RegistryResolver` consumes. Freeze
  its response shape as a contract under `contracts/` before implementing the
  resolver against it.

No behaviour changes until a backend is explicitly selected. This keeps the GA
line backwards-compatible (coding-rules §11 post-GA discipline).

---

## 3. Steps (each ≤ a few files, own commit, clear done-signal)

### Phase 0 — Cleanup precondition (mechanical) — DONE 2026-06-24
- **0.1 [done]** Reconcile the two resolver copies. **Finding on inspection:**
  they are *not* drifted duplicates but an intentional split — `bard_infra/nameres/`
  is the framework-agnostic library (exceptions on `RuntimeError`/`ValueError`,
  no `common` dependency, vendorable; where Phase 2's `RegistryResolver` lands),
  while `common/name_resolution.py` is the app-config binding (exceptions on
  `ConfigError` so the config layer fails fast — depended on by `config.py` +
  6 test sites). The real defect was the misleading "vendored — keep in sync"
  header. **Fix (Eddie's call, "fix headers + share pure bits"):** corrected both
  docstrings to document the deliberate split; `common` now imports the genuinely
  identical pure pieces (`Resolver` ABC, `EndpointResolution`) from the library
  so both bindings provably share one contract; the `ConfigError`-raising
  `_parse_port`/empty-check/`SystemResolver` stay in `common` (they can't be
  shared without breaking the `ConfigError` contract). *635 passed, 100% line+
  branch coverage.*

### Phase 1 — Selector seam (no new mesh yet)
- **1.1** Add `RESOLVER_BACKEND` to `common/config.py` (default `system`),
  validated at startup, with a `make_resolver(config) -> Resolver` factory.
  *Done: factory returns `SystemResolver` for default + unit test for the
  unknown-value crash.* One commit.
- **1.2** Route the one current construction site (`common/config.py:356`
  `validate_endpoint(host, SystemResolver())`) through the factory. *Done:
  behaviour identical, factory is the only place `SystemResolver` is named.* One commit.

### Phase 2 — Registry-backed resolver (Vector B name plane = INFRA-2 core)
- **2.1** Freeze the Registry name-lookup response contract under `contracts/`
  (schema + example). *Done: schema file + golden example.* One commit.
- **2.2** Add Registry endpoint serving the node list as name→addresses, against
  the existing authoritative store (`registry/device_store.py` / `fleet.py`).
  *Done: endpoint test asserts a known node resolves.* One commit.
- **2.3** Implement `RegistryResolver(Resolver)` consuming 2.2, registered in the
  1.1 factory under `RESOLVER_BACKEND=registry`. *Done: resolver unit tests + the
  factory returns it; 100% branch cov.* One commit.

### Phase 3 — Nebula substrate (Vector B data plane), config-only
- **3.1** Ansible role to stand up Nebula: self-hosted CA, one lighthouse, per-node
  certs + `config.yml`, overlay subnet chosen to not collide with the tailnet.
  ARM64 binaries pinned (gx10). *Done: `nebula` up on two nodes, ping across
  overlay.* One commit. (Mirror the existing `ansible/` Tailscale-fleet pattern.)
- **3.2** Point `RegistryResolver` node records at Nebula overlay IPs (data, not
  code). Run the existing fabric demo end-to-end over Nebula with
  `RESOLVER_BACKEND=registry`. *Done: `/infer` round-trips gx10↔macbook with
  Tailscale **down**.* One commit. **This is the proof Tailscale is removable.**

### Phase 4 — Make LokNet the default agent transport (Vector A)
- **4.1** Flip agent defaults so `BARDPRO_BROKER_ENABLED=true` is the documented
  norm; agents reach the Router via public TLS front door, no mesh. *Done:
  agent fleet runs with no tailnet membership.* One commit + README regen.

### Phase 5 — Docs / decision record
- **5.1** ADR: "Mesh is a pluggable L3 substrate below Bard's L7 transport;
  Nebula is the default OSS mesh; Tailscale retained only as a dev convenience."
  Update README, ARCHITECTURE.md, INFRA-2 feature entry → reference this plan. One commit.

---

## 4. Acceptance (the done-signal for the whole arc)

1. `RESOLVER_BACKEND=system` (default) behaves exactly as today — no regression.
2. With `RESOLVER_BACKEND=registry` + Nebula up and **Tailscale stopped**, the
   fabric demo (`/infer` gx10↔macbook) succeeds.
3. Agent fleet operates with **no tailnet membership** via LokNet.
4. 100% line+branch coverage maintained; no new AGPL/BSL-restricted dependency
   (Nebula is MIT, ARM64-native — satisfies §13 + §5).
5. Tailscale demoted in docs to a dev-only convenience, never a product dependency.

## 5. Out of scope (tracked, not done here)
- Managed/public DNS (Cloud DNS/Route53) for a public Router FQDN — INFRA-2's
  *other* half; separate plan.
- Nebula HA (multiple lighthouses), cert rotation automation — follow-on.
- Removing Tailscale from developer machines — optional; it stays as convenience.
