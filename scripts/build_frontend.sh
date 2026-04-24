#!/usr/bin/env bash
# Build the React frontend and stage it inside backend/ so the uploaded
# source_code_path (= ./backend) is self-contained at deploy time.
#
# Usage:  ./scripts/build_frontend.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="${ROOT}/frontend"
STATIC="${ROOT}/backend/static"

echo "==> Installing frontend deps"
(cd "${FRONTEND}" && npm install --no-audit --no-fund)

echo "==> Building Vite bundle"
(cd "${FRONTEND}" && npm run build)

echo "==> Staging dist → backend/static"
rm -rf "${STATIC}"
cp -R "${FRONTEND}/dist" "${STATIC}"

echo "==> Done. backend/static now contains:"
ls -la "${STATIC}"
