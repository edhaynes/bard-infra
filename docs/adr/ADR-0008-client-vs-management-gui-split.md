# ADR-0008: Client GUI vs Management GUI — division of responsibility

Date: 2026-06-09
Status: Proposed — **deferred to v2 (Walk); not MVP** (see `ROADMAP.md`)
Roadmap tier: v2 — Walk
Author: Jason-bard (PM / acting architect)
Relates to: ADR-0006 (trust front door), ADR-0007 (console is additive to Flutter), `TRUST_MODEL.md §3`, features.md #40 #44 #45 #46 #47 #48
Does NOT supersede: ADR-0007 (which established *that* the console exists; this ADR defines *what goes where*)

## Context

Bard now has two GUI surfaces, both already scaffolded in the tree:

- **Client GUI** — `clients/app/` (Flutter, cross-platform: Windows / Android / macOS / Linux / iOS). The five-tab end-user app (Dashboard / Connections / Terminal / Chat / Models).
- **Management GUI** — `clients/console/` (React + Vite, desktop/web). The admin / topology surface introduced by ADR-0007.

ADR-0007 settled that the console is *additive* and not a replacement, but did not draw the functional line between the two. Without an explicit boundary, capabilities — especially fleet-wide concerns like Ansible-driven key management (#46), Ansible Vault secrets (#47), and the default-deny sandbox policy (#48) — risk landing in the wrong surface or being built twice. Eddie 2026-06-09 asked to record the split.

## Decision

**Guiding principle:** if it is *"do something **with** my device,"* it belongs in the **Client**. If it is *"see and govern **other** devices / users / workgroups,"* it belongs in the **Management** console. First-person/single-device/consent-driven → Client. Third-person/fleet-or-org/policy-driven → Management.

**Hard rule:** anything touching **fleet-wide keys, org/workgroup policy, or Ansible (#46/#47) is Management-only and must never appear in the end-user Client.**

Both surfaces share **one contract** — `contracts/control-plane.openapi.yaml` — so they cannot drift (continues the ADR-0007 single-contract rule).

### Responsibility matrix

| Capability | Client (Flutter) | Management (React) |
|---|---|---|
| Chat / inference UI | ✅ | — |
| Local model download & load (#39) | ✅ | catalog/usage view only |
| Terminal / ssh to *my* agent (#38) | ✅ (my agent) | ✅ (any agent) |
| Device registration / enroll mode (#44/#45) | ✅ register *this* device | ✅ admit/approve, set org membership |
| Create / join workgroup (#44) | ✅ request join | ✅ manager gate, admit, revoke |
| Connections (routers/agents I reach) | ✅ | — |
| Org → workgroup → device → user/app topology (#45) | my-view only | ✅ **primary home** |
| Visibility / hidden-object policy (#45) | — | ✅ |
| Device capability profiles CPU/GPU/mem/net/storage (#45) | reports own | ✅ aggregates fleet |
| Ansible key mgmt / client querying / provisioning (#46) | — | ✅ **console-only** |
| Ansible Vault secrets at rest (#47) | — | ✅ **console-only** |
| Sandbox permission grants + resource quotas (#48) | ✅ consent prompt ("allow :80?") | ✅ author standing policy, push via #46 |
| Remote compute lifecycle (#41) | ✅ drive a remote box | ✅ schedule / observe across fleet |
| Audit log / fleet health | — | ✅ |

### The one shared seam — #48 permission model

The sandbox permission/resource model (#48) is the only capability that legitimately spans both surfaces:

- The **Management** console *authors* standing allow-policy (capabilities + cgroup resource budgets) and distributes it via Ansible (#46).
- The **Client** renders the *consent prompt* when an incoming request is not covered by a standing rule ("grant port 80 to the HTML server?").

Both ends use the **same policy schema** — authored centrally, consented locally. This is a deliberate single seam, not duplication.

## Scale & commercial tiers (Eddie 2026-06-09)

The split is also the **packaging boundary**:

- **Client tier — individuals & small business (< 12 devices/users).** Works with
  **the Flutter client alone**; no management console required. The client therefore
  carries the *light* admin a small workgroup needs — device registration, workgroup
  create/join, member admit/approve, revoke, and basic permission grants — without the
  console's fleet/topology/Ansible machinery. Commercially this tier is **"ridiculously
  cheap"** (Eddie) — broad, low-friction, low-cost.
- **Management console — enterprise/org-scale add-on, paid ("extra $$").** Becomes
  worthwhile past small scale: fleet topology, org-wide policy & visibility, capability
  aggregation, audit, and the **Ansible** fleet ops (#46/#47) — which are inherently
  multi-device/enterprise. It is a **separate paid SKU**, not bundled with the client.

This *refines* the responsibility matrix above: rows marked Management-✅ that a small
workgroup still needs (manager gate, admit, revoke) are **also surfaced in the client at
the small-scale tier**; the console is the *scale-out* surface for the same actions plus
the enterprise-only ones (Ansible, fleet topology, org policy). The hard rule still holds
— **Ansible / fleet keys / org policy never ship in the client**, which is exactly why
they mark the paid console boundary. Exact pricing is tracked in features.md #49.

## Consequences

- Two client codebases, justified by distinct audiences and reinforced by the shared control-plane contract. (Carried over from ADR-0007.)
- A clear test for triage of every new feature: *whose device, and is it policy or action?* → picks the surface.
- Fleet-wide secret/key tooling is structurally confined to the console; the end-user app never holds Ansible, Vault, or org policy. This also keeps the §3 hardware-bound device identity keys out of any fleet tool (see the open #46/#47 tension below).

## Open items (do not block this ADR)

- **#46/#47 vs zero-trust:** Ansible may manage *operational* secrets (CA roots, enrollment tokens, service creds) only — never the §3 device-bound identity private keys, which stay in Secure Enclave/TPM. Likely its own ADR once #45 key-ownership is resolved.
- **#45 key-ownership** (device-bound vs per-user/per-application keys) is unresolved and feeds the topology the console renders; resolve in the trust-decisions ADR (reserved ADR-0009).

## Alternatives considered

- **One unified GUI.** Rejected: mixes end-user and admin concerns, bloats the mobile client with fleet tooling, and weakens topology/graph UX (the ADR-0007 rationale).
- **Put fleet/Ansible features in the Client too "for convenience."** Rejected: violates least-privilege and the zero-trust posture — fleet keys and org policy must not ship in an end-user app.
- **No written boundary, decide per feature.** Rejected: invites duplication and wrong-surface drift; Eddie asked for it recorded.
