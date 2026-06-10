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
        _enrich_task_quality(item)
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

    response = {
        "id": task["id"],
        "task_id": task["id"],
        "source_name": task.get("source_name", ""),
        "source_url": task.get("source_url", ""),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
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
    _enrich_task_quality(response, task=task, extracted=extracted)
    response["publication_gate"] = _publication_gate(task, extracted)
    response["evidence_items"] = _evidence_items(extracted)
    return response


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

    gate = _publication_gate(task, extracted)
    if publish and not gate["can_publish"]:
        raise HTTPException(422, {"message": "无法发布地图图层", "blockers": gate["blockers"]})

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
        "publish_time": extracted.get("publish_time"),
        "province": extracted.get("province"),
        "city": extracted.get("city"),
        "district": extracted.get("district"),
        "control_type": extracted.get("control_type", "临时管控"),
        "risk_class": extracted.get("risk_class", "control"),
        "time_status": "unknown",
        "start_time": (extracted.get("time") or {}).get("start"),
        "end_time": (extracted.get("time") or {}).get("end"),
        "time_mode": (extracted.get("time") or {}).get("mode", "single"),
        "time_windows": (extracted.get("time") or {}).get("windows"),
        "validity_basis": (extracted.get("time") or {}).get("note"),
        "area_text": extracted.get("area_text", ""),
        "geo_type": (extracted.get("geo") or {}).get("geo_type", "fuzzy"),
        "center_poi": (extracted.get("geo") or {}).get("poi"),
        "poi_list": (extracted.get("geo") or {}).get("poi_list"),
        "radius_meters": (extracted.get("geo") or {}).get("radius_m") or (extracted.get("geo") or {}).get("radius_estimated"),
        "geo_json": task.get("geo_json"),
        "geo_confidence": task.get("geo_confidence") or 0.0,
        "geo_grade": "E",
        "evidence_text": extracted.get("evidence_text", ""),
        "evidence_time": (extracted.get("evidence") or {}).get("time_evidence"),
        "evidence_area": (extracted.get("evidence") or {}).get("area_evidence"),
        "evidence_control_type": (extracted.get("evidence") or {}).get("control_type_evidence"),
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


def _enrich_task_quality(item: dict, task: dict | None = None, extracted: dict | None = None) -> None:
    src = task or item
    extracted = extracted if extracted is not None else src.get("extracted_json") or {}
    if isinstance(extracted, str):
        import json
        try:
            extracted = json.loads(extracted)
        except json.JSONDecodeError:
            extracted = {}

    evidence = _evidence_counts(extracted)
    ann = store.get_announcement_by_task(src["id"]) if src.get("id") else None

    item["time_parse_status"] = src.get("time_parse_status") or _time_parse_status(extracted)
    item["geo_parse_status"] = _geo_parse_status(src, extracted)
    item["evidence_status"] = evidence["status"]
    item["evidence_bound_count"] = evidence["bound"]
    item["evidence_required_count"] = evidence["required"]
    item["map_layer_status"] = ann.get("map_layer_status") if ann else _map_layer_status(src)
    item["review_reason"] = src.get("review_reason")


def _evidence_counts(extracted: dict) -> dict:
    ev = extracted.get("evidence") or {}
    required_keys = ("title_evidence", "time_evidence", "area_evidence", "control_type_evidence")
    bound = sum(1 for k in required_keys if ev.get(k))
    if extracted.get("evidence_text") and bound == 0:
        bound = 1
    if bound >= len(required_keys):
        status = "complete"
    elif bound > 0:
        status = "partial"
    else:
        status = "missing"
    return {"status": status, "bound": bound, "required": len(required_keys)}


def _evidence_items(extracted: dict) -> list[dict]:
    ev = extracted.get("evidence") or {}
    return [
        {"label": "标题", "text": ev.get("title_evidence") or ""},
        {"label": "发布时间/单位", "text": ev.get("publish_unit_evidence") or ""},
        {"label": "时间", "text": ev.get("time_evidence") or ""},
        {"label": "区域", "text": ev.get("area_evidence") or ""},
        {"label": "管控类型", "text": ev.get("control_type_evidence") or ""},
    ]


def _time_parse_status(extracted: dict) -> str:
    t = extracted.get("time") or {}
    mode = t.get("mode")
    if mode in ("long_term", "recurring_seasonal"):
        return "success"
    if t.get("start") and t.get("end"):
        return "success"
    if t.get("start") or t.get("end"):
        return "conflict"
    return "missing"


def _geo_parse_status(task: dict, extracted: dict) -> str:
    if task.get("geo_json"):
        return "success"
    geo = extracted.get("geo") or {}
    if geo.get("geo_type") in ("area_no_boundary", "bbox_roads") or task.get("review_reason"):
        return "needs_review"
    if task.get("geo_confidence") is not None and float(task.get("geo_confidence") or 0) > 0:
        return "preview"
    return "missing"


def _map_layer_status(task: dict) -> str:
    preview = task.get("map_preview_status")
    if preview == "generated":
        return "unpublished"
    if preview == "generating":
        return "previewing"
    return "not_generated"


def _publication_gate(task: dict, extracted: dict) -> dict:
    blockers: list[str] = []
    evidence = _evidence_counts(extracted)

    if not task.get("source_name") or not task.get("source_url"):
        blockers.append("来源缺少名称或可回溯链接")
    if evidence["status"] != "complete":
        missing = evidence["required"] - evidence["bound"]
        blockers.append(f"关键字段证据未完整绑定，缺失 {missing} 项")
    if _time_parse_status(extracted) != "success":
        blockers.append("时间解析未成功")
    if not task.get("geo_json") and task.get("map_preview_status") != "generated":
        blockers.append("地理结果尚不可预览")
    if task.get("is_relevant") is False:
        blockers.append("AI 相关性判断为无关")
    if task.get("review_status") == "rejected" or task.get("task_status") == "rejected":
        blockers.append("任务已驳回")

    return {
        "can_publish": len(blockers) == 0,
        "blockers": blockers,
        "summary": "满足发布条件" if not blockers else "无法发布：" + "；".join(blockers),
    }
