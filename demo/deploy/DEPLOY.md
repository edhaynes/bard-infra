# Deploying the refinery demo

Two layers. The **visual demo** (bring-up/down + fault cascade) is self-contained and
needs no secret. **Real self-discovery** additionally needs the bard-infra Registry +
fleet projector.

## A. Visual demo on Cloud Run (orchestrator + console)

One image serves the API and the dashboard same-origin on `$PORT` (8080).

```bash
PROJECT=my-gcp-project \
  REGION=us-central1 \
  bash deploy/deploy_cloudrun.sh
```

What it does (per `coding-rules.md` §6): UBI base images, single-instance, `$PORT`
8080, `--allow-unauthenticated` (it's a public read-only demo, no secret). The console
is built with `VITE_ORCH_BASE=""` so it calls the same origin.

Local container parity:

```bash
podman build -f deploy/Containerfile -t refinery-demo .
podman run --rm -p 8080:8080 refinery-demo
# open http://localhost:8080
```

> No secret is baked or required for this layer. Keep it that way — this is a public repo.

## B. Adding real self-discovery (Registry + projector)

The orchestrator does not need the Registry to run; the Registry is the *discovery
fabric* the fleet projector registers into. Two ways to show it:

1. **On-prem / Tailscale (simplest, matches `scripts/run_local.py`).** Run the bard-infra
   Registry and `scripts/project_fleet.py` on a host you control; both read a shared
   `BARDPRO_JWT_SECRET` / `REFINERY_JWT_SECRET` from the environment.
2. **Cloud Run (advanced).** Follow bard-infra's LokNet pattern
   (`docs/demo/LOKNET_CLOUDRUN.md`): a single-instance Router fronts a private in-process
   Registry; the projector registers over the broker link. The fleet JWT secret MUST come
   from Secret Manager (`--set-secrets BARDPRO_JWT_SECRET=...:latest`), never baked.

```bash
# create the fleet secret once (never commit it)
printf '%s' "$(openssl rand -hex 32)" \
  | gcloud secrets create refinery-jwt-secret --data-file=- --project my-gcp-project
```

## Secret hygiene (always)

- Run a secret scan over the build context and push range before any deploy
  (`coding-rules.md` §0.13, §7). The image carries no secret for layer A.
- `.env` is gitignored; `.env.example` is the template. Never put a real
  `REFINERY_JWT_SECRET` in a committed file — this repo is public.
