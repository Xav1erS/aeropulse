"""公告库 API — GET 列表/详情 + POST 确认/驳回/生成图层"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query

from . import store

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))

router = APIRouter(tags=["announcements"])


@router.get("/announcements")
def list_announcements(
    ann_status: str | None = Query(None),
    control_type: str | None = Query(None),
    province: str | None = Query(None),
    city: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """获取公告库列表（支持按 ann_status / control_type / province / city 筛选）。"""
    items, total = store.get_announcements_with_ann_status(
        ann_status=ann_status,
        control_type=control_type,
        province=province,
        city=city,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/announcements/{ann_id}/detail")
def get_announcement_detail(ann_id: str):
    """获取公告详情（含关联图层列表）。

    注意：路径用 /detail 后缀，避免与 map_layers.py 的
    GET /announcements/{announcement_id}（地图点击详情，扁平结构）冲突。
    """
    ann = store.get_announcement(ann_id)
    if not ann:
        raise HTTPException(404, "公告不存在")

    # 获取关联的图层
    layers = store.get_layers_by_announcement(ann_id)

    # 获取来源任务信息
    task = store.get_ingestion_task(ann.get("source_task_id")) if ann.get("source_task_id") else None

    return {
        "announcement": ann,
        "layers": layers,
        "source_task": task,
    }


@router.post("/announcements/{ann_id}/confirm")
def confirm_announcement(ann_id: str):
    """确认公告：设置 ann_status = 'confirmed'。"""
    ann = store.get_announcement(ann_id)
    if not ann:
        raise HTTPException(404, "公告不存在")

    if ann.get("ann_status") == "confirmed":
        return {"status": "already_confirmed", "ann_status": "confirmed", "message": "公告已确认"}

    store.update_announcement(ann_id, {
        "ann_status": "confirmed",
        "needs_review": False,
        "review_status": "approved",
        "review_reason": "人工确认通过",
    })
    return {"status": "confirmed", "ann_status": "confirmed", "message": "公告已确认"}


@router.post("/announcements/{ann_id}/reject")
def reject_announcement(ann_id: str, body: dict | None = None):
    """驳回公告：设置 ann_status = 'invalid'。"""
    body = body or {}
    ann = store.get_announcement(ann_id)
    if not ann:
        raise HTTPException(404, "公告不存在")

    store.update_announcement(ann_id, {
        "ann_status": "invalid",
        "needs_review": False,
        "review_status": "rejected",
        "review_reason": body.get("reason", "人工驳回"),
    })
    return {"status": "rejected", "ann_status": "invalid", "message": "公告已驳回"}


@router.post("/announcements/{ann_id}/generate-layers")
def generate_layers(ann_id: str):
    """生成图层：使用入库阶段已确认的地理解析结果，生成 map_layers 记录。

    逻辑：
    1. 读取 announcements 表的地理解析结果（center_poi, poi_list, district_name, geo_type 等）
    2. 如果有 geo_json，直接使用
    3. 如果有 poi_list，为每个 POI 创建一个图层
    4. 如果有 district_name，创建一个行政区图层
    5. 图层状态默认为 'draft'
    """
    ann = store.get_announcement(ann_id)
    if not ann:
        raise HTTPException(404, "公告不存在")

    # 检查是否已有图层（避免重复生成）
    existing_layers = store.get_layers_by_announcement(ann_id)
    if existing_layers:
        return {
            "layer_ids": [l["id"] for l in existing_layers],
            "message": f"该公告已有 {len(existing_layers)} 个图层",
            "status": "already_exists",
        }

    layer_ids = []

    # 方案1：直接使用已有的 geo_json
    if ann.get("geo_json"):
        geo = ann["geo_json"]
        if isinstance(geo, str):
            try:
                geo = json.loads(geo)
            except json.JSONDecodeError:
                geo = None

        if geo:
            layer = store.create_layer({
                "announcement_id": ann_id,
                "layer_name": ann.get("title", f"公告 {ann_id} 图层"),
                "geo_json": geo,
                "geo_type": ann.get("geo_type", "fuzzy"),
                "center_poi": ann.get("center_poi"),
                "radius_meters": ann.get("radius_meters"),
                "district_name": ann.get("district_name"),
                "geo_confidence": ann.get("geo_confidence", 0.0),
                "geo_grade": ann.get("geo_grade", "E"),
                "validity_start": ann.get("start_time"),
                "validity_end": ann.get("end_time"),
                "layer_status": "draft",
            })
            layer_ids.append(layer["id"])

    # 方案2：如果有 poi_list 但没有 geo_json，为每个 POI 创建图层
    if not layer_ids and ann.get("poi_list"):
        poi_list = ann["poi_list"]
        if isinstance(poi_list, str):
            try:
                poi_list = json.loads(poi_list)
            except json.JSONDecodeError:
                poi_list = []

        for i, poi in enumerate(poi_list):
            poi_name = poi if isinstance(poi, str) else poi.get("name", f"POI_{i+1}")
            layer = store.create_layer({
                "announcement_id": ann_id,
                "layer_name": f"{poi_name} 缓冲区",
                "geo_json": None,  # 需要后续手动设定坐标
                "geo_type": "poi_buffer",
                "center_poi": poi_name,
                "radius_meters": ann.get("radius_meters"),
                "district_name": ann.get("district_name"),
                "geo_confidence": ann.get("geo_confidence", 0.0),
                "geo_grade": ann.get("geo_grade", "E"),
                "validity_start": ann.get("start_time"),
                "validity_end": ann.get("end_time"),
                "layer_status": "draft",
            })
            layer_ids.append(layer["id"])

    # 方案3：只有 district_name，创建行政区图层
    if not layer_ids and ann.get("district_name"):
        layer = store.create_layer({
            "announcement_id": ann_id,
            "layer_name": f"{ann['district_name']} 行政区",
            "geo_json": None,
            "geo_type": "admin",
            "center_poi": None,
            "radius_meters": None,
            "district_name": ann["district_name"],
            "geo_confidence": ann.get("geo_confidence", 0.0),
            "geo_grade": ann.get("geo_grade", "E"),
            "validity_start": ann.get("start_time"),
            "validity_end": ann.get("end_time"),
            "layer_status": "draft",
        })
        layer_ids.append(layer["id"])

    # 方案4：有 area_text 但没有具体地理数据，创建概略图层
    if not layer_ids and ann.get("area_text"):
        layer = store.create_layer({
            "announcement_id": ann_id,
            "layer_name": ann.get("title", f"公告 {ann_id} 概略图层"),
            "geo_json": None,
            "geo_type": "area_no_boundary",
            "center_poi": ann.get("center_poi"),
            "radius_meters": ann.get("radius_meters"),
            "district_name": ann.get("district_name"),
            "geo_confidence": ann.get("geo_confidence", 0.0),
            "geo_grade": ann.get("geo_grade", "E"),
            "validity_start": ann.get("start_time"),
            "validity_end": ann.get("end_time"),
            "layer_status": "draft",
        })
        layer_ids.append(layer["id"])

    # 更新公告 map_layer_status
    store.update_announcement(ann_id, {"map_layer_status": "draft"})

    return {
        "layer_ids": layer_ids,
        "message": f"已生成 {len(layer_ids)} 个图层",
        "status": "generated",
    }
