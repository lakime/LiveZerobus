-- Reliable refresh of the SAP BDC Delta Sharing catalog.
-- Run this any time the BDC server's metadata or share state changes,
-- or when UC's view of the catalog gets out of sync.
--
-- Why each step matters:
--   DROP + CREATE — forces UC to discard its cached snapshot
--   SHOW SCHEMAS / TABLES — materialises schema and table entries in UC
--   DESCRIBE TABLE x15 — forces UC to fetch column metadata for each table
--                        (without this, Catalog Explorer shows
--                        "No columns available" until you SELECT from a table)
--
-- Usage:  databricks sql query --warehouse-id 6a1fb3b32b00f1cd -f scripts/refresh_sapsofts_catalog.sql
-- Or run interactively in the Databricks SQL editor.

DROP CATALOG IF EXISTS sapsofts CASCADE;
CREATE CATALOG sapsofts USING SHARE `sapsofts`.`sap-procurement`;

SHOW SCHEMAS IN sapsofts;
SHOW TABLES IN sapsofts.procurement;

-- Warm column metadata for each table.
DESCRIBE TABLE sapsofts.procurement.bkpf;
DESCRIBE TABLE sapsofts.procurement.eban;
DESCRIBE TABLE sapsofts.procurement.ekbe;
DESCRIBE TABLE sapsofts.procurement.eket;
DESCRIBE TABLE sapsofts.procurement.ekko;
DESCRIBE TABLE sapsofts.procurement.ekpo;
DESCRIBE TABLE sapsofts.procurement.lfa1;
DESCRIBE TABLE sapsofts.procurement.mara;
DESCRIBE TABLE sapsofts.procurement.mkpf;
DESCRIBE TABLE sapsofts.procurement.mseg;
DESCRIBE TABLE sapsofts.procurement.rbkp;
DESCRIBE TABLE sapsofts.procurement.t001;
DESCRIBE TABLE sapsofts.procurement.t001w;
DESCRIBE TABLE sapsofts.procurement.t023;
DESCRIBE TABLE sapsofts.procurement.t024;

-- Smoke test that everything is now queryable.
SELECT 'ekko' AS table_name, count(*) AS rows FROM sapsofts.procurement.ekko
UNION ALL SELECT 'lfa1', count(*) FROM sapsofts.procurement.lfa1
UNION ALL SELECT 'mara', count(*) FROM sapsofts.procurement.mara
UNION ALL SELECT 'ekpo', count(*) FROM sapsofts.procurement.ekpo;
