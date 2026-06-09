from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import config_to_dict
from .models import AuditConfig, AuditRecord
from .utils import date_to_iso, ensure_dir, utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    raw_url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_priority TEXT NOT NULL,
    city TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    summary TEXT NOT NULL,
    body_text TEXT NOT NULL,
    date_mentions_json TEXT NOT NULL,
    relevant INTEGER NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL,
    scenes_json TEXT NOT NULL,
    evidence_snippets_json TEXT NOT NULL,
    mappability TEXT NOT NULL,
    validity TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    within_time_range INTEGER NOT NULL,
    dedupe_key TEXT NOT NULL,
    is_duplicate INTEGER NOT NULL,
    master_url TEXT NOT NULL,
    error TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES audit_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_pages_run_id ON audit_pages(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_pages_category ON audit_pages(category);
CREATE INDEX IF NOT EXISTS idx_audit_pages_dedupe_key ON audit_pages(dedupe_key);
"""


def save_run(database_path: str, run_id: str, config: AuditConfig, records: list[AuditRecord]) -> None:
    path = Path(database_path)
    ensure_dir(path.parent)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR REPLACE INTO audit_runs(run_id, created_at, config_json) VALUES (?, ?, ?)",
            (run_id, utc_now_iso(), json.dumps(config_to_dict(config), ensure_ascii=False)),
        )
        connection.executemany(
            """
            INSERT INTO audit_pages(
                run_id, raw_url, final_url, canonical_url, source_name, source_priority, city,
                fetched_at, status_code, content_type, title, published_at, summary, body_text,
                date_mentions_json, relevant, category, confidence, reason, scenes_json,
                evidence_snippets_json, mappability, validity, content_hash, within_time_range,
                dedupe_key, is_duplicate, master_url, error
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [_record_to_row(record) for record in records],
        )


def _record_to_row(record: AuditRecord) -> tuple[object, ...]:
    return (
        record.run_id,
        record.raw_url,
        record.final_url,
        record.canonical_url,
        record.source_name,
        record.source_priority,
        record.city,
        record.fetched_at,
        record.status_code,
        record.content_type,
        record.title,
        date_to_iso(record.published_at),
        record.summary,
        record.body_text,
        json.dumps([date_to_iso(value) for value in record.date_mentions], ensure_ascii=False),
        int(record.relevant),
        record.category,
        record.confidence,
        record.reason,
        json.dumps(record.scenes, ensure_ascii=False),
        json.dumps(record.evidence_snippets, ensure_ascii=False),
        record.mappability,
        record.validity,
        record.content_hash,
        int(record.within_time_range),
        record.dedupe_key,
        int(record.is_duplicate),
        record.master_url,
        record.error,
    )

