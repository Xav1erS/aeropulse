"""地图图层 API — GET /map/layers + GET /announcements/{id} + 地点搜索代理"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query

from geo_radar import geometry as g  # noqa: F401 (kept for stable API)
from geo_radar import temporal
from geo_radar.amap import AmapClient, AmapError

from . import store

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))

router = APIRouter(tags=["map"])

DISCLAIMER = (
    "本系统基于公开公告展示低空管控风险，不构成飞行许可、审批结论或法律意见。"
    "实际飞行前仍需通过 UOM、空管、公安或公告发布单位进一步核验。"
)


@router.get("/map/layers")
def get_layers(
    selected_time: str = Query(..., description="时间轴选中时间 ISO 8601"),
    province: str | None = Query(None),
    city: str | None = Query(None),
    district: str | None = Query(None),
    control_type: str | None = Query(None),
    include_expired: bool = Query(False),
    include_review: bool = Query(True),
    bounds: str | None = Query(None, description="视野范围 sw_lng,sw_lat,ne_lng,ne_lat"),
):
    """获取地图图层数据（对齐 SPEC §5.3 GET /api/v1/map/layers）。"""
    import traceback
    try:
        try:
            sel_time = _parse_iso_datetime(selected_time)
        except ValueError:
            raise HTTPException(400, "selected_time 格式无效，需 ISO 8601")

        # 获取已发布的公告（旧系统兼容）
        filters = {"map_layer_status": "published"}
        if city:
            filters["city"] = city
        if province:
            filters["province"] = province
        if control_type:
            filters["control_type"] = control_type

        announcements = store.list_announcements(**filters)

        features = []

        # 从 map_layers 表读取（新系统）
        published_layers = store.get_published_layers_geojson()
        for layer in published_layers:
            geo_json = layer.get("geo_json")
            if isinstance(geo_json, str):
                try:
                    geo_json = json.loads(geo_json)
                except json.JSONDecodeError:
                    geo_json = None

            if not geo_json:
                city_coords = _city_default_coord(layer.get("city", "") or layer.get("ann_city", ""))
                if city_coords:
                    geo_json = {"type": "Point", "coordinates": city_coords}
                else:
                    continue

            start = layer.get("validity_start") or layer.get("start_time")
            end = layer.get("validity_end") or layer.get("end_time")
            ts = "active"
            if end and end < selected_time:
                ts = "expired"
            elif start and start > selected_time:
                ts = "not_started"
            if ts == "expired" and not include_expired:
                continue

            control_t = layer.get("control_type") or layer.get("ann_control_type", "临时管控")
            style_hint = _style_hint(control_t, ts, layer.get("geo_grade", "E"), False)

            features.append({
                "type": "Feature",
                "announcement_id": layer["announcement_id"],
                "title": layer.get("title") or layer.get("ann_title", ""),
                "control_type": control_t,
                "time_status": ts,
                "source_level": layer.get("source_level", "P2"),
                "geo_confidence": layer.get("geo_confidence", 0),
                "geo_grade": layer.get("geo_grade", "E"),
                "extraction_method": "manual",
                "geometry": geo_json,
                "properties": {
                    "announcement_id": layer["announcement_id"],
                    "title": layer.get("title") or layer.get("ann_title", ""),
                    "control_type": control_t,
                    "time_status": ts,
                    "source_name": layer.get("ann_source_name", ""),
                    "source_level": layer.get("source_level", "P2"),
                    "geo_confidence": layer.get("geo_confidence", 0),
                    "style_hint": style_hint,
                    "radius_meters": layer.get("radius_meters"),
                    "center_poi": layer.get("center_poi"),
                },
            })

        # 从 announcements 表读取（旧系统兼容，已有 geo_json 的公告）
        for ann in announcements:
            # 跳过已经在 map_layers 中处理过的公告
            existing_ids = {f["announcement_id"] for f in features}
            if ann["id"] in existing_ids:
                continue
            # 时间状态判断
            ts = _evaluate_time_status(ann, sel_time)

            # 过滤逻辑
            if ts == "expired" and not include_expired:
                continue
            if ts == "not_started" and not include_review and ann.get("needs_review"):
                continue

            # 解析 GeoJSON
            geometry = ann.get("geo_json")
            if isinstance(geometry, str):
                try:
                    geometry = json.loads(geometry)
                except json.JSONDecodeError:
                    geometry = None

            if not geometry:
                # 没有几何数据的公告：用 city 名称生成默认坐标（山东省主要城市默认坐标）
                city_coords = _city_default_coord(ann.get("city", ""))
                if city_coords:
                    geometry = {"type": "Point", "coordinates": city_coords}
                else:
                    continue

            # 样式
            style_hint = _style_hint(ann["control_type"], ts, ann.get("geo_grade", "E"), ann.get("needs_review", False))

            features.append({
                "type": "Feature",
                "announcement_id": ann["id"],
                "title": ann["title"],
                "control_type": ann["control_type"],
                "time_status": ts,
                "source_level": ann.get("source_level", "P2"),
                "geo_confidence": ann.get("geo_confidence", 0),
                "geo_grade": ann.get("geo_grade", "E"),
                "extraction_method": ann.get("extraction_method", "manual"),
                "geometry": geometry,
                "properties": {
                    "announcement_id": ann["id"],
                    "title": ann["title"],
                    "control_type": ann["control_type"],
                    "time_status": ts,
                    "source_name": ann.get("source_name", ""),
                    "source_level": ann.get("source_level", "P2"),
                    "geo_confidence": ann.get("geo_confidence", 0),
                    "style_hint": style_hint,
                    "radius_meters": ann.get("radius_meters"),
                    "center_poi": ann.get("center_poi"),
                },
            })

        # 视野过滤（简易 BBox）
        if bounds:
            features = _filter_by_bounds(features, bounds)

        summary = _build_layer_summary(features)

        return {
            "selected_time": selected_time,
            "summary": summary,
            "features": features,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_layers error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"内部错误: {e}")


@router.get("/announcements/nearby")
def nearby_announcements(
    lng: float = Query(..., description="经度 GCJ-02"),
    lat: float = Query(..., description="纬度 GCJ-02"),
    radius: float = Query(5000, ge=100, le=50000, description="搜索半径，米"),
    time: str | None = Query(None, description="所选时间 ISO 8601"),
):
    when = _parse_iso_datetime(time) if time else datetime.now(CST)
    features = []
    for ann in store.list_announcements(map_layer_status="published", limit=500):
        geometry = ann.get("geo_json")
        if isinstance(geometry, str):
            try:
                geometry = json.loads(geometry)
            except json.JSONDecodeError:
                geometry = None
        if not geometry:
            coord = _city_default_coord(ann.get("city", ""))
            geometry = {"type": "Point", "coordinates": coord} if coord else None
        if not geometry:
            continue
        distance = _distance_to_geometry(lng, lat, geometry)
        if distance is None or distance > radius:
            continue
        ts = _evaluate_time_status(ann, when)
        features.append({
            "type": "Feature",
            "announcement_id": ann["id"],
            "title": ann["title"],
            "control_type": ann["control_type"],
            "time_status": ts,
            "distance_meters": round(distance),
            "geometry": geometry,
            "properties": {
                "announcement_id": ann["id"],
                "title": ann["title"],
                "control_type": ann["control_type"],
                "time_status": ts,
                "source_name": ann.get("source_name", ""),
                "source_level": ann.get("source_level", "P2"),
            },
        })
    features.sort(key=lambda f: f["distance_meters"])
    return {"features": features[:20], "total": len(features), "selected_time": time}


@router.get("/announcements/{announcement_id}")
def get_announcement_detail(
    announcement_id: str,
    selected_time: str | None = Query(None, description="详情卡所选时间 ISO 8601"),
):
    """获取公告详情（图层点击）。对齐 SPEC §5.3 GET /api/v1/announcements/{id}。"""
    ann = store.get_announcement(announcement_id)
    if not ann:
        raise HTTPException(404, "公告不存在")
    time_status = ann.get("time_status", "unknown")
    if selected_time:
        try:
            time_status = _evaluate_time_status(ann, _parse_iso_datetime(selected_time))
        except ValueError:
            raise HTTPException(400, "selected_time 格式无效，需 ISO 8601")

    return {
        "id": ann["id"],
        "announcement_id": ann["id"],
        "title": ann.get("title", ""),
        "control_type": ann.get("control_type", ""),
        "time_status": time_status,
        "selected_time": selected_time,
        "start_time": ann.get("start_time"),
        "end_time": ann.get("end_time"),
        "area_text": ann.get("area_text", ""),
        "source_name": ann.get("source_name", ""),
        "source_url": ann.get("source_url", ""),
        "source_level": ann.get("source_level", ""),
        "source_trust_score": ann.get("source_trust_score"),
        "confidence_score": ann.get("confidence_score", 0),
        "geo_confidence": ann.get("geo_confidence", 0),
        "geo_grade": ann.get("geo_grade", ""),
        "geo_note": ann.get("geo_note", ""),
        "evidence_text": ann.get("evidence_text", ""),
        "evidence_time": ann.get("evidence_time"),
        "evidence_area": ann.get("evidence_area"),
        "evidence_control_type": ann.get("evidence_control_type"),
        "aircraft_types": ann.get("aircraft_types") or [],
        "publish_unit": ann.get("publish_unit", ""),
        "publish_time": ann.get("publish_time"),
        "last_checked_at": ann.get("last_checked_at"),
        "review_status": ann.get("review_status"),
        "review_reason": ann.get("review_reason"),
        "disclaimer": DISCLAIMER,
    }


@router.get("/place/search")
def search_place(
    keywords: str = Query(..., description="搜索关键词"),
    city: str = Query("全国", description="限定城市"),
):
    """地点搜索代理 — POI 搜索 + geocode 回退 + 行政区边界。

    搜索策略（自动级联）：
    1. 高德 POI 搜索 (place/text) — 地标、商场、机场、公园、街道等
    2. POI 无结果时回退地理编码 (geocode/geo) — 结构化地址如"市南区香港中路10号"
    3. 若关键词匹配行政区，同时返回行政边界 polyline 用于地图渲染
    """
    try:
        client = AmapClient()
        result: dict = {"status": "1", "info": "OK", "pois": [], "district": None}

        # Step 1: POI 搜索
        poi_list = _search_poi_multi(client, keywords, city)
        if poi_list:
            result["pois"] = poi_list
        else:
            # Step 2: 回退地理编码
            pt = client.geocode(keywords, city)
            if pt:
                result["pois"] = [{
                    "name": pt.name,
                    "location": f"{pt.lng},{pt.lat}",
                    "type": "geocode",
                }]

        if not result["pois"]:
            return {"status": "0", "info": "未找到结果", "pois": [], "district": None}

        # Step 3: 尝试获取行政区边界（省/市/区县名）
        try:
            rings, center = client.district_rings(keywords)
            if rings:
                result["district"] = {
                    "name": center.name,
                    "center": f"{center.lng},{center.lat}",
                    "type": "MultiPolygon" if len(rings) > 1 else "Polygon",
                    "coordinates": rings,
                }
        except Exception:
            pass  # 非行政区关键词会失败，忽略

        return result
    except AmapError as e:
        raise HTTPException(502, f"高德服务异常: {e}")
    except Exception as e:
        raise HTTPException(500, f"搜索失败: {e}")


@router.get("/place/regeo")
def regeo_place(
    lng: float = Query(..., description="经度 GCJ-02"),
    lat: float = Query(..., description="纬度 GCJ-02"),
):
    """逆地理编码：根据坐标返回省/市/区。
    
    用于地图拖拽/缩放时自动同步地区选择器，确保"当前视野"与"筛选条件"一致。
    """
    try:
        client = AmapClient()
        addr = client.regeo(lng, lat)
        if not addr:
            return {"status": "0", "info": "逆地理编码失败", "province": "", "city": "", "district": ""}
        return {"status": "1", "info": "OK", **addr}
    except AmapError as e:
        raise HTTPException(502, f"高德服务异常: {e}")
    except Exception as e:
        raise HTTPException(500, f"逆地理编码失败: {e}")


def _search_poi_multi(client: AmapClient, keywords: str, city: str, limit: int = 5) -> list[dict]:
    """POI 搜索返回多条结果（最多 limit 条）。"""
    import requests as _r
    data = client._get("place/text", {"keywords": keywords, "city": city, "offset": str(limit), "page": "1"})
    items = data.get("pois") or []
    return [{"name": p["name"], "location": p["location"], "type": "poi", "address": p.get("address", "")} for p in items]


# ─── 风险查询 ─────────────────────────────────────────────



# ─── Helpers ─────────────────────────────────────────────

def _evaluate_time_status(ann: dict, when: datetime) -> str:
    """客户端时间状态判断（简化版，对齐 temporal.evaluate）。"""
    when = _ensure_cst(when)
    start = ann.get("start_time")
    end = ann.get("end_time")
    mode = ann.get("time_mode", "single")

    if mode == "long_term":
        return "long_term"

    if mode == "recurring_seasonal":
        windows = ann.get("time_windows") or []
        if isinstance(windows, str):
            try:
                windows = json.loads(windows)
            except json.JSONDecodeError:
                windows = []
        cur = (when.month, when.day)
        for w in windows:
            sm, sd = (int(x) for x in w["start"].split("-"))
            em, ed = (int(x) for x in w["end"].split("-"))
            s, e = (sm, sd), (em, ed)
            if s <= e:
                if s <= cur <= e:
                    return "active"
            else:
                if cur >= s or cur <= e:
                    return "active"
        return "expired"

    # single mode
    try:
        st = _parse_iso_datetime(start) if start else None
    except (ValueError, TypeError):
        st = None
    try:
        et = _parse_iso_datetime(end) if end else None
    except (ValueError, TypeError):
        et = None

    if not st and not et:
        return "unknown"
    if st and when < st:
        return "not_started"
    if et and when > et:
        return "expired"
    return "active"


def _parse_iso_datetime(value: str) -> datetime:
    """Parse ISO datetime and treat timezone-less values as Asia/Shanghai."""
    normalized = value.replace("Z", "+00:00")
    return _ensure_cst(datetime.fromisoformat(normalized))


def _ensure_cst(dt: datetime) -> datetime:
    """Normalize aware/naive datetimes before comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CST)
    return dt.astimezone(CST)


