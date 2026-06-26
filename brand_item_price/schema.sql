CREATE TABLE IF NOT EXISTS brand (
  id INTEGER PRIMARY KEY,
  brand_code TEXT NOT NULL UNIQUE,
  brand_name TEXT NOT NULL,
  status TEXT DEFAULT 'ENABLED',
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS brand_item (
  id INTEGER PRIMARY KEY,
  brand_id INTEGER NOT NULL,
  item_code TEXT,
  item_name TEXT,
  series TEXT,
  item_type TEXT,
  model TEXT,
  factory_model TEXT,
  source_brand_code TEXT,
  spec TEXT,
  key_features TEXT,
  properties TEXT,
  packing_qty INTEGER,
  min_order_qty INTEGER,
  accessories TEXT,
  unit TEXT,
  attachment TEXT,
  created_at TEXT,
  FOREIGN KEY (brand_id) REFERENCES brand(id)
);

CREATE TABLE IF NOT EXISTS brand_current_price (
  id INTEGER PRIMARY KEY,
  brand_item_id INTEGER NOT NULL UNIQUE,
  supply_price REAL,
  retail_price REAL,
  discount_price REAL,
  currency TEXT DEFAULT 'CNY',
  sales_status TEXT DEFAULT 'ON_SALE',
  remark TEXT,
  ext_json TEXT,
  updated_at TEXT,
  FOREIGN KEY (brand_item_id) REFERENCES brand_item(id)
);

CREATE INDEX IF NOT EXISTS idx_brand_item_code ON brand_item(item_code);
CREATE INDEX IF NOT EXISTS idx_brand_item_name ON brand_item(item_name);
CREATE INDEX IF NOT EXISTS idx_brand_item_model ON brand_item(model);
CREATE INDEX IF NOT EXISTS idx_brand_item_factory_model ON brand_item(factory_model);
