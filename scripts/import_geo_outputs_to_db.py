#!/usr/bin/env python3
"""将 geo_radar 落图产物导入 SQLite announcements 表。

读取：
  - outputs/announcements.json   （116 条，含落图元数据）
  - outputs/zones.geojson        （96 个几何要素）
  - outputs/merged_extracted_seed.json （116 条，含结构化时间/地理/分类字段）

写入：
  - data/aeropulse.db → announcements 表（upsert by id）

用法：
  .\\.venv\\Scripts\\python.exe scripts/import_geo_outputs_to_db.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))

# ── 源文件路径 ────────────────────────────────────────────
ANNOUNCEMENTS_PATH = PROJECT_ROOT / "outputs" / "announcements.json"
ZONES_PATH = PROJECT_ROOT / "outputs" / "zones.geojson"
MERGED_SEED_PATH = PROJECT_ROOT / "outputs" / "merged_extracted_seed.json"

# ── source_level → trust_score 映射 ────────────────────────
LEVEL_TRUST = {"P0": 0.9, "P1": 0.7, "P2": 0.5, "P3": 0.3, "P4": 0.15}

# ── 省份简称 → 全称（用于 province 字段） ──────────────────
PROVINCE_SHORT_MAP = {
    "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
    "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
    "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
    "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
    "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
    "甘肃": "甘肃省", "青海": "青海省", "台湾": "台湾省",
    "广西": "广西壮族自治区", "内蒙古": "内蒙古自治区", "西藏": "西藏自治区",
    "宁夏": "宁夏回族自治区", "新疆": "新疆维吾尔自治区",
    "北京": "北京市", "上海": "上海市", "天津": "天津市", "重庆": "重庆市",
    "香港": "香港特别行政区", "澳门": "澳门特别行政区",
}


def now_iso() -> str:
    return datetime.now(CST).isoformat()


def load_json(path: Path):
    """加载 JSON 文件."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_id_segments(ann_id: str) -> tuple[str, str]:
    """从 id 解析 province 和 city.
    
    id 格式: "{province_short}_{city}_{title_key}_{date}"
    例如: "河北_保定市_低慢小临时管控_2026-02-27"
    """
    parts = ann_id.split("_")
    province_short = parts[0] if len(parts) >= 1 else ""
    city_raw = parts[1] if len(parts) >= 2 else ""
    province = PROVINCE_SHORT_MAP.get(province_short, province_short)
    return province, city_raw


