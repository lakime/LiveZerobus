# CI/CD with GitHub Actions

LiveZerobus ships with four GitHub workflows under `.github/workflows/`. Together
they cover the full lifecycle: PR validation, app + pipeline deploys on merge,
weekly model retraining, and on-demand UC bootstrapping.

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | every PR + push | Frontend type-check + build, backend ruff lint. No Databricks auth. |
| `deploy.yml` | push to `main`, manual | Build SPA → sync `pipelines/` → sync `backend/` → `databricks apps deploy livezerobus`. Optional: trigger pipeline run. |
| `train-model.yml` | weekly cron, manual, push to `ml/**` | `python ml/train_supplier_model.py` — registers a new MLflow version and promotes `@prod`. |
| `bootstrap.yml` | manual only | One-shot UC catalog + schema + Bronze tables + dim seed via `scripts/setup_unity_catalog.py`. Idempotent. |

## 1. One-time service-principal setup

CI/CD authenticates as a dedicated Databricks service principal (let's call
it `livezerobus-cicd`) using OAuth machine-to-machine (M2M) credentials.
Don't reuse your personal credentials.

```bash
# 1. Create the SP (once, by an admin)
databricks service-principals create --display-name livezerobus-cicd

# 2. Mint an OAuth secret for it (shown ONCE; copy immediately)
databricks service-principals create-secret \
  --service-principal-id <id-from-step-1>

# 3. Grant the SP what it needs:
#    - workspace access to /Workspace/Users/<sp>/livezerobus  (auto-created)
#    - app management on `livezerobus`
#    - SELECT/MODIFY on the livezerobus.procurement schema
#    - CAN_USE on the SQL Warehouse used by bootstrap
#    - CAN_QUERY on the Foundation Model serving endpoint (only if you also
#      want CI to smoke-test agent endpoints — not needed for plain deploy)
```

OAuth M2M tokens are minted on demand by the SDK from the (client_id,
client_secret) pair, so there's no expiry to chase — rotate the secret
itself when policy demands.

**Lakebase OAuth role** (only if CI ever talks directly to Lakebase — usually
not needed; the deployed app uses its own SP for that):

```sql
-- in Lakebase SQL editor as superuser, against project myzerobus / branch production
CREATE EXTENSION IF NOT EXISTS databricks_auth;
SELECT databricks_create_role(
  role_name => '<cicd-sp-uuid>',
  identity_type => 'SERVICE_PRINCIPAL'
);
GRANT USAGE  ON SCHEMA liveoltp TO "<cicd-sp-uuid>";
GRANT SELECT ON ALL TABLES IN SCHEMA liveoltp TO "<cicd-sp-uuid>";
```

## 2. GitHub repository configuration

In **Repository → Settings → Secrets and variables → Actions**:

### Secrets (encrypted)

| Name | Value |
|---|---|
| `DATABRICKS_HOST` | `https://<workspace>.azuredatabricks.net` |
| `DATABRICKS_CLIENT_ID` | service principal application id (UUID from step 1) |
| `DATABRICKS_CLIENT_SECRET` | OAuth secret minted in step 2 |

### Variables (plaintext, repo-wide)

| Name | Value | Used by |
|---|---|---|
| `DATABRICKS_WORKSPACE_PATH` | e.g. `/Workspace/Users/livezerobus-cicd@example.com/livezerobus` | `deploy.yml` (auto-derives from `current-user me` if unset) |
| `DATABRICKS_PIPELINE_ID` | e.g. `068ab7c4-...` | `deploy.yml` (only the optional pipeline-trigger step) |
| `DATABRICKS_WAREHOUSE_ID` | the SQL Warehouse ID `setup_unity_catalog.py` uses | `bootstrap.yml` |

> Use **variables**, not secrets, for the path / ids — they're not sensitive,
> and variables show up in workflow logs (helpful for debugging).

## 3. Workflow walkthroughs

### 3.1 `ci.yml` — pull-request gate

Fires on every PR and every branch push (except docs-only changes). No
credentials needed.

- **Frontend job**: `npm ci → npx tsc --noEmit → npm run build`. Catches type
  errors and broken JSX *before* deploy. Also strips stale `.js` siblings of
  `.tsx` files (the trap we hit during dev).
- **Backend job**: `ruff check` over backend, simulators, pipelines, ml,
  scripts, lakebase_sync. Currently lenient (`|| true` on the lint command);
  remove that suffix to enforce.

### 3.2 `deploy.yml` — push to `main` deploys everything

Triggered automatically on any push to `main` that touches `backend/`,
`frontend/`, `pipelines/`, or the deploy scripts/workflow. Also available as
a **Run workflow** button for manual one-shot deploys from any branch.

Steps:

1. **Auth check** — `databricks current-user me` confirms the SP can talk
2. **Resolve workspace path** — uses repo variable, else derives from
   `current-user me`
3. **Build frontend** — `./scripts/build_frontend.sh` (which also strips
   stale `.js` siblings)
