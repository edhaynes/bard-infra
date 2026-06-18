# ADR-0004: ssh-backed CLI tab (key-only sshd in the agent + dartssh2 in the client)

Date: 2026-06-09
Status: Accepted (direction) — scheduled v2 (Walk), Sprint 5; not in MVP
Author: assistant draft; accepted by Eddie (2026-06-09 planning session)
Roadmap tier: v2 — Walk
Relates to: `DESIGN.md §3 / §6 Lane C / Lane F`, features.md #38 #39, `ROADMAP.md`

## Context

The Pro client offers an in-app terminal. The decision (DESIGN) is to back it with **ssh**
rather than a bespoke RPC: the in-app terminal is an ssh client attaching to an `sshd` inside
the UBI agent, and the image also ships `openssh-clients` so a user can ssh **outbound** from
the prompt. This was a candidate MVP feature; per the 2026-06-09 planning session it is
**deferred to v2** to keep the first release lean.

## Decision

- **Transport:** ssh. Agent runs `sshd` configured **key-only (no passwords)**; the app holds
  a key and attaches to it. Image also ships `openssh-clients` for outbound hops.
- **Client dep:** `dartssh2` in the Flutter app. **NEW DEP — license / ARM / maintenance must
  be reviewed and flagged to Eddie before merging** (CLAUDE.md §13).
- **Schedule:** v2, Sprint 5 — after the MVP (Sprints 0–4) ships.
- **PQ note:** when the v3 trust layer lands, the ssh transport uses OpenSSH PQ KEX
  (`mlkem768x25519-sha256`); PQ *identity* is app-level ML-DSA, not `ssh-keygen`
  (`TRUST_MODEL.md §9`).

## Consequences

- Adds `sshd` hardening (key-only, no root login) to the agent image and a new flagged Flutter
  dependency — both kept off the MVP critical path.
- Reuses standard, audited tooling rather than a hand-rolled terminal protocol.

## Alternatives considered

- **Bespoke WebSocket/RPC terminal.** Rejected: re-implements a solved, security-sensitive
  problem; ssh is the known-good template (CLAUDE.md "template-first").
- **Ship in MVP.** Rejected for v1 scope; recorded as v2/Sprint 5.
