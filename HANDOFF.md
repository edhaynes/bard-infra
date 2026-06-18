# Bard — Handoff to local Claude

Status: Active handoff — written 2026-06-09 after Sprint 0 + Sprint 1 (cloud session).
Read this first, then `ROADMAP.md`.

> **Why this doc exists.** The work below was done in the **Claude Code cloud (web)**
> sandbox, which repeatedly **reset its working tree between turns** (losing local,
> uncommitted state — and once even reverting committed-but-unpushed work). Everything
> that matters was pushed, so **the remote branch is the single source of truth.** You
> (local Claude on Eddie's machine) won't have the reset problem, but treat the remote as
> canonical and pull before working.

---

## 0. Get the code

```sh
git fetch origin
git checkout claude/laughing-bell-57o15u
git pull origin claude/laughing-bell-57o15u
```

- **Branch:** `claude/laughing-bell-57o15u`  •  **PR:** #4 (draft) →
  https://github.com/edhaynes/bard-llm/pull/4
- **Project lives in:** `bardLLMPro/` (incubating inside the `bard-llm` repo;
  splits into its own GitHub repo later).
- **Current version:** `bardLLMPro/VERSION` = `0.1.4`.
- **HEAD should be:** `6443102` (+ this handoff commit on top).

---

## 1. What's done

### Sprint 0 — scope reconcile & decision freeze (docs only) — `a2a5726`
- **`ROADMAP.md`** is the **scope authority** (above `DESIGN.md`): crawl/walk/run tiers +
  Sprints 0–4 to MVP, the locked MVP forks, ADR→tier map, TPM-optional tiering.
- Wrote **ADR-0001…0005** (MVP): JSON wire protocol · no-mesh MVP · UBI+Podman+llama.cpp
  agent · ssh CLI tab (scheduled v2) · Flutter client (off Swift/SwiftUI, macOS/iOS-first).
- Demoted the trust layer (**ADR-0006…0010 + `TRUST_MODEL.md`**) to *Proposed — deferred
  to v2/v3, direction only, not MVP*.
- **TPM is optional** → two-tier device assurance (hardware = high, software keystore =
  standard) in `TRUST_MODEL.md §3/§7/§9` + ADR-0009.
- Fixed the stale source docs (`BARD_LLM_PRO_ARCHITECTURE.md`, `_MVP_SPEC.md`): struck
  iSH-runs-a-container, de-duped the high-water-mark paragraph, "LiteLLM-is-the-router".

### Versioning infra — `b34ec65`, `cfd8b2e`
- **`bardLLMPro/VERSION` is the single source of truth.** `pyproject.toml` reads it
  dynamically (hatchling `[tool.hatch.version] path="VERSION"`); `common/version.py`
  prefers the `VERSION` file, falls back to package metadata. Separate
  `bardLLMPro/CHANGELOG.md` (Keep a Changelog).

### Sprint 1 — real inference (llama.cpp) — `cfd8b2e`, `023fb33`, `2d3527d`, `6443102`
- **1a (`cfd8b2e`):** `LlamaCppEngine` (in `agent/engine.py`) forwards a text request to a
  llama.cpp **OpenAI-compatible** server (`/v1/chat/completions`) over **httpx** (injectable
  client for tests). `make_engine(config)` selects `echo | llamacpp`. `agent/app.py` maps
  `InferenceError` → retryable `502 inference_failed`. New config fields
  (`inference_backend`, `llama_base_url`, `llama_model`, `llama_api_key`,
  `inference_max_tokens`, `inference_temperature`).
- **1b (`023fb33`):** multi-stage `agent/Containerfile` — builder compiles llama.cpp's
  `llama-server` (pinned `ARG LLAMACPP_REF=b4585`, portable CPU build `-DGGML_NATIVE=OFF`,
  `-DLLAMA_CURL=ON`) for the native buildx arch; runtime copies the binary + shared libs to
  `/usr/local/{bin,lib}`.
- **1c (`023fb33`):** `scripts/fetch_model.{sh,ps1}` (config-driven GGUF download, default
  **Qwen2.5-0.5B-Instruct Q4_K_M, Apache-2.0, ~350 MB**, idempotent, atomic, optional
  SHA-256); `agent/entrypoint.sh` launches `llama-server` on `127.0.0.1:8080` and waits for
  `/health` when `BARDPRO_INFERENCE_BACKEND=llamacpp` (echo path unchanged).
- **Integration (`2d3527d`):** e2e `/infer`→engine→model test; `scripts/smoke_local.py` is
  backend-aware (`make_engine`). README updated to reality (`6443102`).

**Frozen interface contract (don't break it):** `llama-server` binary at
`/usr/local/bin/llama-server`, listens on `127.0.0.1:8080`, model at
`${BARDPRO_MODEL_DIR}/model.gguf` — matches the engine's `BARDPRO_LLAMA_BASE_URL` default
`http://127.0.0.1:8080/v1`.

---

## 2. Current quality bar (verified in the cloud sandbox)

- **36 tests pass**, **ruff clean**, **`sh -n` clean** on the shell scripts, **echo smoke
  PASS** over real localhost TLS.
- **NOT verified anywhere yet** (no podman / no llama.cpp binary in the sandbox — *this is
  the highest-value thing for you to do on a real machine*):
  1. `podman buildx` **multi-arch** build of the agent image (amd64 + arm64).
  2. Running the container with `BARDPRO_INFERENCE_BACKEND=llamacpp` and a **live model
     completion** through `/infer`.
  3. **shellcheck** / **pwsh** lint of `scripts/fetch_model.{sh,ps1}` + `entrypoint.sh`.
  4. Confirm the pinned `LLAMACPP_REF=b4585` tag and the Qwen GGUF URL actually resolve
     (both were chosen without network access — adjust if they 404).

---

## 3. How to run & test

```sh
cd bardLLMPro
uv venv && uv pip install -e ".[dev]"

uv run pytest -q            # 36 tests
uv run ruff check .         # lint
uv run python scripts/smoke_local.py   # echo path over real TLS → SMOKE: PASS

# Real model end-to-end (needs a llama.cpp server, e.g. `brew install llama.cpp`):
uv run scripts/fetch_model.sh          # downloads ./models/model.gguf
llama-server --model ./models/model.gguf --port 8080 &   # OpenAI-compatible on :8080
BARDPRO_INFERENCE_BACKEND=llamacpp uv run python scripts/smoke_local.py

# Build the agent container (real podman; CI-deferred in the cloud):
podman build -t bardllm-pro-agent -f agent/Containerfile .
```

---

## 4. What's next (in ROADMAP order)

- **Sprint 2 — Flutter client → Router (NEEDS EDDIE'S GO).** Wire `clients/app/` to the
  live Router: Settings (router URL + token via config), model list from `GET /agents`,
  compose → `POST /v1/message` → render, error-envelope handling, Dart domain model from
  the contracts. **Priority targets: macOS + iOS first** (ADR-0005), keep Windows/Linux/
  Android building. Done-signal: client on macOS+iOS sends a prompt to a live Router and
  shows a real llama.cpp answer; `flutter analyze` clean, widget tests green.
- **Sprint 3** — end-to-end on one LAN (real Router↔Registry↔Agent, certs, agent
  self-register, `/version`).
- **Sprint 4** — CI multi-arch build + shellcheck + live smoke + README regen + tag.
- **Sprint 5 (v2)** — ssh CLI tab (sshd in agent + `dartssh2`; **§13 dep review first**).
- **Sprint 6 (v2)** — remote agent spawn/lifecycle (Podman remote API).
- **Requested but NOT delivered:** a detailed dependency-aware **`PROJECT_PLAN.md`** for
  Sprints 1–6 — a cloud sub-agent was launched for it but never produced output. Eddie
  asked for it; worth writing.

---

## 5. Open decisions for Eddie (don't guess these)

1. **Sprint 2 go/no-go** (Flutter is a big, different-domain commitment).
2. **LiteLLM-for-router (§13 dep sign-off).** LiteLLM was deliberately **kept out of the
   agent** (httpx suffices). Its multi-backend routing belongs at the **Router (Lane A)**
   and is a heavy new dependency — get license/ARM/size sign-off before adding, or stay on
   direct httpx routing.
3. **CI now or Sprint 4?** The CI-deferred verifications (§2) have a home in `ci/ci.yml`.
4. **Watch PR #4** for CI/review activity?

---

## 6. Conventions & rules (from `CLAUDE.md` — non-negotiable)

- **`ROADMAP.md` is scope authority.** If a task conflicts with it, stop and flag it.
- **Edit only your lane's files**; contracts in `contracts/` are frozen — never patch a
  contract inside a lane, flag it instead.
- **Bump `bardLLMPro/VERSION` every commit** (fix/chore/docs → patch, feat → minor) and add
  a `CHANGELOG.md` entry in the same commit.
- **Secret-scan before every commit/push** (gitleaks if present; else the pattern grep used
  in this branch's history). Show the diff summary.
- **Commit style:** Conventional Commits (`feat(bard-pro):`, `docs(bard-pro):`, …). Push to
  `claude/laughing-bell-57o15u`. Keep PR #4 updated.
- **No new dependency** without telling Eddie name/purpose/license/ARM (§13).
- Config over hardcoding (§1); swappable backends behind interfaces (§2); files ≤500 lines.

---

## 7. Read-first file map

| File | Why |
|---|---|
| `bardLLMPro/ROADMAP.md` | Scope authority: tiers, sprints, locked forks. |
| `bardLLMPro/DESIGN.md` | MVP architecture + the 6 contract-first lanes. |
| `bardLLMPro/docs/adr/ADR-0001…0005` | The accepted MVP decisions. |
| `bardLLMPro/docs/adr/ADR-0006…0010` + `TRUST_MODEL.md` | Deferred v2/v3 direction (TPM optional). |
| `bardLLMPro/contracts/` | Frozen wire/registry/router/agent/power-profile schemas. |
| `bardLLMPro/agent/engine.py` | Where real inference lives (`LlamaCppEngine`). |
| `bardLLMPro/docs/MEMORY.md` | Standing decisions (newest on top). |
| Root `CLAUDE.md` | The rules. |
