from __future__ import annotations

import re
import time
from collections import deque
from urllib import robotparser
from urllib.parse import unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .models import AuditConfig, FetchResult, SourceConfig
from .utils import (
    canonicalize_url,
    looks_like_binary_url,
    looks_like_login_url,
    is_public_wechat_article_url,
    normalize_for_match,
    same_site,
    utc_now_iso,
)


GENERIC_LINK_TERMS = ["公告", "通告", "通知", "动态", "新闻", "资讯", "活动", "赛事", "考试", "景区", "机场", "无人机"]
WECHAT_TEXT_URL_PATTERN = re.compile(r"https://mp\.weixin\.qq\.com/s(?:/|\?)[^\s\"'<>]+")
TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？)]）】》"


class PoliteHttpClient:
    def __init__(self, config: AuditConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})
        self.last_hit_by_host: dict[str, float] = {}
        self.robots_by_site: dict[str, robotparser.RobotFileParser | None] = {}

    def fetch(self, url: str, source: SourceConfig, depth: int) -> FetchResult:
        fetched_at = utc_now_iso()
        if looks_like_login_url(url):
            return self._error_result(url, source, depth, fetched_at, "跳过疑似登录或用户中心页面。")
        if looks_like_binary_url(url):
            return self._error_result(url, source, depth, fetched_at, "跳过非 HTML 附件 URL。")
        if self.config.respect_robots_txt and not self._allowed_by_robots(url):
            return self._error_result(url, source, depth, fetched_at, "robots.txt 不允许抓取。")

        self._wait(url)
        try:
            response = self.session.get(url, timeout=self.config.timeout_seconds, allow_redirects=True)
            _fix_response_encoding(response)
            content_type = response.headers.get("content-type", "")
            html = response.text if _looks_like_html(content_type, response.text) else ""
            return FetchResult(
                raw_url=url,
                final_url=response.url,
                source_name=source.name,
                source_priority=source.priority,
                source_city=source.city,
                fetched_at=fetched_at,
                status_code=response.status_code,
                content_type=content_type,
                html=html,
                depth=depth,
                error="" if html else "响应不是可抽取的 HTML。",
            )
        except requests.RequestException as exc:
            return self._error_result(url, source, depth, fetched_at, f"请求失败：{exc}")

    def _wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        last_hit = self.last_hit_by_host.get(host)
        now = time.monotonic()
        if last_hit is not None:
            wait_seconds = self.config.polite_delay_seconds - (now - last_hit)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        self.last_hit_by_host[host] = time.monotonic()

    def _allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        site = f"{parts.scheme}://{parts.netloc}"
        if site not in self.robots_by_site:
            parser = robotparser.RobotFileParser()
            parser.set_url(urljoin(site, "/robots.txt"))
            try:
                parser.read()
            except Exception:
                self.robots_by_site[site] = None
            else:
                self.robots_by_site[site] = parser
        parser = self.robots_by_site[site]
        if parser is None:
            return True
        return parser.can_fetch(self.config.user_agent, url)

    def _error_result(self, url: str, source: SourceConfig, depth: int, fetched_at: str, error: str) -> FetchResult:
        return FetchResult(
            raw_url=url,
            final_url=url,
            source_name=source.name,
            source_priority=source.priority,
            source_city=source.city,
            fetched_at=fetched_at,
            status_code=0,
            content_type="",
            html="",
            depth=depth,
            error=error,
        )


def crawl_sources(config: AuditConfig) -> list[FetchResult]:
    client = PoliteHttpClient(config)
    results: list[FetchResult] = []

    for source in config.sources:
        max_pages = source.max_pages or config.max_pages_per_source
        queue: deque[tuple[str, int]] = deque([(source.url, 0)])
        seen: set[str] = set()

        while queue and _count_source_results(results, source) < max_pages:
            url, depth = queue.popleft()
            canonical = canonicalize_url(url)
            if canonical in seen:
                continue
            seen.add(canonical)

            result = client.fetch(url, source, depth)
            results.append(result)

            if not result.html or depth >= config.max_depth:
                continue

            for next_url in extract_candidate_links(result.html, result.final_url, source.url, config):
                next_canonical = canonicalize_url(next_url)
                if next_canonical not in seen:
                    queue.append((next_url, depth + 1))

    return results


def extract_candidate_links(html: str, base_url: str, source_url: str, config: AuditConfig) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href)
        if not urlsplit(url).scheme.startswith("http"):
            continue
        if not _link_allowed_by_scope(url, source_url, config):
            continue
        if looks_like_binary_url(url) or looks_like_login_url(url):
            continue
        link_text = anchor.get_text(" ", strip=True)
        if not is_public_wechat_article_url(url) and not _link_matches_scope(url, link_text, config):
            continue
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        links.append(url)

    if config.follow_external_wechat_links:
        for match in WECHAT_TEXT_URL_PATTERN.finditer(html):
            url = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
            if not is_public_wechat_article_url(url):
                continue
            canonical = canonicalize_url(url)
            if canonical in seen:
                continue
            seen.add(canonical)
            links.append(url)

    return links


def _link_allowed_by_scope(url: str, source_url: str, config: AuditConfig) -> bool:
    if same_site(url, source_url):
        return True
    return config.follow_external_wechat_links and is_public_wechat_article_url(url)


def _link_matches_scope(url: str, link_text: str, config: AuditConfig) -> bool:
    haystack = normalize_for_match(unquote(url) + " " + link_text)
    terms = config.cities + config.keywords + GENERIC_LINK_TERMS
    return any(term and term in haystack for term in terms)


def _count_source_results(results: list[FetchResult], source: SourceConfig) -> int:
    return sum(1 for result in results if result.source_name == source.name)


def _looks_like_html(content_type: str, text: str) -> bool:
    lowered = (content_type or "").lower()
    if "text/html" in lowered or "application/xhtml" in lowered:
        return True
    stripped = (text or "").lstrip()[:100].lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


def _fix_response_encoding(response: requests.Response) -> None:
    declared = (response.encoding or "").lower()
    if declared in {"", "ascii", "iso-8859-1"} and response.apparent_encoding:
        response.encoding = response.apparent_encoding
