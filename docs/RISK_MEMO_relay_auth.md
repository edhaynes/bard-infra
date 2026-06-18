# Risk Memo — Bug #56: Client Relay Has No Auth

To: Eddie
From: Jason (Sprint B1, publish hygiene)
Date: 2026-06-12
Decision needed: ship the closed beta with the relay as-is, or block it until
per-device identity (Sprint B4) lands.
References: `docs/SECURITY_AUDIT.md` (finding **C-1**, Critical);
`plans/HANDOFF_bard-arch-completion.md` (B1 done-signal, B4 scope).

---

## What #56 is

The client relay path **Maude → Router → remote agent** has **no
authentication and handles plaintext**. The audit (C-1) found that the relay
endpoint trusts a `?session=` URL parameter as identity and fans every utterance
out to all other sessions on the relay. There is no account binding, no
per-recipient encryption, and the relay itself sees cleartext. In short: the
"private / E2EE" story for the relay is **paper-only today** — the transport
exists, the identity and encryption that would make it private do not.

This is distinct from the core fabric. The Router/Registry/Agent hops are JWT-on-
every-hop, TLS-default, no `verify=False`. #56 is specifically the **client
relay** seam, not the fabric.

## Why it's acceptable for single-user Profile A (the audit's own reasoning)

The audit rates C-1 Critical **as a launch-gate**, not as a live exposure today,
and the reason is containment:

- **Single owner, trusted devices.** Profile A is one person's home fleet. The
  only "sessions" on the relay belong to the owner. "Broadcast to all other
  sessions" is broadcast to yourself.
- **No multi-tenant surface.** There is no second tenant to impersonate, no
  other user's traffic to intercept. The confidentiality break C-1 describes
  requires a second party on the relay to victimize. Profile A has none.
- **Bound to loopback / Tailnet-private today.** The relay binds 127.0.0.1 / a
  Tailscale-private address. There is no public reachability — an attacker would
  already need to be inside the owner's trust boundary to reach it at all.

The audit's headline says the shipped fabric is "structurally sound for Profile
A," and its fix-list places the relay-auth work under *"Before any public Maude
rendezvous / 'private' P2P marketing"* — **not** under "before single-owner use."
The risk is **shipping order**, not deception, **provided** the beta stays
single-user and the relay stays private-bound.

## Why it becomes Critical the moment the deployment is not single-user

Every mitigation above is the single-user assumption. Remove it and C-1 is a
live, exploitable break — with **no code change required to flip it**:

- **A second user / multi-tenant tier.** Now "fans every utterance to all other
  sessions" means user B hears user A. The `?session=` param is forgeable
  identity — any client can claim any session. That is a direct confidentiality
  and integrity break against real third parties.
- **Public / non-loopback deployment.** If the relay ever binds a public
  interface, an unauthenticated outsider can join, eavesdrop, and inject. The
  audit's required guard ("refuse non-loopback bind without auth") does not exist
  yet.
- **Any "private" or "E2EE" marketing.** Branding the relay as private while it
  is unauthenticated plaintext converts an honest roadmap gap into a
  misrepresentation. The audit is explicit: do not ship that branding before
  wss + account-bound auth + real per-recipient E2EE.

The same fleet-wide-shared-secret weakness underneath #56 is why the proper fix
is **per-device identity** (also closes the #54 class), scheduled for B2→B4.

## The two options

**Option 1 — Accept for single-user beta now.**
- Ship the closed beta with the relay as-is, under hard constraints: single user
  only, relay bound loopback / Tailnet-private only, **no** "private/E2EE"
  branding anywhere in the beta.
- Pro: B1 ships now; Profile A is feature-complete and the audit supports this
  posture for a single owner; no engineering work blocks the beta.
- Con: the relay is a latent Critical. Discipline (no second user, no public
  bind, no "private" wording) is the only thing holding it — a process control,
  not a technical one. Easy to violate by accident later.
- Mitigation to attach: add the audit's "refuse non-loopback bind without auth"
  guard as a cheap belt-and-suspenders so an accidental public bind fails fast
  rather than silently exposing the relay.

**Option 2 — Block until per-device identity lands (Sprint B4).**
- Hold the client relay out of the beta entirely until B4 authenticates it on
  the per-device identity from B2/B3. Profile A beta can still ship **without**
  the relay (the fabric works; Maude relay simply stays off).
- Pro: no latent Critical ships; the "private" story becomes true before anyone
  could rely on it; removes the human-discipline dependency.
- Con: delays the relay feature for beta testers by the B2→B4 sequence (identity
  is the foundation, so it can't be short-cut); B4 is sequential after B2/B3.

## Recommendation

**Option 1 — accept for the single-user beta — with the constraints enforced,
not just stated.** The audit's own reasoning supports single-owner use, the
fabric is sound, and the risk is purely the single-user assumption holding. Make
the assumption load-bearing in code, not in a wiki: (a) land the cheap
"refuse non-loopback bind without auth" guard before the beta, (b) keep all beta
material free of "private/E2EE" relay claims, and (c) treat #56 as a hard blocker
for the very next step that adds a second identity, a multi-tenant tier, or any
public reachability — that step does not ship until B4 closes it. This unblocks
B1 now without converting a documented roadmap gap into a real exposure.

---

Eddie's decision: ___________________________________________________

(date / sign-off)
