#!/usr/bin/env bash
# Deploy the refinery demo (orchestrator + console) to Cloud Run.
# Requires: gcloud authenticated, a project with Cloud Run + Cloud Build enabled.
#
#   PROJECT=my-proj REGION=us-central1 bash deploy/deploy_cloudrun.sh
#
# This deploys the VISUAL demo (bring-up/down + faults). It needs NO secret — the
# orchestrator does not talk to the Registry. To also show real self-discovery, run
# the bard-infra Registry + scripts/project_fleet.py and pass REFINERY-* env (see
# DEPLOY.md); only then is a Secret-Manager JWT involved.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT=<gcp-project-id>}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-refinery-demo}"
IMAGE="gcr.io/${PROJECT}/${SERVICE}"

echo "Building ${IMAGE} via Cloud Build (amd64, custom Containerfile)..."
gcloud builds submit \
  --project "${PROJECT}" \
  --config /dev/stdin . <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "deploy/Containerfile", "-t", "${IMAGE}", "."]
images: ["${IMAGE}"]
EOF

echo "Deploying ${SERVICE} to Cloud Run (${REGION})..."
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --set-env-vars "REFINERY_TICK_SECONDS=1.0,REFINERY_CONSOLE_DIST=/app/console-dist" \
  --project "${PROJECT}"

echo "Done. Open the printed URL — the dashboard is served at /."
