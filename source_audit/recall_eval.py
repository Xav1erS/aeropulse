from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .classifier import (
    FORMAL_NOTICE_TERMS,
    LONG_TERM_TERMS,
    RESTRICTION_TERMS,
    SCENE_KEYWORDS,
    TEMPORARY_TERMS,
)
from .utils import compact_key, ensure_dir


REQUIRED_GOLDEN_COLUMNS = {"id", "title", "city", "url", "type"}
DEFAULT_REPORT_PATH = "data/outputs/recall_eval_report.md"
TITLE_FUZZY_THRESHOLD = 0.86
KEYWORD_COVERAGE_THRESHOLD = 0.6

GENERIC_TITLE_WORDS = {
    "关于",
    "通知",
    "公告",
    "通告",
    "提示",
    "须知",
    "山东",
    "山东省",
    "期间",
    "有关",
    "做好",
    "加强",
    "管理",
}


@dataclass(frozen=True)
class GoldenSample:
    id: str
    title: str
    city: str
    url: str
    type: str
    source_level: str = ""


@dataclass(frozen=True)
class AuditCandidate:
    raw_url: str
    final_url: str
    canonical_url: str
    master_url: str
    title: str
    city: str
    category: str
    source_priority: str
    source_name: str


@dataclass(frozen=True)
class RecallMatch:
    golden: GoldenSample
    recalled: bool
    method: str = ""
    score: float = 0.0
    matched_keywords: tuple[str, ...] = ()
    candidate: AuditCandidate | None = None


def run_recall_eval(
    golden_path: str | Path,
    database_path: str | Path,
    report_path: str | Path = DEFAULT_REPORT_PATH,
) -> dict[str, object]:
    golden_samples = load_golden_samples(golden_path)
    candidates = load_audit_candidates(database_path)
    matches = evaluate_samples(golden_samples, candidates)
    result = build_result(matches, has_source_level=golden_has_source_level(golden_path))
    write_recall_report(result, report_path)
    result["report_path"] = str(report_path)
    return result


def load_golden_samples(path: str | Path) -> list[GoldenSample]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"golden CSV 不存在: {target}")

    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = REQUIRED_GOLDEN_COLUMNS - fieldnames
        if missing:
            raise ValueError("golden CSV 缺少字段: " + ", ".join(sorted(missing)))

        samples = []
        for row in reader:
            sample = GoldenSample(
                id=(row.get("id") or "").strip(),
                title=(row.get("title") or "").strip(),
                city=(row.get("city") or "").strip(),
                url=(row.get("url") or "").strip(),
                type=(row.get("type") or "").strip().upper(),
                source_level=(row.get("source_level") or "").strip().upper(),
            )
            if sample.id or sample.title or sample.url:
                samples.append(sample)

    return samples


def golden_has_source_level(path: str | Path) -> bool:
    target = Path(path)
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return "source_level" in set(reader.fieldnames or [])


def load_audit_candidates(database_path: str | Path) -> list[AuditCandidate]:
    target = Path(database_path)
    if not target.exists():
        raise FileNotFoundError(f"SQLite 数据库不存在: {target}")

    connection = sqlite3.connect(target)
    try:
        connection.row_factory = sqlite3.Row
        if not _table_exists(connection, "audit_pages"):
            raise ValueError("SQLite 数据库缺少 audit_pages 表。")

        rows = connection.execute(
            """
            SELECT
                raw_url, final_url, canonical_url, master_url, title, city,
                category, source_priority, source_name
            FROM audit_pages
            """
        ).fetchall()
    finally:
        connection.close()

    return [
        AuditCandidate(
            raw_url=row["raw_url"] or "",
            final_url=row["final_url"] or "",
            canonical_url=row["canonical_url"] or "",
            master_url=row["master_url"] or "",
            title=row["title"] or "",
            city=row["city"] or "",
            category=row["category"] or "",
            source_priority=row["source_priority"] or "",
            source_name=row["source_name"] or "",
        )
        for row in rows
    ]


