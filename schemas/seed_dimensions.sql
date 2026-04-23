-- Seed SKU + supplier dimensions used by simulators and scoring.

MERGE INTO ${catalog}.${schema}.dim_sku t
USING (
  SELECT * FROM VALUES
    ('SKU-001','Steel Rod 12mm',   'steel',  800, 200, 2000, 4.20),
    ('SKU-002','Copper Wire 2.5mm','copper', 600, 150, 1800, 7.50),
    ('SKU-003','Plastic Pellets',  'oil',   1200, 300, 3000, 1.10),
    ('SKU-004','Wheat Flour 25kg', 'wheat',  900, 200, 2200, 9.80),
    ('SKU-005','Aluminum Sheet',   'copper', 500, 100, 1500, 11.00),
    ('SKU-006','Oil Filter',       'oil',    400, 100, 1000, 3.20),
    ('SKU-007','Steel Beam',       'steel',  300,  80, 1200, 48.00),
    ('SKU-008','Copper Pipe',      'copper', 450, 100, 1400, 14.50)
  AS v(sku, sku_name, commodity, reorder_point, safety_stock, target_stock, unit_cost_hint)
) s
ON t.sku = s.sku
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO ${catalog}.${schema}.dim_supplier t
USING (
  SELECT * FROM VALUES
    ('SUP-01','Acme Metals',       'US', 'gold',   0.96, 0.92),
    ('SUP-02','Bolt Foundry',      'DE', 'gold',   0.94, 0.95),
    ('SUP-03','Continental Alloys','PL', 'silver', 0.88, 0.87),
    ('SUP-04','DeltaWare Ltd',     'UK', 'silver', 0.90, 0.89),
    ('SUP-05','Eastgate Supply',   'CN', 'bronze', 0.78, 0.80),
    ('SUP-06','Fjord Materials',   'NO', 'gold',   0.97, 0.93),
    ('SUP-07','Global Copperworks','CL', 'silver', 0.86, 0.85),
    ('SUP-08','Helix Chemicals',   'NL', 'gold',   0.95, 0.91)
  AS v(supplier_id, supplier_name, country, tier, on_time_pct, quality_score)
) s
ON t.supplier_id = s.supplier_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;
