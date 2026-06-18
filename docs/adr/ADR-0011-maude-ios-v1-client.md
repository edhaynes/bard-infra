# ADR-0011: Maude (claudeTalk iOS) is the v1 client; Flutter deferred to v2

Date: 2026-06-10
Status: Accepted (v1 — Crawl). Supersedes ADR-0005 for MVP scope.
Author: Jason draft; accepted by Eddie (2026-06-10, "yes drop flutter for maude")
Roadmap tier: v1 — Crawl (MVP)
Relates to: ADR-0005 (superseded for v1; its rationale stands for v2), ROADMAP.md §1,
PROJECT_PLAN.md Sprint 2, github.com/edhaynes/claudeTalk `plans/PLAN_appstore_mvp.md`,
root features.md #58

## Context

ADR-0005 accepted a Flutter cross-platform client as the MVP client, partly to escape
the Swift/SwiftUI Release-build bug class (#88173) and to get Windows/Linux/Android
from one codebase. Sprint 2 (wire the Flutter skeleton to the Router) sat blocked on a
go/no-go while the demo track consumed v0.3.0–v0.10.0.

Meanwhile the Maude app (claudeTalk repo) shipped a working, tested Bard client on
2026-06-10 (claudeTalk v0.1.0): `VoiceBackend` protocol, `BardProClient` speaking
HTTPS + JWT `POST /v1/message` validated against the real Router contract (an
integration test passes against a live composed Registry+Router), Keychain-held JWT,
push-to-talk voice UX with on-device STT/TTS, and an App Store plan (Sprints 1–4 in
claudeTalk `plans/PLAN_appstore_mvp.md`). Building a second client in Flutter for the
MVP would duplicate a client that already exists, works, and has a store path.

## Decision

- **Maude is the v1 (MVP) client** for Bard. The MVP client deliverable is
  satisfied by claudeTalk v0.1.0+; client-side work continues in that repo under its
  own plan.
- **PROJECT_PLAN Sprint 2 (Flutter wiring) is removed from the MVP critical path.**
  The v1 path is now S1 ✅ → S3 (remainder: TLS-default fleet verification) → S4
  (CI, packaging, README, release).
- **Flutter moves to v2 — Walk**, alongside the console: it remains the chosen answer
  for Windows/Linux/Android/desktop breadth (ADR-0005's rationale is unchanged — it is
  re-scoped, not rejected). The `clients/app/` skeleton stays in-tree, marked v2.

## Consequences

- One client codebase to harden for the MVP and the Chris demo; voice PTT becomes a
  demo-able differentiator ("talk to your fleet").
- iOS/macOS-only client coverage in v1; Windows/Linux users wait for v2 Flutter (or
  use the demo console / curl against the documented API).
- The Swift-bug-class risk ADR-0005 fled returns in scope for the client — accepted:
  Maude is a small app, already builds green, and pins none of the known-bad patterns
  (its views are small; no `-Onone` workaround has been needed).
- Bard's protocol/contracts remain client-agnostic; nothing in this decision
  changes the wire contract.

## Alternatives considered

- **Proceed with Flutter Sprint 2 anyway** — two clients before one MVP ships;
  rejected for scope.
- **Port Maude to Flutter now** — discards working Swift voice UX (SFSpeech/AVSpeech
  are platform-native strengths); rejected for v1, revisit for v2 breadth.
