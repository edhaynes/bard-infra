Status: In Progress — redefined 2026-06-17 (MVP = private group push-to-talk on the Bard LokNet fabric)
Author: Jason-bard

# Bard MVP — private group push-to-talk

## The MVP (north star — Eddie, 2026-06-17)

A private **group push-to-talk** "box," running **on the Bard LLM / LokNet
fabric**. From an **iPhone**, a user creates a box (a **public LokNet** he owns
and manages), brings in his peeps on a **Mac** and an **Android** phone, they
**join from different networks** ("different parts of town"), and **push-to-talk
works** across all three. MVP onboarding is the **shared invite link**
(SMS/AirDrop/email → redeem); the slicker **select-from-roster** is Sprint 2.

> Supersedes the earlier "basement / 5-platform / talk-to-the-kid-on-the-Windows-
> desktop" framing. The shift: 3 consumer audio devices, peer-shared link, PTT
> across the internet — not one person onboarding their own 5-box fleet.

## LokNet model
- **Private LokNet** = your own devices (a personal fabric).
- **Public LokNet** = a shared group you create and run. **The MVP box is a
  public LokNet, owner-managed** — the iPhone user is the admin and can **add,
  delete, and suspend** members.

## Devices (voice participants)
**iPhone, Mac, Android** — 3 consumer audio endpoints. Linux/Windows clients and
headless boxes (frogstation/gx10) are **not** voice participants; frogstation/gx10
are the **compute/agent fleet**, a separate track.

## Locked decisions
1. **One Flutter client** (`clients/app`) for iPhone / Mac / Android.
2. **Squawk Box wraps LiveKit** (Apache-2.0; official Flutter SDK; ARM64 server).
3. **Onboarding: MVP = shared invite link** (the easier path — invite/redeem +
   web-join already built); **Sprint 2 = select-from-roster** (the nicer UX, needs
   directory/presence/push).
4. The box = a **public LokNet, owner-managed**.

## Already built — do NOT rebuild
- **Invite/redeem** (one-click, no account, single-use); **per-device identity**;
  **channel membership**; **workgroup + plugin enablement** — i.e. the owner-
  management primitives (enroll → approve → revoke, workgroup assign).
- **Web-join slice** (`scripts/join_server.py`) + the control-plane registry
  (`scripts/console_registry.py`).
- **LokNet outbound-broker transport** (#59) + plugin catalog/console.
- Fabric proven **live over Tailscale** (Mac + gx10, by name) — registration + routing.

## The gap (honest)
- **Flutter clients:** onboarding + PTT exist on **zero** of the 3 platforms.
- **LiveKit PTT:** greenfield integration (wrap LiveKit + the plugin-launch hook).
- **Cloud coordinator (public-LokNet front door):** the LokNet Router is **coded,
  not deployed** → the off-network ("different parts of town") case needs it.
- **Owner-management UX** (add/delete/suspend) not surfaced in a client.
- **Bug #63** — invite-onboarded (per-device) token rejected at the Registry
  `/agents` lookup → blocks any device on the data path.

## MVP Sprint — "make a box, share a link, talk"
Goal: from an iPhone, create a public-LokNet box, share an invite link to a Mac +
Android, all join from different networks (via the coordinator), and **PTT works**;
owner can add/delete/suspend.
1. **Deploy the coordinator** — LokNet Router → Cloud Run, stable FQDN (the
   public-LokNet front door / off-network rendezvous). Coded; deploy + point
   clients at it.
2. **Fix bug #63** — Registry accepts per-device tokens (or Router uses a service
   token for internal lookups) so a redeemed device reaches the data path. Small.
3. **Flutter — create + join a box:** create-a-box (mint an invite for the public-
   LokNet channel); OS **share-sheet** the link; on a peer, **deep-link → redeem →
   secure storage** (`deviceSecret`) → per-device token minting.
4. **LiveKit PTT:** self-host a LiveKit server (Cloud Run / ARM); the plugin-launch
   hook so Squawk Box actually starts; map the box's channel → a LiveKit room;
   hold-to-talk (publish mic on key-down/up).
5. **Owner management:** surface **add / delete / suspend** (reuse approve/revoke +
   workgroup) in the owner's app.
- **Demo:** iPhone makes a box → shares the link to Mac + Android → all join from
  different networks → **PTT works**; owner suspends/removes a member.

## Sprint 2 — select-from-roster (validate the other mechanism)
- Peer **directory + presence**; **select** peers (no SMS); **push/accept** to pull
  them into the box; pre-enrollment so peers are selectable.

## Out of scope (this MVP)
- 5-platform breadth (Linux/Windows clients); headless boxes as voice participants;
  the old "talk to the kid on the Windows desktop."
- v2 builds (Quay / Valkey / Ansible); private-LokNet personal-fabric polish.

## Risks
- **LiveKit PTT** half-duplex behavior + per-platform mic / audio-session quirks
  (iOS, Android, macOS) — spike PTT on iPhone + one other target first.
- **Coordinator** single-instance (no HA) — fine for the MVP; Valkey is v2.
- **Off-network reliability** — NAT traversal via the coordinator's outbound broker
  (already proven mesh-free in smoke tests).
