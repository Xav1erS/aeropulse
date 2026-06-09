from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from .models import ExtractedPage, FetchResult
from .utils import make_summary, normalize_text


DATE_PATTERNS = (
    re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"),
    re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})"),
)

DATE_META_KEYS = {
    "article:published_time",
    "pubdate",
    "publishdate",
    "publish_date",
    "published_time",
    "date",
    "datetime",
    "release_date",
    "create_date",
}


def extract_page(fetch: FetchResult) -> ExtractedPage:
    if not fetch.html:
        error_summary = fetch.error or f"未取得 HTML 正文，HTTP 状态 {fetch.status_code}"
        return ExtractedPage(
            raw_url=fetch.raw_url,
            final_url=fetch.final_url,
            title="",
            published_at=None,
            body_text="",
            summary=error_summary,
            date_mentions=[],
        )

    metadata = _extract_with_trafilatura(fetch.html, fetch.final_url)
    fallback = _extract_with_bs4(fetch.html)

    title = (metadata.get("title") or fallback.get("title") or "").strip()
    body_text = normalize_text(metadata.get("text") or fallback.get("text") or "")
    published_at = _parse_date(metadata.get("date")) or _parse_date(fallback.get("date"))
    date_mentions = find_date_mentions(" ".join([title, body_text]))

    return ExtractedPage(
        raw_url=fetch.raw_url,
        final_url=fetch.final_url,
        title=title,
        published_at=published_at,
        body_text=body_text,
        summary=make_summary(body_text),
        date_mentions=date_mentions,
    )


def find_date_mentions(text: str) -> list[date]:
    found: list[date] = []
    seen: set[str] = set()
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text or ""):
            parsed = _date_from_parts(match.groups())
            if not parsed:
                continue
            key = parsed.isoformat()
            if key not in seen:
                found.append(parsed)
                seen.add(key)
    return found


def _extract_with_trafilatura(html: str, url: str) -> dict[str, str]:
    try:
        import trafilatura
    except ImportError:
        return {}

    try:
        extracted = trafilatura.extract(
            html,
            url=url,
            output_format="json",
            include_comments=False,
            include_tables=False,
            with_metadata=True,
        )
    except Exception:
        return {}

    if not extracted:
        return {}
    try:
        payload: dict[str, Any] = json.loads(extracted)
    except json.JSONDecodeError:
        return {}

    return {
        "title": str(payload.get("title") or ""),
        "date": str(payload.get("date") or ""),
        "text": str(payload.get("text") or ""),
    }


def _extract_with_bs4(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "form", "header", "footer", "nav"]):
        tag.decompose()

    title = _first_non_empty(
        _meta_content(soup, "property", "og:title"),
        _meta_content(soup, "name", "title"),
        soup.title.get_text(" ", strip=True) if soup.title else "",
        soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "",
    )

    date_value = ""
    for key in DATE_META_KEYS:
        date_value = _first_non_empty(
            date_value,
            _meta_content(soup, "property", key),
            _meta_content(soup, "name", key),
        )

    text = soup.get_text("\n", strip=True)
    if not date_value:
        date_match = find_date_mentions(text[:3000])
        date_value = date_match[0].isoformat() if date_match else ""

    return {"title": title, "date": date_value, "text": text}


def _meta_content(soup: BeautifulSoup, attr: str, value: str) -> str:
    tag = soup.find("meta", attrs={attr: value})
    if not tag:
        return ""
    return str(tag.get("content") or "").strip()


def _first_non_empty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    cleaned = str(value).strip()
    for pattern in DATE_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            return _date_from_parts(match.groups())
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _date_from_parts(parts: tuple[str, ...]) -> date | None:
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None

