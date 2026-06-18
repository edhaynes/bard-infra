# ADR-0010: OO domain-model GUIs (React+Vite / Flutter) over a single Valkey source of truth, behind the control plane

Date: 2026-06-09
Status: Proposed — **deferred to v2 (Walk); not MVP** (Valkey/console/OO model = v2; PQ encryption-at-rest = v3). See `ROADMAP.md`
Roadmap tier: v2 — Walk (PQ-at-rest parts: v3 — Run)
Author: Jason-bard (PM / acting architect)
Relates to: ADR-0006 (trust front door), ADR-0007 (console is additive), ADR-0008 (client vs management split), `TRUST_MODEL.md §3`, features.md #45 #46 #48, `docs/MEMORY.md` (UBI runtime)
Conforms to: shared-rules (Eddie 2026-06-09 — "other rules as in shared-rules"); CLAUDE.md §1, §2, §5, §13

## Context

Eddie 2026-06-09 set three architecture directives and answered the follow-up clarifications:

1. **"The GUIs should have an object-oriented structure based on React and Vite."** — Clarified: **the management console** (`clients/console/`) is React+Vite; the **end-user client stays Flutter** (ADR-0005/0007/0008 preserved, the built five-tab app is kept). "OO structure" is satisfied by a real **domain-model layer of classes**, not by class-component React.
2. **"There is one source of truth which is a distributed [Redis] database with appropriate locks."** — Clarified engine: **Valkey** (BSD-3, Linux Foundation, RESP/Redis wire-compatible) over Redis (RSALv2/SSPL) for licensing (§13).
3. **GUIs do not touch the store directly** — they go **through the control-plane API**, Valkey behind it (preserves ADR-0006 zero-trust single front door).

## Decision

### 1. OO domain model, thin rendering layer

The trust graph from `TRUST_MODEL.md §3` (Organization → Workgroup〔visible/hidden〕 → Device〔capability profile: CPU/GPU/mem/net/storage〕 → User / Application) is modeled as an **object-oriented domain layer**:

- **Console:** TypeScript classes generated from / validated against `contracts/control-plane.openapi.yaml` (e.g. `Organization`, `Workgroup`, `Device`, `User`, `Application`, `CapabilityProfile`, `Permission`). React + Vite is the **rendering layer only**; no business rules in components.
- **Client:** a **parallel Dart domain model** generated from the **same contract**, so the two GUIs share semantics without sharing code (the ADR-0007/0008 single-contract anti-drift rule).
- **Permissions are first-class domain objects** and **OO with inheritance and polymorphism** (Eddie 2026-06-09, extends #48): a `Permission` base type specializes into `PortPermission`, `NetworkEgressPermission`, `MountPermission`, `DevicePermission`, `ResourceQuota` (cpu/mem/gpu/storage), `CapabilityPermission`, etc.; grant/deny/evaluation is polymorphic (`evaluate(request) -> Decision`), and grants **inherit** down the hierarchy (org → workgroup → device → application/task). Default-deny still holds (#48); inheritance only ever *narrows or grants* under an explicit (possibly automated) rule.

### 2. Single source of truth = distributed Valkey, behind the control plane

- **One source of truth: a distributed Valkey** cluster. All authoritative state (registry, trust graph, membership, capability profiles, permission policy) lives there.
- **GUIs never connect to Valkey.** They call `control-plane.openapi.yaml`; the control-plane service is the only thing holding Valkey credentials and the only writer. This keeps the §5 deployment model (no DB creds in clients) and ADR-0006 intact.
- **Durability:** because Valkey is the source of truth (not a cache), it runs with **AOF + RDB persistence and replication** — a restart must not lose authoritative state. Configured via the §1 config layer (no hardcoded endpoints).
- **Encrypted at rest:** the Valkey AOF/RDB on disk (and any backups) are **encrypted at rest** — this store is subject to the system-wide "all data encrypted at rest" invariant (Eddie 2026-06-09; `docs/MEMORY.md`). Encryption keys are quantum-resistant per the PQ invariant and never co-located with the ciphertext.
- **Locking:** "appropriate locks" = atomic compare-and-set on the store (`WATCH`/`MULTI` or atomic Lua) for coordination/liveness. ⚠️ A distributed lock (Redlock-style) is **not** treated as a correctness boundary for **security-critical mutations** (group membership, MLS epoch advance, key rotation) — those are guarded by **monotonic epoch / fencing tokens** and ultimately by the **MLS protocol's own epoch ordering**, per Kleppmann's well-known Redlock caveats (GC pause / clock skew can otherwise admit two lock holders).

### 3. Runtime

Everything runs in a **Red Hat UBI container — UBI 10 by default, UBI 9 where needed** (Eddie 2026-06-09). Recorded as a standing decision in `docs/MEMORY.md`; migration of the existing UBI-9 agent image is a tracked follow-up (arm64 rebuild + the RHEL 10 x86-64-v3 baseline caveat).

## Consequences

- **No business logic in React/Flutter widgets** — both render an OO model; logic is testable without a UI.
- **Valkey is operationally critical** — it needs HA (replication/failover), backup of AOF/RDB, and monitoring; a cache-grade deployment is insufficient for a source of truth.
- **The control plane is the sole writer/gatekeeper** — a clean security boundary, but it must not become a bottleneck; read-scaling via Valkey replicas is available behind it.
- **Permission inheritance must be auditable** — an effective-permission resolver has to explain *why* a task got a capability (which ancestor granted it), or default-deny debugging becomes opaque.
- **Two domain models (TS + Dart)** stay in sync only via the contract — contract changes must regenerate both.

## Alternatives considered

- **Class-component React for "OO".** Rejected: modern React is hooks/functional; OO belongs in the domain layer, not the view. The directive is met by the model classes.
- **Redis (not Valkey).** Rejected on §13 licensing (RSALv2/SSPL) for a redistributed enterprise product; Valkey is wire-compatible and BSD-3.
- **A relational DB (Postgres) as source of truth.** Reasonable for a graph + ACID, but Eddie specified Redis/Valkey; revisit only if relational integrity/queries prove painful. Noted, not chosen.
- **GUIs read Valkey directly (CQRS read-side).** Rejected: ships DB creds into clients and breaks the ADR-0006 single front door.
- **Redlock as the correctness primitive for trust mutations.** Rejected per the lock caveat above; fencing tokens + MLS epoch ordering are authoritative.
