Status: Implemented, 2026-06-10 — v1 Crawl MVP complete (bardpro-v1.0.0): S1✅ S2-removed(ADR-0011) S3✅ S4✅. `ROADMAP.md` is scope authority; this plan sequences the work and assigns lanes.

# Bard — PROJECT_PLAN (Sprints to v1)

> The artifact requested in `HANDOFF.md §4` ("a detailed dependency-aware PROJECT_PLAN").
> Scope/forks come from `ROADMAP.md` (crawl/walk/run; v1 = Crawl). This doc adds the
> **dependency graph, the critical path, lane assignment, and the per-sprint done-gates.**

## Quality gates — apply to EVERY sprint's done-signal (shared-rules §0.16, §11)
1. **Contract-first:** the frozen `contracts/` define behaviour; code conforms, never edits a frozen contract.
2. **Tests against the contract**, covering success **and every error branch**.
3. **100% line + branch coverage** of new/changed logic (`pytest --cov-branch`); coverage MUST NOT drop.
4. **Green before commit** — full regression passes, or no commit.
5. **Healthy before handover** — for any server/backend step, the service is started and verified **up + healthy + ready** (real request succeeds) before it's called done. No trusting a piped `exit 0`.

## Dependency graph & critical path

```
S0 reconcile ✅ ──> S1 inference ✅verified ──┐
                                              ├─> S3 LAN e2e ──> S4 CI/package/release ──> v1
S2 Flutter client — REMOVED from MVP 2026-06-10 (ADR-0011: Maude is the v1 client; Flutter → v2)
   (coverage-to-100%, CI/Lane E author = parallel, no barrier until they feed S3/S4)
```

- **Critical path (one exclusive owner):** **S1-verify → S3 integration → S4 release.** Sequential, highest risk, the backend/integration spine.
- **Parallel lanes (behind frozen contracts, rejoin at S3/S4):** coverage-to-100% (done), CI/Lane E. (Flutter S2 removed from MVP — ADR-0011; client work continues in the claudeTalk repo.)

## Sprint status & next actions

| Sprint | State | Owner | Done-gate (+ the 5 gates above) |
|---|---|---|---|
| **S0** Reconcile/freeze | ✅ done | — | ADRs 0001–0005; trust demoted to v2/v3; ROADMAP authority |
| **S1** Real inference (llama.cpp) | ✅ **verified 2026-06-09 (v0.1.6)** | critical path | `podman build` ok on arm64; container boots; llama health-gate; `/healthz`=200; `/infer`→real completion ("Paris"). bugs.md #51 fixed |
| **S2** ~~Flutter client → Router~~ | ❌ removed from MVP (2026-06-10, ADR-0011) | — | superseded: Maude (claudeTalk v0.1.0) is the v1 client — BardProClient passes a live Registry+Router integration test; Flutter lane re-scoped to v2 |
| **S3** End-to-end on one LAN | ✅ **remainder verified 2026-06-10 (v0.13.1)** | critical path | real Router↔Registry↔Agent; agent self-registers; real TLS; JWT via verifier seam; power-profile limits; `/version` on router+agent shown in client; `smoke_local.py` brings up the stack; client gets a real answer. Demo fleet (v0.8–0.10) proved LAN e2e; TLS-default remainder closed: `smoke_local.py` passes with **no** `BARDPRO_ALLOW_INSECURE_HTTP` opt-in — 3 HTTPS services, register 200 (lastSeen/status active), echo round-trip 200 |
| **S4** Package/CI/docs/release | 🔄 in progress (CI shipped v0.13.0) | critical path + CI lane | CI lint+secret-scan+tests on macOS+Linux; `podman buildx` multi-arch (amd64+arm64); unique build number; one-command bring-up; README regen; tag+CHANGELOG. Live workflow `.github/workflows/bardpro-ci.yml` (amd64 per-PR; arm64 weekly/dispatch under QEMU — private repo, no native arm runners) |

## Parallel work items (no barrier; tracked)

| Item | Lane | Scope | Notes |
|---|---|---|---|
| **Coverage → 100% branch** | parallel | tests for `router/clients.py` (now 34%); coverage-omit config for `*/main.py` uvicorn entrypoints + `tests/fakes/gen_test_certs.py`; close partials in `registry/app.py`/`router/app.py`/`test_e2e.py` | baseline **82%** measured 2026-06-09; do NOT enable `--cov-fail-under=100` until the gap is closed, else the suite red-fails and blocks commits |
| **CI / Lane E** | parallel | author `ci/ci.yml`: lint + secret scan + tests (macOS+Linux) + `podman buildx` multi-arch + shellcheck (`scripts/*.sh`, `entrypoint.sh`) | `shellcheck`/`pwsh` not installed locally (handoff §2.3) → CI host runs them; feeds S4 |
| **Flutter client (S2)** | removed from MVP | see S2 row | ADR-0011 |

## Open decisions (Eddie — don't guess; HANDOFF §5)
1. **LiteLLM at the Router (§13 dep sign-off)** — kept out of the agent (httpx suffices); its multi-backend routing belongs at the Router. Heavy dep → license/ARM/size sign-off before adding, or stay on direct httpx routing. Gates part of S3.
2. **CI now vs Sprint 4** — the deferred build/lint verifications have a home in `ci/ci.yml`.
3. **PR #4** — keep updated as the branch advances.

## Post-MVP (v2 — Walk; out of this plan)
S5 ssh CLI tab · S6 remote compute lifecycle · then Valkey + control plane, React console, OO domain model w/ software-key trust (ROADMAP v2 tier).
