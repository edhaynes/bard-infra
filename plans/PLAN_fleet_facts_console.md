Status: In Progress
Author: Jason-infra
Started: 2026-07-01

# PLAN — Fleet node-tree console with Ansible-gathered hardware facts

Feature #91 (management screen for the fabric). A React/Vite node tree in the
existing `bard-pro-console` that shows every registered device and, per node,
its real hardware facts — **CPU, memory, GPU, storage, networking**.

Local first (dev), same artifact deploys to the cloud later (no code fork —
config only, per coding-rules §5/§6).

## Decisions (Eddie, 2026-07-01 — see ADR-0018)

- **The node container is the sole security boundary.** Each node runs ONE
  lightweight hardened podman container; everything (facts, inference, future
  resources) goes through it — no side-channel to the host. Smallest footprint.
- **Two postures, one control plane.** Default = **read-only facts**. Owner-
  enabled (per device or workgroup) = **read/write + serve resources**; first
  resource = **LLM inference** (bard-llm / llama.cpp). This inverts today's
  default (container serves inference by default) — resource weight lands only on
  enable. The enable toggle **rides the existing #65 per-device/workgroup seam**.
- **Facts source = open-source Ansible `setup` — Option A: driven *through* the
  node container**, not a side-channel SSH-to-host. We consume ansible's output;
  we do not write a gatherer. GPU (not covered by `setup`) filled by an
  `nvidia-smi` task. Rejected: psutil-in-agent (B/C alternatives in ADR-0018).
- **Facts = the HOST's read-only truth.** The facts posture gets narrow
  read-only host introspection (host `/proc`+`/sys` ro, host net ns) so a
  cgroup-limited container reports the node's real hardware, not its own view.
- **Home for the UI = extend `clients/console` (`bard-pro-console`)**, add a
  "Fleet" node-tree pane. Not a fourth frontend.

> **Downstream is independent of the gather transport.** The projector reads
> whatever ansible cached; the console renders `NodeFacts`. So S2/S3/S4 build
> against the frozen contract NOW; the container/connection wiring is S1/S5.

## The pipeline

```
ansible setup (gather_facts)  ─►  jsonfile fact cache  ─►  facts projector (py)  ─►  GET /nodes  ─►  console node-tree
  + nvidia-smi custom fact         one JSON per host        ansible_facts → 5 fields   control-plane    bard-pro-console
```

Ansible does ALL the gathering. Everything downstream just maps + serves +
renders. The one thing `setup` does NOT cover is GPU — filled by a supplemental
`nvidia-smi` task inside the same playbook (`set_fact … cacheable: true`), so it
lands in the same cache entry. Stays 100% in ansible; the agent is untouched.

## The frozen contract — `NodeFacts` (API-first freeze point, coding-rules §11)

Added to `contracts/control-plane.openapi.yaml`. Everything downstream builds
against this; nothing renders a shape not in this contract.

```
NodeFacts:
  nodeId:      string                          # inventory hostname == fleet id where they align
  cpu:
    model:     string                          # ansible_processor[-1] / processor model
    arch:      string                          # ansible_architecture
    cores:     integer                         # ansible_processor_cores * count (physical)
    vcpus:     integer                         # ansible_processor_vcpus
  memory:
    totalMb:   integer                         # ansible_memtotal_mb
  gpu:         { model: string, memoryMb: integer } | null   # nvidia-smi custom fact; null = none
  storage:     [ { device: string, sizeGb: number } ]        # ansible_devices (real disks only)
  networking:  [ { iface: string, ipv4: string|null, speedMbps: integer|null } ]  # ansible_interfaces
  gatheredAt:  string                          # ansible_date_time.iso8601 / cache mtime

NodesView:
  nodes:       [ NodeFacts ]
  generatedAt: string
```

Field mapping (ansible_facts → NodeFacts) lives ONLY in the projector, so the
huge raw fact blob never reaches the client.

## Sprints (each independently verifiable, §18.5)

### S1 — Ansible fact capture  ✅ (playbook + cache landed; container-connection is S5)
- `ansible/ansible.cfg`: enable `jsonfile` fact caching → `.facts_cache/`.
- `ansible/playbooks/facts.yml`: `gather_facts: true` over `bard_fleet` +
  nvidia-smi GPU custom fact (`bard_gpu`, cacheable, empty on non-GPU hosts).
- `.gitignore`: ignore the cache dir (runtime state).
- Done-signal: the playbook writes `.facts_cache/<host>` with `ansible_processor*`,
  `ansible_memtotal_mb`, `ansible_devices`, `ansible_interfaces`, `bard_gpu`.
- **Option A note:** the playbook/cache are transport-agnostic. Re-pointing the
  connection at the node *container* (podman/ssh connection plugin) + host-`/proc`
  read-only introspection is validated in S5 on real hardware (§11.1) — it does
  NOT change the playbook logic or the cached shape, so S2–S4 are unblocked.

### S2 — Contract + facts projector (backend, pure)
- Freeze `NodeFacts` / `NodesView` in `contracts/control-plane.openapi.yaml`.
- `registry/node_facts.py`: pure `project_facts(raw: dict) -> NodeFacts` +
  `load_facts_cache(dir) -> list[NodeFacts]`. Cache dir via config (§2, no
  hardcode). 100% line+branch coverage; every mapping branch asserted
  (missing fields, no GPU, no default ipv4, virtual/loopback ifaces filtered).

### S3 — `GET /nodes` endpoint
- `registry/app.py`: read-only `GET /nodes` → `NodesView`, same bearer auth as
  `/fleet`. Fail-soft: empty cache → `{nodes: [], generatedAt}` (not a 500).

### S4 — Console node-tree pane (frontend)
- `clients/console/src`: `NodeFacts` type mirroring the contract; `fleetTree.ts`
  pure helpers (build tree, format bytes/GB, group by workgroup→node);
  `FleetPane.tsx` (expandable tree, CPU/Mem/GPU/Storage/Networking panel);
  nav entry; sample data; styles cloned from existing console; Playwright
  structural tests. Sample-mode renders the tree with no backend.

### S5 — Wire live + verify
- api-mode: console `GET /nodes`; run the playbook against the real fleet;
  confirm gx10/snoopy render with REAL facts (§11.1 — real data, not asserted).
- Screenshots for Eddie's §14 visual sign-off.

## Open / to confirm
- **Base image (ADR-0018 amendment):** minimal facts posture → Red Hat distroless
  Python (**Project Hummingbird**; `ubi-micro`/`ubi-minimal` fallback);
  inference posture keeps UBI-9. Caveat: distroless has no `nvidia-smi`, so GPU
  facts come from the enabled/inference posture — validate on real hardware (S5).
- **GPU fill:** nvidia-smi custom fact in the playbook (chosen — stays in
  ansible). AMD/Intel GPU probes are a follow-up if the fleet grows them.
- **Endpoint:** new `GET /nodes` (chosen) vs enriching `/fleet`. New endpoint
  keeps the facts payload (heavy) off the fast-refresh device list.
- **Windows nodes:** `setup` works over WinRM too, but GPU/df facts differ;
  frogstation→bullfrog is moving to Linux anyway — Linux fleet first.
