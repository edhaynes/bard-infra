Status: In progress — Jason (B1✅ B2✅ B7✅ B3✅ B4✅ B5✅ B6✅ B8✅ landed; started 2026-06-12)

# HANDOFF — Finish the Bard architecture (console, identity, plugins, publish)

Author: Jason (2026-06-12 session). Merges Eddie's 2026-06-12 instructions with
the publish-readiness recon of the same day. Scope authority remains
`ROADMAP.md` (ADR-0014 two-profile strategy); this handoff sequences the v2
Walk work Eddie prioritized and adds his new rulings.

## Eddie's instructions being merged (2026-06-12, verbatim intent)

1. "What's the gap before we publish?" → gap analysis below; #56 risk decision
   is his to make.
2. "I want a management console where you can add devices a-la-Tailscale,
   **but it's private**" → feature **#64** (filed in features.md): self-hosted
   control plane, enroll/approve/name/revoke devices, live status; no
   third-party coordination server; nothing leaves the network.
3. "Manage your plug-ins, like Squawk Box" → feature **#65**: console Plugins
   pane; Squawk Box (the Maude walkie-talkie client presented as a plugin) is
   the first catalog entry — and it is ALSO the eds-rules book's capstone
   worked example, so the plugin seam shown in the book and the one the
   console manages MUST be the same contract.
4. Standing crew rulings now in canon (eds-rules / shared-rules): the Powell
   rule (90% info → decide; <90% certain → ask Eddie), sprints sized for 90%
   first-try success and independent enough to run in parallel, quality bar
   90% working / 95% publish, count-capped rule docs.

## Where the architecture stands (recon 2026-06-12)

- **Shipping:** v1.5.2 on branch `claude/laughing-bell-57o15u` (clean tree,
  local). Router/Registry/Agent + TLS/JWT + LokNet outbound broker +
  llama.cpp UBI agent. 208 tests, enforced 100% line+branch, CI with
  gitleaks, adversarial pentest suite. Profile A is feature-complete.
- **Already in the repo for Profile B:** `clients/console/` React stub with
  typed topology model; `contracts/control-plane.openapi.yaml`;
  `contracts/trust.schema.yaml` (orgs → workgroups → devices);
  power-profile capability advertisement; Registry heartbeat liveness.
- **Known gaps:** bug **#56** relay auth (Critical for multi-user; Eddie's
  risk call for single-user beta); fleet-wide shared JWT secret (the audit's
  standing weakness — per-device identity fixes it properly);
  `pyproject.toml` license says MIT while the repo is proprietary; Cloud Run
  recipe authored but never executed; no live-inference e2e in CI; no
  production ops runbook.

## Sprint series

Per shared-rules §18.5: each sprint is independently verifiable, sized for
90% first-try success, one purpose per commit, contract-first with 100%
line+branch coverage on new logic (§11). Sprints B2/B3/B4 are sequential
(identity is the foundation); B5–B8 parallelize after B3; B1 can run anytime.

### B1 — Publish hygiene (small; run anytime)
- Fix `pyproject.toml` license metadata (MIT → proprietary/SPDX ref).
- Draft the closed-beta checklist + a one-page #56 risk memo for Eddie
  (accept for single-user beta / block until B4 — his call, Powell rule).
- **Done-signal:** CI green; memo in `docs/`; Eddie has ruled on #56 timing.

### B2 — Per-device identity (contract first)
- Extend `contracts/control-plane.openapi.yaml`: device enrollment lifecycle
  (issue join token → pending → approve → active → revoke), per-device keys.
- Freeze contract, write tests against it, then implement in Registry
  (JSON store now, keep the Valkey seam per ADR-0010). Replace fleet-wide
  JWT secret with per-device credentials; router validates per-device.
- **Done-signal:** enrollment lifecycle passes e2e in tests; pentest suite
  extended (revoked device rejected; token reuse rejected); 100% coverage.

