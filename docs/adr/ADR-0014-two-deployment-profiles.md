# ADR-0014: Two deployment profiles — Ad-hoc (home) and Managed (enterprise)

Date: 2026-06-10
Status: Accepted (organizing principle). **First product MVP = Profile A (home
hobbyist).** Eddie 2026-06-10.
Author: Jason draft; accepted by Eddie in the same session.
Roadmap tier: Profile A is the next/near-term product MVP; Profile B is the enterprise
expansion (v2+). (The shipped `bardpro-v1.0.0` backend milestone is the engine beneath
Profile A, not the product MVP itself.)
Relates to: ADR-0008 (client vs management GUI split), ADR-0011 (Maude client),
ADR-0013 (broker transport), TRUST_MODEL.md, PLAN_loknet.md, claudeTalk MARKET_SCAN.md.

## Context
**The product is the backend** — the fabric (Router + Registry + agents) and its
frozen API/contracts. Clients are pluggable consumers of that API; **Maude
(claudeTalk) is the worked *example* client**, not the product's sole client (refines
ADR-0011: Maude demonstrates integration — JWT + `/v1/message` — it is not "the
client"). The same backend serves two very different buyers who want opposite things
from it. Conflating them produces something too heavy for one and too loose for the
other. Eddie named the two paths (2026-06-10).

## Decision
Treat the product as **one codebase, two deployment profiles** — selected by config,
which frontend is present, and which trust tier is enabled. Never fork the core.

### Profile A — Ad-hoc (home hobbyist) — **the first product MVP**
- **No management console.** A client app integrated to the backend API — **Maude is
  the example client**; the product surface is the API/contracts, not one app.
- **An ad-hoc network of the user's own stuff** — they own every device; trust is
  implicit. No strict onboarding, no central authority, no approval gate.
- **Zero mandatory cloud.** `gcloud`/Cloud Run and any hosted dependency are
  **strictly optional and redundant** — the whole thing must run fully on a home LAN /
  self-hosted box with no account anywhere. (Hard constraint, Eddie 2026-06-10.)
- Rendezvous = LAN-direct or self-hosted; the LokNet broker is optional and, when
  used, points at a self-hosted Router — never a required cloud endpoint.
- Registry = the existing JSON-file store. Minimal/default JWT auth.

### Profile B — Managed (enterprise / IT manager)
- **Management console present** (the management frontend; ADR-0008 split — this is
  what consumes it). End-user clients integrate via the backend API (Maude is the
  reference example); the console is the *operator's* tool, not an end-user app.
- **Strict device onboarding** — only valid/approved devices join (allowlist +
  approval gate; the TRUST_MODEL two-gate device approval).
- **Strict security** — mTLS, zero-trust identity (TRUST_MODEL v2 software identity →
  v3 hybrid-PQ + MLS).
- **MITM authorization** — an inline authorizing mediator on every hop. The LokNet
  **Router is the policy-enforcement point**: every agent dials in and every client
  request passes through it, so it already sits in the man-in-the-middle position to
  authenticate, authorize, and (optionally) inspect each connection. Profile B turns
  that mediation into enforced policy rather than pass-through.

### Shared core (both profiles)
Same Router/Registry/agent, same contracts, same broker transport. A profile is
**config + frontend presence + trust tier**, not a code fork.

## Consequences
- **Cloud is never load-bearing.** This is now a standing constraint on LokNet and
  everything after: Cloud Run is *one* rendezvous option; a self-hostable equivalent
  (home box running the public Router, LAN-direct, or self-hosted Headscale) must
  always exist. Slice 3's Cloud Run recipe is an *option*, not the path.
- **Resolves the console question (prev turn):** the management console belongs to
  **Profile B only**. The hobbyist never sees it. So we do not rush a console for the
  near-term market; we mature `demo-console` into the Profile-B management frontend on
  the enterprise track, and retire the redundant `console/` stub + the v2-deferred
  Flutter `clients/app/`.
- **Aligns with the market read** (claudeTalk `MARKET_SCAN.md`): Profile A == the
  homelab/self-host **beachhead** (lowest CAC, ships first, client-only); Profile B ==
  the enterprise expansion and the Red Hat / Chris Wright story (console + trust
  fabric). The roadmap should sequence A before B.
- The trust fabric (TRUST_MODEL v2/v3) is now explicitly **Profile-B scope** — it does
  not gate Profile A shipping.

## Open decisions (Clarify — flagged, not blocking)
1. **Profile A discovery mechanism** (no cloud): mDNS/Bonjour LAN auto-discovery vs
   manual pairing vs self-hosted Headscale? (Recommend: LAN auto-discovery first.)
2. **MITM authorization shape (Profile B):** confirm the Router is the single policy
   enforcement point (recommended — it already mediates every hop) vs a separate
   inline gateway.
3. ~~Sequence~~ **RESOLVED (Eddie 2026-06-10): Profile A is the first product MVP**;
   Profile B follows. Open sub-question: re-tier crawl/walk/run around profiles, or tag
   each existing roadmap item with its profile? (Recommend: tag items with profile.)

## Alternatives considered
- **One product for both** — too heavy for the hobbyist, too loose for IT; rejected.
- **Two codebases** — divergence and double maintenance; rejected. Config-selected
  profiles over one core.
