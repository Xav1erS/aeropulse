"""SQLite 数据访问层：DataSource / IngestionTask / Announcement CRUD。

设计原则：
- 单文件 SQLite（data/aeropulse.db），PoC 零配置
- 所有字段对齐 SPEC 数据模型（§4.1–§4.3）
- 时间统一 Asia/Shanghai
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

CST = timezone(timedelta(hours=8))

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "aeropulse.db"


def _now() -> str:
    return datetime.now(CST).isoformat()


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db() -> None:
    """创建所有表（幂等）。"""
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS data_sources (
        id TEXT PRIMARY KEY,
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'government_website',
        source_level TEXT NOT NULL DEFAULT 'P2',
        source_trust_score REAL NOT NULL DEFAULT 0.5,
        coverage_area TEXT,
        coverage_level TEXT,
        province TEXT,
        city TEXT,
        district TEXT,
        keywords TEXT DEFAULT '[]',
        crawl_mode TEXT NOT NULL DEFAULT 'manual_trigger',
        last_crawled_at TEXT,
        last_crawl_status TEXT,
        valid_announcement_count INTEGER NOT NULL DEFAULT 0,
        pending_review_count INTEGER NOT NULL DEFAULT 0,
        anomaly_count INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ingestion_tasks (
        id TEXT PRIMARY KEY,
        submit_channel TEXT NOT NULL DEFAULT 'manual',
        submission_type TEXT NOT NULL DEFAULT 'text',
        source_id TEXT,
        source_name TEXT NOT NULL,
        source_url TEXT,
        raw_text TEXT NOT NULL,
        task_status TEXT NOT NULL DEFAULT 'submitted',
        classification_result TEXT,
        is_relevant INTEGER,
        parse_confidence REAL,
        geo_confidence REAL,
        time_parse_status TEXT,
        review_status TEXT NOT NULL DEFAULT 'pending_confirm',
        review_reason TEXT,
        map_preview_status TEXT NOT NULL DEFAULT 'not_generated',
        extracted_json TEXT,
        geo_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by TEXT
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id TEXT PRIMARY KEY,
        source_task_id TEXT NOT NULL,
        extraction_method TEXT NOT NULL DEFAULT 'manual',
        title TEXT NOT NULL,
        publish_unit TEXT,
        source_name TEXT NOT NULL,
        source_url TEXT,
        source_level TEXT NOT NULL DEFAULT 'P2',
        source_trust_score REAL NOT NULL DEFAULT 0.5,
        publish_time TEXT,
        last_checked_at TEXT NOT NULL,
        province TEXT,
        city TEXT,
        district TEXT,
        control_type TEXT NOT NULL DEFAULT '临时管控',
        risk_class TEXT NOT NULL DEFAULT 'control',
        time_status TEXT NOT NULL DEFAULT 'unknown',
        start_time TEXT,
        end_time TEXT,
        time_mode TEXT,
        time_windows TEXT,
        validity_basis TEXT,
        area_text TEXT NOT NULL DEFAULT '',
        geo_type TEXT NOT NULL DEFAULT 'fuzzy',
        center_poi TEXT,
        poi_list TEXT,
        radius_meters INTEGER,
        district_name TEXT,
        geo_json TEXT,
        geo_confidence REAL NOT NULL DEFAULT 0.0,
        geo_grade TEXT NOT NULL DEFAULT 'E',
        geo_note TEXT,
        roster_status TEXT,
        aircraft_types TEXT,
        evidence_text TEXT,
        evidence_time TEXT,
        evidence_area TEXT,
        evidence_control_type TEXT,
        confidence_score REAL NOT NULL DEFAULT 0.0,
        needs_review INTEGER NOT NULL DEFAULT 1,
        review_status TEXT NOT NULL DEFAULT 'pending_confirm',
        review_reason TEXT,
        map_layer_status TEXT NOT NULL DEFAULT 'not_published',
        duplicate_group_id TEXT,
        version_id TEXT NOT NULL DEFAULT 'v1',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS map_layers (
        id TEXT PRIMARY KEY,
        announcement_id TEXT NOT NULL,
        layer_name TEXT NOT NULL,
        geo_json TEXT,
        geo_type TEXT,
        center_poi TEXT,
        radius_meters INTEGER,
        district_name TEXT,
        geo_confidence REAL DEFAULT 0.0,
        geo_grade TEXT DEFAULT 'E',
        validity_start TEXT,
        validity_end TEXT,
        layer_status TEXT NOT NULL DEFAULT 'draft',
        published_at TEXT,
        paused_at TEXT,
        archived_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (announcement_id) REFERENCES announcements(id)
    );

    CREATE INDEX IF NOT EXISTS idx_tasks_status ON ingestion_tasks(task_status);
    CREATE INDEX IF NOT EXISTS idx_tasks_review ON ingestion_tasks(review_status);
    CREATE INDEX IF NOT EXISTS idx_ann_map ON announcements(map_layer_status);
    CREATE INDEX IF NOT EXISTS idx_ann_time ON announcements(time_status);
    CREATE INDEX IF NOT EXISTS idx_ann_start ON announcements(start_time);
    CREATE INDEX IF NOT EXISTS idx_ann_end ON announcements(end_time);
    CREATE INDEX IF NOT EXISTS idx_ann_province ON announcements(province);
    CREATE INDEX IF NOT EXISTS idx_ann_city ON announcements(city);
    CREATE INDEX IF NOT EXISTS idx_layers_status ON map_layers(layer_status);
    CREATE INDEX IF NOT EXISTS idx_layers_ann ON map_layers(announcement_id);
    """)

    # 安全迁移：添加 ann_status 列（SQLite 3.35+）
    try:
        db.execute("ALTER TABLE announcements ADD COLUMN ann_status TEXT DEFAULT 'pending'")
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 迁移已有公告：如果 ann_status 为 NULL，根据 review_status 设置默认值
    db.execute("""
        UPDATE announcements SET ann_status = 'confirmed' 
        WHERE (ann_status IS NULL OR ann_status = '') AND review_status = 'approved'
    """)
    db.execute("""
        UPDATE announcements SET ann_status = 'pending'
        WHERE (ann_status IS NULL OR ann_status = '')
    """)
    db.commit()
    db.close()


