# Research Brief — Squawk Box (Construction SMB Owner Persona)

Status: Draft, 2026-06-12
Author: Linda (research manager)
Product: Squawk Box — push-to-talk (walkie-talkie) plugin on the Bard platform
Scope: GTM/UX research for the headline consumer persona. No code touched.

Evidence convention: facts with a `[src]` marker are web-verified (sources listed
at end). Everything labeled **(inference)** is reasoned judgment, not a cited fact.

---

## 1. The persona — "Marco," construction SMB owner

**Profile.** Owner-operator of a small-to-mid construction firm: 5–50 crew,
2–6 active jobsites, runs the business from a truck and a phone. Not technical.
Buys tools that "just work." His workers skew non-technical, often have older or
shared Android phones, frequently wear gloves, and work in noise and dust. Crew
turnover is high (day labor, subs, seasonal), so onboarding happens *constantly*,
not once.

**Why this market is real.** Construction is the single biggest vertical for
Zello, and the heaviest users are dispatch and "work teams" / crews on noisy job
sites. [zello-construction] This is a proven, money-spending persona — not a
hypothesis.

**Pain with current options:**

- **Two-way radios (LMR).** Range dies between jobsite and office; no site-to-office
  link without repeaters/licensing; batteries die mid-shift; one more device to
  buy, charge, lose, and replace. Dead zones in basements/steel structures.
  Construction buyers explicitly evaluate PoC/app alternatives *because* radio
  range and infrastructure don't cover multi-site work. [poclink][weavix]
- **Phones (calls/texts).** Too slow for hands-busy work — dialing, waiting for
  pickup, typing with gloves on. No "all crew at once" broadcast. Breaks the flow
  of physical work. **(inference, but strongly supported by why PTT exists at all)**
- **Existing PTT apps.** They work, but onboarding is heavy (accounts, admin
  consoles, per-seat licensing — see §2) and pricing punishes a fluctuating
  headcount. For a 12-person crew with churn, per-seat admin is friction Marco
  doesn't want to manage.

**What he actually needs (the job to be done):**

1. **Instant channel** — press, talk, whole crew hears it. Zero dial/connect lag.
2. **Dead-simple for non-technical workers** — a worker should be talking in
   seconds with no training and no "create an account" wall.
3. **Works on the phones they already have** — Android-first, cellular + Wi-Fi,
   no special hardware required (rugged/PTT-button devices are a *nice-to-have*,
   not a gate). [zello-construction][teams]
4. **Survives the environment** — loud, gloved, dusty. Big button, loud output,
   noise handling on the mic (see §4).

**Persona-level insight (inference):** the binding constraint for Marco is not
audio quality or features — it's **getting a churning, non-technical crew onto a
channel fast and cheap.** That is the wedge. Whoever makes onboarding trivial and
pricing predictable wins this persona, because the underlying PTT tech is
commoditized.

---

## 2. Competitor scan — the invite/onboarding flow (the key metric)

The metric that matters: **from "owner wants a channel" to "worker is talking,"
how many steps, and what walls (account? app install?) does the worker hit?**

Click/step counts below are best-effort reconstructions from each vendor's own
docs **(inference on exact counts; the account/install gates are verified)**.

### Zello (consumer free app + Zello Work)
- **Owner path (Work):** Zello Work is an admin-console product. Owner adds each
  user via "New User" (username, password, display name) then "Create and Invite
  User," or bulk-imports, then sends SignOn links. [zello-work-add][zello-signon]
- **Worker path:** worker must **install the app** and **sign in** (network name +
  username + password), though SignOn links pre-fill credentials and bundle a
  download link. [zello-signon] Account: **required.** Install: **required.**
- **Consumer free app:** channels can be shared via **link or QR code**; worker
  joins by scanning/searching — but the free app **still requires a Zello
  account.** [zello-share][zello-qr]
- **Steps to talking (Work):** roughly **6–10** (owner: create user → invite;
  worker: receive link → install → sign in → open → select channel → connect).
- **Note:** Zello's "QR Assist" is explicitly marketed as **no app, no account**
  via QR — proof Zello itself sees the account wall as friction worth removing for
  some use cases. [zello-qr]

### Voxer
- **Owner path:** create account (phone number required), then "Invite Friends"
  pulls phone contacts; invite is sent per contact. [voxer-getting-started]
- **Worker path:** **must create an account** (incl. phone number) and **install
  the app**, then accept. Account: **required.** Install: **required.**
- **Steps to talking:** roughly **6–8**. Contact-centric, not channel-link-centric —
  worse for a churning crew because everyone must be a mutual contact.

### Two-way radio (LMR baseline)
- **Owner path:** buy N radios, charge them, possibly license a frequency /
  program channels.
- **Worker path:** hand worker a radio, turn the knob to the channel. **Zero
  software onboarding** — and this is the bar to beat on *worker simplicity.*
- **Steps to talking:** ~**1** for the worker (turn knob), but **high upfront cost,
  per-device logistics, range limits, no site-to-office.** The radio wins on
  worker-side simplicity and loses on everything app-PTT is good at. **(inference)**

