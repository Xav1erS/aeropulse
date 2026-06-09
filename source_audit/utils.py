from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "_",
    "from",
    "spm",
    "source",
    "src",
    "timestamp",
    "isappinstalled",
}

BINARY_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bmp",
    ".css",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".svg",
    ".tar",
    ".xls",
    ".xlsx",
    ".zip",
}

LOGIN_HINTS = (
    "login",
    "signin",
    "passport",
    "oauth",
    "sso",
    "usercenter",
    "admin",
    "登录",
    "注册",
)


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def compact_key(text: str) -> str:
    text = normalize_for_match(text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


def make_summary(text: str, max_chars: int = 260) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def sha1_text(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8", errors="ignore")).hexdigest()


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme.lower() or "http"
    netloc = parts.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_pairs.append((key, value))

    query = urlencode(sorted(query_pairs), doseq=True)
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def site_key(url: str) -> str:
    netloc = urlsplit(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def same_site(left: str, right: str) -> bool:
    return bool(site_key(left)) and site_key(left) == site_key(right)


def is_public_wechat_article_url(url: str) -> bool:
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host != "mp.weixin.qq.com":
        return False
    path = parts.path.rstrip("/")
    return path == "/s" or path.startswith("/s/")


def looks_like_binary_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return any(path.endswith(ext) for ext in BINARY_EXTENSIONS)


def looks_like_login_url(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in LOGIN_HINTS)


def find_keyword_snippets(text: str, keywords: list[str], max_snippets: int = 5) -> list[str]:
    compacted = re.sub(r"\s+", " ", text or "").strip()
    lowered = compacted.lower()
    snippets: list[str] = []
    seen: set[str] = set()

    for keyword in keywords:
        if not keyword:
            continue
        index = lowered.find(keyword.lower())
        if index < 0:
            continue
        start = max(index - 70, 0)
        end = min(index + len(keyword) + 90, len(compacted))
        snippet = compacted[start:end].strip()
        if start > 0:
            snippet = "…" + snippet
        if end < len(compacted):
            snippet = snippet + "…"
        if snippet not in seen:
            snippets.append(snippet)
            seen.add(snippet)
        if len(snippets) >= max_snippets:
            break

    return snippets


def date_to_iso(value: date | None) -> str:
    return value.isoformat() if value else ""