### B3 — Enrollment UX (the Tailscale moment)
- `bardpro enroll` path: agent boots with a join token (env/flag), lands
  "pending"; approval flips it active. QR rendering for the token (terminal
  + console later). LAN auto-discovery stays an open ADR-0014 question —
  join-token is the v1 mechanism (decision recorded, revisit with #63 mDNS).
- **Done-signal:** smoke script — fresh agent + join token → pending →
  approved → serves a real request through the router.

### B4 — Close #56: relay auth on device identity
- The client relay path (Maude → Router → remote agent) authenticates with
  the same per-device identity from B2. Closes SECURITY_AUDIT's Critical.
- **Done-signal:** pentest tests prove unauthenticated relay is rejected;
  SECURITY_AUDIT.md updated; this unblocks any multi-user deployment.

### B5 — Console, read-only (parallel after B3)
- Wire `clients/console/` to the control-plane API: real device list, live
  status from Registry heartbeats, capabilities from power profiles. No
  mutations yet. Playwright structural tests per shared-rules §14; visual
  sign-off is Eddie's (screenshot request — the LLM cannot see the render).
- **Done-signal:** console renders the real fleet on a dev box; Playwright
  green; Eddie has screenshots.

### B6 — Console, manage
- Approve/revoke/rename devices and workgroup assignment from the console
  (the #64 core). Audit log of console actions.
- **Done-signal:** full enroll→approve→serve→revoke loop driven entirely
  from the UI, demonstrated end-to-end in the smoke script + Playwright.
- ✅ Shipped 2026-06-12 (branch sprint-b6-console-manage, v1.5.5): contract
  extensions (control-plane rename/workgroup/audit paths + additive
  `DeviceRecord.workgroup`), Registry rename/assign + `registry/audit_log.py`
  (append-only JSONL + `GET /audit`), console actions + Activity pane,
  `scripts/smoke_console_manage.py` proves the loop on real sockets
  (8/8 PASS). Pending: Eddie's screenshot sign-off per §14.

### B7 — Plugin seam v1 (parallel with B5/B6)
- Define the plugin manifest contract (id, version, required capabilities,
  config schema, health endpoint) as a frozen schema in `contracts/` —
  THE seam the book's capstone chapter walks through; coordinate wording
  with eds-rules F7 so book and code show the identical contract.
- Squawk Box = first manifest (Maude presented as a plugin; no new app
  code — the manifest + registry listing IS the deliverable). Console gets
  a read-only Plugins pane.
- **Done-signal:** contract schema frozen + tested; Squawk Box appears in
  the console's plugin list.

### B8 — Plugin manage + second plugin
- Enable/disable per device/workgroup, config storage, plugin health in the
  console (#65 complete). SSH plugin manifest as the second catalog entry
  (proves the seam generalizes; actual ssh implementation remains ROADMAP
  Sprint 5 scope).
- **Done-signal:** two plugins managed from the console; enable state
  round-trips through the control plane.
- ✅ Shipped 2026-06-12 (branch sprint-b8-plugin-manage, v1.5.6): contract
  extensions (control-plane `GET /plugins`, enable/disable per
  device/workgroup, per-target config get/set validated against the
  manifest's configSchema, reported plugin health on the heartbeat pattern;
  AuditEntry extended additively — **plugin-manifest.schema.json itself
  untouched**), `registry/plugin_store.py` (fail-fast catalog from the
  example manifests: Squawk Box + SSH), console Plugins pane (toggle per
  target, schema-driven settings form, collapsed Advanced JSON, plain-words
  health), plugin actions audited, `scripts/smoke_plugin_manage.py` proves
  the loop on a real socket (8/8 PASS). SSH service implementation stays
  ROADMAP Sprint 5; enablement is desired state in the control plane.
  Pending: Eddie's screenshot sign-off per §14.

### B9 — Ops + publish
- Execute (not just author) the Cloud Run recipe once; write the self-host
  production runbook (certs, monitoring, log rotation, graceful shutdown);
  add the live-llama.cpp e2e to CI (HANDOFF §2's highest-value gap).
- **Done-signal:** a clean-machine self-host following only the runbook
  succeeds; CI runs one real inference; beta checklist all green.

## Standing constraints for every sprint

- Branch state: current work sits on `claude/laughing-bell-57o15u` with
  unreviewed range — the next session should get Eddie's review/merge ruling
  before building atop it (Powell rule: ask, don't assume).
- Trackers: features #64/#65 are filed with inline Clarify questions —
  answer them when the sprint picks the item up, fold answers back in.
- Secret hygiene §7 applies to every push; the repo's CI already enforces
  gitleaks — keep it that way.
- The book dependency runs ONE way: the book documents the plugin seam the
  code defines (B7); the book never defines the seam.

## Out of scope (parked, tracked elsewhere)

- Book editorial backlog (eds-rules `FABLE_CLAUDE_HANDOFF.md`) — separate
  work item; its rule-renumbering task must coordinate with Appendix D and
  the version-locked tuned model when picked up.
- F12 rule-effectiveness study, F13 README on-ramp (eds-rules features.md).
- v3 trust fabric (TRUST_MODEL.md, ADR-0006) — direction, not these sprints.
