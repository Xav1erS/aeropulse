from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from source_audit.recall_eval import load_golden_samples, run_recall_eval


class RecallEvalTest(TestCase):
    def test_recall_eval_counts_url_fuzzy_keyword_and_misses(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "audit.sqlite"
            golden_path = root / "golden.csv"
            report_path = root / "outputs" / "recall_eval_report.md"

            _write_db(db_path)
            _write_golden(golden_path)

            result = run_recall_eval(golden_path, db_path, report_path)

            self.assertEqual(result["total_golden_count"], 4)
            self.assertEqual(result["recalled_count"], 3)
            self.assertEqual(result["recall_rate"], 0.75)
            self.assertEqual(result["A_type_recall_rate"], 0.6667)
            self.assertEqual(result["P0/P1_recall_rate"], 0.6667)
            self.assertEqual(len(result["missed_samples"]), 1)
            self.assertEqual(result["missed_samples"][0]["id"], "g4")
            self.assertTrue(report_path.exists())
            self.assertIn("Recall Eval 报告", report_path.read_text(encoding="utf-8"))

    def test_missing_required_golden_column_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            golden_path = Path(tmp) / "bad.csv"
            with golden_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "title", "city", "url"])
                writer.writeheader()

            with self.assertRaises(ValueError):
                load_golden_samples(golden_path)


def _write_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE audit_pages (
                raw_url TEXT,
                final_url TEXT,
                canonical_url TEXT,
                master_url TEXT,
                title TEXT,
                city TEXT,
                category TEXT,
                source_priority TEXT,
                source_name TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO audit_pages(
                raw_url, final_url, canonical_url, master_url, title, city,
                category, source_priority, source_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "https://example.com/exact",
                    "https://example.com/exact",
                    "https://example.com/exact",
                    "",
                    "赛事期间无人机临时管控公告",
                    "济南",
                    "A",
                    "P0",
                    "测试政府",
                ),
                (
                    "https://example.com/fuzzy-db",
                    "https://example.com/fuzzy-db",
                    "https://example.com/fuzzy-db",
                    "",
                    "关于高考期间无人机临时管控通告",
                    "济南",
                    "A",
                    "P1",
                    "测试主办方",
                ),
                (
                    "https://example.com/keyword-db",
                    "https://example.com/keyword-db",
                    "https://example.com/keyword-db",
                    "",
                    "泰山景区游客须知：禁止使用无人机",
                    "泰安",
                    "B",
                    "P1",
                    "测试景区",
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def _write_golden(path: Path) -> None:
    rows = [
        {
            "id": "g1",
            "title": "赛事期间无人机临时管控公告",
            "city": "济南",
            "url": "https://example.com/exact",
            "type": "A",
            "source_level": "P0",
        },
        {
            "id": "g2",
            "title": "关于高考期间无人机临时管控的通告",
            "city": "济南",
            "url": "https://example.com/fuzzy-golden",
            "type": "A",
            "source_level": "P1",
        },
        {
            "id": "g3",
            "title": "泰山景区无人机禁飞提示",
            "city": "泰安",
            "url": "https://example.com/keyword-golden",
            "type": "B",
            "source_level": "P2",
        },
        {
            "id": "g4",
            "title": "烟台机场净空保护区备案提醒",
            "city": "烟台",
            "url": "https://example.com/missed",
            "type": "A",
            "source_level": "P0",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "title", "city", "url", "type", "source_level"])
        writer.writeheader()
        writer.writerows(rows)
