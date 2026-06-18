Status: Implemented, 2026-06-08 — five-tab shell (Dashboard/Connections/Terminal/Chat/Models) on AppState; analyze clean, 4 widget tests green, macOS build OK. Persistence (shared_preferences) + remote lifecycle remain follow-ups (§5/§6).

# PLAN — Bard client: five-tab restructure (Dashboard / Connections / Terminal / Chat / Models)

Author: Jason-bard (Project Management)
Date: 2026-06-08
Scope: `bardLLMPro/clients/app/` (Flutter/Dart) only. No server-side changes.
Driver: bugs.md #50 — the client has no path to actually run a model. This rework
adds the Chat path and the Connections config that #50 needs.

> Borrowed design language: the `bard-llm` (consumer) Swift app is a
> `TabView` (`LlamaServerApp.swift` → Models / Chat / Terminal / Settings) with the
> selected tab persisted via `@AppStorage("selectedTab")`. We keep that shape —
> a bottom `NavigationBar` with a persisted index — but move to Flutter (decided,
> ADR-0005 / feature #40) to escape the Swift/SwiftUI bug class, and we present an
> enterprise look (no album art / skins, feature #39).

---

## 1. Decisions (locked with Eddie 2026-06-08)

| # | Question | Decision |
|---|----------|----------|
| D1 | Tab set | **Five tabs:** Dashboard · Connections · Terminal · Chat · Models. Models stays its own tab (Pro list, feature #39); Dashboard is health/metrics, not the model list. |
| D2 | Connections | **Backend-endpoint manager + active selection.** Define/edit/select/delete connections (Router + Registry host:port, Agent ssh host:port/user, token, TLS). One is "active"; Dashboard/Chat/Terminal/Models all read the active connection. Replaces the ad-hoc Settings the MVP DESIGN deferred. Remote container lifecycle (#41 start/stop) is **out of scope** this pass — left as a seam. |
| D3 | Terminal | **Auto-connect to the active connection's agent** on tab open (host/port/user from the connection) — lands at the `[bard@ubi9 ~]$` prompt, no manual form. Shows a "no active connection" state when none is selected. |
| D4 | Chat | **Through the Router** — `POST /v1/message` (the Bard JSON envelope already in `api.dart`), targeting the agent chosen from the model list. Not the direct OpenAI endpoint. |

---

## 2. Architecture

```
                 ┌────────────────────────────┐
                 │  AppState (ChangeNotifier)  │  in-memory this pass
                 │  • List<Connection>         │  (persistence = follow-up, §6)
                 │  • activeConnection         │
                 │  • models cache             │
                 └──────────────┬─────────────┘
        ListenableBuilder       │  injected via ctor into each screen
   ┌──────────┬─────────────┬───┴────────┬──────────┬──────────┐
 Dashboard  Connections   Terminal      Chat       Models
 health +   CRUD + active  ssh→agent     Router      Pro list
 metrics    selection      (dartssh2)    /v1/message (Registry)
                 │                            │          │
                 └──────────── BardApi(active connection) ┘
```

- **State**: a single `AppState extends ChangeNotifier`, created in `HomeShell`,
  passed by constructor to each screen. Screens rebuild via `ListenableBuilder`.
  **No new dependency** — `ChangeNotifier`/`ListenableBuilder` are in `flutter`.
- **`BardApi`** is rebuilt from `AppState.activeConnection` (routerBaseUrl,
  registryBaseUrl, token) — replaces today's hardcoded `_api => null` (bug #50).
- **Auth interface seam** (per DESIGN §8h / feature #42): the token lives on the
  `Connection`; a future PQ-identity verifier swaps in behind the same field. Do
  not bake JWT-only assumptions into the screens.

## 3. Files

| File | Status | Responsibility |
|------|--------|----------------|
| `lib/connection.dart` | NEW | `Connection` value type (id, name, routerBaseUrl, registryBaseUrl, agentHost, sshPort, sshUser, sshPassword?, useTls) + `defaultConnections`. |
| `lib/app_state.dart` | NEW | `AppState extends ChangeNotifier` — connections, active selection, models cache, `BardApi? get api`. |
| `lib/dashboard_screen.dart` | NEW | Active-connection summary + live `/healthz` + `/version` probes (Router/Registry/Agent) with graceful offline state. |
| `lib/connections_screen.dart` | NEW | List of connections, add/edit form, set-active, delete, test-connect. |
| `lib/chat_screen.dart` | NEW | Chat UI (bubbles + input) → `BardApi.sendMessage` to the active Router, target = selected model/agent. |
| `lib/health.dart` | NEW | Small `/healthz` + `/version` probe helper (keeps screens thin, ≤500-line rule). |
| `lib/models_screen.dart` | KEEP | Pro model list — unchanged behaviour; now fed by `AppState`. |
| `lib/terminal_screen.dart` | EDIT | Auto-connect from active connection; drop the manual host/port form (keep console + input bar). |
| `lib/api.dart` | KEEP | Already mirrors the contracts; consumed via `AppState`. |
| `lib/model_info.dart` | KEEP | Unchanged. |
| `lib/main.dart` | EDIT | 5-tab `NavigationBar` shell; owns `AppState`; persisted selected index. |
| `test/widget_test.dart` | EDIT | Update to assert the five tabs + Chat input (old test asserted Models/Terminal only). |

Every file targets ≤500 lines / one class (CLAUDE.md §3).

## 4. Done signals

1. `flutter analyze` clean.
2. `flutter test` green (rewritten widget test: five tabs render; Chat tab shows an input; Connections shows the seeded localhost connection).
3. `flutter build macos` succeeds (matches the existing Lane F done-signal).
4. Manual: selecting a connection drives Dashboard health, Terminal target, and Chat routing.

## 5. Out of scope (this pass)

- Remote container start/stop (#41) — Connections leaves the seam, no lifecycle UI.
- Trust/workgroup identity (#42) — token field is the auth seam; no MLS/PQ here.
- Real host CPU/MEM metrics — Dashboard shows agent health/version; live metrics need
  an agent metrics endpoint (follow-up).

## 6. Follow-ups (need Eddie sign-off / later work)

- **Dependency for persistence:** `shared_preferences` (Flutter-team, BSD-3, all five
  targets, native ARM) to persist `connections` + active selection across launches.
  **Not added in this pass** (hard rule #5) — flagged for approval. Until then,
  connections are in-memory and reset on relaunch (seeded with a `localhost` default).
- SSH key-based auth on `Connection` (production path; password is dev-only convenience).
- ADR for the client app-shell + AppState pattern if it proves durable.
