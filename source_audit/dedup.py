from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher

from .models import AuditRecord
from .utils import compact_key, sha1_text


def assign_dedupe_keys(records: list[AuditRecord]) -> list[AuditRecord]:
    masters: list[AuditRecord] = []

    for record in records:
        matched_master = _find_master(record, masters)
        if matched_master:
            record.is_duplicate = True
            record.master_url = matched_master.master_url or matched_master.canonical_url
            record.dedupe_key = matched_master.dedupe_key
            continue

        record.is_duplicate = False
        record.master_url = record.canonical_url
        record.dedupe_key = _build_dedupe_key(record)
        masters.append(record)

    return records


def _find_master(record: AuditRecord, masters: list[AuditRecord]) -> AuditRecord | None:
    for master in masters:
        if record.canonical_url == master.canonical_url:
            return master
        if record.content_hash and record.content_hash == master.content_hash:
            return master
        if _likely_same_notice(record, master):
            return master
    return None


def _likely_same_notice(left: AuditRecord, right: AuditRecord) -> bool:
    left_title = compact_key(left.title)
    right_title = compact_key(right.title)
    if len(left_title) < 8 or len(right_title) < 8:
        return False

    similarity = SequenceMatcher(None, left_title, right_title).ratio()
    if similarity >= 0.92 and _date_close(left.published_at, right.published_at):
        return True
    if similarity >= 0.96:
        return True
    return False


def _date_close(left: date | None, right: date | None) -> bool:
    if not left or not right:
        return True
    return abs((left - right).days) <= 1


def _build_dedupe_key(record: AuditRecord) -> str:
    date_part = record.published_at.isoformat() if record.published_at else "unknown-date"
    title_part = compact_key(record.title)[:120]
    if not title_part:
        title_part = record.content_hash[:16] or compact_key(record.summary)[:120]
    return sha1_text("|".join([date_part, title_part, record.category]))

