#!/usr/bin/env bash
#
# Deploy the public LokNet Router to Google Cloud Run (feature #59 / ADR-0013,
# slice 3). The Router is the SINGLE FRONT DOOR: agents dial OUT to its
# /v1/agent-link WebSocket (outbound 443 only — no Tailscale, no inbound), and
# clients POST /v1/message. See docs/demo/LOKNET_CLOUDRUN.md for the full story.
#
# This script is AUTHORED, not run by CI or by an agent — Eddie runs the public
# deploy. It is idempotent (re-runnable) and parameterized: nothing is
# hardcoded. Set these env vars (or accept the defaults that are safe to show):
#
#   PROJECT       (required)  GCP project id            — no default, never hardcoded
#   REGION        (optional)  Cloud Run region          — default us-central1
#   SERVICE       (optional)  Cloud Run service name    — default loknet-router
#   REPO          (optional)  Artifact Registry repo    — default bardpro
#   IMAGE_TAG     (optional)  image tag                 — default $(git rev-parse --short HEAD) or "latest"
#   SECRET_NAME   (optional)  Secret Manager secret     — default bardpro-jwt-secret
#   BUILDER       (optional)  podman | docker | gcloud  — default podman
#
# Example:
#   PROJECT=my-gcp-project REGION=us-central1 bash scripts/deploy_loknet_router.sh
#
# What you get: a single-instance, JWT-gated public Router. Single instance is
# deliberate — the broker link map and the in-process Registry are in memory,
# so a second instance would not see the first's links (the v2 Valkey control
# plane, ADR-0010, lifts this). Hence --min-instances=1 --max-instances=1.

set -euo pipefail

# --- parameters (no hardcoded project id; placeholders mirror the runbook) ----
PROJECT="${PROJECT:?set PROJECT to your GCP project id (never hardcode it)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-loknet-router}"
REPO="${REPO:-bardpro}"
SECRET_NAME="${SECRET_NAME:-bardpro-jwt-secret}"
BUILDER="${BUILDER:-podman}"

# Default the image tag to the short SHA so each build is uniquely identifiable
# (CLAUDE.md §11 — unique build per artifact); fall back to "latest" outside a
# git checkout.
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"
REGISTRY_HOST="${REGION}-docker.pkg.dev"
IMAGE="${REGISTRY_HOST}/${PROJECT}/${REPO}/loknet-router:${IMAGE_TAG}"

# Resolve paths relative to this script so it runs from anywhere (no cwd
# assumption — CLAUDE.md §4).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONTAINERFILE="${PROJECT_DIR}/router/Containerfile.cloud"

echo "LokNet Router deploy"
echo "  project : ${PROJECT}"
echo "  region  : ${REGION}"
echo "  service : ${SERVICE}"
echo "  image   : ${IMAGE}"
echo "  builder : ${BUILDER}"
echo

# --- 1. ensure the Artifact Registry repo exists (idempotent) -----------------
# describe || create: re-running is a no-op once the repo is there.
if ! gcloud artifacts repositories describe "${REPO}" \
        --project="${PROJECT}" \
        --location="${REGION}" >/dev/null 2>&1; then
    gcloud artifacts repositories create "${REPO}" \
        --project="${PROJECT}" \
        --location="${REGION}" \
        --repository-format=docker \
        --description="Bard images (LokNet Router, agents)"
fi

# --- 2. ensure the JWT secret exists in Secret Manager (idempotent) -----------
# The secret VALUE is never written here. If the secret is absent, fail loudly
# with the exact command to create it — the operator supplies the material out
# of band (CLAUDE.md §3 / §6: secrets never live in source or scripts).
if ! gcloud secrets describe "${SECRET_NAME}" \
        --project="${PROJECT}" >/dev/null 2>&1; then
    echo "ERROR: Secret Manager secret '${SECRET_NAME}' not found." >&2
    echo "Create it once (value never touches this repo), e.g.:" >&2
    echo "  printf '%s' \"\$BARDPRO_JWT_SECRET\" | gcloud secrets create ${SECRET_NAME} \\" >&2
    echo "      --project=${PROJECT} --data-file=-" >&2
    exit 1
fi

# --- 3. build + push the Router image -----------------------------------------
case "${BUILDER}" in
    podman|docker)
        "${BUILDER}" build \
            --platform=linux/amd64 \
            -f "${CONTAINERFILE}" \
            -t "${IMAGE}" \
            "${PROJECT_DIR}"
        # Short-lived OAuth token, never stored.
        "${BUILDER}" login \
            -u oauth2accesstoken \
            -p "$(gcloud auth print-access-token)" \
            "${REGISTRY_HOST}"
        "${BUILDER}" push "${IMAGE}"
        ;;
    gcloud)
        # Cloud Build path — no local container engine required.
        gcloud builds submit "${PROJECT_DIR}" \
            --project="${PROJECT}" \
            --tag="${IMAGE}"
        ;;
    *)
        echo "ERROR: unknown BUILDER '${BUILDER}' (use podman | docker | gcloud)" >&2
        exit 1
        ;;
esac

# --- 4. deploy to Cloud Run (idempotent: deploy upserts the service) ----------
# --min-instances=1 --max-instances=1: single instance is REQUIRED while the
#   broker link map + in-process Registry are in memory (ADR-0010 Valkey lifts
#   it later). A 2nd instance would not see the 1st's live agent links.
# --set-secrets: JWT comes from Secret Manager, NEVER a plain --set-env-vars
#   (mirrors the existing scale-to-zero echo node).
# --allow-unauthenticated: the platform edge is open; the JWT gates every
#   request at the app (TokenVerifier seam), so this is intentional.
# --timeout=3600: Cloud Run caps a single WebSocket at 60 min; the agent's
#   slice-1 reconnect loop re-establishes the link after a forced close, so the
#   cap is survivable, not fatal (see LOKNET_CLOUDRUN.md).
# $PORT is injected by Cloud Run and honored by the Containerfile CMD.
gcloud run deploy "${SERVICE}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --image="${IMAGE}" \
    --platform=managed \
    --allow-unauthenticated \
    --min-instances=1 \
    --max-instances=1 \
    --timeout=3600 \
    --cpu=1 \
    --memory=512Mi \
    --set-secrets="BARDPRO_JWT_SECRET=${SECRET_NAME}:latest" \
    --set-env-vars="BARDPRO_LOG_FORMAT=json,BARDPRO_REGISTRY_HOST=127.0.0.1"

URL="$(gcloud run services describe "${SERVICE}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --format='value(status.url)')"

echo
echo "Deployed. Public Router URL: ${URL}"
echo "Point a remote agent at it (no Tailscale, outbound 443 only):"
echo "  BARDPRO_BROKER_ENABLED=true \\"
echo "  BARDPRO_BROKER_URL=wss://${URL#https://}/v1/agent-link \\"
echo "  BARDPRO_SELF_REGISTER=true   uvicorn agent.main:app"
