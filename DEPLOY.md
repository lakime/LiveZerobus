# Deploying LiveZerobus

No bundles, no Terraform — this repo ships just the app source. Push it to
the existing `livezerobus` Databricks App with two CLI calls, wrapped in
`scripts/deploy_app.sh`.

## Prerequisites

- Databricks CLI (v0.240+):
  ```
  curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
  databricks auth login --host https://<your-workspace>.azuredatabricks.net
  ```
- `node` 20+ and `npm`
- The empty Databricks App named `livezerobus` already exists in the workspace
- Foundation Model API enabled — the app calls
  `databricks-meta-llama-3-3-70b-instruct` for the agent layer

## One command to push code

```
./scripts/deploy_app.sh
```

That does:

1. `scripts/build_frontend.sh` → `npm install && npm run build` in `frontend/`,
   then copies `frontend/dist/` into `backend/static/`.
2. `databricks sync --full backend /Workspace/Users/<you>/livezerobus` →
   uploads the backend folder (containing `app.yaml`, `requirements.txt`,
   the FastAPI package, and the staged React bundle).
3. `databricks apps deploy livezerobus --source-code-path <workspace-path>` →
   tells the existing app to restart from the uploaded code.

Override defaults with env vars if needed:

```
APP_NAME=livezerobus \
WORKSPACE_PATH=/Workspace/Users/puzar@softserveinc.com/livezerobus \
  ./scripts/deploy_app.sh
```

## Point the App at Lakebase + FM API

The FastAPI backend mints a short-lived OAuth token via the Databricks SDK
and uses it both as the Postgres password and as the Bearer for the
Foundation Model endpoint, so you only need a small amount of config.
Either set these once in `backend/app.yaml` (replace the `CHANGE_ME`
placeholders and re-run `deploy_app.sh`), or update the running app:

```
databricks apps update livezerobus \
  --env PGHOST=<instance>.database.cloud.databricks.com \
  --env PGUSER=<service-principal-uuid> \
  --env FM_MODEL=databricks-meta-llama-3-3-70b-instruct \
  --env BUDGET_MONTHLY_USD=25000
```

Defaults: `PGPORT=5432`, `PGDATABASE=databricks_postgres`,
`FM_MODEL=databricks-meta-llama-3-3-70b-instruct`,
`BUDGET_MONTHLY_USD=25000`.

## Everything else (run by hand when you want data flowing)

These pieces live in the repo as reference source; they're **not** pushed
by the deploy script. Create / run them in the Databricks UI yourself:

| Folder | What it does |
| --- | --- |
| `schemas/setup.sql` | One-shot catalog / schema / Bronze / dims / agent-state tables (paste into SQL editor) |
| `schemas/bronze_tables.sql` + `schemas/seed_dimensions.sql` | Parameterized variants consumed by `scripts/setup_unity_catalog.py` |
| `schemas/lakebase_schema.sql` | Postgres-side DDL — Gold mirrors + the seven agent-state tables written by the app |
| `scripts/setup_unity_catalog.py` | Python version of the Bronze / dim DDL — run as a notebook or one-off job |
| `pipelines/` | Lakeflow SDP pipeline (Bronze → Silver → Gold + ML scoring). Create a Pipeline in the UI, point it at these files, set `livezerobus.model_name` in its configuration. |
| `ml/train_supplier_model.py` | Trains + registers `livezerobus.procurement.supplier_scoring_model` in UC with alias `@prod`. |
| `lakebase_sync/` | Declares synced tables Delta → Lakebase; run once your Lakebase instance exists. |
| `simulators/` | Four data-stream producers (seed inventory / supplier quotes / planting demand / grow-input prices) writing via Zerobus. |

## Local dev

```
# backend
cd backend
pip install -r requirements.txt
PGHOST=... PGUSER=... \
FM_MODEL=databricks-meta-llama-3-3-70b-instruct \
FRONTEND_DIST=../frontend/dist DEV=1 \
  uvicorn app.main:app --reload

# frontend (in another terminal)
cd frontend
npm install
npm run dev   # Vite dev server on :5173, proxies /api to :8000
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `uvicorn: error: No module named 'app'` in app logs | You synced the wrong folder. `databricks sync` must target `backend/` (which contains `app.yaml` + the `app/` package), not the repo root. |
| Frontend shows `Frontend bundle not found` JSON | You skipped `scripts/build_frontend.sh` before syncing. Re-run `deploy_app.sh`. |
| `psycopg.OperationalError: FATAL: password authentication failed` | The service-principal UUID in `PGUSER` doesn't match the identity the app runs as, or it hasn't been granted access to the Lakebase instance. |
| Emails tab says "no threads" after `Run agent cycle` | Check the pipeline has produced at least one `BUY_NOW` in `gd_procurement_recommendations`; the negotiator only opens RFQs for open recommendations. |
| Agent runs log shows `status=ERROR` with `403` | The SP the app runs as lacks `CAN_QUERY` on the FM serving endpoint. Grant it in Serving → endpoint → Permissions. |
| `databricks: command not found` | Install the CLI (see Prerequisites) and re-authenticate. |
