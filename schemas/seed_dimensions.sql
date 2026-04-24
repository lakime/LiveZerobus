-- Seed SKU + supplier dimensions used by simulators and scoring.
-- Parameterized variant — takes ${catalog}/${schema} via Spark widgets.

MERGE INTO ${catalog}.${schema}.dim_sku t
USING (
  SELECT * FROM VALUES
    ('SEED-LETT-BUT-01','Butterhead "Rex"',            'lettuce',     'Rex',              32, 200.0, 0.95, 0.35, 120.0, 40.0, 400.0, 0.35, true),
    ('SEED-LETT-RED-01','Red Oakleaf "Salanova"',      'lettuce',     'Salanova',         35, 180.0, 0.92, 0.32, 110.0, 35.0, 380.0, 0.42, true),
    ('SEED-LETT-ROM-01','Romaine "Dragoon"',           'lettuce',     'Dragoon',          28, 220.0, 0.94, 0.30, 130.0, 40.0, 420.0, 0.30, false),
    ('SEED-BAS-GEN-01', 'Genovese Basil "Nufar"',      'basil',       'Nufar',            25, 150.0, 0.90, 0.55,  90.0, 25.0, 300.0, 0.85, true),
    ('SEED-BAS-THA-01', 'Thai Basil "Siam Queen"',     'basil',       'Siam Queen',       27, 140.0, 0.88, 0.58,  85.0, 25.0, 280.0, 1.10, false),
    ('SEED-KALE-LAC-01','Lacinato Kale "Nero di Toscana"','kale',     'Nero di Toscana',  30, 170.0, 0.91, 0.40, 100.0, 30.0, 340.0, 0.48, true),
    ('SEED-KALE-RED-01','Red Russian Kale',            'kale',        'Red Russian',      30, 165.0, 0.89, 0.38, 100.0, 30.0, 330.0, 0.55, true),
    ('SEED-ARU-AST-01', 'Astro Arugula',               'arugula',     'Astro',            21, 160.0, 0.93, 0.45, 115.0, 35.0, 380.0, 0.38, true),
    ('SEED-SPIN-SPA-01','Space Spinach',               'spinach',     'Space',            26, 190.0, 0.87, 0.80, 140.0, 45.0, 460.0, 0.52, false),
    ('SEED-MG-RAD-01',  'Radish Microgreens "Rambo"',  'microgreens', 'Rambo',             8, 320.0, 0.96, 7.50, 350.0,100.0,1100.0, 0.18, true),
    ('SEED-MG-PEA-01',  'Pea Shoots "Speckled"',       'microgreens', 'Speckled Pea',     12, 450.0, 0.97,18.00, 700.0,200.0,2200.0, 0.12, true),
    ('SEED-MG-SUN-01',  'Sunflower Microgreens',       'microgreens', 'Black Oil',        10, 380.0, 0.95,14.00, 600.0,170.0,1900.0, 0.15, true),
    ('SEED-MG-BROC-01', 'Broccoli Microgreens',        'microgreens', 'Waltham 29',        9, 300.0, 0.94, 6.00, 300.0, 90.0,1000.0, 0.22, true),
    ('SEED-MG-AMA-01',  'Amaranth Microgreens "Red Garnet"','microgreens','Red Garnet',   11, 260.0, 0.91, 2.80, 200.0, 60.0, 700.0, 0.34, false),
    ('SEED-HERB-CIL-01','Cilantro "Calypso"',          'herb',        'Calypso',          30, 145.0, 0.85, 3.60, 220.0, 65.0, 720.0, 0.58, true),
    ('SEED-HERB-PAR-01','Parsley "Giant of Italy"',    'herb',        'Giant of Italy',   35, 130.0, 0.82, 2.50, 180.0, 55.0, 600.0, 0.44, true),
    ('SEED-HERB-DIL-01','Dill "Bouquet"',              'herb',        'Bouquet',          35, 120.0, 0.83, 2.20, 170.0, 50.0, 560.0, 0.36, false),
    ('SEED-BOK-SHA-01', 'Shanghai Bok Choy',           'asian-green', 'Shanghai',         30, 210.0, 0.93, 0.40, 120.0, 35.0, 400.0, 0.40, true),
    ('SEED-MUST-WAS-01','Wasabi Mustard',              'asian-green', 'Wasabina',         22, 175.0, 0.90, 0.70, 110.0, 30.0, 360.0, 0.68, false),
    ('SEED-TAT-RED-01', 'Red Tatsoi',                  'asian-green', 'Rosie',            25, 180.0, 0.89, 0.65, 115.0, 30.0, 380.0, 0.62, true)
  AS v(sku, sku_name, crop_type, variety, days_to_harvest, tray_yield_g, germination_rate,
       seed_per_tray_g, reorder_point_g, safety_stock_g, target_stock_g, unit_cost_hint, organic_preferred)
) s
ON t.sku = s.sku
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO ${catalog}.${schema}.dim_supplier t
USING (
  SELECT * FROM VALUES
    ('SUP-JOHNNY',   'Johnny''s Selected Seeds',  'US', 'preferred', 0.97, 0.95, true,  'orders@johnnyseeds.demo',    'Maine-based. Strong on lettuce + herbs.'),
    ('SUP-HIGHMOW',  'High Mowing Organic Seeds', 'US', 'preferred', 0.96, 0.96, true,  'sales@highmowing.demo',      '100% certified organic.'),
    ('SUP-TRUELEAF', 'True Leaf Market',          'US', 'qualified', 0.91, 0.89, false, 'wholesale@trueleaf.demo',    'Bulk microgreens specialist.'),
    ('SUP-KITAZAWA', 'Kitazawa Seed Co',          'US', 'qualified', 0.92, 0.91, false, 'orders@kitazawa.demo',       'Asian greens leader.'),
    ('SUP-RIJK',     'Rijk Zwaan',                'NL', 'preferred', 0.98, 0.97, false, 'accounts@rijkzwaan.demo',    'Premium greenhouse breeder.'),
    ('SUP-ENZA',     'Enza Zaden',                'NL', 'preferred', 0.95, 0.96, true,  'orders@enzazaden.demo',      'Vertical-farm focus.'),
    ('SUP-VITALIS',  'Vitalis Organic Seeds',     'NL', 'qualified', 0.93, 0.94, true,  'eu@vitalis.demo',            'Organic arm of Enza.'),
    ('SUP-WESTCOAST','West Coast Seeds',          'CA', 'qualified', 0.89, 0.88, true,  'sales@westcoast.demo',       'Pacific NW regional.'),
    ('SUP-KOPPERT',  'Koppert Cress',             'NL', 'probation', 0.82, 0.90, false, 'b2b@koppertcress.demo',      'Specialty microgreens, new partner.'),
    ('SUP-VILMORIN', 'Vilmorin',                  'FR', 'qualified', 0.90, 0.92, false, 'international@vilmorin.demo','Long-standing French breeder.')
  AS v(supplier_id, supplier_name, country, tier, on_time_pct, quality_score, organic_cert, email, notes)
) s
ON t.supplier_id = s.supplier_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;
