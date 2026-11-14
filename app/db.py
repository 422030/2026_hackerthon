"""SQLite 연결과 스키마. ORM 을 쓰지 않는다."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

DDL = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY,
  filename TEXT,
  status TEXT,
  stage TEXT,
  pages_total INTEGER DEFAULT 0,
  pages_done INTEGER DEFAULT 0,
  mode TEXT,
  doc_json TEXT,
  degraded_json TEXT,
  created_at TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS pages(
  job_id TEXT,
  page_no INTEGER,
  sha1 TEXT,
  image_path TEXT,
  ocr_json TEXT,
  analysis_json TEXT,
  source TEXT,
  elapsed_ms INTEGER,
  PRIMARY KEY(job_id, page_no)
);

CREATE TABLE IF NOT EXISTS llm_cache(
  key TEXT PRIMARY KEY,
  task TEXT NOT NULL DEFAULT 'page_analysis',
  content_sig TEXT,
  prompt_version TEXT,
  model_id TEXT,
  analysis_json TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS eval_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT,
  config TEXT,
  report_json TEXT
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(DDL)
