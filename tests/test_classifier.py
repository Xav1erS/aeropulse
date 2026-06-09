from __future__ import annotations

from datetime import date
from unittest import TestCase

from source_audit.classifier import classify_page
from source_audit.models import AuditConfig, ExtractedPage, FetchResult, SourceConfig


class ClassifierTest(TestCase):
    def setUp(self) -> None:
        self.config = AuditConfig(
            cities=["济南"],
            keywords=["无人机", "低慢小", "机场净空"],
            start_date=date(2025, 1, 1),
            end_date=date(2026, 12, 31),
            sources=[SourceConfig(name="济南市人民政府", url="https://example.com/", priority="P0")],
            current_date=date(2026, 6, 7),
        )

    def test_formal_temporary_notice_is_a(self) -> None:
        page = self._page("关于赛事期间临时禁飞的通告", "赛事期间严禁无人机等低慢小飞行物升空。")
        result = classify_page(page, self._fetch(priority="P0"), self.config)
        self.assertTrue(result.relevant)
        self.assertEqual(result.category, "A")
        self.assertGreaterEqual(result.confidence, 0.8)

    def test_activity_notice_is_b(self) -> None:
        page = self._page("景区游客须知", "景区活动期间禁止携带和使用无人机。")
        result = classify_page(page, self._fetch(priority="P1"), self.config)
        self.assertEqual(result.category, "B")

    def test_airport_clearance_rule_is_c(self) -> None:
        page = self._page("机场净空保护规定", "机场净空保护区内飞行需备案并按规定申报空域。")
        result = classify_page(page, self._fetch(priority="P0"), self.config)
        self.assertEqual(result.category, "C")

    def test_unrelated_page_is_not_relevant(self) -> None:
        page = self._page("天气提醒", "今天有雨，请注意出行安全。")
        result = classify_page(page, self._fetch(priority="P0"), self.config)
        self.assertFalse(result.relevant)
        self.assertEqual(result.category, "E")

    def test_registration_rule_is_current_even_after_publish_date(self) -> None:
        page = self._page(
            "关于加强民用无人驾驶航空器登记备案和安全管理的通告",
            "民用无人机所有者应当依法进行实名登记，起飞前需查询适飞空域和管制空域情况。",
        )
        result = classify_page(page, self._fetch(priority="P0"), self.config)
        self.assertEqual(result.category, "C")
        self.assertNotIn("临时管控", result.scenes)
        self.assertEqual(result.validity, "当前/未来有效")

    def test_long_term_low_slow_notice_is_c_not_a(self) -> None:
        page = self._page(
            "济南市关于加强民用无人机等低慢小航空器安全管理的通告",
            "根据通用航空飞行管制条例，本通告自2022年3月1日起施行，有效期至2027年2月28日。民用无人机飞行活动应实名登记，在管制空域内须申请。",
        )
        result = classify_page(page, self._fetch(priority="P0"), self.config)
        self.assertEqual(result.category, "C")

    def test_balloon_management_notice_is_c_not_a(self) -> None:
        page = self._page(
            "济南市气象局关于规范升放气球活动的通告",
            "根据通用航空飞行管制条例和升放气球管理办法，升放气球活动应当经许可后施放。",
        )
        result = classify_page(page, self._fetch(priority="P0"), self.config)
        self.assertEqual(result.category, "C")

    def test_reposted_formal_temporary_notice_can_be_a(self) -> None:
        page = self._page(
            "关于在赛事期间加强对低慢小航空器及空飘物重点管控的通告",
            "赛事期间未经批准严禁无人机、孔明灯等低慢小航空器起飞。荣成马拉松组委会 荣成市公安局",
        )
        result = classify_page(page, self._fetch(priority="P2"), self.config)
        self.assertEqual(result.category, "A")
        self.assertGreaterEqual(result.confidence, 0.7)

    def test_exam_reminder_with_flight_stop_is_b(self) -> None:
        page = self._page(
            "2026年夏季高考致广大市民朋友的倡议书",
            "考试期间请主动停止在考点周边500米范围内的无人机飞行、航拍活动。",
        )
        result = classify_page(page, self._fetch(priority="P2"), self.config)
        self.assertEqual(result.category, "B")

    def _page(self, title: str, body: str) -> ExtractedPage:
        return ExtractedPage(
            raw_url="https://example.com/a",
            final_url="https://example.com/a",
            title=title,
            published_at=date(2026, 6, 1),
            body_text=body,
            summary=body,
            date_mentions=[date(2026, 6, 10)],
        )

    def _fetch(self, priority: str) -> FetchResult:
        return FetchResult(
            raw_url="https://example.com/a",
            final_url="https://example.com/a",
            source_name="测试来源",
            source_priority=priority,
            source_city="济南",
            fetched_at="2026-06-07T00:00:00Z",
            status_code=200,
            content_type="text/html",
            html="",
        )
