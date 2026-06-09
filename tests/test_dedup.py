from __future__ import annotations

from datetime import date
from unittest import TestCase

from source_audit.dedup import assign_dedupe_keys
from source_audit.models import AuditRecord


class DedupTest(TestCase):
    def test_similar_same_day_titles_are_duplicates(self) -> None:
        records = [
            self._record("https://a.example/notice", "关于高考期间无人机临时管控的通告"),
            self._record("https://b.example/news", "关于高考期间无人机临时管控通告"),
        ]
        assign_dedupe_keys(records)

        self.assertFalse(records[0].is_duplicate)
        self.assertTrue(records[1].is_duplicate)
        self.assertEqual(records[0].dedupe_key, records[1].dedupe_key)

    def _record(self, url: str, title: str) -> AuditRecord:
        return AuditRecord(
            run_id="test",
            raw_url=url,
            final_url=url,
            canonical_url=url,
            source_name="测试来源",
            source_priority="P0",
            city="济南",
            fetched_at="2026-06-07T00:00:00Z",
            status_code=200,
            content_type="text/html",
            title=title,
            published_at=date(2026, 6, 1),
            summary="高考期间无人机临时管控。",
            body_text="高考期间无人机临时管控。",
            date_mentions=[date(2026, 6, 7)],
            relevant=True,
            category="A",
            confidence=0.9,
            reason="测试",
            scenes=["无人机", "临时管控"],
            evidence_snippets=["无人机临时管控"],
            mappability="半自动地图化",
            validity="当前/未来有效",
            content_hash="",
            within_time_range=True,
        )

