from __future__ import annotations

from datetime import date
from unittest import TestCase

from source_audit.models import AuditRecord
from source_audit.reporting import compute_stats


class ReportingTest(TestCase):
    def test_timeliness_stats_split_historical_temporary_controls(self) -> None:
        records = [
            self._record("A", "历史样本", "历史临时管控"),
            self._record("A", "当前/未来有效", "当前临时管控"),
            self._record("B", "当前/未来有效", "当前活动提示"),
            self._record("C", "当前/未来有效", "长期规则"),
        ]

        stats = compute_stats(records)

        self.assertEqual(stats["relevant_page_count"], 4)
        self.assertEqual(stats["current_future_count"], 3)
        self.assertEqual(stats["time_sensitive_count"], 3)
        self.assertEqual(stats["current_future_time_sensitive_count"], 2)
        self.assertEqual(stats["historical_time_sensitive_count"], 1)
        self.assertEqual(stats["current_future_category_counts"]["A"], 1)
        self.assertEqual(stats["current_future_category_counts"]["C"], 1)

    def _record(self, category: str, validity: str, title: str) -> AuditRecord:
        return AuditRecord(
            run_id="run",
            raw_url=f"https://example.com/{title}",
            final_url=f"https://example.com/{title}",
            canonical_url=f"https://example.com/{title}",
            source_name="测试来源",
            source_priority="P0",
            city="济南",
            fetched_at="2026-06-07T00:00:00Z",
            status_code=200,
            content_type="text/html",
            title=title,
            published_at=date(2026, 1, 1),
            summary=title,
            body_text=title,
            date_mentions=[],
            relevant=True,
            category=category,
            confidence=0.8,
            reason="测试",
            scenes=["临时管控"] if category in {"A", "B"} else ["适飞空域"],
            evidence_snippets=[title],
            mappability="半自动地图化",
            validity=validity,
            content_hash=title,
            within_time_range=True,
        )
