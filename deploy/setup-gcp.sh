#!/usr/bin/env bash
# One-time setup: Artifact Registry repo + Workload Identity Federation so
# GitHub Actions can deploy this service to Cloud Run without a stored key.
#
# Run once locally with an account that has Owner/Editor on the project
# (`gcloud auth login` first). Safe to re-run — every command is idempotent
# (`|| true` / `--quiet` where creation would otherwise fail on a rerun).
#
# Usage: GITHUB_REPO=davicho01/yabot.jobs-mcp ./deploy/setup-gcp.sh

set -euo pipefail

PROJECT_ID="yabotjobs"
REGION="us-central1"
REPOSITORY="yabot-jobs-mcp"
SERVICE_ACCOUNT_ID="gh-deploy-yabot-jobs-mcp"
POOL_ID="github-actions-pool"
PROVIDER_ID="github-actions-provider"
GITHUB_REPO="${GITHUB_REPO:?Set GITHUB_REPO=owner/repo, e.g. davicho01/yabot.jobs-mcp}"

gcloud config set project "${PROJECT_ID}"

echo "Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  iam.googleapis.com \
  sts.googleapis.com

echo "Creating Artifact Registry repo (ok if it already exists)..."
gcloud artifacts repositories create "${REPOSITORY}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="yabot-jobs-mcp container images" || true

echo "Creating deploy service account (ok if it already exists)..."
gcloud iam service-accounts create "${SERVICE_ACCOUNT_ID}" \
  --display-name="GitHub Actions deployer for yabot-jobs-mcp" || true

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Granting the deploy service account the roles it needs..."
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet
done

echo "Creating Workload Identity Pool (ok if it already exists)..."
gcloud iam workload-identity-pools create "${POOL_ID}" \
  --location="global" \
  --display-name="GitHub Actions pool" || true

echo "Creating Workload Identity Provider scoped to ${GITHUB_REPO}..."
gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL_ID}" \
  --display-name="GitHub Actions provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '${GITHUB_REPO}'" \
  --issuer-uri="https://token.actions.githubusercontent.com" || true

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
POOL_RESOURCE_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"

echo "Allowing the GitHub repo to impersonate the deploy service account..."
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_RESOURCE_NAME}/attribute.repository/${GITHUB_REPO}" \
  --quiet

echo
echo "Done. Add these as GitHub repo secrets (Settings -> Secrets and variables -> Actions):"
echo "  GCP_WORKLOAD_IDENTITY_PROVIDER = ${POOL_RESOURCE_NAME}/providers/${PROVIDER_ID}"
echo "  GCP_SERVICE_ACCOUNT            = ${SERVICE_ACCOUNT_EMAIL}"
echo
echo "And these as GitHub repo variables (Settings -> Secrets and variables -> Actions -> Variables),"
echo "once you know this service's own public Cloud Run URL for YABOT_MCP_PUBLIC_URL:"
echo "  YABOT_API_BASE_URL      = <your production backend URL>"
echo "  YABOT_FRONTEND_BASE_URL = <your production frontend URL>"
echo "  YABOT_MCP_PUBLIC_URL    = <this service's own public Cloud Run URL, once known>"