4. **Sync `pipelines/` to workspace** — `databricks sync --full`
5. **Sync `backend/` to workspace** — same, into the app's source-code path
6. **`databricks apps deploy livezerobus`** — Apps redeploys from the
   workspace path
7. **Tail logs for 25 s** so the run summary shows the boot output

**Optional step 8** (manual dispatch only, opt-in checkbox):
`databricks pipelines start-update <PIPELINE_ID>` — refreshes the Lakeflow
pipeline after a code change.

Concurrency group: `deploy-${{ github.ref }}` — stops two pushes to `main`
from racing each other.

### 3.3 `train-model.yml` — weekly model refresh

Runs on a Monday-02:00-UTC cron, plus manual dispatch and on any push to
`ml/**`. Installs sklearn + mlflow + numpy + pandas + databricks-sdk on the
runner, then `python ml/train_supplier_model.py`:

- logs an MLflow run under `/Shared/livezerobus.procurement.supplier_scoring`
- registers a new version of `livezerobus.procurement.supplier_scoring_model`
- promotes that version to `@prod` (controllable via the `promote_to_prod`
  input on manual dispatch)

The Lakeflow pipeline references the model as
`models:/...supplier_scoring_model@prod` — so on the next MV refresh
of `gd_supplier_leaderboard`, executors automatically pick up the new
artifact. No pipeline redeploy.

To roll back: dispatch this workflow manually with `promote_to_prod=false`,
then run a one-liner in Databricks:

```python
import mlflow
mlflow.set_registry_uri("databricks-uc")
mlflow.tracking.MlflowClient().set_registered_model_alias(
    "livezerobus.procurement.supplier_scoring_model", "prod", "<previous_version>"
)
```

### 3.4 `bootstrap.yml` — manual UC bootstrap

The one-time setup of the catalog, schema, Bronze tables, and dimension
seed. Manual only. Inputs:

- `catalog` (default `livezerobus`)
- `schema` (default `procurement`)
- `warehouse_id` — overrides the repo variable for one-off targeting

Idempotent: re-runs are safe. Useful when standing up a fresh dev workspace,
or when the dim tables drift and need a clean re-seed.

Note: the **Lakebase** schema (`liveoltp`) and the 5 synced tables are still
manual today (not in this workflow) because Lakebase Synced Table creation
isn't well-served by the SDK on the Projects API. Once `lakebase_sync/apply.py`
is rewritten for `w.postgres.*` (see ARCHITECTURE.md §13.3 / §14), wire that
into a fifth workflow `lakebase-bootstrap.yml` with the same shape.

## 4. Local equivalents

Each workflow has a local equivalent so you can debug without pushing:

| Workflow | Local equivalent |
|---|---|
| `ci.yml` (frontend) | `cd frontend && npm ci && npx tsc --noEmit && npm run build` |
| `ci.yml` (backend) | `pip install ruff && ruff check backend/app simulators pipelines ml scripts lakebase_sync` |
| `deploy.yml` | `./scripts/deploy_app.sh` (covers steps 3–7 from §3.2) |
| `train-model.yml` | `python ml/train_supplier_model.py` (with the same env vars set) |
| `bootstrap.yml` | `python scripts/setup_unity_catalog.py` |

## 5. Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `Authentication failed` / `401` in any workflow | `DATABRICKS_CLIENT_SECRET` rotated, revoked, or wrong host | Re-mint the SP secret (see §1 step 2), update the GitHub secret, double-check `DATABRICKS_HOST` includes `https://` |
| `Source code path must be a valid workspace path` in `deploy.yml` | Sync step skipped or path wrong | Check the `Resolve workspace path` step output and the `Sync backend/` step ran |
| Frontend job fails with stale dropdown UI | `.js` sibling shadowing `.tsx` (the trap from earlier) | CI strips them automatically; if it still happens, re-confirm `vite.config.ts` has `resolve.extensions: [".tsx", ".ts", ".jsx", ".js", ...]` |
| `train-model.yml` succeeds but `gd_supplier_leaderboard` still uses old scores | Spark executors cached the previous artifact | Right-click `gd_supplier_leaderboard` in pipeline UI → Full refresh selected. New executors load `@prod` fresh. |
| `bootstrap.yml` fails with `permission denied on schema` | SP lacks `USE CATALOG` / `CREATE SCHEMA` | Grant `USE CATALOG livezerobus` and `CREATE SCHEMA` on the catalog (Catalog Explorer → Permissions) |

## 6. What's NOT covered (and why)

Three things stayed off the CI/CD path on purpose:

1. **Simulator runs.** They're long-lived processes — wrong shape for a
   GitHub job that's expected to finish. Run them on a Databricks Job (or
   your laptop) instead. A future workflow could `databricks jobs run-submit`
   a simulator wrapper, but it's overkill for the demo.
2. **Lakebase synced-table creation.** Today this is UI-driven; once
   `lakebase_sync/apply.py` is rewritten for the Projects API it can become
   a workflow.
3. **FM serving endpoint creation.** It's already live; CI doesn't need to
   touch it. If you ever provision per-environment endpoints, add a workflow
   that calls `databricks serving-endpoints create`.
