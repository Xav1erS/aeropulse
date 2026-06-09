"""入库任务 API — GET/POST 任务列表 + 手动提交 + 审批/驳回"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query

from . import store

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))

router = APIRouter(tags=["ingestion"])


@router.get("/ingestion-tasks")
def list_tasks(
    task_status: str | None = Query(None),
    review_status: str | None = Query(None),
    submit_channel: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items, total = store.list_ingestion_tasks(
        task_status=task_status,
        review_status=review_status,
        submit_channel=submit_channel,
        limit=limit,
        offset=offset,
    )
    # 为列表视图添加 title_preview
    for item in items:
        raw = item.get("raw_text", "")
        item["title_preview"] = raw[:50].replace("\n", " ") + ("..." if len(raw) > 50 else "")
    return {"items": items, "total": total}


@router.post("/ingestion-tasks/manual-submit")
def manual_submit(body: dict):
    """手动提交公告（链接或正文）。

    body: {
        submission_type: "text" | "url",
        source_id: str | null,
        source_name: str,
        source_url: str | null,
        manual_text: str | null,       // submission_type=text 时
        manual_url: str | null,        // submission_type=url 时
        source_level_hint: str | null,
        submitter_note: str | null,
    }
    """
    sub_type = body.get("submission_type", "text")
    raw_text = ""
    if sub_type == "text":
        raw_text = body.get("manual_text", "")
    elif sub_type == "url":
        raw_text = f"[URL提交] {body.get('manual_url', '')}\n备注：{body.get('submitter_note', '')}"
    else:
        raise HTTPException(400, "submission_type 必须为 text 或 url")

    if not raw_text.strip():
        raise HTTPException(400, "公告内容不能为空")

    task = store.create_ingestion_task({
        "submit_channel": "manual",
        "submission_type": sub_type,
        "source_id": body.get("source_id"),
        "source_name": body.get("source_name", "手动提交"),
        "source_url": body.get("source_url") or body.get("manual_url"),
        "raw_text": raw_text,
        "task_status": "submitted",
        "review_status": "pending_confirm",
        "created_by": "admin",
    })

    # 异步触发 AI 管线（PoC 阶段同步调用 BackgroundTasks）
    # 这里先返回，实际管线由独立步骤触发
    return {
        "task_id": task["id"],
        "task_status": "submitted",
        "message": "公告已提交，正在进入 AI 解析流程",
    }


@router.get("/ingestion-tasks/{task_id}")
def get_task_detail(task_id: str):
    task = store.get_ingestion_task(task_id)
    if not task:
        raise HTTPException(404, "入库任务不存在")

    # 构造解析详情响应（对齐 SPEC §5.2 GET /ingestion-tasks/{task_id}）
    extracted = task.get("extracted_json") or {}
    if isinstance(extracted, str):
        import json
        try:
            extracted = json.loads(extracted)
        except json.JSONDecodeError:
            extracted = {}

    return {
        "task_id": task["id"],
        "task_status": task["task_status"],
        "raw_text": task["raw_text"],
        "is_relevant": task.get("is_relevant"),
        "classification_result": task.get("classification_result"),
        "classification_reason": extracted.get("classification_reason", ""),
        "extracted_fields": _build_extracted_fields(extracted),
        "temporal_result": _build_temporal(extracted),
        "geo_parse_result": _build_geo(extracted),
        "evidence_text": extracted.get("evidence_text", ""),
        "review_status": task.get("review_status"),
        "review_reason": task.get("review_reason"),
        "parse_confidence": task.get("parse_confidence"),
        "geo_confidence": task.get("geo_confidence"),
        "map_preview_status": task.get("map_preview_status"),
    }


@router.post("/ingestion-tasks/{task_id}/approve")
def approve_task(task_id: str, body: dict | None = None):
    """确认入库并发布到地图。"""
    body = body or {}
    task = store.get_ingestion_task(task_id)
    if not task:
        raise HTTPException(404, "入库任务不存在")

    publish = body.get("publish_to_map", True)
    extracted = task.get("extracted_json") or {}
    if isinstance(extracted, str):
        import json
        try:
            extracted = json.loads(extracted)
        except json.JSONDecodeError:
            extracted = {}

    # 更新任务状态
    store.update_ingestion_task(task_id, {
        "task_status": "approved",
        "review_status": "approved",
        "review_reason": body.get("review_reason") or "人工确认通过",
    })

    # 创建公告记录
    now = datetime.now(CST).isoformat()
    ann_id = f"ann_{now[:10]}_{task_id}"
    ann_data = {
        "id": ann_id,
        "source_task_id": task_id,
        "extraction_method": "llm" if extracted else "manual",
        "title": extracted.get("title") or task.get("source_name", ""),
        "publish_unit": extracted.get("publish_unit", ""),
        "source_name": task.get("source_name", ""),
        "source_url": task.get("source_url", ""),
        "source_level": body.get("source_level") or "P2",
        "source_trust_score": 0.7,
        "control_type": extracted.get("control_type", "临时管控"),
        "risk_class": extracted.get("risk_class", "control"),
        "time_status": "unknown",
        "area_text": extracted.get("area_text", ""),
        "geo_type": (extracted.get("geo") or {}).get("geo_type", "fuzzy"),
        "geo_confidence": task.get("geo_confidence") or 0.0,
        "geo_grade": "E",
        "evidence_text": extracted.get("evidence_text", ""),
        "confidence_score": task.get("parse_confidence") or 0.0,
        "needs_review": False,
        "review_status": "approved",
        "map_layer_status": "published" if publish else "preview",
    }
    store.create_announcement(ann_data)

    store.update_ingestion_task(task_id, {"map_preview_status": "generated"})

    return {
        "announcement_id": ann_id,
        "review_status": "approved",
        "map_layer_status": "published" if publish else "preview",
        "message": "公告已确认入库，并生成地图图层",
    }


@router.post("/ingestion-tasks/{task_id}/reject")
def reject_task(task_id: str, body: dict | None = None):
    body = body or {}
    task = store.get_ingestion_task(task_id)
    if not task:
        raise HTTPException(404, "入库任务不存在")

    store.update_ingestion_task(task_id, {
        "task_status": "rejected",
        "review_status": "rejected",
        "review_reason": body.get("reason", "人工驳回"),
    })
    return {
        "task_id": task_id,
        "review_status": "rejected",
        "message": "任务已驳回",
    }


# ─── Helpers ─────────────────────────────────────────────

def _build_extracted_fields(extracted: dict) -> dict:
    ev = extracted.get("evidence", {})
    return {
        "title": _field(extracted.get("title"), extracted.get("parse_confidence", 0), ev.get("title_evidence")),
        "publish_unit": _field(extracted.get("publish_unit"), extracted.get("parse_confidence", 0), ev.get("publish_unit_evidence")),
        "start_time": _field((extracted.get("time") or {}).get("start"), extracted.get("parse_confidence", 0), ev.get("time_evidence")),
        "end_time": _field((extracted.get("time") or {}).get("end"), extracted.get("parse_confidence", 0), ev.get("time_evidence")),
        "control_type": _field(extracted.get("control_type"), extracted.get("parse_confidence", 0), ev.get("control_type_evidence")),
        "area_text": _field(extracted.get("area_text"), extracted.get("parse_confidence", 0), ev.get("area_evidence")),
    }


def _field(value, confidence, evidence):
    return {"value": value, "confidence": confidence, "evidence": evidence or ""}


def _build_temporal(extracted: dict) -> dict:
    t = extracted.get("time") or {}
    return {
        "time_status": "unknown",
        "time_mode": t.get("mode", "unknown"),
        "validity_basis": t.get("note", ""),
    }


def _build_geo(extracted: dict) -> dict:
    g = extracted.get("geo") or {}
    return {
        "geo_type": g.get("geo_type", "fuzzy"),
        "center_poi": g.get("poi") or (g.get("poi_list", [None])[0] if g.get("poi_list") else None),
        "radius_meters": g.get("radius_m"),
        "geo_confidence": extracted.get("parse_confidence", 0),
        "geo_grade": "C",
        "roster_status": g.get("roster_status"),
    }