def evaluate_samples(golden_samples: list[GoldenSample], candidates: list[AuditCandidate]) -> list[RecallMatch]:
    return [_match_sample(sample, candidates) for sample in golden_samples]


def build_result(matches: list[RecallMatch], has_source_level: bool) -> dict[str, object]:
    total = len(matches)
    recalled = [match for match in matches if match.recalled]
    missed = [match.golden for match in matches if not match.recalled]
    a_type_matches = [match for match in matches if match.golden.type == "A"]

    result: dict[str, object] = {
        "total_golden_count": total,
        "recalled_count": len(recalled),
        "recall_rate": _rate(len(recalled), total),
        "A_type_recall_rate": _rate(sum(1 for match in a_type_matches if match.recalled), len(a_type_matches)),
        "missed_samples": [_sample_to_dict(sample) for sample in missed],
        "matches": matches,
    }

    if has_source_level:
        p0_p1_matches = [match for match in matches if match.golden.source_level in {"P0", "P1"}]
        result["P0/P1_recall_rate"] = _rate(
            sum(1 for match in p0_p1_matches if match.recalled),
            len(p0_p1_matches),
        )

    return result


def write_recall_report(result: dict[str, object], report_path: str | Path) -> None:
    target = Path(report_path)
    ensure_dir(target.parent)

    lines = [
        "# Recall Eval 报告",
        "",
        f"- total_golden_count: **{result['total_golden_count']}**",
        f"- recalled_count: **{result['recalled_count']}**",
        f"- recall_rate: **{_format_rate(result['recall_rate'])}**",
        f"- A_type_recall_rate: **{_format_rate(result['A_type_recall_rate'])}**",
    ]
    if "P0/P1_recall_rate" in result:
        lines.append(f"- P0/P1_recall_rate: **{_format_rate(result['P0/P1_recall_rate'])}**")

    lines.extend(
        [
            "",
            "## 召回样本",
            "",
            _matched_table(result["matches"]),
            "",
            "## missed_samples",
            "",
            _missed_table(result["missed_samples"]),
            "",
            "说明：召回判断按 URL 完全匹配、标题模糊匹配、标题关键词匹配依次执行；本评估不联网，只读取 SQLite 中已有 `audit_pages` 数据。",
            "",
        ]
    )

    target.write_text("\n".join(lines), encoding="utf-8")


def _match_sample(sample: GoldenSample, candidates: list[AuditCandidate]) -> RecallMatch:
    url_match = _find_url_match(sample, candidates)
    if url_match:
        return RecallMatch(sample, True, method="url_exact", score=1.0, candidate=url_match)

    fuzzy_match, fuzzy_score = _find_fuzzy_title_match(sample, candidates)
    if fuzzy_match:
        return RecallMatch(sample, True, method="title_fuzzy", score=fuzzy_score, candidate=fuzzy_match)

    keyword_match, keyword_score, keywords = _find_keyword_title_match(sample, candidates)
    if keyword_match:
        return RecallMatch(
            sample,
            True,
            method="title_keywords",
            score=keyword_score,
            matched_keywords=tuple(keywords),
            candidate=keyword_match,
        )

    return RecallMatch(sample, False)


def _find_url_match(sample: GoldenSample, candidates: list[AuditCandidate]) -> AuditCandidate | None:
    golden_url = sample.url.strip()
    if not golden_url:
        return None
    for candidate in candidates:
        candidate_urls = {
            candidate.raw_url.strip(),
            candidate.final_url.strip(),
            candidate.canonical_url.strip(),
            candidate.master_url.strip(),
        }
        if golden_url in candidate_urls:
            return candidate
    return None


def _find_fuzzy_title_match(sample: GoldenSample, candidates: list[AuditCandidate]) -> tuple[AuditCandidate | None, float]:
    golden_title = compact_key(sample.title)
    if len(golden_title) < 8:
        return None, 0.0

    best_candidate = None
    best_score = 0.0
    for candidate in candidates:
        score = _title_similarity(golden_title, compact_key(candidate.title))
        if score > best_score:
            best_candidate = candidate
            best_score = score

    if best_candidate and best_score >= TITLE_FUZZY_THRESHOLD:
        return best_candidate, round(best_score, 3)
    return None, round(best_score, 3)


