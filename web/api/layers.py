"""图层管理 API — GET 列表/详情/预览 + POST 发布/暂停/归档"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query

from . import store

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))

router = APIRouter(tags=["layers"])


@router.get("/layers")
def list_layers(
    layer_status: str | None = Query(None),
    control_type: str | None = Query(None),
    geo_grade: str | None = Query(None),
    province: str | None = Query(None),
    city: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """获取图层列表（支持筛选和分页）。"""
    items, total = store.list_layers(
        layer_status=layer_status,
        control_type=control_type,
        geo_grade=geo_grade,
        province=province,
        city=city,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/layers/{layer_id}")
def get_layer_detail(layer_id: str):
    """获取图层详情。"""
    layer = store.get_layer(layer_id)
    if not layer:
        raise HTTPException(404, "图层不存在")

    ann = store.get_announcement(layer.get("announcement_id", ""))

    return {
        "layer": layer,
        "announcement": ann,
    }


@router.get("/layers/{layer_id}/preview")
def preview_layer(layer_id: str):
    """预览图层（返回 GeoJSON 用于地图展示）。"""
    layer = store.get_layer(layer_id)
    if not layer:
        raise HTTPException(404, "图层不存在")

    geo_json = layer.get("geo_json")
    if isinstance(geo_json, str):
        try:
            geo_json = json.loads(geo_json)
        except json.JSONDecodeError:
            geo_json = None

    ann = store.get_announcement(layer.get("announcement_id", ""))

    return {
        "layer": layer,
        "geo_json": geo_json,
        "announcement": {
            "title": ann.get("title", "") if ann else "",
            "control_type": ann.get("control_type", "") if ann else "",
            "area_text": ann.get("area_text", "") if ann else "",
            "source_name": ann.get("source_name", "") if ann else "",
        } if ann else None,
    }


@router.post("/layers/{layer_id}/publish")
def publish_layer(layer_id: str):
    """发布图层：设置 layer_status = 'published'。

    地图页将自动展示该图层（如果时间有效）。
    """
    layer = store.get_layer(layer_id)
    if not layer:
        raise HTTPException(404, "图层不存在")

    if layer.get("layer_status") == "published":
        return {"status": "already_published", "layer_status": "published", "message": "图层已发布"}

    now = datetime.now(CST).isoformat()
    store.update_layer(layer_id, {
        "layer_status": "published",
        "published_at": now,
        "paused_at": None,
    })

    # 同步更新公告的 map_layer_status
    store.update_announcement(layer["announcement_id"], {"map_layer_status": "published"})

    return {
        "status": "published",
        "layer_status": "published",
        "published_at": now,
        "message": "图层已发布",
    }


@router.post("/layers/{layer_id}/pause")
def pause_layer(layer_id: str):
    """暂停图层：设置 layer_status = 'paused'。

    地图页将不再展示该图层。
    """
    layer = store.get_layer(layer_id)
    if not layer:
        raise HTTPException(404, "图层不存在")

    if layer.get("layer_status") == "paused":
        return {"status": "already_paused", "layer_status": "paused", "message": "图层已暂停"}

    now = datetime.now(CST).isoformat()
    store.update_layer(layer_id, {
        "layer_status": "paused",
        "paused_at": now,
    })

    # 同步更新公告的 map_layer_status
    store.update_announcement(layer["announcement_id"], {"map_layer_status": "draft"})

    return {
        "status": "paused",
        "layer_status": "paused",
        "paused_at": now,
        "message": "图层已暂停",
    }


@router.post("/layers/{layer_id}/archive")
def archive_layer(layer_id: str):
    """归档图层：设置 layer_status = 'archived'。

    归档后图层从后台和地图页隐藏。
    """
    layer = store.get_layer(layer_id)
    if not layer:
        raise HTTPException(404, "图层不存在")

    if layer.get("layer_status") == "archived":
        return {"status": "already_archived", "layer_status": "archived", "message": "图层已归档"}

    now = datetime.now(CST).isoformat()
    store.update_layer(layer_id, {
        "layer_status": "archived",
        "archived_at": now,
    })

    return {
        "status": "archived",
        "layer_status": "archived",
        "archived_at": now,
        "message": "图层已归档",
    }
