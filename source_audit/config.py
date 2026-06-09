from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import AuditConfig, SourceConfig


VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)).date()


def normalize_priority(value: str | None) -> str:
    priority = (value or "P2").upper()
    return priority if priority in VALID_PRIORITIES else "P2"


def load_config(path: str | Path) -> AuditConfig:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("缺少 PyYAML，请先运行 pip install -r requirements.txt") from exc

    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    time_range = data.get("time_range") or {}
    crawl = data.get("crawl") or {}
    wechat = data.get("wechat") or {}
    image_ocr = data.get("image_ocr") or {}
    storage = data.get("storage") or {}
    output = data.get("output") or {}

    sources = [_parse_source(item) for item in data.get("sources", [])]
    cities = [str(city).strip() for city in data.get("cities", []) if str(city).strip()]
    if not cities:
        cities = sorted({source.city for source in sources if source.city})

    return AuditConfig(
        cities=cities,
        keywords=[str(keyword).strip() for keyword in data.get("keywords", []) if str(keyword).strip()],
        start_date=parse_date(time_range.get("start")),
        end_date=parse_date(time_range.get("end")),
        sources=sources,
        polite_delay_seconds=float(crawl.get("polite_delay_seconds", 2.0)),
        max_pages_per_source=int(crawl.get("max_pages_per_source", 30)),
        max_depth=int(crawl.get("max_depth", 1)),
        timeout_seconds=int(crawl.get("timeout_seconds", 12)),
        user_agent=str(crawl.get("user_agent", "source-audit/0.1 (+public-source-risk-audit)")),
        database_path=str(storage.get("database_path", "data/source_audit.sqlite")),
        output_dir=str(output.get("output_dir", "outputs")),
        current_date=parse_date(data.get("current_date")) or date.today(),
        include_unknown_dates=bool(time_range.get("include_unknown_dates", True)),
        respect_robots_txt=bool(crawl.get("respect_robots_txt", True)),
        follow_external_wechat_links=bool(wechat.get("follow_mp_links", False)),
    image_ocr_enabled=bool(image_ocr.get("enabled", False)),
    image_ocr_max_images_per_page=int(image_ocr.get("max_images_per_page", 5)),
    image_ocr_max_image_bytes=int(image_ocr.get("max_image_bytes", 4_000_000)),
    image_ocr_min_text_chars=int(image_ocr.get("min_text_chars", 6)),
    mistral_ocr_api_key=str(image_ocr.get("mistral_api_key", "") or os.environ.get("MISTRAL_API_KEY", "")),
    mistral_ocr_model=str(image_ocr.get("mistral_model", "mistral-ocr-latest")),
    )


def build_config_from_cli(args: Any) -> AuditConfig:
    sources = [_parse_cli_source(value) for value in args.source or []]
    return AuditConfig(
        cities=args.city or [],
        keywords=args.keyword or [],
        start_date=parse_date(args.start_date),
        end_date=parse_date(args.end_date),
        sources=sources,
        polite_delay_seconds=args.polite_delay,
        max_pages_per_source=args.max_pages,
        max_depth=args.max_depth,
        timeout_seconds=args.timeout,
        database_path=args.db,
        output_dir=args.out_dir,
        current_date=parse_date(args.current_date) or date.today(),
        include_unknown_dates=not args.exclude_unknown_dates,
        respect_robots_txt=not args.ignore_robots_txt,
        follow_external_wechat_links=args.follow_wechat_links,
        image_ocr_enabled=args.image_ocr,
        image_ocr_max_images_per_page=args.ocr_max_images,
    )


def config_to_dict(config: AuditConfig) -> dict[str, Any]:
    data = asdict(config)
    for key in ("start_date", "end_date", "current_date"):
        data[key] = data[key].isoformat() if data[key] else None
    return data


def validate_config(config: AuditConfig) -> None:
    if not config.sources:
        raise ValueError("至少需要提供一个公开来源 URL。")
    if not config.cities:
        raise ValueError("至少需要提供一个城市。")
    if config.start_date and config.end_date and config.start_date > config.end_date:
        raise ValueError("time_range.start 不能晚于 time_range.end。")
    if config.polite_delay_seconds < 0:
        raise ValueError("polite_delay_seconds 不能为负数。")
    if config.max_pages_per_source < 1:
        raise ValueError("max_pages_per_source 必须大于 0。")
    if config.max_depth < 0:
        raise ValueError("max_depth 不能为负数。")
    if config.image_ocr_max_images_per_page < 1:
        raise ValueError("image_ocr.max_images_per_page 必须大于 0。")
    if config.image_ocr_max_image_bytes < 1:
        raise ValueError("image_ocr.max_image_bytes 必须大于 0。")
    if config.image_ocr_min_text_chars < 0:
        raise ValueError("image_ocr.min_text_chars 不能为负数。")


def _parse_source(item: Any) -> SourceConfig:
    if isinstance(item, str):
        return SourceConfig(name=item, url=item)
    if not isinstance(item, dict):
        raise ValueError(f"无效来源配置: {item!r}")
    url = str(item.get("url", "")).strip()
    if not url:
        raise ValueError(f"来源缺少 url: {item!r}")
    return SourceConfig(
        name=str(item.get("name") or url).strip(),
        url=url,
        priority=normalize_priority(item.get("priority")),
        city=str(item.get("city") or "").strip(),
        max_pages=int(item["max_pages"]) if item.get("max_pages") else None,
    )


def _parse_cli_source(value: str) -> SourceConfig:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) == 3:
        priority, name, url = parts
        return SourceConfig(name=name, url=url, priority=normalize_priority(priority))
    return SourceConfig(name=value, url=value)
