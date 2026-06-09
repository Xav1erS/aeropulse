from __future__ import annotations

from datetime import date
from unittest import TestCase

from source_audit.classifier import classify_page
from source_audit.crawler import extract_candidate_links
from source_audit.models import AuditConfig, ExtractedPage, FetchResult, SourceConfig
from source_audit.ocr import extract_image_urls


class WechatOcrTest(TestCase):
    def setUp(self) -> None:
        self.config = AuditConfig(
            cities=["威海"],
            keywords=["无人机", "低慢小", "临时管控"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            sources=[SourceConfig(name="威海公开入口", url="https://www.weihai.gov.cn/", priority="P0")],
            current_date=date(2026, 6, 7),
        )

    def test_wechat_links_are_followed_only_when_enabled(self) -> None:
        html = """
        <html><body>
          <a href="https://mp.weixin.qq.com/s/example">微信公众号公告</a>
        </body></html>
        """

        disabled = extract_candidate_links(html, "https://www.weihai.gov.cn/a.html", "https://www.weihai.gov.cn/", self.config)
        self.config.follow_external_wechat_links = True
        enabled = extract_candidate_links(html, "https://www.weihai.gov.cn/a.html", "https://www.weihai.gov.cn/", self.config)

        self.assertEqual(disabled, [])
        self.assertEqual(enabled, ["https://mp.weixin.qq.com/s/example"])

    def test_wechat_plain_text_urls_are_discovered_when_enabled(self) -> None:
        html = """
        <html><body>
          参考资料：https://mp.weixin.qq.com/s/rzCMFWsvorEy75GRv6z5QA.
        </body></html>
        """

        self.config.follow_external_wechat_links = True
        links = extract_candidate_links(html, "https://example.com/a.html", "https://example.com/", self.config)

        self.assertEqual(links, ["https://mp.weixin.qq.com/s/rzCMFWsvorEy75GRv6z5QA"])

    def test_extract_wechat_image_urls_prefers_data_src(self) -> None:
        html = """
        <html><body>
          <img data-src="//mmbiz.qpic.cn/mmbiz_png/a/0?wx_fmt=png" src="placeholder.gif">
          <img src="/local/notice.jpg">
          <img src="data:image/png;base64,abc">
        </body></html>
        """

        urls = extract_image_urls(html, "https://mp.weixin.qq.com/s/example")

        self.assertEqual(
            urls,
            [
                "https://mmbiz.qpic.cn/mmbiz_png/a/0?wx_fmt=png",
                "https://mp.weixin.qq.com/local/notice.jpg",
            ],
        )

    def test_ocr_text_in_body_participates_in_classification(self) -> None:
        page = ExtractedPage(
            raw_url="https://mp.weixin.qq.com/s/example",
            final_url="https://mp.weixin.qq.com/s/example",
            title="公众号图片公告",
            published_at=date(2026, 6, 1),
            body_text="[图片OCR]\n关于高考期间对无人机等低慢小航空器实施临时管控的通告",
            summary="关于高考期间对无人机等低慢小航空器实施临时管控的通告",
            date_mentions=[date(2026, 6, 7)],
        )
        result = classify_page(page, self._fetch(priority="P0"), self.config)

        self.assertTrue(result.relevant)
        self.assertEqual(result.category, "A")

    def _fetch(self, priority: str = "P2") -> FetchResult:
        return FetchResult(
            raw_url="https://mp.weixin.qq.com/s/example",
            final_url="https://mp.weixin.qq.com/s/example",
            source_name="微信公众号",
            source_priority=priority,
            source_city="威海",
            fetched_at="2026-06-07T00:00:00Z",
            status_code=200,
            content_type="text/html",
            html="",
        )
