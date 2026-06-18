# Bard — Architecture (current)

**This is the single source of truth for Bard's architecture — everything flows
from here.** The API contract, the frontend & backend impl, the tests, system
integration, and deploy all **derive from this doc** (the change-flow pipeline,
§3). ADRs in `docs/adr/` are the decision *records* (the *why* and the moment a
call was made); their accepted decisions are **rolled up into this living doc**.
If this doc and reality diverge, **fix this doc first**, then let the change flow
downstream. No architecture lives in scattered plans/READMEs — they point here.

## 1. What Bard is

A **private group push-to-talk** product on a **private inference fabric**. A user
makes a "box" (a group), brings in peers across different networks, and they
push-to-talk — built on the Bard fabric (identity, membership, transport). See
the MVP definition memory + `plans/PLAN_device_identity_mvp.md`.

## 2. Two repos; one app; capabilities are plugins (ADR-direction)

- **`bard-infra`** — the **platform / fabric** ("infra for everybody"): router,
  registry, agent, `common`, name-resolution (`bard_infra/nameres`), boxes,
  identity, the Flutter client, the console, contracts.
- **`bard-llm`** — the **LLM plugin** (the iOS LlamaServer app). One plugin among many.
- **One Bard app:** the `bard-infra` Flutter client is the shell; **LLM, Chat,
  Terminal, SSH, Squawk Box (PTT)** are **plugins** added to it. The current MVP
  is the **Box only**; legacy Pro-client tabs are out of scope (feature #85).

## 3. The change-flow pipeline (the build discipline)

```
Arch  →  API  →  (frontend & backend & tests, in parallel)  →  system integration test  →  deploy
```

Flow is one-directional and **a change at any stage drags everything downstream
of it.** The API/contract is **frozen first**; impl fans out against it (backend
∥ frontend, each with 100% branch-covered tests); integration must pass before
deploy. (coding-rules §11.) Post-GA, major arch/API changes go on a
**major-revision branch** with backwards-compat attempts; pre-GA they change in place.

## 4. The fabric

| Component | Role |
|---|---|
| **Registry** (`registry/`) | identity store, enrollment, channels/boxes, membership, recovery escrow |
| **Router** (`router/`) | the data path: `POST /v1/message`, and the **broker** WS (`/v1/agent-link`) that pushes to connected devices (box ping fan-out) |
| **Agent** (`agent/`) | the generic node daemon (inference backends ride it); runs read-only + default-deny (#53); bootc image-mode node authored in `deploy/bootc/` |
| **common** (`common/`) | shared auth/config/protocol; `JwtVerifier` (fleet HMAC) + `PerDeviceVerifier`/`FleetOrDeviceVerifier` (EdDSA per-device) |
| **nameres** (`bard_infra/nameres`) | name resolution (INFRA-1 MagicDNS; INFRA-2 self-hosted DNS) |
| **LokNet** | private LokNets (your devices) vs public LokNets (shared boxes); the outbound broker is the off-network rendezvous |

## 5. Identity — user + device (ADR-0017, supersedes ADR-0016 §1)

Two key tiers (pragmatic ADR-0009: software Ed25519; PQ/HW-seal/MLS are v3):

- **User key** — the human's identity, **seed-derived**, **spans all the user's
  devices**, identified by a **username**. Recovered via two-tier escrow
  (password + one-time **OMG code** / a private "do-not-share" QR, #86).
- **Device key** — per-device Ed25519, generated on-device, **enrolled under the
  user**, with a device name. Device tokens are self-signed EdDSA (`sub=deviceId`);
  the backend resolves **device → user**.
- **Membership is USER-level.** Boxes have users; a user participates from any
  enrolled device.

## 6. Frozen API — user + device (the impl codes to THIS)

Identity / onboarding:
- `POST /users` — sign up. `{username, userPublicKey, wraps:{password, omg}}` → `{user}`. 409 if username taken.
- `GET /users/{username}/escrow` — sign in / recover (no auth). → `{userPublicKey, wraps:{password, omg}}` (ciphertext only). 404 unknown.
- `POST /users/{username}/devices` — enroll this device under the user; **user-signed** assertion. `{deviceId, devicePublicKey, deviceName}` → `{device}`. Idempotent for same device+key; 409 on a different key for a claimed deviceId.
- `GET /users/{username}/channels` — the boxes/workgroups the user is in → `{channels:[{channelId, owner, label}]}`.

Device auth: a device self-signs an EdDSA JWT (`sub=deviceId`, `iss=bardllm-pro`, `exp`); `PerDeviceVerifier` verifies against the stored device public key; the backend maps `device.user` for user-level checks.

Boxes (user-level membership; device token on the wire, resolved to the user):
- `POST /channels` — create box → `{channel:{channelId, owner:<username>, label}}`.
- `POST /invites` — owner mints an invite (owner = the caller's user).
- `POST /invites/{token}/redeem` — join: adds the **user** to the channel; idempotent.
- `GET /channels/{id}/members` — `{channelId, members:[{username, label, devices:[…]}]}`.
- `POST /channels/{id}/ping` (router) — member-gated at the **user** level; fan-out `box.ping` to all member users' connected devices.

Recovery: the escrow holds the **user** seed under the username; `wraps.password`
+ `wraps.omg` are opaque ciphertext (zero-knowledge server). Recover = fetch
escrow → decrypt (password or OMG/private-QR) → user key → enroll the new device.

## 7. Transport & deployment

- **Dev:** same-LAN (Mac LAN IP) or Tailscale tailnet (MagicDNS). No Tailscale in the product path.
- **Product / cross-network:** the **cloud coordinator** (LokNet Router → Cloud Run) — devices dial *out* to one public FQDN. Coded; **deploy parked on Eddie's GCP.** This is the gate for a real off-network user (no Tailscale).
- **Nodes:** the agent runs read-only; `deploy/bootc/` makes the node an immutable, small **bootc image-mode** RHEL 10 deployment (agent as a Quadlet), with periodic-rebuild CI. Authored; build/boot in Eddie's subscribed env.

## 8. Status

- **Done (device-only, ADR-0016):** S1–S7 — device identity, boxes, ping, recovery. **Now being reworked to user+device (ADR-0017).**
- **In progress:** the user+device rework (this doc's §5/§6), Box-first trim (#85).
- **Parked:** cross-network coordinator deploy (GCP), bootc build (subscribed env), the real plugins (LLM/Chat/Terminal/SSH/Squawk).
- **Sign-off:** §14 on-device verification (now iOS Simulator on the Mac).
