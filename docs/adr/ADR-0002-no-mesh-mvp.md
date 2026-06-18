# ADR-0002: No mesh in the MVP — direct TLS over the LAN

Date: 2026-06-09
Status: Accepted (v1 — Crawl)
Author: assistant draft; accepted by Eddie (2026-06-09 planning session)
Roadmap tier: v1 — Crawl (MVP); mesh returns as an opt-in pluggable transport in v2
Relates to: `DESIGN.md §2`, `TRUST_MODEL.md §10.1`, `BARD_LLM_PRO_ARCHITECTURE.md` (superseded mesh-as-core claim)

## Context

The first-draft architecture treated a Tailscale mesh as core infrastructure. That couples
the MVP to a vendor (or to standing up Headscale), adds NAT-traversal and control-plane
surface, and blocks a single-LAN demo on networking work that teaches us nothing about the
actual product (routing a real prompt to a real model).

## Decision

The MVP uses **direct TLS** between client, Router, Registry, and Agent on a single LAN
(using a Tailscale-assigned IP if one happens to be present, but **not depending on it**).
No mesh, no NAT traversal, no coordination server.

The mesh returns post-MVP as a **pluggable transport** (v2): Tailscale (vendor-supported,
recommended for enterprise) or self-hosted Headscale, selected by a configurable control URL
(CLAUDE.md §1). The MLS/identity security layer (v3) rides on top and does **not** depend on
the mesh for its guarantees.

## Consequences

- Single-LAN end-to-end is reachable in Sprint 3 without networking yak-shaving.
- Cross-NAT / remote-host reachability is explicitly a v2 concern (paired with remote spawn,
  Sprint 6).
- The transport must stay behind an interface so the mesh adapter slots in without touching
  router/agent logic.

## Alternatives considered

- **Tailscale from day one.** Rejected for MVP: vendor coupling + setup cost for zero MVP
  learning. Reintroduced as one transport option in v2.
- **mTLS-only, no mesh ever.** Too limiting for the multi-host Pro story; mesh is deferred,
  not abandoned.
