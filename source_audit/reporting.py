from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .models import AuditRecord
from .utils import date_to_iso, ensure_dir


CSV_COLUMNS = [
    "run_id",
    "city",
    "source_priority",
    "source_name",
    "category",
    "confidence",
    "relevant",
    "within_time_range",
    "is_duplicate",
    "mappability",
    "validity",
    "scenes",
    "reason",
    "evidence_snippets",
    "title",
    "published_at",
    "summary",
    "raw_url",
    "final_url",
    "canonical_url",
    "dedupe_key",
    "master_url",
    "fetched_at",
    "status_code",
    "content_type",
    "error",
]


def write_csv(records: list[AuditRecord], path: str | Path) -> None:
    target = Path(path)
    ensure_dir(target.parent)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(_record_to_csv_row(record))


def write_markdown_report(records: list[AuditRecord], path: str | Path, run_id: str) -> dict[str, object]:
    target = Path(path)
    ensure_dir(target.parent)
    stats = compute_stats(records)
    lines = [
        "# Source Audit 报告",
        "",
        f"- run_id: `{run_id}`",
        f"- raw_url_count: **{stats['raw_url_count']}**",
        f"- unique_url_count: **{stats['unique_url_count']}**",
        f"- relevant_page_count: **{stats['relevant_page_count']}**",
        f"- 当前/未来有效样本数: **{stats['current_future_count']}**",
        f"- 当前/未来有效 A/B 临时管控样本数: **{stats['current_future_time_sensitive_count']}**",
        f"- 历史 A/B 临时管控样本数: **{stats['historical_time_sensitive_count']}**",
        "",
        "## A/B/C/D/E 数量",
        "",
        _counter_table(stats["category_counts"], "类别", include_all=["A", "B", "C", "D", "E"]),
        "",
        "## 当前/未来有效样本分类",
        "",
        _counter_table(stats["current_future_category_counts"], "类别", include_all=["A", "B", "C", "D", "E"]),
        "",
        "## 时效性聚焦口径",
        "",
        _timeliness_table(stats),
        "",
        "## P0/P1/P2/P3 来源占比",
        "",
        _ratio_table(stats["priority_counts"], "优先级", include_all=["P0", "P1", "P2", "P3"]),
        "",
        "## 城市分布",
        "",
        _counter_table(stats["city_counts"], "城市"),
        "",
        "## 场景分布",
        "",
        _counter_table(stats["scene_counts"], "场景"),
        "",
        "## 地图化可行性",
        "",
        _counter_table(stats["mappability_counts"], "类型", include_all=["可地图化", "半自动地图化", "不可地图化"]),
        "",
        "## 有效性分布",
        "",
        _counter_table(stats["validity_counts"], "有效性", include_all=["当前/未来有效", "历史样本", "未知"]),
        "",
        "## 高置信样本",
        "",
        _sample_table(stats["sample_records"]),
        "",
        "说明：A/B/C/D/E、地图化和有效性均为规则初筛结果，应由人工复核后用于正式结论。",
        "",
    ]
    target.write_text("\n".join(lines), encoding="utf-8")
    return stats


def compute_stats(records: list[AuditRecord]) -> dict[str, object]:
    eligible = [record for record in records if record.within_time_range]
    unique_records = [record for record in eligible if not record.is_duplicate]
    relevant_records = [record for record in unique_records if record.relevant]
    current_future_records = [record for record in relevant_records if record.validity == "当前/未来有效"]
    time_sensitive_records = [record for record in relevant_records if record.category in {"A", "B"}]
    current_future_time_sensitive_records = [
        record for record in time_sensitive_records if record.validity == "当前/未来有效"
    ]
    historical_time_sensitive_records = [record for record in time_sensitive_records if record.validity == "历史样本"]

    category_counts = Counter(record.category for record in relevant_records)
    current_future_category_counts = Counter(record.category for record in current_future_records)
    priority_counts = Counter(record.source_priority for record in relevant_records)
    city_counts = Counter(record.city for record in relevant_records)
    scene_counts: Counter[str] = Counter()
    for record in relevant_records:
        scene_counts.update(record.scenes)
    mappability_counts = Counter(record.mappability for record in relevant_records)
    validity_counts = Counter(record.validity for record in relevant_records)
    sample_records = sorted(relevant_records, key=lambda item: item.confidence, reverse=True)[:12]

    return {
        "raw_url_count": len(records),
        "unique_url_count": len(unique_records),
        "relevant_page_count": len(relevant_records),
        "category_counts": category_counts,
        "current_future_category_counts": current_future_category_counts,
        "priority_counts": priority_counts,
        "city_counts": city_counts,
        "scene_counts": scene_counts,
        "mappability_counts": mappability_counts,
        "validity_counts": validity_counts,
        "current_future_count": len(current_future_records),
        "time_sensitive_count": len(time_sensitive_records),
        "current_future_time_sensitive_count": len(current_future_time_sensitive_records),
        "historical_time_sensitive_count": len(historical_time_sensitive_records),
        "historical_relevant_count": sum(1 for record in relevant_records if record.validity == "历史样本"),
        "unknown_validity_relevant_count": sum(1 for record in relevant_records if record.validity == "未知"),
        "sample_records": sample_records,
    }


