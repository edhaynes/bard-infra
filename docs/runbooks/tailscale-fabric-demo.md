# Runbook — Bard fabric over Tailscale + live dashboard

**What it demonstrates.** The Bard fabric (Registry + Router + Agents) running
across the **Tailscale tailnet**: agents on *different physical nodes* register
to one Registry **by MagicDNS name** (never a raw IP), are routed by name, and
show up live in the management console. This is the "Tailscale base
functionality" demo — and it exercises **INFRA-1** (name-based addressing, so a
node whose IP churns is still reachable) with `ENFORCE_PEER_NAME_RESOLUTION` on.

**Verified live 2026-06-16:** `edwards-macbook-pro` + `gx10` both `online`,
addressed by name, fleet visible in the console. (frogstation joins as a 3rd
agent once it's on SSH — it is not required for this demo.)

## Prereqs
- Nodes on the tailnet, reachable by MagicDNS name (e.g. the Mac + `gx10`).
- The **bardLLMPro** repo on the registry node; each remote agent node reachable
  by SSH with the repo rsync'd + a built `.venv` (the launcher does this; default
  remote dir `/srv/models/tmp/bardpro-demo`, override `BARDPRO_REMOTE_DIR`).
- `uv` on every node.

## Bring it up (one command)
The reusable launcher lives in bardLLMPro (`scripts/tailscale_fleet_up.sh`). First
arg is the Registry/Router node; the rest are agent nodes:

```bash
cd ~/projects/bard-llm/bardLLMPro
scripts/tailscale_fleet_up.sh edwards-macbook-pro gx10
```

It generates a throwaway JWT secret, brings up Registry (CORS-enabled for the
console) + Router + a local Agent on the registry node, SSHes into each agent
node to start a self-registering Agent (`BARDPRO_ADVERTISED_ADDRESS=http://<node>:<port>`),
all addressed by name over HTTP (tailnet is already WireGuard-encrypted:
`BARDPRO_REGISTRY_SCHEME=http` + `BARDPRO_ALLOW_INSECURE_HTTP=true`). It writes
the manager JWT + `connection.env` to a run dir and prints the console command.

## The dashboard
```bash
cd ~/projects/bard-llm/bardLLMPro/clients/console
VITE_API_BASE_URL=http://edwards-macbook-pro:8081 \
  VITE_API_TOKEN="$(cat <run-dir>/manager.jwt)" \
  npm run dev -- --port 5173        # 5173 matches the Registry's CORS allowlist
# open http://localhost:5173
```
The console (`clients/console`, React/Vite) reads `GET /fleet` from the Registry
and shows each device by name with status, power profile, and enrollment.

## Verify (CLI, no browser)
```bash
curl -s -H "Authorization: Bearer $(cat <run-dir>/manager.jwt)" \
  http://edwards-macbook-pro:8081/fleet | python3 -m json.tool
```
Expect every node `online`, `address: http://<node>:<port>` (a **name**, not an IP).
The Registry log shows continuous `POST /register 200` from each node's tailnet IP.

## What it proves
- A **remote** node (gx10) registers to the Registry **over the tailnet, by name**.
- Addressing is name-based → survives IP churn (Tailscale reassigned frogstation's
  IP twice this session; names never changed).
- `ENFORCE_PEER_NAME_RESOLUTION=true` is satisfied (names pass; raw-IP peers rejected).

## Teardown
```bash
cd ~/projects/bard-llm/bardLLMPro && scripts/tailscale_fleet_down.sh
# console: kill the vite dev server (its pid is printed at launch)
```

## Notes
- The console must run on a port in the Registry's `BARDPRO_CONSOLE_ORIGINS`
  allowlist (default `:5173`); the console's own default vite port is `5273`, so
  pass `--port 5173` or add `:5273` to the allowlist.
- Not required for this demo (ROADMAP): topology graph, Prometheus/Grafana,
  Valkey HA, the public cloud coordinator (that's for the *off-tailnet* product
  case — see `docs/REVIEW_2026-06-16.md`).
