#!/usr/bin/env bash
# Push the local backend/ (FastAPI + staged React bundle) to the Databricks
# App named $APP_NAME. No bundles, no Terraform — just two CLI calls:
#   1) databricks sync    backend  <workspace-path>
#   2) databricks apps deploy <app> --source-code-path <workspace-path>
#
# Usage:
#   ./scripts/deploy_app.sh                     # defaults below
#   APP_NAME=livezerobus ./scripts/deploy_app.sh
#   WORKSPACE_PATH=/Workspace/Users/me@x/live ./scripts/deploy_app.sh
#
# Prereqs:
#   - databricks CLI authenticated (`databricks auth login --host ...`)
#   - node + npm installed locally (for the frontend build)
#   - the App slot (e.g. `livezerobus`) already exists in the workspace
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="${APP_NAME:-livezerobus}"

# Default workspace path: /Workspace/Users/<caller>/<app-name>
if [[ -z "${WORKSPACE_PATH:-}" ]]; then
  CALLER="$(databricks current-user me --output json | python3 -c 'import json,sys; print(json.load(sys.stdin)["userName"])')"
  WORKSPACE_PATH="/Workspace/Users/${CALLER}/${APP_NAME}"
fi

echo "==> App:             ${APP_NAME}"
echo "==> Workspace path:  ${WORKSPACE_PATH}"

# 1. Build React → stage into backend/static so the uploaded tree is self-contained
echo "==> Building frontend"
"${ROOT}/scripts/build_frontend.sh"

# 2. Push backend/ (contains app.yaml, requirements.txt, app/, static/) to the workspace
echo "==> Syncing backend/ → ${WORKSPACE_PATH}"
databricks sync --full "${ROOT}/backend" "${WORKSPACE_PATH}"

# 3. Tell the existing App to (re)deploy from that path
echo "==> Deploying ${APP_NAME}"
databricks apps deploy "${APP_NAME}" --source-code-path "${WORKSPACE_PATH}"

echo "==> Done. Tail logs with:  databricks apps logs ${APP_NAME}"