# ─── DataSource ───────────────────────────────────────────

def list_data_sources(
    province: str | None = None,
    source_level: str | None = None,
    enabled: bool | None = None,
) -> list[dict]:
    db = get_db()
    where = ["1=1"]
    params: list = []
    if province:
        where.append("province = ?")
        params.append(province)
    if source_level:
        where.append("source_level = ?")
        params.append(source_level)
    if enabled is not None:
        where.append("enabled = ?")
        params.append(1 if enabled else 0)
    rows = db.execute(
        f"SELECT * FROM data_sources WHERE {' AND '.join(where)} ORDER BY source_level, source_name",
        params,
    ).fetchall()
    db.close()
    return [_row_to_dict(r) for r in rows]


def get_data_source(source_id: str) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM data_sources WHERE id = ?", [source_id]).fetchone()
    db.close()
    return _row_to_dict(row) if row else None


def update_data_source(source_id: str, updates: dict) -> dict | None:
    existing = get_data_source(source_id)
    if not existing:
        return None
    allowed = {"enabled", "source_name", "source_url", "source_type", "source_level",
               "source_trust_score", "coverage_area", "coverage_level", "province", "city",
               "district", "keywords", "crawl_mode", "last_crawled_at", "last_crawl_status",
               "valid_announcement_count", "pending_review_count", "anomaly_count"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return existing
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [source_id]
    db = get_db()
    db.execute(f"UPDATE data_sources SET {set_clause} WHERE id = ?", values)
    db.commit()
    db.close()
    return get_data_source(source_id)


def create_data_source(data: dict) -> dict:
    now = _now()
    src_id = data.get("id") or f"src_{now[:10]}_{_next_seq('data_sources')}"
    db = get_db()
    db.execute(
        """INSERT INTO data_sources (id, source_name, source_url, source_type, source_level,
           source_trust_score, coverage_area, coverage_level, province, city, district,
           keywords, crawl_mode, enabled, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            src_id,
            data["source_name"],
            data["source_url"],
            data.get("source_type", "government_website"),
            data.get("source_level", "P2"),
            data.get("source_trust_score", 0.5),
            data.get("coverage_area", ""),
            data.get("coverage_level", ""),
            data.get("province", ""),
            data.get("city", ""),
            data.get("district", ""),
            json.dumps(data.get("keywords", [])),
            data.get("crawl_mode", "manual_trigger"),
            1 if data.get("enabled", True) else 0,
            now, now,
        ],
    )
    db.commit()
    db.close()
    return get_data_source(src_id)


# ─── IngestionTask ───────────────────────────────────────

def list_ingestion_tasks(
    task_status: str | None = None,
    review_status: str | None = None,
    submit_channel: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    db = get_db()
    where = ["1=1"]
    params: list = []
    if task_status:
        where.append("task_status = ?")
        params.append(task_status)
    if review_status:
        where.append("review_status = ?")
        params.append(review_status)
    if submit_channel:
        where.append("submit_channel = ?")
        params.append(submit_channel)
    clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM ingestion_tasks WHERE {clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM ingestion_tasks WHERE {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    db.close()
    return [_row_to_dict(r) for r in rows], total


def get_ingestion_task(task_id: str) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM ingestion_tasks WHERE id = ?", [task_id]).fetchone()
    db.close()
    return _row_to_dict(row) if row else None


def create_ingestion_task(data: dict) -> dict:
    now = _now()
    task_id = data.get("id") or f"task_{now[:10]}_{_next_seq('ingestion_tasks')}"
    db = get_db()
    db.execute(
        """INSERT INTO ingestion_tasks (id, submit_channel, submission_type, source_id,
           source_name, source_url, raw_text, task_status, review_status,
           map_preview_status, created_at, updated_at, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            task_id,
            data.get("submit_channel", "manual"),
            data.get("submission_type", "text"),
            data.get("source_id"),
            data.get("source_name", "未知来源"),
            data.get("source_url"),
            data.get("raw_text", ""),
            data.get("task_status", "submitted"),
            data.get("review_status", "pending_confirm"),
            "not_generated",
            now, now,
            data.get("created_by"),
        ],
    )
    db.commit()
    db.close()
    return get_ingestion_task(task_id)


def update_ingestion_task(task_id: str, updates: dict) -> dict | None:
    existing = get_ingestion_task(task_id)
    if not existing:
        return None
    allowed = {"task_status", "classification_result", "is_relevant", "parse_confidence",
               "geo_confidence", "time_parse_status", "review_status", "review_reason",
               "map_preview_status", "extracted_json", "geo_json", "source_name", "source_url"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return existing
    # 布尔转 int
    for k in ("is_relevant",):
        if k in fields and isinstance(fields[k], bool):
            fields[k] = 1 if fields[k] else 0
    # dict/list 转 json
    for k in ("extracted_json", "geo_json"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    db = get_db()
    db.execute(f"UPDATE ingestion_tasks SET {set_clause} WHERE id = ?", values)
    db.commit()
    db.close()
    return get_ingestion_task(task_id)


# ─── Announcement ────────────────────────────────────────

def list_announcements(
    map_layer_status: str | None = None,
    time_status: str | None = None,
    control_type: str | None = None,
    province: str | None = None,
    city: str | None = None,
    ann_status: str | None = None,
    limit: int = 500,
) -> list[dict]:
    db = get_db()
    where = ["1=1"]
    params: list = []
    if map_layer_status:
        where.append("map_layer_status = ?")
        params.append(map_layer_status)
    if time_status:
        where.append("time_status = ?")
        params.append(time_status)
    if control_type:
        where.append("control_type = ?")
        params.append(control_type)
    if province:
        where.append("province = ?")
        params.append(province)
    if city:
        where.append("city = ?")
        params.append(city)
    if ann_status:
        where.append("ann_status = ?")
        params.append(ann_status)
    rows = db.execute(
        f"SELECT * FROM announcements WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    db.close()
    return [_row_to_dict(r) for r in rows]


def list_announcements_time_range(
    map_layer_status: str = "published",
    province: str | None = None,
    city: str | None = None,
) -> tuple[list[dict], dict]:
    """获取公告时间范围摘要，用于时间轴自适应范围计算。
    
    返回: (公告列表(仅含id/title/control_type/start_time/end_time/time_mode), 
           {min_start, max_end, total_count})
    """
    db = get_db()
    where = ["map_layer_status = ?"]
    params: list = [map_layer_status]
    if province:
        where.append("province = ?")
        params.append(province)
    if city:
        where.append("city = ?")
        params.append(city)
    
    clause = " AND ".join(where)
    
    # 获取时间范围
    range_row = db.execute(
        f"""SELECT 
            MIN(start_time) as min_start,
            MAX(CASE WHEN end_time IS NOT NULL THEN end_time ELSE start_time END) as max_end,
            COUNT(*) as total_count
        FROM announcements WHERE {clause}""",
        params,
    ).fetchone()
    
    # 获取轻量公告列表（不含geo_json）
    rows = db.execute(
        f"""SELECT id, title, control_type, start_time, end_time, time_mode,
                   time_status, source_name, province, city
        FROM announcements WHERE {clause}
        ORDER BY start_time ASC""",
        params,
    ).fetchall()
    
    db.close()
    
    announcements = []
    for r in rows:
        announcements.append({
            "id": r["id"],
            "title": r["title"],
            "control_type": r["control_type"],
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "time_mode": r["time_mode"],
            "time_status": r["time_status"],
            "source_name": r["source_name"],
            "province": r["province"],
            "city": r["city"],
        })
    
    range_info = {
        "min_start": range_row["min_start"],
        "max_end": range_row["max_end"],
        "total_count": range_row["total_count"],
    }
    return announcements, range_info


def get_announcement(ann_id: str) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM announcements WHERE id = ?", [ann_id]).fetchone()
    db.close()
    return _row_to_dict(row) if row else None


def get_announcement_by_task(source_task_id: str) -> dict | None:
    db = get_db()
    row = db.execute(
        "SELECT * FROM announcements WHERE source_task_id = ? ORDER BY updated_at DESC LIMIT 1",
        [source_task_id],
    ).fetchone()
    db.close()
    return _row_to_dict(row) if row else None


def create_announcement(data: dict) -> dict:
    now = _now()
    ann_id = data.get("id") or f"ann_{now[:10]}_{_next_seq('announcements')}"
    db = get_db()
    db.execute(
        """INSERT INTO announcements (id, source_task_id, extraction_method, title,
           publish_unit, source_name, source_url, source_level, source_trust_score,
           publish_time, last_checked_at, province, city, district,
           control_type, risk_class, time_status, start_time, end_time,
           time_mode, time_windows, validity_basis, area_text,
           geo_type, center_poi, poi_list, radius_meters, district_name,
           geo_json, geo_confidence, geo_grade, geo_note, roster_status,
           aircraft_types, evidence_text, evidence_time, evidence_area,
           evidence_control_type, confidence_score, needs_review, review_status,
           review_reason, map_layer_status, duplicate_group_id, version_id,
           ann_status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            ann_id,
            data["source_task_id"],
            data.get("extraction_method", "manual"),
            data.get("title", ""),
            data.get("publish_unit", ""),
            data.get("source_name", ""),
            data.get("source_url", ""),
            data.get("source_level", "P2"),
            data.get("source_trust_score", 0.5),
            data.get("publish_time"),
            now,
            data.get("province"),
            data.get("city"),
            data.get("district"),
            data.get("control_type", "临时管控"),
            data.get("risk_class", "control"),
            data.get("time_status", "unknown"),
            data.get("start_time"),
            data.get("end_time"),
            data.get("time_mode"),
            json.dumps(data.get("time_windows")) if data.get("time_windows") else None,
            data.get("validity_basis"),
            data.get("area_text", ""),
            data.get("geo_type", "fuzzy"),
            data.get("center_poi"),
            json.dumps(data.get("poi_list")) if data.get("poi_list") else None,
            data.get("radius_meters"),
            data.get("district_name"),
            json.dumps(data.get("geo_json")) if data.get("geo_json") else None,
            data.get("geo_confidence", 0.0),
            data.get("geo_grade", "E"),
            data.get("geo_note"),
            data.get("roster_status"),
            json.dumps(data.get("aircraft_types")) if data.get("aircraft_types") else None,
            data.get("evidence_text", ""),
            data.get("evidence_time"),
            data.get("evidence_area"),
            data.get("evidence_control_type"),
            data.get("confidence_score", 0.0),
            1 if data.get("needs_review", True) else 0,
            data.get("review_status", "pending_confirm"),
            data.get("review_reason"),
            data.get("map_layer_status", "not_published"),
            data.get("duplicate_group_id"),
            data.get("version_id", "v1"),
            data.get("ann_status", "pending"),
            now, now,
        ],
    )
    db.commit()
    db.close()
    return get_announcement(ann_id)


def update_announcement(ann_id: str, updates: dict) -> dict | None:
    existing = get_announcement(ann_id)
    if not existing:
        return None
    allowed = {"title", "publish_unit", "source_name", "source_url", "source_level",
               "source_trust_score", "publish_time", "province", "city", "district",
               "control_type", "risk_class", "time_status", "start_time", "end_time",
               "time_mode", "time_windows", "validity_basis", "area_text",
               "geo_type", "center_poi", "poi_list", "radius_meters", "district_name",
               "geo_json", "geo_confidence", "geo_grade", "geo_note", "roster_status",
               "aircraft_types", "evidence_text", "evidence_time", "evidence_area",
               "evidence_control_type", "confidence_score", "needs_review",
               "review_status", "review_reason", "map_layer_status",
               "duplicate_group_id", "version_id", "ann_status"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return existing
    for k in ("needs_review",):
        if k in fields and isinstance(fields[k], bool):
            fields[k] = 1 if fields[k] else 0
    for k in ("time_windows", "poi_list", "geo_json", "aircraft_types"):
        if k in fields and fields[k] is not None and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [ann_id]
    db = get_db()
    db.execute(f"UPDATE announcements SET {set_clause} WHERE id = ?", values)
    db.commit()
    db.close()
    return get_announcement(ann_id)




# ─── MapLayer ────────────────────────────────────────────

def list_layers(
    layer_status: str | None = None,
    control_type: str | None = None,
    geo_grade: str | None = None,
    province: str | None = None,
    city: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    db = get_db()
    where = ["1=1"]
    params: list = []
    if layer_status:
        where.append("ml.layer_status = ?")
        params.append(layer_status)
    if control_type:
        where.append("a.control_type = ?")
        params.append(control_type)
    if geo_grade:
        where.append("ml.geo_grade = ?")
        params.append(geo_grade)
    if province:
        where.append("a.province = ?")
        params.append(province)
    if city:
        where.append("a.city = ?")
        params.append(city)
    clause = " AND ".join(where)
    total = db.execute(
        f"""SELECT COUNT(*) FROM map_layers ml 
        LEFT JOIN announcements a ON ml.announcement_id = a.id 
        WHERE {clause}""",
        params,
    ).fetchone()[0]
    rows = db.execute(
        f"""SELECT ml.*, a.title as ann_title, a.control_type as ann_control_type, 
        a.province as ann_province, a.city as ann_city, a.source_name as ann_source_name,
        a.start_time as ann_start_time, a.end_time as ann_end_time
        FROM map_layers ml 
        LEFT JOIN announcements a ON ml.announcement_id = a.id 
        WHERE {clause} ORDER BY ml.created_at DESC LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    db.close()
    items = [_row_to_dict(r) for r in rows]
    return items, total


def get_layer(layer_id: str) -> dict | None:
    db = get_db()
    row = db.execute(
        """SELECT ml.*, a.title as ann_title, a.control_type as ann_control_type, 
        a.province as ann_province, a.city as ann_city, a.source_name as ann_source_name,
        a.start_time as ann_start_time, a.end_time as ann_end_time
        FROM map_layers ml 
        LEFT JOIN announcements a ON ml.announcement_id = a.id 
        WHERE ml.id = ?""",
        [layer_id],
    ).fetchone()
    db.close()
    return _row_to_dict(row) if row else None


def get_layers_by_announcement(ann_id: str) -> list[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM map_layers WHERE announcement_id = ? ORDER BY created_at ASC",
        [ann_id],
    ).fetchall()
    db.close()
    return [_row_to_dict(r) for r in rows]


def create_layer(data: dict) -> dict:
    now = _now()
    layer_id = data.get("id") or f"layer_{now[:10]}_{_next_seq('map_layers')}"
    db = get_db()
    db.execute(
        """INSERT INTO map_layers (id, announcement_id, layer_name, geo_json, geo_type,
           center_poi, radius_meters, district_name, geo_confidence, geo_grade,
           validity_start, validity_end, layer_status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            layer_id,
            data["announcement_id"],
            data.get("layer_name", ""),
            json.dumps(data.get("geo_json")) if data.get("geo_json") and not isinstance(data.get("geo_json"), str) else data.get("geo_json"),
            data.get("geo_type", ""),
            data.get("center_poi"),
            data.get("radius_meters"),
            data.get("district_name"),
            data.get("geo_confidence", 0.0),
            data.get("geo_grade", "E"),
            data.get("validity_start"),
            data.get("validity_end"),
            data.get("layer_status", "draft"),
            now, now,
        ],
    )
    db.commit()
    db.close()
    return get_layer(layer_id)


def update_layer(layer_id: str, updates: dict) -> dict | None:
    existing = get_layer(layer_id)
    if not existing:
        return None
    allowed = {"layer_name", "geo_json", "geo_type", "center_poi", "radius_meters",
               "district_name", "geo_confidence", "geo_grade", "validity_start",
               "validity_end", "layer_status", "published_at", "paused_at", "archived_at"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return existing
    # geo_json 转字符串
    if "geo_json" in fields and fields["geo_json"] is not None and not isinstance(fields["geo_json"], str):
        fields["geo_json"] = json.dumps(fields["geo_json"], ensure_ascii=False)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [layer_id]
    db = get_db()
    db.execute(f"UPDATE map_layers SET {set_clause} WHERE id = ?", values)
    db.commit()
    db.close()
    return get_layer(layer_id)


def get_published_layers_geojson(now_iso: str | None = None) -> list[dict]:
    """获取当前已发布且时间有效的图层 GeoJSON（供地图页使用）。"""
    if now_iso is None:
        now_iso = _now()
    db = get_db()
    rows = db.execute(
        """SELECT ml.*, a.title as ann_title, a.control_type as ann_control_type,
        a.source_name as ann_source_name, a.source_level, a.province, a.city,
        a.start_time as ann_start_time, a.end_time as ann_end_time,
        a.evidence_text, a.publish_unit, a.time_mode
        FROM map_layers ml 
        LEFT JOIN announcements a ON ml.announcement_id = a.id 
        WHERE ml.layer_status = 'published'
        ORDER BY ml.created_at DESC""",
    ).fetchall()
    db.close()

    result = []
    for r in rows:
        d = _row_to_dict(r)
        # 时间过滤
        start = d.get("validity_start") or d.get("ann_start_time")
        end = d.get("validity_end") or d.get("ann_end_time")
        if end and end < now_iso:
            continue  # expired
        d["start_time"] = start
        d["end_time"] = end
        d["title"] = d.get("ann_title", "")
        d["control_type"] = d.get("ann_control_type", "")
        result.append(d)
    return result


# ─── Stats ───────────────────────────────────────────────

def get_stats_overview() -> dict:
    db = get_db()
    # 数据源
    enabled_sources = db.execute("SELECT COUNT(*) FROM data_sources WHERE enabled = 1").fetchone()[0]
    source_anomalies = db.execute("SELECT COALESCE(SUM(anomaly_count), 0) FROM data_sources").fetchone()[0]

    # announcements 表（聚合后公告，含批量导入 + 手工审批生成）
    total_announcements = db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
    pending_announcements = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE ann_status = 'pending'"
    ).fetchone()[0]
    confirmed_announcements = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE ann_status = 'confirmed'"
    ).fetchone()[0]
    conflict_announcements = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE ann_status = 'conflict'"
    ).fetchone()[0]
    evidence_missing_ann = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE ann_status = 'evidence_missing'"
    ).fetchone()[0]
    
    # 旧 map_layer_status 兼容统计
    published_layers_old = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE map_layer_status = 'published'"
    ).fetchone()[0]
    
    # map_layers 表统计
    published_layers = db.execute(
        "SELECT COUNT(*) FROM map_layers WHERE layer_status = 'published'"
    ).fetchone()[0]
    draft_layers = db.execute(
        "SELECT COUNT(*) FROM map_layers WHERE layer_status = 'draft'"
    ).fetchone()[0]
    paused_layers = db.execute(
        "SELECT COUNT(*) FROM map_layers WHERE layer_status = 'paused'"
    ).fetchone()[0]
    archived_layers = db.execute(
        "SELECT COUNT(*) FROM map_layers WHERE layer_status = 'archived'"
    ).fetchone()[0]
    
    now = _now()
    upcoming_active_layers = db.execute(
        "SELECT COUNT(*) FROM map_layers WHERE layer_status = 'published' AND validity_start IS NOT NULL AND validity_start > ?",
        [now],
    ).fetchone()[0]
    expired_layers_count = db.execute(
        "SELECT COUNT(*) FROM map_layers WHERE layer_status = 'published' AND validity_end IS NOT NULL AND validity_end < ?",
        [now],
    ).fetchone()[0]

    ann_pending_review = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE needs_review = 1"
    ).fetchone()[0]
    layers_without_evidence = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE map_layer_status = 'published' AND (evidence_text IS NULL OR evidence_text = '')"
    ).fetchone()[0]
    bulk_imported = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE extraction_method = 'seed_bulk_import'"
    ).fetchone()[0]
    ann_geo_grade_e = db.execute(
        "SELECT COUNT(*) FROM announcements WHERE geo_grade = 'E' AND (geo_json IS NULL OR geo_json = '')"
    ).fetchone()[0]

    # ingestion_tasks 表
    ingestion_total = db.execute("SELECT COUNT(*) FROM ingestion_tasks").fetchone()[0]
    ingestion_pending = db.execute(
        "SELECT COUNT(*) FROM ingestion_tasks WHERE review_status = 'pending_confirm'"
    ).fetchone()[0]
    total_parsed = db.execute(
        "SELECT COUNT(*) FROM ingestion_tasks WHERE task_status IN ('parsed','approved','published')"
    ).fetchone()[0]
    parse_success = db.execute(
        "SELECT COUNT(*) FROM ingestion_tasks WHERE task_status = 'parsed' AND parse_confidence IS NOT NULL"
    ).fetchone()[0]
    parse_success_rate = (parse_success / total_parsed) if total_parsed > 0 else 0.0

    # 当前时间有效性统计（map_layers 表）
    active_layers = published_layers - expired_layers_count

    # 有效公告数
    valid_announcements = confirmed_announcements

    # 合并统计
    pending_review = ann_pending_review + ingestion_pending

    db.close()
    return {
        "enabled_sources": enabled_sources,
        "candidate_tasks": total_announcements + ingestion_total,
        "valid_announcements": valid_announcements,
        "pending_review": pending_review,
        "pending_announcements": pending_announcements,
        "published_layers": max(published_layers, published_layers_old),
        "active_layers": active_layers,
        "expired_layers": expired_layers_count,
        "not_started_layers": 0,
        "parse_success_count": parse_success,
        "parse_success_total": total_parsed,
        "parse_success_rate": round(parse_success_rate, 2),
        "layers_without_evidence": layers_without_evidence,
        "source_anomaly_count": source_anomalies,
        "overreach_text_count": 0,
        "bulk_imported": bulk_imported,
        "ann_geo_grade_e": ann_geo_grade_e,
        "ann_pending_review": ann_pending_review,
        "ingestion_pending": ingestion_pending,
        "ingestion_total": ingestion_total,
        "draft_layers": draft_layers,
        "paused_layers": paused_layers,
        "conflict_announcements": conflict_announcements,
        "evidence_missing_ann": evidence_missing_ann,
        "upcoming_active_layers": upcoming_active_layers,
        "updated_at": now,
    }


# ─── Helpers ─────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # JSON 字段还原
    for k in ("keywords", "time_windows", "poi_list", "aircraft_types", "geo_json", "extracted_json"):
        if k in d and d[k] is not None:
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    # int 布尔字段还原
    for k in ("enabled", "is_relevant", "needs_review"):
        if k in d and d[k] is not None:
            d[k] = bool(d[k])
    return d


def get_announcements_with_ann_status(
    ann_status: str | None = None,
    control_type: str | None = None,
    province: str | None = None,
    city: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """获取公告列表（带 ann_status 筛选，支持分页）。"""
    db = get_db()
    where = ["1=1"]
    params: list = []
    if ann_status:
        where.append("a.ann_status = ?")
        params.append(ann_status)
    if control_type:
        where.append("a.control_type = ?")
        params.append(control_type)
    if province:
        where.append("a.province = ?")
        params.append(province)
    if city:
        where.append("a.city = ?")
        params.append(city)
    clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM announcements a WHERE {clause}", params).fetchone()[0]
    rows = db.execute(
        f"""SELECT a.*, (SELECT COUNT(*) FROM map_layers ml WHERE ml.announcement_id = a.id) as layer_count
        FROM announcements a WHERE {clause} ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    db.close()
    items = [_row_to_dict(r) for r in rows]
    return items, total


def _next_seq(table: str) -> int:
    db = get_db()
    row = db.execute(f"SELECT COUNT(*) + 1 FROM {table}").fetchone()
    db.close()
    return row[0]


# 启动时自动初始化
init_db()
