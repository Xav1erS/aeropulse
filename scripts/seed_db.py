"""种子数据迁移脚本：将 data/announcements_seed.json 迁移到 SQLite。

生成对应的 DataSource + IngestionTask + Announcement 记录。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保项目根在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from web.api import store

SEED_PATH = _PROJECT_ROOT / "data" / "announcements_seed.json"


def migrate():
    if not SEED_PATH.exists():
        print(f"种子数据文件不存在：{SEED_PATH}")
        return

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    print(f"共 {len(seed)} 条种子公告")

    for ann in seed:
        ann_id = ann["id"]
        source_name = ann.get("source_name", "未知来源")
        source_url = ann.get("source_url", "")
        source_level = ann.get("source_level", "P2")

        # 1. 创建或更新 DataSource
        src_id = f"src_{ann_id}"
        existing_src = store.get_data_source(src_id)
        if not existing_src:
            store.create_data_source({
                "id": src_id,
                "source_name": source_name,
                "source_url": source_url,
                "source_type": "government_website" if source_level == "P0" else "official_media",
                "source_level": source_level,
                "source_trust_score": {"P0": 0.95, "P1": 0.8, "P2": 0.6, "P3": 0.4}.get(source_level, 0.5),
                "coverage_area": ann.get("city", ""),
                "coverage_level": "city",
                "province": "山东省",
                "city": ann.get("city", ""),
                "keywords": ["无人机", "低慢小", "禁飞", "管控"],
                "crawl_mode": "manual_trigger",
                "enabled": True,
            })
            print(f"  [DataSource] 新建 {src_id}: {source_name}")

        # 2. 创建 IngestionTask（标记为已完成）
        task_id = f"task_{ann_id}"
        existing_task = store.get_ingestion_task(task_id)
        if not existing_task:
            task = store.create_ingestion_task({
                "id": task_id,
                "submit_channel": "auto",
                "submission_type": "text",
                "source_id": src_id,
                "source_name": source_name,
                "source_url": source_url,
                "raw_text": ann.get("evidence_text", ""),
                "task_status": "approved",
                "review_status": "approved",
                "map_preview_status": "generated",
                "created_by": "seed_migration",
            })
            # 更新抽取结果
            store.update_ingestion_task(task_id, {
                "classification_result": _map_control_type_to_classification(ann.get("control_type", "")),
                "is_relevant": True,
                "parse_confidence": ann.get("confidence_score", 0.9),
                "geo_confidence": ann.get("geo", {}).get("geo_confidence", ann.get("confidence_score", 0.9)),
                "time_parse_status": "success",
                "extracted_json": json.dumps(ann, ensure_ascii=False),
            })
            print(f"  [Task] 新建 {task_id}")

        # 3. 创建 Announcement（已发布）
        existing_ann = store.get_announcement(ann_id)
        if not existing_ann:
            geo = ann.get("geo") or {}
            time_info = ann.get("time") or {}
            store.create_announcement({
                "id": ann_id,
                "source_task_id": task_id,
                "extraction_method": "manual",
                "title": ann.get("title", ""),
                "publish_unit": ann.get("publish_unit", ""),
                "source_name": source_name,
                "source_url": source_url,
                "source_level": source_level,
                "source_trust_score": {"P0": 0.95, "P1": 0.8, "P2": 0.6, "P3": 0.4}.get(source_level, 0.5),
                "publish_time": ann.get("publish_time"),
                "province": "山东省",
                "city": ann.get("city", ""),
                "control_type": ann.get("control_type", "临时管控"),
                "risk_class": ann.get("risk_class", "control"),
                "time_status": "unknown",
                "start_time": time_info.get("start"),
                "end_time": time_info.get("end"),
                "time_mode": time_info.get("mode", "single"),
                "time_windows": time_info.get("windows"),
                "area_text": ann.get("area_text", ""),
                "geo_type": geo.get("geo_type", "fuzzy"),
                "center_poi": geo.get("poi"),
                "poi_list": geo.get("poi_list"),
                "radius_meters": geo.get("radius_m") or geo.get("radius_estimated"),
                "geo_note": geo.get("note"),
                "roster_status": geo.get("roster_status"),
                "aircraft_types": ann.get("aircraft_types"),
                "evidence_text": ann.get("evidence_text", ""),
                "confidence_score": ann.get("confidence_score", 0),
                "needs_review": False,
                "review_status": "approved",
                "review_reason": "种子数据，已人工验证",
                "map_layer_status": "published",
            })
            print(f"  [Announcement] 新建 {ann_id}: {ann.get('title', '')[:30]}...")

    # 输出统计
    stats = store.get_stats_overview()
    print(f"\n迁移完成！")
    print(f"  数据源: {stats['enabled_sources']} 个")
    print(f"  入库任务: {stats['candidate_tasks']} 条")
    print(f"  已发布图层: {stats['published_layers']} 个")


def _map_control_type_to_classification(control_type: str) -> str:
    mapping = {
        "临时禁飞": "TEMP_NO_FLY",
        "临时空域管制": "TEMP_NO_FLY",
        "临时管控": "TEMP_CONTROL",
        "备案通知": "REGISTRATION_NOTICE",
        "安全提醒": "SAFETY_REMINDER",
    }
    return mapping.get(control_type, "TEMP_CONTROL")


if __name__ == "__main__":
    migrate()