def _find_keyword_title_match(
    sample: GoldenSample,
    candidates: list[AuditCandidate],
) -> tuple[AuditCandidate | None, float, list[str]]:
    keywords = extract_title_keywords(sample.title, sample.city)
    if len(keywords) < 2:
        return None, 0.0, []

    best_candidate = None
    best_score = 0.0
    best_hits: list[str] = []
    for candidate in candidates:
        candidate_title = compact_key(candidate.title)
        hits = [keyword for keyword in keywords if keyword in candidate_title]
        score = len(hits) / len(keywords)
        if score > best_score:
            best_candidate = candidate
            best_score = score
            best_hits = hits

    if best_candidate and best_score >= KEYWORD_COVERAGE_THRESHOLD and len(best_hits) >= 2:
        return best_candidate, round(best_score, 3), best_hits
    return None, round(best_score, 3), best_hits


def extract_title_keywords(title: str, city: str = "") -> list[str]:
    compact_title = compact_key(title)
    vocabulary = _keyword_vocabulary()
    hits = [term for term in vocabulary if term in compact_title and term not in GENERIC_TITLE_WORDS]
    if city and city in compact_title:
        hits.append(city)

    if len(hits) < 2:
        hits.extend(_fallback_title_terms(compact_title))

    return _dedupe_preserve_order(hits)


def _keyword_vocabulary() -> list[str]:
    terms: set[str] = set()
    for values in SCENE_KEYWORDS.values():
        terms.update(values)
    terms.update(FORMAL_NOTICE_TERMS)
    terms.update(RESTRICTION_TERMS)
    terms.update(TEMPORARY_TERMS)
    terms.update(LONG_TERM_TERMS)
    return sorted((term for term in terms if len(term) >= 2), key=len, reverse=True)


def _fallback_title_terms(compact_title: str) -> list[str]:
    cleaned = compact_title
    for word in GENERIC_TITLE_WORDS:
        cleaned = cleaned.replace(word, " ")
    return [term for term in re.split(r"\s+", cleaned) if len(term) >= 3]


def _title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    return SequenceMatcher(None, left, right).ratio()


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _sample_to_dict(sample: GoldenSample) -> dict[str, str]:
    return {
        "id": sample.id,
        "title": sample.title,
        "city": sample.city,
        "url": sample.url,
        "type": sample.type,
        "source_level": sample.source_level,
    }


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _format_rate(value: object) -> str:
    return f"{float(value):.4f}"


def _matched_table(matches: object) -> str:
    typed_matches = list(matches) if isinstance(matches, list) else []
    recalled = [match for match in typed_matches if isinstance(match, RecallMatch) and match.recalled]
    if not recalled:
        return "_无_"

    rows = [
        "| id | type | method | score | golden_title | matched_title | matched_url |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for match in recalled:
        candidate = match.candidate
        matched_title = _escape_cell(candidate.title if candidate else "")
        matched_url = candidate.final_url if candidate else ""
        rows.append(
            f"| {_escape_cell(match.golden.id)} | {_escape_cell(match.golden.type)} | {match.method} | "
            f"{match.score:.3f} | {_escape_cell(match.golden.title)} | {matched_title} | {matched_url} |"
        )
    return "\n".join(rows)


def _missed_table(samples: object) -> str:
    typed_samples = list(samples) if isinstance(samples, list) else []
    if not typed_samples:
        return "_无_"

    rows = [
        "| id | type | source_level | city | title | url |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in typed_samples:
        sample = item if isinstance(item, dict) else {}
        rows.append(
            f"| {_escape_cell(sample.get('id', ''))} | {_escape_cell(sample.get('type', ''))} | "
            f"{_escape_cell(sample.get('source_level', ''))} | {_escape_cell(sample.get('city', ''))} | "
            f"{_escape_cell(sample.get('title', ''))} | {sample.get('url', '')} |"
        )
    return "\n".join(rows)


def _escape_cell(value: object) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ").strip()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result