### Microsoft Teams Walkie Talkie
- **Owner path:** requires an M365/Teams tenant; admin enables Walkie Talkie via
  an org-wide or frontline app policy in the Teams Admin Center, pins the app,
  and workers must already be **members of the underlying Teams channel.** [teams]
- **Worker path:** worker needs a **Teams account/license**, the **Teams app
  installed**, then opens Walkie Talkie → selects channel → Connect. [teams]
  Account: **required (full M365 identity).** Install: **required.**
- **Steps to talking:** **high** — this is an IT-administered enterprise flow.
  **Disqualifying for Marco**: he has no M365 tenant and no IT department.
  Strong for large orgs already on Teams, irrelevant to the SMB persona.

### Motorola WAVE PTX
- **Owner path:** administered via the WAVE PTX Portal — add users to the fleet
  (manual or CSV import), create a TalkGroup, add users to it. [wave-talkgroup]
- **Worker path:** worker enters an **activation code** (emailed/SMS'd by admin);
  if their number isn't in the system they're prompted to **create a trial
  account**; app install required. [wave-talkgroup] Account: **required.**
  Install: **required.**
- **Steps to talking:** **high** (portal-driven provisioning + activation code).
  Carrier/enterprise-grade; overkill and over-administered for a 12-person crew.

### Scorecard

| Competitor | Account req? | Install req? | Owner flow | Worker steps to talk | Fit for Marco |
|---|---|---|---|---|---|
| Two-way radio | No | No (hardware) | Buy/charge/program | ~1 (turn knob) | Simple but range/cost/no-office |
| Zello (free) | **Yes** | Yes | Share link/QR | ~5–7 | Decent; account wall + per-seat at scale |
| Zello Work | **Yes** | Yes | Admin console | ~6–10 | Heavy onboarding, per-seat |
| Voxer | **Yes** | Yes | Contact invites | ~6–8 | Contact-centric = bad for churn |
| Teams Walkie Talkie | **Yes (M365)** | Yes | IT admin policy | High | Disqualified (no tenant) |
| Motorola WAVE PTX | **Yes** | Yes | Portal + codes | High | Over-administered |

**The pattern:** *every* software competitor requires both an account and an app
install on the worker side. The only zero-account, zero-software worker experience
is the physical radio. **That gap is the opening.** **(inference)**

---

## 3. The minimal-invite benchmark — fewest-possible-clicks for Squawk Box

### Theoretical floor

**Owner:** tap "New Channel" → name it (optional/auto-named) → tap "Share" → pick
SMS/QR. **≈ 2–3 taps**, and the result is a single link + QR.

**Worker:** tap the link → page opens in browser → tap "Talk" → browser prompts
for mic permission → tap "Allow" → **talking.** **≈ 3 taps, no account, no app
install** (if delivered as a PWA / web-PTT that runs in the mobile browser, the
worker never visits an app store).

> **Floor: owner ≈ 3 clicks, worker ≈ 3 clicks (no account, no install).**

This beats every software competitor (which all sit at install + account + 5–10
steps) and matches the radio's worker simplicity while adding site-to-office reach
and no hardware cost.

### The realistic target

Treat **owner ≤ 3, worker ≤ 4 (no account, no app-store visit)** as the number to
beat. Even if a thin "enter your name" step is added for identity (see tradeoffs),
worker stays at ~4 and still has **no password, no store, no admin console** — a
categorical improvement over Zello/Voxer/WAVE.

### Tradeoffs of the no-account model

Going account-less is the differentiator, but it has costs that must be designed
around rather than ignored: **(inference)**

- **Identity.** Without accounts, "who is talking?" is ambiguous. Mitigation: a
  one-field display name on join (no password), stored locally / in the channel
  token. Cheap, keeps worker at ~4 taps.
- **Abuse / channel hijack.** An open link can leak (worker forwards it, it ends up
  on a forum). Mitigations: per-channel rotating join tokens, owner sees a live
  roster and can one-tap kick/ban a device, optional link expiry, optional join
  approval. Default open for speed; let the owner tighten if needed.
- **Billing.** No account = no per-seat to bill. This is a *feature*, not a bug,
  for this persona — it forces the pricing model toward owner-paid flat (see §5).
  The owner is the only entity that needs an account (he pays); workers stay
  anonymous-but-named. This neatly aligns the billing unit (the channel/company)
  with the value unit.
- **Continuity.** Anonymous device loses the channel if it clears browser storage.
  Mitigation: the join link is durable; re-tapping re-joins. Acceptable for a
  churning crew where re-invite is expected anyway.

**Design stance:** owner has a real (billed) account; **workers never do.** That
single asymmetry is the whole product wedge.

---

## 4. Squelch & noisy-environment fit

**Verdict: noise handling is _table stakes_ to be credible, but the *construction-
tuned* execution can be a modest differentiator — not the headline.** **(inference)**

- Construction is *the* noisy-environment use case, and it's already Zello's
  biggest market, so buyers expect PTT to cope with machinery noise out of the
  box. [zello-construction] Failing here disqualifies you; excelling here doesn't
  by itself win the deal.
- Classic radio "squelch" (a threshold gate that mutes below a level) maps in the
  app world to **mic-side noise gating + noise suppression + AGC** so a worker
  standing next to a compressor doesn't broadcast a wall of hiss, and so quiet
  speech still triggers transmission. Vendor docs are thin on the specifics
  (no published squelch specs found for Zello/Voxer), which suggests it's handled
  as generic audio processing rather than marketed as a feature. [search-gap]
- What competitors lean on instead for loud sites: **rugged devices with hardware
  PTT buttons and loud speakers** (Sonim, Kyocera, Zebra integrations) rather than
  software squelch as a selling point. [teams][zello-construction]

**Recommendation for Squawk Box:** ship solid mic-side noise suppression + an
**adjustable sensitivity ("ignore background noise" slider in plain words, not
"squelch")** and a **big, loud, glove-friendly Talk button**. Frame it in Marco's
language ("cut the jobsite noise," "hear it over the saw"), not radio jargon.
Treat it as a quality gate, not the wedge.

---

## 5. Pricing instinct

**Owner-paid flat (per-channel / per-company) — not per-seat.** The incumbents
price per seat (Zello Work ≈ $8/user/mo, $6.80 annual). [zello-pricing] For a
crew with churn and day labor, per-seat is exactly the wrong shape: it taxes
growth, creates admin work every time someone joins/leaves, and tempts account
sharing. [pricing-models] Marco thinks like a contractor buying a *tool*, not a
SaaS buyer counting seats — he wants one predictable line item he can fold into
overhead, the way he'd buy a box of radios once. A **flat per-company (or
per-active-channel) price** maps onto the no-account model perfectly: workers
aren't seats, so there's nothing to meter, and the owner gets unlimited crew on
his channel(s). This also converts better at the point of sale — "$X/month,
your whole crew, no per-head cost" is a one-sentence pitch versus a per-seat
calculator. **(inference, supported by per-seat's known SMB failure modes)**

---

## 6. Recommendation — the single highest-leverage UX decision

**Make the worker side account-less and install-less: the owner shares one
link/QR, the worker taps it, grants mic, and is talking in the browser — no app
store, no password, no admin console.**

This is the one decision that simultaneously (a) beats every software competitor's
onboarding, (b) matches the physical radio's worker-side simplicity while adding
site-to-office reach and zero hardware cost, and (c) forces the pricing into the
owner-paid flat model this persona actually wants. Everything else (squelch,
audio, rugged-device support) is table stakes or polish.

**Click-count target to beat:**

> **Owner ≤ 3 taps to a shareable channel; worker ≤ 4 taps to talking — with
> no account and no app-store install on the worker side.**

If a competitor forces the worker through an account + app install (all of them
currently do), Squawk Box wins this persona on onboarding alone.

---

## Sources

- [zello-construction] Zello — Construction PTT / For Construction Pros:
  https://zello.com/industries/construction-push-to-talk/ ;
  https://www.forconstructionpros.com/equipment/article/21121692/
- [zello-work-add] Adding users to the network — Zello Work:
  https://paidsupport.zello.com/hc/en-us/articles/26981814818061
- [zello-signon] Onboarding Users With SignOn Links — Zello Work:
  https://paidsupport.zello.com/hc/en-us/articles/26982696618765
- [zello-share] Sharing Channels — Zello Support:
  https://support.zello.com/hc/en-us/articles/230746587
- [zello-qr] QR Assist (no app / no account) — Zello:
  https://support.zello.com/zw/qr-assist
- [zello-pricing] Zello pricing: https://zello.com/pricing/
- [voxer-getting-started] Voxer Getting Started / FAQ:
  https://support.voxer.com/hc/en-us/articles/204329943 ; https://www.voxer.com/faq
- [teams] Manage the Walkie Talkie app in Microsoft Teams — Microsoft Learn:
  https://learn.microsoft.com/en-us/microsoftteams/walkie-talkie
- [wave-talkgroup] WAVE PTX — set up a TalkGroup / provisioning — Motorola:
  https://support.motorolasolutions.com/s/article/KB0058016
- [poclink] Construction site comms: Zello vs two-way radios vs LTE PoC — Poclink:
  https://poclink.com/blogs/buying-guides/construction-site-communication-comparing-zello-two-way-radios-and-lte-poc-systems
- [weavix] Alternatives to Two-Way Radios — weavix:
  https://weavix.com/blogs/alternatives-two-way-radios/
- [pricing-models] B2B SaaS pricing: flat vs usage vs per-seat — rethinklab:
  https://rethinklab.co/blog/b2b-saas-pricing-models-flat-fee-vs-usage-vs-per-seat
- [search-gap] No published squelch/noise-spec docs found for Zello or Voxer
  (June 2026 search); inference that noise handling is generic audio processing.