def _record_to_csv_row(record: AuditRecord) -> dict[str, object]:
    return {
        "run_id": record.run_id,
        "city": record.city,
        "source_priority": record.source_priority,
        "source_name": record.source_name,
        "category": record.category,
        "confidence": record.confidence,
        "relevant": int(record.relevant),
        "within_time_range": int(record.within_time_range),
        "is_duplicate": int(record.is_duplicate),
        "mappability": record.mappability,
        "validity": record.validity,
        "scenes": "；".join(record.scenes),
        "reason": record.reason,
        "evidence_snippets": " || ".join(record.evidence_snippets),
        "title": record.title,
        "published_at": date_to_iso(record.published_at),
        "summary": record.summary,
        "raw_url": record.raw_url,
        "final_url": record.final_url,
        "canonical_url": record.canonical_url,
        "dedupe_key": record.dedupe_key,
        "master_url": record.master_url,
        "fetched_at": record.fetched_at,
        "status_code": record.status_code,
        "content_type": record.content_type,
        "error": record.error,
    }


def _counter_table(counter: Counter[str], label: str, include_all: list[str] | None = None) -> str:
    keys = include_all or [key for key, _ in counter.most_common()]
    if not keys:
        return "_无_"
    rows = [f"| {label} | 数量 |", "| --- | ---: |"]
    for key in keys:
        rows.append(f"| {key} | {counter.get(key, 0)} |")
    return "\n".join(rows)


def _ratio_table(counter: Counter[str], label: str, include_all: list[str]) -> str:
    total = sum(counter.values())
    rows = [f"| {label} | 数量 | 占比 |", "| --- | ---: | ---: |"]
    for key in include_all:
        count = counter.get(key, 0)
        ratio = f"{(count / total * 100):.1f}%" if total else "0.0%"
        rows.append(f"| {key} | {count} | {ratio} |")
    return "\n".join(rows)


def _timeliness_table(stats: dict[str, object]) -> str:
    rows = [
        "| 口径 | 数量 | 说明 |",
        "| --- | ---: | --- |",
        f"| 当前/未来有效供给 | {stats['current_future_count']} | 可用于当前供给密度判断的主口径 |",
        f"| 当前/未来有效 A/B 临时管控 | {stats['current_future_time_sensitive_count']} | 临时空域管制、活动/考试/景区限制的当前有效样本 |",
        f"| 历史 A/B 临时管控 | {stats['historical_time_sensitive_count']} | 已过期，仅用于历史覆盖和来源发现验证 |",
        f"| 历史相关样本 | {stats['historical_relevant_count']} | 全部类别中的历史样本 |",
        f"| 有效性未知相关样本 | {stats['unknown_validity_relevant_count']} | 缺少明确日期或规则信号，需人工复核 |",
    ]
    return "\n".join(rows)


def _sample_table(records: list[AuditRecord]) -> str:
    if not records:
        return "_无_"
    rows = [
        "| 类别 | 置信度 | 城市 | 标题 | 来源 | 证据片段 |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for record in records:
        evidence = (record.evidence_snippets[0] if record.evidence_snippets else record.summary).replace("|", "/")
        title = (record.title or record.final_url).replace("|", "/")
        rows.append(
            f"| {record.category} | {record.confidence:.2f} | {record.city} | "
            f"[{title}]({record.final_url}) | {record.source_name} | {evidence} |"
        )
    return "\n".join(rows)