def _style_hint(control_type: str, time_status: str, geo_grade: str, needs_review: bool) -> str:
    """返回前端样式标识。对齐 SPEC §7.2。"""
    if time_status == "expired":
        return "grey_expired"
    if time_status == "not_started":
        return f"future_{_control_key(control_type)}"
    if geo_grade in ("D", "E") or needs_review:
        return "grey_review"

    color_map = {
        "临时禁飞": "red_active",
        "临时管控": "orange_active",
        "临时空域管制": "red_active",
        "备案通知": "yellow_active",
        "安全提醒": "yellow_active",
        "长期规则": "purple_longterm",
    }
    return color_map.get(control_type, "orange_active")


def _control_key(control_type: str) -> str:
    mapping = {"临时禁飞": "red", "临时空域管制": "red", "临时管控": "orange", "备案通知": "yellow", "安全提醒": "yellow", "长期规则": "purple"}
    return mapping.get(control_type, "orange")


def _build_layer_summary(features: list[dict]) -> dict:
    status_counts = {"active": 0, "not_started": 0, "expired": 0, "long_term": 0, "unknown": 0}
    type_counts = {"temp_no_fly": 0, "temp_control": 0, "notice": 0, "long_term": 0}
    for feature in features:
        status = feature.get("time_status") or (feature.get("properties") or {}).get("time_status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        bucket = _control_type_bucket(feature.get("control_type") or (feature.get("properties") or {}).get("control_type"))
        type_counts[bucket] = type_counts.get(bucket, 0) + 1
    return {
        "active_count": status_counts.get("active", 0),
        "not_started_count": status_counts.get("not_started", 0),
        "expired_count": status_counts.get("expired", 0),
        "long_term_count": status_counts.get("long_term", 0),
        "unknown_count": status_counts.get("unknown", 0),
        "total": len(features),
        "status_counts": status_counts,
        "type_counts": type_counts,
    }


def _control_type_bucket(control_type: str | None) -> str:
    if control_type in ("临时禁飞", "临时空域管制"):
        return "temp_no_fly"
    if control_type == "临时管控":
        return "temp_control"
    if control_type in ("备案通知", "安全提醒"):
        return "notice"
    if control_type == "长期规则":
        return "long_term"
    return "notice"


def _filter_by_bounds(features: list, bounds_str: str) -> list:
    """简易视野 BBox 过滤。"""
    try:
        parts = [float(x) for x in bounds_str.split(",")]
        if len(parts) != 4:
            return features
        sw_lng, sw_lat, ne_lng, ne_lat = parts
    except ValueError:
        return features

    filtered = []
    for f in features:
        g = f.get("geometry")
        if not g:
            continue
        coords = _extract_coords(g)
        if not coords:
            filtered.append(f)
            continue
        # 简单判断：任意点在视野内
        for lng, lat in coords:
            if sw_lng <= lng <= ne_lng and sw_lat <= lat <= ne_lat:
                filtered.append(f)
                break
    return filtered


def _extract_coords(geometry: dict) -> list:
    """从 GeoJSON geometry 提取坐标点列表。"""
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    points = []
    if gtype == "Point":
        points = [coords]
    elif gtype == "Polygon":
        for ring in coords:
            points.extend(ring)
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                points.extend(ring)
    return points


def _distance_to_geometry(lng: float, lat: float, geometry: dict) -> float | None:
    coords = _extract_coords(geometry)
    if not coords:
        return None
    return min(_haversine_m(lng, lat, p[0], p[1]) for p in coords if len(p) >= 2)


def _haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@router.get("/map/timeline-summary")
def timeline_summary(
    province: str | None = Query(None),
    city: str | None = Query(None),
):
    """时间轴摘要接口：返回公告时间范围、事件列表和里程碑点。
    
    用于前端时间轴自适应范围计算和事件密度可视化。
    """
    announcements, range_info = store.list_announcements_time_range(
        map_layer_status="published",
        province=province,
        city=city,
    )
    
    # 计算里程碑点（公告开始/结束时间）
    milestones = []
    for ann in announcements:
        if ann.get("start_time"):
            milestones.append({
                "time": ann["start_time"],
                "type": "start",
                "announcement_id": ann["id"],
                "title": ann.get("title", ""),
                "control_type": ann.get("control_type", ""),
            })
        if ann.get("end_time"):
            milestones.append({
                "time": ann["end_time"],
                "type": "end",
                "announcement_id": ann["id"],
                "title": ann.get("title", ""),
                "control_type": ann.get("control_type", ""),
            })
    
    milestones.sort(key=lambda x: x["time"])
    
    # 按管控类型分组统计
    type_counts = {}
    for ann in announcements:
        ct = ann.get("control_type", "其他")
        type_counts[ct] = type_counts.get(ct, 0) + 1
    
    return {
        "range": range_info,
        "announcements": announcements,
        "milestones": milestones,
        "type_counts": type_counts,
    }


def _city_default_coord(city: str) -> list | None:
    """全国主要城市默认坐标（GCJ-02）。"""
    coords = {
        # 直辖市
        "北京": [116.407, 39.904], "北京市": [116.407, 39.904],
        "天津": [117.190, 39.125], "天津市": [117.190, 39.125],
        "上海": [121.473, 31.230], "上海市": [121.473, 31.230],
        "重庆": [106.551, 29.563], "重庆市": [106.551, 29.563],
        # 河北
        "石家庄": [114.514, 38.042], "石家庄市": [114.514, 38.042],
        "唐山": [118.180, 39.630], "唐山市": [118.180, 39.630],
        "秦皇岛": [119.600, 39.935], "秦皇岛市": [119.600, 39.935],
        "邯郸": [114.539, 36.626], "邯郸市": [114.539, 36.626],
        "邢台": [114.505, 37.071], "邢台市": [114.505, 37.071],
        "保定": [115.465, 38.874], "保定市": [115.465, 38.874],
        "张家口": [114.886, 40.769], "张家口市": [114.886, 40.769],
        "承德": [117.963, 40.952], "承德市": [117.963, 40.952],
        "沧州": [116.839, 38.305], "沧州市": [116.839, 38.305],
        "廊坊": [116.684, 39.538], "廊坊市": [116.684, 39.538],
        "衡水": [115.670, 37.739], "衡水市": [115.670, 37.739],
        # 山西
        "太原": [112.549, 37.870], "太原市": [112.549, 37.870],
        "大同": [113.300, 40.076], "大同市": [113.300, 40.076],
        "阳泉": [113.581, 37.857], "阳泉市": [113.581, 37.857],
        "长治": [113.116, 36.195], "长治市": [113.116, 36.195],
        "晋城": [112.851, 35.491], "晋城市": [112.851, 35.491],
        "朔州": [112.433, 39.332], "朔州市": [112.433, 39.332],
        "晋中": [112.753, 37.687], "晋中市": [112.753, 37.687],
        "运城": [111.007, 35.026], "运城市": [111.007, 35.026],
        "忻州": [112.734, 38.417], "忻州市": [112.734, 38.417],
        "临汾": [111.519, 36.088], "临汾市": [111.519, 36.088],
        "吕梁": [111.144, 37.519], "吕梁市": [111.144, 37.519],
        # 内蒙古
        "呼和浩特": [111.749, 40.842], "呼和浩特市": [111.749, 40.842],
        "包头": [109.840, 40.657], "包头市": [109.840, 40.657],
        "乌海": [106.795, 39.655], "乌海市": [106.795, 39.655],
        "赤峰": [118.889, 42.258], "赤峰市": [118.889, 42.258],
        "通辽": [122.243, 43.653], "通辽市": [122.243, 43.653],
        "鄂尔多斯": [109.781, 39.608], "鄂尔多斯市": [109.781, 39.608],
        "呼伦贝尔": [119.766, 49.212], "呼伦贝尔市": [119.766, 49.212],
        "巴彦淖尔": [107.388, 40.743], "巴彦淖尔市": [107.388, 40.743],
        "乌兰察布": [113.133, 40.994], "乌兰察布市": [113.133, 40.994],
        # 辽宁
        "沈阳": [123.463, 41.678], "沈阳市": [123.463, 41.678],
        "大连": [121.615, 38.914], "大连市": [121.615, 38.914],
        "鞍山": [122.994, 41.108], "鞍山市": [122.994, 41.108],
        "抚顺": [123.957, 41.881], "抚顺市": [123.957, 41.881],
        "本溪": [123.767, 41.294], "本溪市": [123.767, 41.294],
        "丹东": [124.355, 40.000], "丹东市": [124.355, 40.000],
        "锦州": [121.127, 41.095], "锦州市": [121.127, 41.095],
        "营口": [122.235, 40.667], "营口市": [122.235, 40.667],
        "阜新": [121.670, 42.022], "阜新市": [121.670, 42.022],
        "辽阳": [123.237, 41.268], "辽阳市": [123.237, 41.268],
        "盘锦": [122.071, 41.120], "盘锦市": [122.071, 41.120],
        "铁岭": [123.726, 42.224], "铁岭市": [123.726, 42.224],
        "朝阳": [120.451, 41.573], "朝阳市": [120.451, 41.573],
        "葫芦岛": [120.837, 40.711], "葫芦岛市": [120.837, 40.711],
        # 吉林
        "长春": [125.324, 43.887], "长春市": [125.324, 43.887],
        "吉林": [126.553, 43.838], "吉林市": [126.553, 43.838],
        "四平": [124.350, 43.166], "四平市": [124.350, 43.166],
        "辽源": [125.145, 42.888], "辽源市": [125.145, 42.888],
        "通化": [125.940, 41.728], "通化市": [125.940, 41.728],
        "白山": [126.423, 41.941], "白山市": [126.423, 41.941],
        "松原": [124.825, 45.141], "松原市": [124.825, 45.141],
        "白城": [122.839, 45.620], "白城市": [122.839, 45.620],
        "延边": [129.509, 42.891], "延边市": [129.509, 42.891],
        # 黑龙江
        "哈尔滨": [126.642, 45.803], "哈尔滨市": [126.642, 45.803],
        "齐齐哈尔": [123.918, 47.354], "齐齐哈尔市": [123.918, 47.354],
        "鸡西": [130.969, 45.295], "鸡西市": [130.969, 45.295],
        "鹤岗": [130.298, 47.350], "鹤岗市": [130.298, 47.350],
        "双鸭山": [131.159, 46.647], "双鸭山市": [131.159, 46.647],
        "大庆": [125.103, 46.590], "大庆市": [125.103, 46.590],
        "伊春": [128.840, 47.728], "伊春市": [128.840, 47.728],
        "佳木斯": [130.319, 46.800], "佳木斯市": [130.319, 46.800],
        "七台河": [131.003, 45.771], "七台河市": [131.003, 45.771],
        "牡丹江": [129.633, 44.552], "牡丹江市": [129.633, 44.552],
        "黑河": [127.528, 50.245], "黑河市": [127.528, 50.245],
        "绥化": [126.969, 46.654], "绥化市": [126.969, 46.654],
        # 江苏
        "南京": [118.797, 32.060], "南京市": [118.797, 32.060],
        "无锡": [120.312, 31.491], "无锡市": [120.312, 31.491],
        "徐州": [117.284, 34.204], "徐州市": [117.284, 34.204],
        "常州": [119.974, 31.811], "常州市": [119.974, 31.811],
        "苏州": [120.585, 31.299], "苏州市": [120.585, 31.299],
        "南通": [120.894, 31.981], "南通市": [120.894, 31.981],
        "连云港": [119.221, 34.597], "连云港市": [119.221, 34.597],
        "淮安": [119.015, 33.610], "淮安市": [119.015, 33.610],
        "盐城": [120.162, 33.348], "盐城市": [120.162, 33.348],
        "扬州": [119.413, 32.394], "扬州市": [119.413, 32.394],
        "镇江": [119.425, 32.190], "镇江市": [119.425, 32.190],
        "泰州": [119.923, 32.456], "泰州市": [119.923, 32.456],
        "宿迁": [118.275, 33.963], "宿迁市": [118.275, 33.963],
        # 浙江
        "杭州": [120.212, 30.266], "杭州市": [120.212, 30.266],
        "宁波": [121.544, 29.868], "宁波市": [121.544, 29.868],
        "温州": [120.699, 27.994], "温州市": [120.699, 27.994],
        "嘉兴": [120.756, 30.746], "嘉兴市": [120.756, 30.746],
        "湖州": [120.087, 30.894], "湖州市": [120.087, 30.894],
        "绍兴": [120.582, 30.053], "绍兴市": [120.582, 30.053],
        "金华": [119.647, 29.078], "金华市": [119.647, 29.078],
        "衢州": [118.860, 28.970], "衢州市": [118.860, 28.970],
        "舟山": [122.207, 29.985], "舟山市": [122.207, 29.985],
        "台州": [121.421, 28.656], "台州市": [121.421, 28.656],
        "丽水": [119.923, 28.468], "丽水市": [119.923, 28.468],
        # 安徽
        "合肥": [117.227, 31.820], "合肥市": [117.227, 31.820],
        "芜湖": [118.433, 31.353], "芜湖市": [118.433, 31.353],
        "蚌埠": [117.389, 32.916], "蚌埠市": [117.389, 32.916],
        "淮南": [117.000, 32.625], "淮南市": [117.000, 32.625],
        "马鞍山": [118.506, 31.670], "马鞍山市": [118.506, 31.670],
        "淮北": [116.798, 33.955], "淮北市": [116.798, 33.955],
        "铜陵": [117.812, 30.945], "铜陵市": [117.812, 30.945],
        "安庆": [117.063, 30.543], "安庆市": [117.063, 30.543],
        "黄山": [118.339, 29.715], "黄山市": [118.339, 29.715],
        "滁州": [118.317, 32.301], "滁州市": [118.317, 32.301],
        "阜阳": [115.814, 32.890], "阜阳市": [115.814, 32.890],
        "宿州": [116.964, 33.648], "宿州市": [116.964, 33.648],
        "六安": [116.522, 31.734], "六安市": [116.522, 31.734],
        "亳州": [115.779, 33.845], "亳州市": [115.779, 33.845],
        "池州": [117.491, 30.665], "池州市": [117.491, 30.665],
        "宣城": [118.759, 30.941], "宣城市": [118.759, 30.941],
        # 福建
        "福州": [119.296, 26.074], "福州市": [119.296, 26.074],
        "厦门": [118.089, 24.480], "厦门市": [118.089, 24.480],
        "莆田": [119.008, 25.454], "莆田市": [119.008, 25.454],
        "三明": [117.639, 26.263], "三明市": [117.639, 26.263],
        "泉州": [118.676, 24.874], "泉州市": [118.676, 24.874],
        "漳州": [117.647, 24.513], "漳州市": [117.647, 24.513],
        "南平": [118.178, 26.642], "南平市": [118.178, 26.642],
        "龙岩": [117.017, 25.075], "龙岩市": [117.017, 25.075],
        "宁德": [119.548, 26.666], "宁德市": [119.548, 26.666],
        # 江西
        "南昌": [115.858, 28.683], "南昌市": [115.858, 28.683],
        "景德镇": [117.178, 29.269], "景德镇市": [117.178, 29.269],
        "萍乡": [113.854, 27.623], "萍乡市": [113.854, 27.623],
        "九江": [116.001, 29.705], "九江市": [116.001, 29.705],
        "新余": [114.917, 27.818], "新余市": [114.917, 27.818],
        "鹰潭": [117.069, 28.260], "鹰潭市": [117.069, 28.260],
        "赣州": [114.934, 25.831], "赣州市": [114.934, 25.831],
        "吉安": [114.993, 27.113], "吉安市": [114.993, 27.113],
        "宜春": [114.416, 27.816], "宜春市": [114.416, 27.816],
        "抚州": [116.358, 27.949], "抚州市": [116.358, 27.949],
        "上饶": [117.943, 28.455], "上饶市": [117.943, 28.455],
        # 山东
        "济南": [117.001, 36.651], "济南市": [117.001, 36.651],
        "青岛": [120.383, 36.067], "青岛市": [120.383, 36.067],
        "淄博": [118.055, 36.813], "淄博市": [118.055, 36.813],
        "枣庄": [117.324, 34.864], "枣庄市": [117.324, 34.864],
        "东营": [118.676, 37.434], "东营市": [118.676, 37.434],
        "烟台": [121.448, 37.464], "烟台市": [121.448, 37.464],
        "潍坊": [119.162, 36.707], "潍坊市": [119.162, 36.707],
        "济宁": [116.587, 35.415], "济宁市": [116.587, 35.415],
        "泰安": [117.089, 36.200], "泰安市": [117.089, 36.200],
        "威海": [122.120, 37.513], "威海市": [122.120, 37.513],
        "日照": [119.527, 35.416], "日照市": [119.527, 35.416],
        "临沂": [118.356, 35.104], "临沂市": [118.356, 35.104],
        "德州": [116.357, 37.434], "德州市": [116.357, 37.434],
        "聊城": [115.985, 36.457], "聊城市": [115.985, 36.457],
        "滨州": [117.973, 37.382], "滨州市": [117.973, 37.382],
        "菏泽": [115.481, 35.234], "菏泽市": [115.481, 35.234],
        # 河南
        "郑州": [113.625, 34.747], "郑州市": [113.625, 34.747],
        "开封": [114.307, 34.798], "开封市": [114.307, 34.798],
        "洛阳": [112.454, 34.620], "洛阳市": [112.454, 34.620],
        "平顶山": [113.193, 33.766], "平顶山市": [113.193, 33.766],
        "安阳": [114.393, 36.098], "安阳市": [114.393, 36.098],
        "鹤壁": [114.297, 35.748], "鹤壁市": [114.297, 35.748],
        "新乡": [113.927, 35.303], "新乡市": [113.927, 35.303],
        "焦作": [113.242, 35.216], "焦作市": [113.242, 35.216],
        "濮阳": [115.029, 35.762], "濮阳市": [115.029, 35.762],
        "许昌": [113.852, 34.036], "许昌市": [113.852, 34.036],
        "漯河": [114.017, 33.581], "漯河市": [114.017, 33.581],
        "三门峡": [111.200, 34.773], "三门峡市": [111.200, 34.773],
        "南阳": [112.528, 32.991], "南阳市": [112.528, 32.991],
        "商丘": [115.656, 34.414], "商丘市": [115.656, 34.414],
        "信阳": [114.091, 32.147], "信阳市": [114.091, 32.147],
        "周口": [114.697, 33.626], "周口市": [114.697, 33.626],
        "驻马店": [114.022, 33.012], "驻马店市": [114.022, 33.012],
        # 湖北
        "武汉": [114.316, 30.582], "武汉市": [114.316, 30.582],
        "黄石": [115.039, 30.200], "黄石市": [115.039, 30.200],
        "十堰": [110.798, 32.629], "十堰市": [110.798, 32.629],
        "宜昌": [111.286, 30.692], "宜昌市": [111.286, 30.692],
        "襄阳": [112.122, 32.009], "襄阳市": [112.122, 32.009],
        "鄂州": [114.890, 30.391], "鄂州市": [114.890, 30.391],
        "荆门": [112.199, 31.035], "荆门市": [112.199, 31.035],
        "孝感": [113.917, 30.925], "孝感市": [113.917, 30.925],
        "荆州": [112.240, 30.335], "荆州市": [112.240, 30.335],
        "黄冈": [114.872, 30.454], "黄冈市": [114.872, 30.454],
        "咸宁": [114.322, 29.841], "咸宁市": [114.322, 29.841],
        "随州": [113.382, 31.690], "随州市": [113.382, 31.690],
        "恩施": [109.479, 30.295], "恩施市": [109.479, 30.295],
        # 湖南
        "长沙": [112.979, 28.195], "长沙市": [112.979, 28.195],
        "株洲": [113.134, 27.828], "株洲市": [113.134, 27.828],
        "湘潭": [112.944, 27.830], "湘潭市": [112.944, 27.830],
        "衡阳": [112.572, 26.893], "衡阳市": [112.572, 26.893],
        "邵阳": [111.468, 27.239], "邵阳市": [111.468, 27.239],
        "岳阳": [113.129, 29.357], "岳阳市": [113.129, 29.357],
        "常德": [111.699, 29.032], "常德市": [111.699, 29.032],
        "张家界": [110.479, 29.117], "张家界市": [110.479, 29.117],
        "益阳": [112.355, 28.554], "益阳市": [112.355, 28.554],
        "郴州": [113.015, 25.771], "郴州市": [113.015, 25.771],
        "永州": [111.612, 26.420], "永州市": [111.612, 26.420],
        "怀化": [110.002, 27.569], "怀化市": [110.002, 27.569],
        "娄底": [111.995, 27.697], "娄底市": [111.995, 27.697],
        "湘西": [109.739, 28.311], "湘西州": [109.739, 28.311],
        # 广东
        "广州": [113.264, 23.129], "广州市": [113.264, 23.129],
        "韶关": [113.598, 24.810], "韶关市": [113.598, 24.810],
        "深圳": [114.058, 22.543], "深圳市": [114.058, 22.543],
        "珠海": [113.577, 22.271], "珠海市": [113.577, 22.271],
        "汕头": [116.682, 23.353], "汕头市": [116.682, 23.353],
        "佛山": [113.122, 23.022], "佛山市": [113.122, 23.022],
        "江门": [113.082, 22.579], "江门市": [113.082, 22.579],
        "湛江": [110.359, 21.270], "湛江市": [110.359, 21.270],
        "茂名": [110.925, 21.663], "茂名市": [110.925, 21.663],
        "肇庆": [112.465, 23.047], "肇庆市": [112.465, 23.047],
        "惠州": [114.417, 23.112], "惠州市": [114.417, 23.112],
        "梅州": [116.122, 24.289], "梅州市": [116.122, 24.289],
        "汕尾": [115.375, 22.787], "汕尾市": [115.375, 22.787],
        "河源": [114.700, 23.744], "河源市": [114.700, 23.744],
        "阳江": [111.983, 21.858], "阳江市": [111.983, 21.858],
        "清远": [113.056, 23.682], "清远市": [113.056, 23.682],
        "东莞": [113.752, 23.021], "东莞市": [113.752, 23.021],
        "中山": [113.393, 22.516], "中山市": [113.393, 22.516],
        "潮州": [116.622, 23.657], "潮州市": [116.622, 23.657],
        "揭阳": [116.372, 23.550], "揭阳市": [116.372, 23.550],
        "云浮": [112.045, 22.915], "云浮市": [112.045, 22.915],
        # 广西
        "南宁": [108.367, 22.817], "南宁市": [108.367, 22.817],
        "柳州": [109.416, 24.326], "柳州市": [109.416, 24.326],
        "桂林": [110.290, 25.274], "桂林市": [110.290, 25.274],
        "梧州": [111.279, 23.477], "梧州市": [111.279, 23.477],
        "北海": [109.120, 21.481], "北海市": [109.120, 21.481],
        "防城港": [108.355, 21.687], "防城港市": [108.355, 21.687],
        "钦州": [108.654, 21.981], "钦州市": [108.654, 21.981],
        "贵港": [109.599, 23.112], "贵港市": [109.599, 23.112],
        "玉林": [110.181, 22.654], "玉林市": [110.181, 22.654],
        "百色": [106.618, 23.902], "百色市": [106.618, 23.902],
        "贺州": [111.567, 24.404], "贺州市": [111.567, 24.404],
        "河池": [108.085, 24.693], "河池市": [108.085, 24.693],
        "来宾": [109.221, 23.750], "来宾市": [109.221, 23.750],
        "崇左": [107.365, 22.379], "崇左市": [107.365, 22.379],
        # 海南
        "海口": [110.199, 20.044], "海口市": [110.199, 20.044],
        "三亚": [109.512, 18.253], "三亚市": [109.512, 18.253],
        "三沙": [112.339, 16.831], "三沙市": [112.339, 16.831],
        "儋州": [109.581, 19.521], "儋州市": [109.581, 19.521],
        # 四川
        "成都": [104.066, 30.573], "成都市": [104.066, 30.573],
        "自贡": [104.778, 29.339], "自贡市": [104.778, 29.339],
        "攀枝花": [101.718, 26.582], "攀枝花市": [101.718, 26.582],
        "泸州": [105.442, 28.871], "泸州市": [105.442, 28.871],
        "德阳": [104.397, 31.127], "德阳市": [104.397, 31.127],
        "绵阳": [104.679, 31.468], "绵阳市": [104.679, 31.468],
        "广元": [105.844, 32.435], "广元市": [105.844, 32.435],
        "遂宁": [105.593, 30.533], "遂宁市": [105.593, 30.533],
        "内江": [105.058, 29.580], "内江市": [105.058, 29.580],
        "乐山": [103.766, 29.552], "乐山市": [103.766, 29.552],
        "南充": [106.111, 30.837], "南充市": [106.111, 30.837],
        "眉山": [103.849, 30.077], "眉山市": [103.849, 30.077],
        "宜宾": [104.643, 28.752], "宜宾市": [104.643, 28.752],
        "广安": [106.633, 30.456], "广安市": [106.633, 30.456],
        "达州": [107.468, 31.209], "达州市": [107.468, 31.209],
        "雅安": [103.042, 29.980], "雅安市": [103.042, 29.980],
        "巴中": [106.757, 31.867], "巴中市": [106.757, 31.867],
        "资阳": [104.628, 30.129], "资阳市": [104.628, 30.129],
        # 贵州
        "贵阳": [106.630, 26.647], "贵阳市": [106.630, 26.647],
        "六盘水": [104.830, 26.594], "六盘水市": [104.830, 26.594],
        "遵义": [106.927, 27.726], "遵义市": [106.927, 27.726],
        "安顺": [105.947, 26.253], "安顺市": [105.947, 26.253],
        "毕节": [105.305, 27.284], "毕节市": [105.305, 27.284],
        "铜仁": [109.189, 27.731], "铜仁市": [109.189, 27.731],
        "黔西南": [104.904, 25.090], "黔西南州": [104.904, 25.090],
        "黔东南": [107.983, 26.583], "黔东南州": [107.983, 26.583],
        "黔南": [107.523, 26.254], "黔南州": [107.523, 26.254],
        # 云南
        "昆明": [102.833, 24.881], "昆明市": [102.833, 24.881],
        "曲靖": [103.796, 25.490], "曲靖市": [103.796, 25.490],
        "玉溪": [102.547, 24.352], "玉溪市": [102.547, 24.352],
        "保山": [99.162, 25.112], "保山市": [99.162, 25.112],
        "昭通": [103.717, 27.338], "昭通市": [103.717, 27.338],
        "丽江": [100.227, 26.857], "丽江市": [100.227, 26.857],
        "普洱": [100.966, 22.825], "普洱市": [100.966, 22.825],
        "临沧": [100.089, 23.884], "临沧市": [100.089, 23.884],
        "楚雄": [101.546, 25.033], "楚雄州": [101.546, 25.033],
        "红河": [103.376, 23.369], "红河州": [103.376, 23.369],
        "文山": [104.216, 23.399], "文山州": [104.216, 23.399],
        "西双版纳": [100.798, 22.009], "西双版纳州": [100.798, 22.009],
        "大理": [100.267, 25.607], "大理州": [100.267, 25.607],
        "德宏": [98.585, 24.437], "德宏州": [98.585, 24.437],
        "怒江": [98.853, 25.823], "怒江州": [98.853, 25.823],
        "迪庆": [99.703, 27.819], "迪庆州": [99.703, 27.819],
        # 西藏
        "拉萨": [91.172, 29.650], "拉萨市": [91.172, 29.650],
        "日喀则": [88.887, 29.267], "日喀则市": [88.887, 29.267],
        "昌都": [97.172, 31.141], "昌都市": [97.172, 31.141],
        "林芝": [94.361, 29.644], "林芝市": [94.361, 29.644],
        "山南": [91.773, 29.237], "山南市": [91.773, 29.237],
        "那曲": [92.051, 31.476], "那曲市": [92.051, 31.476],
        "阿里": [80.106, 32.501], "阿里地区": [80.106, 32.501],
        # 陕西
        "西安": [108.940, 34.261], "西安市": [108.940, 34.261],
        "铜川": [108.945, 34.897], "铜川市": [108.945, 34.897],
        "宝鸡": [107.238, 34.363], "宝鸡市": [107.238, 34.363],
        "咸阳": [108.709, 34.330], "咸阳市": [108.709, 34.330],
        "渭南": [109.510, 34.500], "渭南市": [109.510, 34.500],
        "延安": [109.490, 36.585], "延安市": [109.490, 36.585],
        "汉中": [107.024, 33.068], "汉中市": [107.024, 33.068],
        "榆林": [109.735, 38.285], "榆林市": [109.735, 38.285],
        "安康": [109.029, 32.685], "安康市": [109.029, 32.685],
        "商洛": [109.918, 33.873], "商洛市": [109.918, 33.873],
        # 甘肃
        "兰州": [103.823, 36.061], "兰州市": [103.823, 36.061],
        "嘉峪关": [98.289, 39.773], "嘉峪关市": [98.289, 39.773],
        "金昌": [102.188, 38.520], "金昌市": [102.188, 38.520],
        "白银": [104.138, 36.545], "白银市": [104.138, 36.545],
        "天水": [105.725, 34.581], "天水市": [105.725, 34.581],
        "武威": [102.638, 37.928], "武威市": [102.638, 37.928],
        "张掖": [100.450, 38.926], "张掖市": [100.450, 38.926],
        "平凉": [106.665, 35.543], "平凉市": [106.665, 35.543],
        "酒泉": [98.494, 39.733], "酒泉市": [98.494, 39.733],
        "庆阳": [107.643, 35.709], "庆阳市": [107.643, 35.709],
        "定西": [104.592, 35.581], "定西市": [104.592, 35.581],
        "陇南": [104.922, 33.401], "陇南市": [104.922, 33.401],
        "临夏": [103.211, 35.601], "临夏州": [103.211, 35.601],
        "甘南": [102.911, 34.983], "甘南州": [102.911, 34.983],
        # 青海
        "西宁": [101.778, 36.617], "西宁市": [101.778, 36.617],
        "海东": [102.104, 36.502], "海东市": [102.104, 36.502],
        # 宁夏
        "银川": [106.231, 38.487], "银川市": [106.231, 38.487],
        "石嘴山": [106.383, 38.984], "石嘴山市": [106.383, 38.984],
        "吴忠": [106.198, 37.998], "吴忠市": [106.198, 37.998],
        "固原": [106.242, 36.016], "固原市": [106.242, 36.016],
        "中卫": [105.197, 37.500], "中卫市": [105.197, 37.500],
        # 新疆
        "乌鲁木齐": [87.617, 43.793], "乌鲁木齐市": [87.617, 43.793],
        "克拉玛依": [84.889, 45.580], "克拉玛依市": [84.889, 45.580],
        "吐鲁番": [89.190, 42.948], "吐鲁番市": [89.190, 42.948],
        "哈密": [93.514, 42.827], "哈密市": [93.514, 42.827],
        "昌吉": [87.267, 44.011], "昌吉州": [87.267, 44.011],
        "博尔塔拉": [82.066, 44.906], "博尔塔拉州": [82.066, 44.906],
        "巴音郭楞": [86.145, 41.764], "巴音郭楞州": [86.145, 41.764],
        "阿克苏": [80.265, 41.168], "阿克苏地区": [80.265, 41.168],
        "克孜勒苏": [76.168, 39.715], "克孜勒苏州": [76.168, 39.715],
        "喀什": [75.990, 39.470], "喀什地区": [75.990, 39.470],
        "和田": [79.922, 37.114], "和田地区": [79.922, 37.114],
        "伊犁": [81.324, 43.917], "伊犁州": [81.324, 43.917],
        "塔城": [82.980, 46.746], "塔城地区": [82.980, 46.746],
        "阿勒泰": [88.141, 47.845], "阿勒泰地区": [88.141, 47.845],
        # 香港、澳门、台湾
        "香港": [114.174, 22.279], "香港市": [114.174, 22.279],
        "澳门": [113.543, 22.187], "澳门市": [113.543, 22.187],
        "台北": [121.565, 25.033], "台北市": [121.565, 25.033],
        "高雄": [120.312, 22.621], "高雄市": [120.312, 22.621],
        "台中": [120.684, 24.144], "台中市": [120.684, 24.144],
        "台南": [120.216, 22.997], "台南市": [120.216, 22.997],
        "基隆": [121.739, 25.127], "基隆市": [121.739, 25.127],
        "新竹": [120.968, 24.807], "新竹市": [120.968, 24.807],
        "嘉义": [120.449, 23.480], "嘉义市": [120.449, 23.480],
    }
    return coords.get(city)
