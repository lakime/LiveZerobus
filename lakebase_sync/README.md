# Lakebase sync (Delta → Postgres)

This folder contains everything needed to land the Gold Delta tables
into the Lakebase Postgres instance `databricks_postgres` (branch
`production`) where the Databricks App can read them with millisecond
latency over a plain Postgres connection.

Two things happen:

1. **Postgres DDL** — `../schemas/lakebase_schema.sql` creates `live.*`
   tables + indexes.
2. **Synced Tables** — one per entry in `synced_tables.yml`. Databricks
   keeps each Postgres table continuously synced from the source Delta
   table (`CONTINUOUS` policy) or refreshed on a schedule (`SNAPSHOT`).

`apply.py` is idempotent: re-running reconciles spec changes (e.g. you
add a new primary-key column or change scheduling).

To run:

```bash
databricks bundle run lakebase_sync -t dev
```

To verify:

```bash
databricks database execute-query \
  --instance-name databricks_postgres \
  --branch production \
  --query "SELECT count(*) FROM live.procurement_recommendations"
```
