CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, source_name TEXT, sha256 TEXT, status TEXT, warnings TEXT, dpi INTEGER,
  created_at TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS jobs_sha ON jobs(sha256);
CREATE TABLE IF NOT EXISTS cards(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, idx INTEGER, status TEXT, reasons TEXT,
  corners TEXT, center_x_mm REAL, center_y_mm REAL, long_mm REAL, short_mm REAL, angle_deg REAL,
  image_path TEXT, width_px INTEGER, height_px INTEGER);
CREATE INDEX IF NOT EXISTS cards_job ON cards(job_id);
CREATE TABLE IF NOT EXISTS sheets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, pdf_path TEXT, status TEXT, created_at TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS sheet_cards(
  sheet_id INTEGER, card_id INTEGER, slot INTEGER, PRIMARY KEY(sheet_id, slot));
