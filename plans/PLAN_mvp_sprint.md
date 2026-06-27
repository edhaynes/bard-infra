Status: Backlog — scoped 2026-06-17, awaiting greenlight to execute
Author: Jason-bard

# MVP Sprint — scope: "make a box, share a link, talk"

Detailed breakdown of the MVP Sprint in `PLAN_basement_mvp.md`. Sized per §18.5 —
mechanical, independently-verifiable sub-tasks; files listed where they matter.

## Progress — autonomous run, 2026-06-17 (committed + pushed, `claude/laughing-bell`)
**DONE — all sprint work that needed no external decision:**
- **B — bug #63** (`431d245`): Router mints a fleet **service token** for internal
  registry lookups; redeemed/per-device devices now reach the data path (200, was
  502). 518 backend tests, 100% cov.
- **E1 — member-remove** (`309bc6a`): `POST /channels/{id}/members/{deviceId}/remove`
  + `ChannelStore.remove_member`, audited.
- **C0–C5 — Flutter box onboarding** (`9656c44`): deep-link (`bard://invite`),
  create-a-box + OS share-sheet, redeem + secure-storage of the one-time
  `deviceSecret`, per-device HS256 JWT, Box tab with members.
- **E2 — owner management UI** (`2063898`): per-member Remove, Add-via-share,
  Suspend parked-disabled. Flutter: 142 tests, `analyze` clean.

**REMAINING — needs Eddie:**
- **A** coordinator deploy → a **GCP project** (public deploy is Eddie's).
- **D / S0** — where **LiveKit** self-hosts + a domain → then the voice spike (GO/NO-GO).
- **E1 suspend** semantics — recoverable-disable vs hard-remove.
- **Invite-link base** — `bard://` (opens the app) vs the web-join page vs a
  universal link (product call).
- **§14** — on-device / visual sign-off on all the new Flutter UI.

## Streams (what runs in parallel)
**A Coordinator** (ops) and **B Bug #63** (backend) are independent unblockers —
start both now. **C Flutter client** is the long pole — starts now in parallel.
**D LiveKit voice** needs C. **E Owner management** needs C + a small backend add.

## Recommended sequencing — de-risk VOICE first
The scariest unknown is "does PTT work at all, across networks?" Before the full
onboarding polish, run a **thin vertical spike (S0)**. If it works, the rest is
plumbing; if not, we learn in week 1, not week 4.

---

### S0 — Voice spike (de-risk) · ~3 days · needs A1–A2 + D1
Coordinator up + a LiveKit room + a throwaway Flutter build on **iPhone + Mac**
that joins a *hardcoded* room and does hold-to-talk **over the internet** (two
different networks). **GO/NO-GO gate** for the whole voice path.
- Done-signal: two devices on different networks hear each other on PTT.

### A — Coordinator (public-LokNet front door) · ~1–2 days · needs Eddie's GCP
- **A1** Deploy the LokNet Router → Cloud Run (recipe authored, v1.3.0),
  `min-instances=1`.
- **A2** Pin a stable **public FQDN** (Cloud Run URL or a DNS record) = the
  public-LokNet address.
- **A3** Point clients/agents at it (`BARDPRO_BROKER_URL`, `BARDPRO_BROKER_ENABLED`).
- **A4** Verify: a node on a *different* network connects **outbound** + a request
  routes through, mesh-free.
- ⚠ The public deploy is Eddie's (GCP project).

### B — Bug #63 fix · ~0.5–1 day · backend · START NOW
- **B1** Pick the fix: wrap Registry `/agents/{id}` read in `FleetOrDeviceVerifier`
  **(cleaner)**, or have the Router use a service token for internal lookups.
- **B2** Implement + regression test (per-device token → data path **200**, not
  502); 100% line+branch.
- **B3** Verify live: a redeemed device → `/v1/message` → reaches an agent.

### C — Flutter: create + join a box · LONG POLE · ~2–3 wks · START NOW
- **C0** Baseline: confirm iOS / macOS / Android build; add deps `app_links`,
  `flutter_secure_storage`, `share_plus` (`pubspec.yaml` + per-platform config).
- **C1** Deep-link handler: register the scheme (iOS/macOS `Info.plist`
  `CFBundleURLTypes`; Android intent-filter) + `app_links` receiver in `lib/`.
- **C2** Create-a-box: UI → create channel + mint invite (`POST /invites`) → OS
  **share-sheet** the `inviteUrl` (SMS/AirDrop/email).
- **C3** Redeem: open link → parse token → "Join box?" → `POST
  /invites/{token}/redeem` → store `deviceSecret` in secure storage
  (Keychain / Keystore).
- **C4** Per-device auth: mint a per-device JWT from the secret; attach to fabric
  calls; device shows joined/active.
- **C5** Box + members view: show the channel + its membership.
- Spike **iPhone first**, then Mac + Android. ⚠ per-platform deep-link +
  secure-storage quirks are the real time sink.

### D — LiveKit PTT voice · BIGGEST RISK · needs C · ~1.5–2 wks
- **D1** Self-host a LiveKit server (Cloud Run / ARM, Apache-2.0) + a token-mint
  endpoint. (Stood up early for S0.)
- **D2** Plugin-launch hook: make the Squawk Box manifest `entry` actually start
  (the deferred gap), scoped to client-kind plugins.
- **D3** Flutter: add `livekit_client`; the box's channel → a LiveKit room; join.
- **D4** PTT UX: hold-to-talk (publish mic on key-down, muted otherwise); squelch
  from the manifest `configSchema`.
- **D5** Per-platform audio: iOS audio session, Android mic permission, macOS
  capture.
- Done-signal: two devices in a box hear each other on PTT (validated early by S0).

### E — Owner management (add / delete / suspend) · needs C · ~3–5 days
- **E1** Backend: approve/revoke + workgroup exist, but **"suspend" and
  member-remove do NOT** (ChannelStore has no member-removal — flagged earlier).
  Add a member **suspend/remove** endpoint (small).
- **E2** Flutter owner UI: list box members; **add** (share link), **suspend**
  (disable), **remove**.
- Done-signal: owner adds / suspends / removes a member; reflected in the box.

---

## Critical path to the demo
A + B (unblockers, days) → **S0 voice spike (GO/NO-GO)** → C onboarding (long pole)
→ D full PTT → E management. Rough total: **~3–4 weeks**, with voice **de-risked in
week 1**.

## Start now (no Eddie needed)
- **B** (bug #63) — backend, self-contained.
- **C0–C1** (Flutter baseline + deep-link scaffolding) — client, self-contained.

## Needs Eddie / decisions
- **A1** — GCP project for the coordinator deploy (the public deploy is yours).
- **D1** — where LiveKit self-hosts (Cloud Run vs gx10) + a domain.
- **E1** — "suspend" semantics: revoke-but-recoverable vs hard remove.
