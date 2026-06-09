from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .classifier import classify_page, infer_city
from .config import validate_config
from .crawler import crawl_sources
from .dedup import assign_dedupe_keys
from .extractor import extract_page
from .models import AuditConfig, AuditRecord
from .ocr import ImageOcrRunner
from .reporting import write_csv, write_markdown_report
from .storage import save_run
from .utils import canonicalize_url, ensure_dir, sha1_text


def run_audit(config: AuditConfig) -> dict[str, object]:
    validate_config(config)
    run_id = _new_run_id()
    fetched_pages = crawl_sources(config)
    ocr_runner = ImageOcrRunner(config) if config.image_ocr_enabled else None

    records: list[AuditRecord] = []
    for fetch in fetched_pages:
        page = extract_page(fetch)
        if ocr_runner:
            page = ocr_runner.enrich_page(page, fetch.html, fetch.final_url)
        classification = classify_page(page, fetch, config)
        inferred_city = fetch.source_city or infer_city(" ".join([page.title, page.body_text]), config.cities)
        content_hash = sha1_text(" ".join([page.title, page.body_text[:5000]]))
        record = AuditRecord(
            run_id=run_id,
            raw_url=fetch.raw_url,
            final_url=fetch.final_url,
            canonical_url=canonicalize_url(fetch.final_url or fetch.raw_url),
            source_name=fetch.source_name,
            source_priority=fetch.source_priority,
            city=inferred_city,
            fetched_at=fetch.fetched_at,
            status_code=fetch.status_code,
            content_type=fetch.content_type,
            title=page.title,
            published_at=page.published_at,
            summary=page.summary,
            body_text=page.body_text,
            date_mentions=page.date_mentions,
            relevant=classification.relevant,
            category=classification.category,
            confidence=classification.confidence,
            reason=classification.reason,
            scenes=classification.scenes,
            evidence_snippets=classification.evidence_snippets,
            mappability=classification.mappability,
            validity=classification.validity,
            content_hash=content_hash,
            within_time_range=_within_time_range(page.published_at, config),
            error=fetch.error,
        )
        records.append(record)

    assign_dedupe_keys(records)

    output_dir = ensure_dir(config.output_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"source_audit_{stamp}.csv"
    report_path = output_dir / f"source_audit_{stamp}.md"

    save_run(config.database_path, run_id, config, records)
    write_csv(records, csv_path)
    stats = write_markdown_report(records, report_path, run_id)

    return {
        "run_id": run_id,
        "db_path": str(Path(config.database_path)),
        "csv_path": str(csv_path),
        "report_path": str(report_path),
        "stats": stats,
    }


def _within_time_range(published_at, config: AuditConfig) -> bool:
    if not published_at:
        return config.include_unknown_dates
    if config.start_date and published_at < config.start_date:
        return False
    if config.end_date and published_at > config.end_date:
        return False
    return True


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
