# ADR-0005: Flutter cross-platform client (off Swift/SwiftUI), macOS/iOS-first

Date: 2026-06-09
Status: Superseded by ADR-0011 for v1/MVP scope (2026-06-10) — rationale re-scoped to v2 (Windows/Linux/Android breadth); skeleton stays in `clients/app/`
Author: assistant draft; accepted by Eddie (2026-06-09 planning session)
Roadmap tier: v1 — Crawl (MVP)
Relates to: `DESIGN.md §6 Lane F / §8g`, features.md #39 #40, `project_swift_inliner_bug` memory, `ROADMAP.md`

## Context

The client must be one codebase across desktop and mobile with a simple, professional
enterprise look — and must escape the recurring Swift/SwiftUI bug class that plagued the
consumer app (e.g. the `-Onone` SIL-inliner workaround, Swift #88173). It must avoid
hand-rolled novel UI.

## Decision

- **Framework:** **Flutter / Dart** — one codebase → macOS, iOS, Windows, Linux, Android.
  Official `flutter create` template + Material 3 professional widgets; no Swift-toolchain
  coupling; **start from the stock template, do not hand-roll novel UI.**
- **Platform priority (Eddie, 2026-06-09):** **initially focus on macOS + iOS clients**, but
  **design so it works unchanged on Windows and Linux.** Cross-platform is preserved by
  construction (single Flutter codebase, no platform-specific UI forks beyond what the
  template provides, config via the layer in `common/` rather than platform `#ifdef`s);
  Windows/Linux are validated/polished after mac/iOS but are never designed *out*.
- **OO domain model:** a Dart domain model generated from the same contracts as the console
  (ADR-0010), business logic out of widgets.
- **No decorative art / skins** — clean enterprise list + terminal (features.md #39).

## Consequences

- MVP done-signal targets **macOS + iOS first**; Windows/Linux/Android are kept building (CI
  on macOS + Linux minimum, CLAUDE.md §9) but are not the initial polish focus.
- Avoid any mac/iOS-only API, layout, or plugin without a documented Windows/Linux fallback —
  otherwise the "works on Windows/Linux" guarantee silently erodes.
- The ssh CLI tab dep (`dartssh2`, ADR-0004) and any platform plugins must be checked for
  Windows/Linux + ARM support before adoption (CLAUDE.md §13).

## Alternatives considered (rejected for MVP)

- **Tauri 2** — mobile support younger. **Compose Multiplatform** — iOS leg newest.
  **.NET MAUI** — no first-class Linux. **Stay on SwiftUI** — the exact bug class we're
  leaving. Flutter is the mature single-language toolkit that covers all five targets.
