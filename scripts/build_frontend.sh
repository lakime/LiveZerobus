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

# Strip any stale transpiled .js siblings of our .tsx sources. Some IDE
# integrations (Volar, ts-server save actions) drop a .js next to every
# .tsx; Vite's default extension priority resolves .js before .tsx, so
# a stale sibling silently shadows the canonical TSX. Better to delete
# them before every build than to chase the symptom in the deployed UI.
echo "==> Cleaning stale .js siblings under frontend/src"
find "${FRONTEND}/src" -type f -name "*.js" \
  ! -path "*/node_modules/*" -delete 2>/dev/null || true

echo "==> Building Vite bundle"
(cd "${FRONTEND}" && npm run build)

echo "==> Staging dist → backend/static"
rm -rf "${STATIC}"
cp -R "${FRONTEND}/dist" "${STATIC}"

echo "==> Done. backend/static now contains:"
ls -la "${STATIC}"
