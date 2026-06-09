"""AI 管线集成 — 将 extraction_agent + geoparse + temporal 串联。

用于 API 层的异步任务编排。PoC 阶段使用同步调用（单条 <30s），
后续可扩展为 BackgroundTasks / Celery。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# 确保 geo_radar 可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


def process_ingestion_task(task_id: str, api_base_url: str = "") -> dict:
    """对一条入库任务执行完整 AI 管线：LLM抽取 → 地理编码 → 时间归一化。

    Args:
        task_id: 入库任务 ID
        api_base_url: 回调 URL（预留）

    Returns:
        处理结果摘要
    """
    from . import store

    task = store.get_ingestion_task(task_id)
    if not task:
        return {"success": False, "error": "任务不存在"}

    raw_text = task.get("raw_text", "")
    if not raw_text.strip():
        store.update_ingestion_task(task_id, {
            "task_status": "rejected",
            "review_reason": "公告正文为空",
        })
        return {"success": False, "error": "公告正文为空"}

    # Step 1: 更新状态为处理中
    store.update_ingestion_task(task_id, {"task_status": "classifying"})

    # Step 2: LLM 抽取
    result = None
    try:
        from geo_radar import extraction_agent

        result = extraction_agent.extract_from_text(
            body_text=raw_text,
            source_name=task.get("source_name", ""),
            source_url=task.get("source_url", ""),
            source_level="P2",
            city="",
            client=extraction_agent.LLMClient(),
        )
    except Exception as exc:
        logger.error(f"LLM 抽取失败 task={task_id}: {exc}")
        store.update_ingestion_task(task_id, {
            "task_status": "needs_review",
            "review_status": "pending_confirm",
            "review_reason": f"LLM 抽取异常：{exc}",
        })
        return {"success": False, "error": str(exc)}

    # Step 3: 保存抽取结果
    extracted_dict = result.to_announcement_dict(f"ext_{task_id}")
    store.update_ingestion_task(task_id, {
        "task_status": "extracting",
        "classification_result": result.classification_result,
        "is_relevant": result.is_relevant,
        "parse_confidence": result.parse_confidence,
        "time_parse_status": "success" if result.time.get("mode") != "unknown" else "missing",
        "extracted_json": json.dumps(extracted_dict, ensure_ascii=False),
    })

    if not result.is_relevant:
        store.update_ingestion_task(task_id, {
            "task_status": "parsed",
            "review_status": "pending_confirm",
            "review_reason": f"AI 判断为无关：{result.classification_reason}",
        })
        return {"success": True, "status": "non_relevant", "classification": result.classification_result}

    # Step 4: 地理编码（如果有高德 Key）
    try:
        from geo_radar import amap, geoparse

        amap_client = amap.AmapClient()
        gp = geoparse.parse(extracted_dict, amap_client)
        store.update_ingestion_task(task_id, {
            "task_status": "geo_parsing",
            "geo_confidence": gp.confidence,
            "geo_json": json.dumps(gp.geometry) if gp.geometry else None,
        })
    except Exception as exc:
        logger.warning(f"地理编码失败 task={task_id}: {exc}（继续，无 GeoJSON）")
        store.update_ingestion_task(task_id, {
            "task_status": "geo_parsing",
            "geo_confidence": 0.0,
        })

    # Step 5: 时间归一化
    try:
        from datetime import datetime, timezone, timedelta
        from geo_radar import temporal

        now = datetime.now(timezone(timedelta(hours=8)))
        val = temporal.evaluate(extracted_dict, now)
        # 更新 extracted_json 中的时间状态
        extracted_dict["time_status"] = val.status
        extracted_dict["validity_basis"] = val.basis
        store.update_ingestion_task(task_id, {
            "task_status": "time_normalizing",
            "extracted_json": json.dumps(extracted_dict, ensure_ascii=False),
        })
    except Exception as exc:
        logger.warning(f"时间归一化失败 task={task_id}: {exc}")

    # Step 6: 完成
    needs_review = result.needs_review or result.parse_confidence < 0.8
    final_status = "needs_review" if needs_review else "parsed"
    review_status = "pending_confirm" if needs_review else "auto_pass"

    store.update_ingestion_task(task_id, {
        "task_status": final_status,
        "review_status": review_status,
        "review_reason": result.review_reason if needs_review else None,
        "map_preview_status": "generated",
    })

    return {
        "success": True,
        "status": final_status,
        "classification": result.classification_result,
        "parse_confidence": result.parse_confidence,
        "needs_review": needs_review,
    }
