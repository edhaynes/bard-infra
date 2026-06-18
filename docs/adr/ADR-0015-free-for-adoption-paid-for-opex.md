# ADR-0015: Monetization — free for adoption, paid only for opex

Date: 2026-06-11
Status: Accepted
Author: Jason draft; decided by Eddie (2026-06-11, "We need free for adoption, and
just paid for opex")
Relates to: POSITIONING.md business model (refines the 2026-06-10 resolution),
root features.md #76 (the weighed alternatives), #69 (UBI rebuild opex),
#59 (LokNet broker on Cloud Run), ADR-0014 (two profiles)

## Context

The 2026-06-10 resolution was "free Maude + hosted Hub subscription (+ optional
one-time pro unlock)". On 2026-06-11, during the distribution review, two
alternatives were weighed:

1. **Charge for plugins** (free platform + client, plugin catalog as the profit
   lever) — open-core shape, HA/Nabu Casa precedent. Edges identified: trust
   split (security-critical plugins can't be closed/paid for the self-host
   audience), Apple IAP rail vs web rail, and one-time purchases not covering
   recurring costs.
2. **Paid client** ($0.99 one-time after a 2-week window) vs **free client** —
   the paid client caps adoption exactly where the product has install-side
   network effects (invited walkie-talkie members), competes against free
   incumbents (Happy, official Anthropic/OpenAI mobile control), forecloses
   open-sourcing the client, and nets beer money (~120 sales/yr just to cover
   the Apple developer subscription). Mechanically, "paid after trial" on the
   App Store requires free-app + non-consumable IAP anyway.

The live market review (2026-06-11) showed every credible competitor in the
niche is free and/or open source, and the beachhead (r/selfhosted,
r/LocalLLaMA) treats price and closed source as trust signals against.

## Decision

**Everything is free for adoption; the only paid product is a subscription
sized to cover operating expense.**

- Client app: free. No $0.99 unlock, no pro unlock, no trial gate.
- Bard platform and plugins: free. A plugin is paid only if it incurs
  ongoing cost to us (per the POSITIONING pricing principle: hosted service or
  update-dependence), and then it is subscription-at-cost, not margin.
- The subscription covers known opex: hosted Hub/rendezvous cloud resources,
  the public broker/router gcloud instances (Cloud Run), the weekly UBI
  rebuild → Clair → cosign → Quay pipeline (#69), and the Apple developer
  subscription.
- "Not a profit center" stands: price for adoption + sustainability, never
  extraction.

## Consequences

- Revenue is structurally modest by design; the project's success metric is
  adoption and ecosystem, not margin.
- Removes the last pricing objection for the beachhead audience and keeps the
  open-source-client option (PLAN_beachhead_gaps C0) unencumbered.
- The opex ledger becomes load-bearing: subscription pricing must trace to
  actual cost line items (gcloud, rebuild compute, dev sub), so those need
  tracking from day one.
- The two load-bearing requirements for charging (POSITIONING) are unchanged:
  the hosted tier must be blind/E2EE, and multi-tenancy needs the Valkey
  scale-out before the paid tier scales.

## Alternatives considered

- **Plugins as profit lever** — rejected as a profit center (betrays the
  founding principle); survives only as at-cost subs for plugins with real
  ongoing cost.
- **$0.99 client unlock after 14-day window** — rejected: funnel tax exceeds
  revenue; breaks invite flows; dev-sub cost moves to the opex ledger instead.
- **Paid client / free infra** — rejected: caps adoption, competes with free
  incumbents, low ceiling, blocks open-sourcing the client.
