# Product positioning — what we're selling

Status: Current direction, 2026-06-10 (Eddie). Provisional on two items flagged
below (the "LokNet" name and the "VPN" framing). Pairs with ADR-0014 (two profiles,
backend is the product, Maude is the example client) and the claudeTalk MARKET_SCAN.

## Founding principle of Bard Software
**Take computing back to the 80s: you own your stuff.** (Eddie, 2026-06-10 — the
company's north star.)

In the 1980s you owned your computer, your software, your data — no cloud landlord, no
everything-as-a-subscription, no surveillance, no rent on your own files. **Bard Software
exists to return to that: you own your hardware, your software, your data, your AI, your
network.** Everything below is downstream of this principle:
- **Privacy + access** = your stuff, your network — not a vendor's.
- **Free self-host / one-time own-it** = you *own* the software (perpetual), not rent it.
- **Not a profit center** = adoption over extraction; rent-seeking would betray the
  principle. Subscriptions only **cover real cost** (e.g. the weekly UBI rebuilds), never
  extract.
- **Open-weight models first** (Eddie 2026-06-10) = you can only truly *own* (run, keep,
  preserve, fork) a model whose **weights are open**; closed/API models (Claude/ChatGPT,
  #61) are the labeled opt-in exception, never the core. Nuance: *open-weight ≠
  redistributable* — prioritize **permissively-licensed** open weights (Apache/MIT: Qwen,
  Mistral, **Granite**, OLMo, Phi, SmolLM) which we can also **mirror & preserve** (#70);
  restrictively-licensed open-weight models (Llama, Gemma) can run but may not be
  redistributable. So: open-weight-first for the catalog, permissive-first for the archive.
- **Convergence (people + AI + compute), the LokNet Hub, plugins** = the means to put all
  your stuff back under your ownership and control.
- **The honesty lines** (don't overclaim "VPN"; cloud connectors labeled opt-in; E2EE as
  the license to charge) = ownership includes telling you the truth about where your data
  goes.

---

## What sets it apart: **connect your stuff, in your network**

> **Tagline: "Connect your stuff — in your network."**

The differentiator is **convergence**, not any single capability. Sold piece-by-piece,
every part has an incumbent that owns it solo — and we'd be the clone:
- "Secure personal VPN" → **Tailscale** (your devices).
- "E2EE walkie-talkie" → **Signal / Zello** (your people).
- "Private voice AI" → **ChatGPT / Siri** (AI, but theirs, in their cloud).
- "Run your own model" → **Ollama** (your model, but on an island).

**No one connects your *people*, your *AI*, and your *compute* into one private fabric
you own.** That convergence is the product. The transport (**LokNet**) is *plumbing* —
named in the spec, never the headline. We do NOT lead with "VPN" (that's the
Tailscale-clone trap and an overclaim — see flags).

**Proof feature none can copy without rebuilding their model:** *AI as a first-class
member of your group.* Alice, Bob, and a chatbot in the same walkie-talkie; the AI runs
on someone's own hardware and answers the whole group, privately. Signal can't (no AI),
ChatGPT can't (no private group of people), Tailscale can't (no app), Zello can't (no AI).

### The two pillars beneath the tagline: privacy + access
- **Privacy** — data, voice, models, and compute stay on the user's own hardware.
  On-device STT/TTS, local models, the user's own fabric; nothing leaves their network
  unless they explicitly opt in (e.g. the cloud-agent backends, feature #61). ("…*in your
  network*.")
- **Access** — reach your stuff from anywhere with **no third party**; agents dial
  *outbound* only, nothing inbound to open. **LokNet** is the *how* (the plumbing), not
  the *what*. ("*Connect your stuff*…")

Maude is the **example client** (ADR-0014) that demonstrates the convergence — talk to
your people *and* your AI through one app; the backend fabric + LokNet are the product.

## What Maude (the sample app) does
Maude demonstrates the platform's reach: **talk to friends, coworkers, and chatbots** —
i.e. both *people* (peer / walkie-talkie mode) and *AI* (the agent backends) through one
push-to-talk client. Both need a rendezvous in the middle to connect through; see
onboarding.

## Onboarding — "is it sitting in the cloud?" (yes, by default)
A new user must get value with zero setup, while the privacy upgrade stays available.
The ladder:

1. **Install → instant.** Maude ships pointed at a **hosted LokNet rendezvous** + a
   **default chatbot**. The user can talk to a built-in bot immediately and, once they
   invite someone, to friends/coworkers on Maude. No Mac, no fleet, no setup. This is the
   "sitting in the cloud" piece — it makes Maude installable by a normal person.
2. **Privacy holds via E2EE.** The rendezvous is a **thin connection broker, not the
   brain**; person-to-person traffic is **end-to-end encrypted**, so the hosted relay
   transits but can't read it. ⚠️ **E2EE is roadmap** (claudeTalk v1 multi-user plan),
   NOT shipped — it is a **hard dependency for the public hosted launch**, or the
   friends/coworkers path is private in name only.
3. **Real AI privacy = your own backend.** The default hosted chatbot is a convenience
   and sends prompts to the cloud (labeled, opt-in, not "private"). Point Maude at your
   own relay (Mac) / Bard fabric / self-hosted LokNet for private AI — the upgrade
   where "privacy + access" fully lands.
4. **Self-host everything (Profile A / home power user).** Own rendezvous + own fabric,
   nothing hosted. This is ADR-0014's "cloud is never load-bearing": the hosted
   rendezvous is a replaceable default; the self-hosted path always works with no cloud.

**Model:** default-hosted for frictionless onboarding, self-host as the privacy/control
upgrade. Gates to make it real: (a) **ship E2EE before the hosted rendezvous is public**;
(b) decide the **default hosted chatbot** — tiny scale-to-zero model (Cloud Run pattern)
vs. routing to a frontier model (the #61 opt-in).

## How the pieces map
- **LokNet** = the access concept / network (outbound-broker transport, ADR-0013 /
  features #59, shipped v1.1.0–v1.3.0). Plumbing — not the headline.
- **LokNet Hub** = the **rendezvous** your stuff connects through — the central
  connection point. You **self-host a Hub** (free) or **subscribe to a hosted Hub**
  (the upsell). "Hub" reads as benign connective infrastructure (helps the LokNet-name
  concern) and lands the tagline: *connect your stuff → through your Hub → in your network.*
- **The fabric** (Router + Registry + agents) = the private compute/inference the
  network connects (the privacy pillar's substance).
- **Maude / any client** = how you talk to it (the example client, ADR-0014).
- Future: NAS (#60, stranded storage), Ollama bridge (#63), cloud-agent opt-in (#61)
  all extend "connect your stuff, in your network" without changing the prop.

## Platform: the LokNet Hub is pluggable
Decided 2026-06-10 (Eddie): "with plugins for Maude, NAS, Claude, etc — or write your
own." The Hub is an **extensible platform**, not a fixed feature set. "Your stuff" = a
plugin:
- **AI plugins** — Claude, ChatGPT, Ollama, llama.cpp (already the `InferenceEngine`
  seam, #61/#63).
- **Client plugins** — Maude and any app (already the `VoiceBackend` seam; the API is the
  product surface).
- **Storage plugin** — NAS / stranded storage (#60).
- **Write-your-own** — an open plugin SDK + contract so the community extends the Hub.

This is the **Home Assistant model** (hub + integrations, self-hostable, community
ecosystem) — exactly the shape the homelab/power-user beachhead already loves, and the
concrete form of "convergence": the set of things you can connect is open, not ours to
fix. The seams exist today; the **net-new work is a formal plugin SDK + a plugin
runtime/loader in the Hub + a plugin registry** — a v2 platform investment. **Caution:**
don't build the full plugin framework before the core proves out; v1 ships the current
capabilities *as* the first plugins (Maude, Claude/Ollama, self-host), SDK opens in v2.

## Flags — status

1. ~~**The "VPN" framing.**~~ **RESOLVED 2026-06-10:** we do **not** lead with "VPN."
   The identity is *"connect your stuff, in your network"* (the convergence); LokNet is
   plumbing, the **LokNet Hub** is the named connection point. This sidesteps both the
   Tailscale-clone trap and the overclaim (LokNet is app-level access today, not a
   general L3 VPN). If "VPN" appears in copy at all, qualify it.
2. **The "LokNet" name** — partly mitigated by **"LokNet Hub"** ("hub" reads as benign
   connective infrastructure, not mischief). The bare "LokNet" still wants a deliberate
   sign-off before heavy external use; "Hub" carries most user-facing copy.

## Business model — free self-host, paid hosting (the Tailscale/Headscale shape)
Decided 2026-06-10 (Eddie): "users can set up a private LokNet cloud server, or we host
one for a sub" + "free Maude with upsell". **Confirmed model: the Maude app is free; the
upsell is the hosted LokNet Hub subscription (+ optional one-time pro unlock for power
features).** This resolves the Maude launch monetization decision → Sprint 3 unblocked.

**Refined 2026-06-11 (Eddie): "We need free for adoption, and just paid for opex."**
Everything is free for adoption — client, Bard platform, plugins (the 2026-06-11
"charge for plugins" idea was weighed and reduced back to this principle; a plugin is
paid only if it incurs *ongoing cost to us*, per the pricing principle below). The
"optional one-time pro unlock" is dropped; a $0.99 client unlock was weighed and
rejected (funnel tax > revenue; the walkie-talkie has install-side network effects —
invited friends must never hit a paywall). **The only paid product is the subscription
that covers operating expense.** Known opex line items the sub is sized against:
hosted Hub/rendezvous cloud resources, the public broker/router on gcloud (Cloud Run
instances — "there is a bit of opex for pro", Eddie 2026-06-11), the weekly UBI
rebuild/scan/sign pipeline (#69), and the Apple developer subscription. ADR-0015.
**Hub launch price (Eddie 2026-06-11): $19.99/yr** (or $1.99/mo non-renewing); break-even
≈ 25 subscribers against the ~$500 Y1 ledger; $0 ad budget (Plausible-style content
playbook). Y1 price reflects honest amortization of fixed opex over a small base —
revisit downward as the base grows.

- **Self-host LokNet** — free, DIY, full control. Profile-A home power user runs their own
  rendezvous. Satisfies ADR-0014 "cloud never load-bearing": always works, no subscription.
- **Hosted LokNet** — we run the rendezvous; **recurring subscription**. The frictionless
  default ("sitting in the cloud"); the revenue engine.

We monetize **access/convenience (infrastructure), not privacy.** Privacy is free and
inherent (the brand-safe line). The **client app (Maude) is free** — drives adoption, dodges
the "Siri is free" comparison; revenue is the hosted service, not an app purchase. This is
the proven Tailscale (hosted) / Headscale (self-host) freemium split applied to LokNet.

### Pricing principle (Eddie 2026-06-10)
**What costs *us* nothing ongoing is free or one-time (you own the software, perpetual);
what costs us ongoing is a subscription.**
- **Free / one-time, you own it** — runs on the user's own hardware, no cloud cost to us,
  not update-dependent: self-hosted Hub, on-device plugins, the app binary. A one-time
  purchase = a perpetual license to *that version*.
- **Subscription** — (a) anything **we host** (cloud resources = ongoing cost → recurring):
  the hosted LokNet Hub; (b) anything **update-dependent** — ongoing security / model /
  compatibility updates fund the sub. Eddie's honest note: *most* software is
  update-dependent, so most paid tiers lean subscription; the one-time/own-it option stays
  for users who want a version they keep (no guaranteed updates).
This generalizes the per-plugin pricing too: a self-contained plugin can be free/one-time;
a plugin that calls a hosted service or needs continuous updates is a sub.

**Not a profit center (Eddie 2026-06-10): price for adoption, not extraction.** Subs exist
to **cover real ongoing cost + modest sustainability**, never to maximize profit — generous
free tier, deliberately cheap subs, no penny-pinching. The concrete cost that makes
"update-dependent" real: every plugin ships as a **UBI/Podman image needing a weekly
(or more) rebuild** to stay current with RHEL/UBI CVE patches — automated rebuild → Clair
scan → cosign → Quay republish (#53, #69) is continuous compute + work the sub funds. That
security-currency cost is *why* update-dependent = subscription, and it's a cost to cover,
not a margin to grow.

**Two load-bearing requirements for charging:**
1. **Hosted tier must be blind / E2EE** — we route ciphertext, cannot read traffic. The
   M0–M3 E2EE work (multi-user plan) is the *license to charge*: a paid "private" service
   that can read customer traffic is unacceptable.
2. **Multi-tenancy** — one rendezvous for many paying users needs the single-instance →
   Valkey/HA scale-out (v2). Self-host ships on the single-instance broker first; the paid
   hosted tier depends on the scale-out.
