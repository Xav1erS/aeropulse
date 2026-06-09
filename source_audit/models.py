from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class SourceConfig:
    name: str
    url: str
    priority: str = "P2"
    city: str = ""
    max_pages: int | None = None


@dataclass
class AuditConfig:
    cities: list[str]
    keywords: list[str]
    start_date: date | None
    end_date: date | None
    sources: list[SourceConfig]
    polite_delay_seconds: float = 2.0
    max_pages_per_source: int = 30
    max_depth: int = 1
    timeout_seconds: int = 12
    user_agent: str = "source-audit/0.1 (+public-source-risk-audit)"
    database_path: str = "data/source_audit.sqlite"
    output_dir: str = "outputs"
    current_date: date = field(default_factory=date.today)
    include_unknown_dates: bool = True
    respect_robots_txt: bool = True
    follow_external_wechat_links: bool = False
    image_ocr_enabled: bool = False
    image_ocr_max_images_per_page: int = 5
    image_ocr_max_image_bytes: int = 4_000_000
    image_ocr_min_text_chars: int = 6
    mistral_ocr_api_key: str = ""
    mistral_ocr_model: str = "mistral-ocr-latest"


@dataclass
class FetchResult:
    raw_url: str
    final_url: str
    source_name: str
    source_priority: str
    source_city: str
    fetched_at: str
    status_code: int
    content_type: str
    html: str = ""
    depth: int = 0
    error: str = ""


@dataclass
class ExtractedPage:
    raw_url: str
    final_url: str
    title: str
    published_at: date | None
    body_text: str
    summary: str
    date_mentions: list[date] = field(default_factory=list)


@dataclass
class Classification:
    relevant: bool
    category: str
    confidence: float
    reason: str
    scenes: list[str]
    evidence_snippets: list[str]
    mappability: str
    validity: str


@dataclass
class AuditRecord:
    run_id: str
    raw_url: str
    final_url: str
    canonical_url: str
    source_name: str
    source_priority: str
    city: str
    fetched_at: str
    status_code: int
    content_type: str
    title: str
    published_at: date | None
    summary: str
    body_text: str
    date_mentions: list[date]
    relevant: bool
    category: str
    confidence: float
    reason: str
    scenes: list[str]
    evidence_snippets: list[str]
    mappability: str
    validity: str
    content_hash: str
    within_time_range: bool
    dedupe_key: str = ""
    is_duplicate: bool = False
    master_url: str = ""
    error: str = ""
