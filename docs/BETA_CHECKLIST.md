# Closed-Beta Go-Live Checklist — Bard, Profile A (home power user)

Status: Living checklist — run top to bottom before inviting beta users.
Scope: **Profile A only** — single owner, trusted devices, home/Tailnet
deployment. Multi-tenant / hosted / public deployment is explicitly **out of
scope** for this beta and is gated separately (see bug #56 and
`docs/RISK_MEMO_relay_auth.md`).

Last verified against: v1.5.2, branch `claude/laughing-bell-57o15u`,
257 tests / 100% line+branch (HANDOFF cites 208; the suite has grown since).

---

## How to use this

Each box is a thing a human runs or confirms with their own eyes — not a thing
an agent asserts. Tick a box only after you have seen the evidence yourself.
If any **gate** item fails, do not send beta invites until it is resolved.

---

## 1. Code & test health (gate)

- [ ] Working tree clean on the release branch (`git status` shows nothing to commit).
- [ ] Full suite green: `cd bardLLMPro && uv run pytest -q` — all tests pass, **0 failures**.
- [ ] Coverage gate holds: run prints `Required test coverage of 100% reached`
      (enforced by `--cov-branch --cov-fail-under=100` in `pyproject.toml`).
- [ ] Lint clean: `uv run ruff check .` reports `All checks passed!`.
- [ ] Adversarial pentest suite passes: `tests/test_security_pentest.py` green
      (the ~23 attack regression suite — no-auth → 401, forged/expired/`alg:none`
      tokens rejected, M-4 body-token check, #54 broker-hijack rejection).
- [ ] Version is correct and forward-only: `cat VERSION` matches the intended
      beta build; `/version` and `/healthz` expose it.

## 2. Security fixes shipped — confirm present (gate)

These are the launch-gating fixes from `docs/SECURITY_AUDIT.md`. Confirm each is
in the build, not just in the changelog.

- [ ] **#54 — broker `hello` binds JWT `sub` ↔ claimed `agentId`**
      (`router/broker.py` `handle_agent_link`): a link whose `sub != agentId` is
      rejected with WS close 1008 and is **not** registered. (Audit finding H-1.)
- [ ] **#55 — `JwtVerifier` requires `exp`/`iss`/`sub`** (`common/auth.py`):
      a token minted without `exp` is rejected, not treated as non-expiring.
      (Audit finding M-1.)
- [ ] **#58 — minimum JWT secret length enforced (32 bytes)**
      (`common/config.py`): a present-but-too-short `BARDPRO_JWT_SECRET` fails
      fast at startup with a `ConfigError` naming the var (RFC 7518 §3.2 floor),
      on both the `load_config` and `JwtVerifier.from_config` paths.
- [ ] Regression coverage exists for all three — `tests/test_security_pentest.py`
      asserts they stay defended, so a future change can't silently undo them.

## 3. Open gate — bug #56 relay auth (decision required)

- [ ] **Eddie has ruled on #56** (the Maude → Router → remote-agent relay has no
      auth and sees plaintext — `docs/SECURITY_AUDIT.md` C-1, Critical).
      Read `docs/RISK_MEMO_relay_auth.md` and record the decision there.
- [ ] If the ruling is **accept for single-user beta**: confirm the relay binds
      **loopback / Tailnet-private only** (no non-loopback bind), and that no
      beta material brands the relay as "private" or "E2EE".
- [ ] If the ruling is **block until B4** (per-device identity): do **not** ship
      any client relay path in this beta; Maude relay stays off.
- [ ] No second user, no multi-tenant surface, no public reachability is exposed
      by this beta. (The moment a second identity exists, #56 is Critical — see memo.)

## 4. Secret hygiene (gate)

- [ ] `gitleaks` is wired and green: pre-commit hook installed
      (`.pre-commit-config.yaml`) **and** CI job present
      (`gitleaks/gitleaks-action@v2` in the live workflow).
- [ ] Push-range secret scan clean over the full beta range
      (`git log <upstream>..HEAD`), not just the tip commit.
- [ ] No secrets committed: `.env`, `*.key`, `*.pem`, `authkey.txt`,
      `eleven.txt` are gitignored and absent from the tree.
- [ ] **Audit hygiene item M-6 closed:** any plaintext creds that were readable
      on disk (`authkey.txt`, `claudeTalk/eleven.txt`) are moved to
      keychain/secret-manager and the ElevenLabs key has been **rotated**.
- [ ] No secret is read from a committed file at runtime — Router/Registry/Agent
      pull `BARDPRO_JWT_SECRET` from env / Secret Manager and **fail loud** if absent.

## 5. License & legal

- [ ] `pyproject.toml` `license` declares the repo correctly (**Proprietary** —
      not MIT), matching root `LICENSE` ("Bard LLM — Proprietary,
      © 2026 Bard Technology Solutions LLC").
- [ ] Beta participants have an agreement / NDA appropriate to a proprietary,
      pre-release build (App-Store-distributed, non-transferable personal licence).

## 6. Runtime readiness (Profile A deployment)

- [ ] TLS-default verified: cleartext is a **fail-fast logged opt-in**
      (`ALLOW_INSECURE_HTTP`), never a silent downgrade; no `verify=False` anywhere.
- [ ] Each service starts and is healthy: Router, Registry, and Agent processes
      up, `/healthz` returns 200, a representative `/v1/message` round-trips end to end.
- [ ] Config validates at startup: a missing/invalid key crashes with a clear
      message naming the key (no degraded-mode limp-along).
- [ ] Agent container is the rootless cap-dropped UBI-9 image; run recipe applies
      the cap-drop / `no-new-privileges` flags (image doesn't enforce them itself).
- [ ] Graceful shutdown on SIGTERM confirmed (no dropped in-flight requests on stop).

## 7. Observability & ops

- [ ] `/metrics` exposed on Router/Registry/Agent (Prometheus text) and scrapeable.
- [ ] Structured JSON logging on (`BARDPRO_LOG_FORMAT=json`) and going to stdout.
- [ ] A way to see "is the backend up?" for the beta tester — Registry liveness
      (heartbeat/TTL, stale exclusion) is working; dead nodes drop out of the pool.
- [ ] You can reach the beta tester to push a fix and to collect feedback/logs.

## 8. Beta-tester onboarding

- [ ] Install/run instructions are copy-pasteable and have been followed on a
      **clean machine** (README quick start, macOS + Linux at minimum).
- [ ] The tester knows the scope: single-user home use, what works (Profile A
      fabric), and what is explicitly **not** in this beta (multi-user, public
      relay, "private/E2EE" — all roadmap).
- [ ] A feedback channel and a place to file bugs is set up before the invite.
- [ ] Rollback plan: how to take the tester back to a known-good build if the
      beta build misbehaves (versions move forward only — bump + redeploy).

---

## Hard stops — do not invite if any of these are true

- A test fails, coverage is below 100%, or lint is dirty.
- Any gitleaks finding in the push range is unresolved.
- Bug #56 has **not** been ruled on by Eddie, **or** the ruling is "block" and a
  client relay path is still shipping in this beta.
- The relay is reachable from anywhere but loopback / the owner's Tailnet.
- `license` still says MIT, or a real secret sits readable on disk.
- The build was handed over "assumed working" without a service actually started,
  health checked, and a real request succeeding.