def parse_time_text(time_text: str | None) -> tuple[str | None, str | None]:
    """从 time_text 解析 start / end ISO 字符串.
    
    支持格式:
      "2026-03-01 00:00 ~ 2026-03-12 24:00"
      "每年 05-02~05-02、06-20~06-20..."  (周期性，返回 None)
    """
    if not time_text:
        return None, None
    # 周期性
    if "每年" in time_text:
        return None, None
    m = re.match(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*~\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", time_text)
    if m:
        start = m.group(1).replace(" ", "T") + ":00"
        end = m.group(2).replace("24:00", "23:59:59").replace(" ", "T")
        if ":59:59" not in end:
            end += ":00"
        return start, end
    return None, None


def status_to_time_status(status: str) -> str:
    """announcements.json 的 status → SQLite time_status."""
    mapping = {
        "ACTIVE": "active",
        "EXPIRED": "expired",
        "NOT_STARTED": "not_started",
        "LONG_TERM": "long_term",
        "INACTIVE": "inactive",
        "UNKNOWN": "unknown",
    }
    return mapping.get(status, "unknown")


def build_record(
    ann: dict,
    seed_lookup: dict[str, dict],
    geo_lookup: dict[str, dict],
) -> dict:
    """将一条 announcements.json 记录 + 补充数据 → SQLite 写入 dict."""
    ann_id = ann["id"]
    seed = seed_lookup.get(ann_id, {})
    geo_feature = geo_lookup.get(ann_id)

    province, city = parse_id_segments(ann_id)

    # ── 时间字段（优先用 seed 的结构化数据） ──
    seed_time = seed.get("time", {}) if seed else {}
    time_mode = seed_time.get("mode", "single") if seed_time else "single"

    start_time = seed_time.get("start") if seed_time else None
    end_time = seed_time.get("end") if seed_time else None
    time_windows = seed_time.get("windows") if seed_time else None

    # 如果 seed 没有 start/end，回退解析 time_text
    if not start_time and not end_time:
        start_time, end_time = parse_time_text(ann.get("time_text"))

    # ── 地理字段（优先用 seed 的 geo 子对象） ──
    seed_geo = seed.get("geo", {}) if seed else {}
    center_poi = seed_geo.get("poi") if seed_geo else None
    poi_list = seed_geo.get("poi_list") if seed_geo else None
    radius_meters = seed_geo.get("radius_m") if seed_geo else None
    district_name = seed_geo.get("district") if seed_geo else None
    roster_status = seed_geo.get("roster_status") if seed_geo else None

    # ── 几何（从 zones.geojson） ──
    geo_json = None
    if geo_feature and geo_feature.get("geometry"):
        geo_json = geo_feature["geometry"]

    # ── 审查字段 ──
    geo_grade = ann.get("geo_grade", "E")
    needs_review = bool(seed.get("needs_review", geo_grade == "E"))
    review_status = ann.get("review_status", "pending_confirm")
    review_reason = ann.get("review_reason")

    # ── 来源信任分 ──
    source_level = ann.get("source_level", "P2")
    source_trust_score = LEVEL_TRUST.get(source_level, 0.5)

    # ── aircraft_types 统一为字符串 ──
    aircraft_types = ann.get("aircraft_types", "")
    if isinstance(aircraft_types, list):
        aircraft_types = "、".join(aircraft_types)

    # ── evidence_text 截断（避免过长） ──
    evidence_text_full = ann.get("evidence_text") or seed.get("evidence_text") or ""

    return {
        "id": ann_id,
        "source_task_id": ann_id,
        "extraction_method": seed.get("extraction_method", "llm"),
        "title": ann.get("title", "") or seed.get("title", ""),
        "publish_unit": ann.get("publish_unit") or seed.get("publish_unit", ""),
        "source_name": ann.get("source_name", ""),
        "source_url": ann.get("source_url", ""),
        "source_level": source_level,
        "source_trust_score": source_trust_score,
        "publish_time": seed.get("publish_time"),
        "last_checked_at": now_iso(),
        "province": province,
        "city": ann.get("city") or city,
        "district": district_name,
        "control_type": ann.get("control_type", "临时管控"),
        "risk_class": ann.get("risk_class", "control"),
        "time_status": status_to_time_status(ann.get("status", "UNKNOWN")),
        "start_time": start_time,
        "end_time": end_time,
        "time_mode": time_mode,
        "time_windows": time_windows,
        "validity_basis": ann.get("status_basis"),
        "area_text": ann.get("area_text", ""),
        "geo_type": ann.get("geo_type", "fuzzy"),
        "center_poi": center_poi,
        "poi_list": poi_list if poi_list else None,
        "radius_meters": radius_meters,
        "district_name": district_name,
        "geo_json": geo_json,
        "geo_confidence": ann.get("geo_confidence", 0.0),
        "geo_grade": geo_grade,
        "geo_note": review_reason if geo_grade == "E" else None,
        "roster_status": roster_status,
        "aircraft_types": aircraft_types,
        "evidence_text": evidence_text_full,
        "evidence_time": None,
        "evidence_area": ann.get("area_text", ""),
        "evidence_control_type": ann.get("control_type"),
        "confidence_score": ann.get("confidence_score", 0.0),
        "needs_review": needs_review,
        "review_status": review_status,
        "review_reason": review_reason,
        "map_layer_status": "published",
        "duplicate_group_id": None,
        "version_id": "v1",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def upsert_announcement(db, record: dict) -> None:
    """INSERT OR REPLACE into announcements."""
    # JSON 序列化特定字段
    time_windows_json = json.dumps(record["time_windows"], ensure_ascii=False) if record["time_windows"] else None
    poi_list_json = json.dumps(record["poi_list"], ensure_ascii=False) if record["poi_list"] else None
    geo_json_str = json.dumps(record["geo_json"], ensure_ascii=False) if record["geo_json"] else None
    aircraft_types_val = record["aircraft_types"]

    db.execute(
        """INSERT OR REPLACE INTO announcements (
            id, source_task_id, extraction_method, title,
            publish_unit, source_name, source_url, source_level, source_trust_score,
            publish_time, last_checked_at, province, city, district,
            control_type, risk_class, time_status, start_time, end_time,
            time_mode, time_windows, validity_basis, area_text,
            geo_type, center_poi, poi_list, radius_meters, district_name,
            geo_json, geo_confidence, geo_grade, geo_note, roster_status,
            aircraft_types, evidence_text, evidence_time, evidence_area,
            evidence_control_type, confidence_score, needs_review, review_status,
            review_reason, map_layer_status, duplicate_group_id, version_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            record["id"],
            record["source_task_id"],
            record["extraction_method"],
            record["title"],
            record["publish_unit"],
            record["source_name"],
            record["source_url"],
            record["source_level"],
            record["source_trust_score"],
            record["publish_time"],
            record["last_checked_at"],
            record["province"],
            record["city"],
            record["district"],
            record["control_type"],
            record["risk_class"],
            record["time_status"],
            record["start_time"],
            record["end_time"],
            record["time_mode"],
            time_windows_json,
            record["validity_basis"],
            record["area_text"],
            record["geo_type"],
            record["center_poi"],
            poi_list_json,
            record["radius_meters"],
            record["district_name"],
            geo_json_str,
            record["geo_confidence"],
            record["geo_grade"],
            record["geo_note"],
            record["roster_status"],
            aircraft_types_val,
            record["evidence_text"],
            record["evidence_time"],
            record["evidence_area"],
            record["evidence_control_type"],
            record["confidence_score"],
            1 if record["needs_review"] else 0,
            record["review_status"],
            record["review_reason"],
            record["map_layer_status"],
            record["duplicate_group_id"],
            record["version_id"],
            record["created_at"],
            record["updated_at"],
        ],
    )


def main():
    import sqlite3

    print("=" * 64)
    print("  全国 2026 临时管控批量处理结果 → SQLite 导入")
    print("=" * 64)

    # ── 1. 加载数据 ──────────────────────────────────────
    print("\n[1/5] 加载数据文件...")
    announcements = load_json(ANNOUNCEMENTS_PATH)
    print(f"  [OK] announcements.json  : {len(announcements)} records")

    zones = load_json(ZONES_PATH)
    geo_features = zones.get("features", [])
    print(f"  [OK] zones.geojson        : {len(geo_features)} features")

    merged_seed = load_json(MERGED_SEED_PATH)
    print(f"  [OK] merged_extracted_seed: {len(merged_seed)} records")

    # ── 2. 构建索引 ──────────────────────────────────────
    print("\n[2/5] 构建索引...")
    seed_lookup: dict[str, dict] = {s["id"]: s for s in merged_seed}
    geo_lookup: dict[str, dict] = {}
    for f in geo_features:
        props = f.get("properties", {})
        fid = props.get("id")
        if fid:
            geo_lookup[fid] = f
    print(f"  [OK] seed index: {len(seed_lookup)} records")
    print(f"  [OK] geo  index: {len(geo_lookup)} records")

    # ── 3. 构建记录 ──────────────────────────────────────
    print("\n[3/5] 构建 SQLite 记录...")
    records = []
    for ann in announcements:
        rec = build_record(ann, seed_lookup, geo_lookup)
        records.append(rec)
    print(f"  [OK] Built {len(records)} records")

    # ── 4. 写入 SQLite ───────────────────────────────────
    print("\n[4/5] 写入 SQLite ...")
    db_path = PROJECT_ROOT / "data" / "aeropulse.db"
    db = sqlite3.connect(str(db_path))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    for rec in records:
        upsert_announcement(db, rec)

    db.commit()

    # ── 5. 验证 ──────────────────────────────────────────
    print("\n[5/5] 验证导入结果...")
    total = db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]

    # 仅统计本次导入的记录（用 id 集合）
    imported_ids = {r["id"] for r in records}
    placeholders = ",".join("?" * len(imported_ids))
    imported_total = db.execute(
        f"SELECT COUNT(*) FROM announcements WHERE id IN ({placeholders})",
        list(imported_ids),
    ).fetchone()[0]
    imported_published = db.execute(
        f"SELECT COUNT(*) FROM announcements WHERE id IN ({placeholders}) AND map_layer_status = 'published'",
        list(imported_ids),
    ).fetchone()[0]
    imported_with_geo = db.execute(
        f"SELECT COUNT(*) FROM announcements WHERE id IN ({placeholders}) AND geo_json IS NOT NULL AND geo_json != ''",
        list(imported_ids),
    ).fetchone()[0]
    imported_e_no_geo = db.execute(
        f"SELECT COUNT(*) FROM announcements WHERE id IN ({placeholders}) AND geo_grade = 'E' AND (geo_json IS NULL OR geo_json = '')",
        list(imported_ids),
    ).fetchone()[0]

    # 状态分布
    status_rows = db.execute(
        "SELECT time_status, COUNT(*) as cnt FROM announcements GROUP BY time_status ORDER BY cnt DESC"
    ).fetchall()
    status_dist = {r[0]: r[1] for r in status_rows}

    # 管控类型分布
    type_rows = db.execute(
        "SELECT control_type, COUNT(*) as cnt FROM announcements GROUP BY control_type ORDER BY cnt DESC"
    ).fetchall()
    type_dist = {r[0]: r[1] for r in type_rows}

    # geo_grade 分布
    grade_rows = db.execute(
        "SELECT geo_grade, COUNT(*) as cnt FROM announcements GROUP BY geo_grade ORDER BY geo_grade"
    ).fetchall()
    grade_dist = {r[0]: r[1] for r in grade_rows}

    # 待核验
    needs_review_count = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE needs_review = 1"
    ).fetchone()[0]

    db.close()

    # ── 输出报告 ──────────────────────────────────────────
    passed = (
        imported_total >= 116
        and imported_published >= 116
        and imported_with_geo == 96
        and imported_e_no_geo == 20
    )

    print("\n" + "=" * 64)
    print("  导入报告")
    print("=" * 64)
    print(f"  SQLite announcements 总数 (含存量) : {total}")
    print(f"  本次导入记录数                     : {imported_total}")
    print(f"  其中 published                     : {imported_published}")
    print(f"  其中有 geo_json                    : {imported_with_geo}")
    print(f"  其中 geo_grade=E 且无 geo_json     : {imported_e_no_geo}")
    print(f"  待核验 (needs_review=true)         : {needs_review_count}")
    print()
    print("  ── 时间状态分布 ──")
    for status, cnt in sorted(status_dist.items()):
        print(f"    {status:<16}: {cnt}")
    print()
    print("  ── 管控类型分布 ──")
    for ct, cnt in sorted(type_dist.items()):
        print(f"    {ct:<16}: {cnt}")
    print()
    print("  ── 地理精度分布 ──")
    for grade, cnt in sorted(grade_dist.items()):
        print(f"    {grade:<16}: {cnt}")
    print()
    print("  ── 已知风险 ──")
    # 无标题的公告
    no_title = sum(1 for r in records if not r["title"])
    print(f"    无标题公告                      : {no_title}")
    # 无 evidence_text
    no_evidence = sum(1 for r in records if not r["evidence_text"])
    print(f"    无证据文本公告                  : {no_evidence}")
    # 无 source_url
    no_url = sum(1 for r in records if not r["source_url"])
    print(f"    无 source_url 公告              : {no_url}")
    # UNKNOWN 时间状态
    print(f"    time_status=unknown             : {status_dist.get('unknown', 0)}")
    print(f"    time_status=inactive (周期性)    : {status_dist.get('inactive', 0)}")
    print()

    if passed:
        print("  [PASS] All verification checks passed!")
    else:
        print("  [FAIL] Verification failed, check discrepancies:")
        if imported_total < 116:
            print(f"     - imported total < 116, actual: {imported_total}")
        if imported_published < 116:
            print(f"     - imported published < 116, actual: {imported_published}")
        if imported_with_geo != 96:
            print(f"     - imported with_geo expected 96, actual: {imported_with_geo}")
        if imported_e_no_geo != 20:
            print(f"     - imported E no_geo expected 20, actual: {imported_e_no_geo}")

    print("=" * 64)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
