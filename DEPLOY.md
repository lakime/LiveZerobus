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
- A Service Principal bound to the App (see next section)
- Foundation Model API enabled — the app calls
  `databricks-meta-llama-3-3-70b-instruct` for the agent layer

## Service Principal setup

Everything on the data-plane side (Zerobus writes, Lakebase connection,
FM API calls, agent writes into `live.*`) runs as the **App's service
principal**, not as you. The simulators on your laptop can use either
that same SP or a separate one — this repo assumes the same one
(`app-3dxwqo livezerobus`).

### Databricks-managed vs Entra-managed SPs

On Azure Databricks there are two flavors of SP, and the OAuth secret is
generated in a different place depending on which you have. Check which
one you've got: Workspace → Settings → Identity and access → Service
principals → open your SP → the **Managed by** / source field says
either `Databricks` or `Microsoft Entra ID`.

| Property | Databricks-managed SP | Entra-managed SP |
|---|---|---|
| Created in | Databricks Account Console | Azure Portal → Entra ID → App registrations |
| Display name | Set by Databricks admin | Comes from the Entra app |
| `Application ID` (the UUID you'll paste into GRANTs) | Shown in Account Console → Service principals → your SP | Entra → App registrations → Overview → *Application (client) ID* |
| OAuth secret lives in | **Account Console** (not the workspace page) → Service principals → *Secrets* tab → *Generate secret* | **Azure Portal** → Entra ID → your app → *Certificates & secrets* → *New client secret* |
| Secret visible in Databricks workspace UI? | No | No |
| Rotation | Generate a new one alongside the old one; delete old when safe | Same, on Azure side |
| Typical use | Databricks-native workloads (Apps, Jobs, Zerobus clients) | Any Azure-wide SSO / enterprise identity story |

Either flavor works fine for every step in this repo. The rest of this
guide refers to the UUID as `<sp-app-id>` and the secret as
`<sp-secret>`.

### What the SP needs to be granted

Run this in the SQL Editor, substituting the UUID (not the display name
and not the numeric Databricks-internal SP id):

```sql
GRANT USE CATALOG ON CATALOG livezerobus TO `<sp-app-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA livezerobus.procurement TO `<sp-app-id>`;

-- Zerobus writes: MODIFY on the four Bronze tables
GRANT MODIFY ON TABLE livezerobus.procurement.bz_inventory_events  TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.bz_supplier_quotes   TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.bz_demand_events     TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.bz_commodity_prices  TO `<sp-app-id>`;

-- Agent writes: MODIFY on the seven agent-state tables
GRANT MODIFY ON TABLE livezerobus.procurement.email_outbox             TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.email_inbox              TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.po_drafts                TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.budget_ledger            TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.supplier_applications    TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.invoice_reconciliations  TO `<sp-app-id>`;
GRANT MODIFY ON TABLE livezerobus.procurement.agent_runs               TO `<sp-app-id>`;
```

Non-SQL grants (done in the UI):

| Resource | Where | Permission |
|---|---|---|
| Lakebase instance `databricks_postgres` | Lakebase → Instance → Permissions | `CAN_CONNECT_AND_CREATE` |
| Serving endpoint `databricks-meta-llama-3-3-70b-instruct` | Serving → endpoint → Permissions | `CAN_QUERY` |
| Zerobus (if your workspace exposes it as a named resource) | Compute → Zerobus → Permissions | `CAN_USE` |

### Using the SP for the simulators

```
export DATABRICKS_HOST=https://<workspace>.azuredatabricks.net
export DATABRICKS_CLIENT_ID=<sp-app-id>
export DATABRICKS_CLIENT_SECRET=<sp-secret>
export ZEROBUS_ENDPOINT=<workspace>.zerobus.<region>.azuredatabricks.net:443
```

The Databricks SDK picks these up automatically — both flavors of SP use
the same OAuth M2M client-credentials flow against
`<host>/oidc/v1/token`, so the simulator code doesn't care which one
you're using.

For iterative local dev you can skip the SP entirely and run simulators
as your own user:

```
databricks auth login --host https://<workspace>.azuredatabricks.net
# omit DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET — SDK picks up ~/.databrickscfg
```

— as long as your user has `MODIFY` on the four `bz_*` tables.

### The App itself doesn't need the secret

Databricks injects the App's SP identity at runtime. `scripts/deploy_app.sh`
never asks for a client secret: the FastAPI backend calls
`WorkspaceClient().config.authenticate()` and receives a short-lived
OAuth token minted against the App's own SP. You only need the secret
for workloads you run *outside* the App container — simulators, the
synced-tables apply script, the MLflow training job.

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
| Simulator: `PermissionDenied: missing MODIFY on table bz_*` | GRANT block in step *Service Principal setup* wasn't run with the right UUID — display name and numeric SP id both silently do the wrong thing. |
| Simulator: `UNAUTHENTICATED` / `invalid_client` from `oidc/v1/token` | Wrong secret for the SP flavor — Databricks-managed secrets live in Account Console, Entra-managed secrets live in Azure Portal. Make sure you pasted the matching one into `DATABRICKS_CLIENT_SECRET`. |
| Azure SP works for the workspace REST API but fails on Zerobus | Zerobus gRPC needs the token audience `<workspace>`; ensure `DATABRICKS_HOST` is set — the SDK derives the audience from it. |
| `databricks: command not found` | Install the CLI (see Prerequisites) and re-authenticate. |
