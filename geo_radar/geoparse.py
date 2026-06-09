"""Geo Parsing Agent（§6.6）：公告区域描述 → 地图几何 + 置信度分级 + 人审路由。

置信度分级（与方案 §6.6 对齐）：
  A POI明确+半径明确        → 实线（auto_pass）
  B 多考点/场馆明确          → 实线区域组
  C 道路合围/半径估计,有误差 → 橙色半透明（needs_review）
  D 行政区级                 → 虚线大范围
  E 模糊,无法可靠定位        → 不画面，只给待核验点

安全约定：LLM 不直接产出坐标；坐标一律来自高德确定性接口。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import geometry as g
from .amap import AmapClient, AmapError


@dataclass
class GeoParse:
    geo_type: str
    grade: str
    confidence: float
    method: str
    geometry: dict | None          # GeoJSON geometry（GCJ-02）或 None
    center: list[float] | None     # [lng, lat]，用于弹窗/待核验点
    radius_m: float | None
    review_status: str             # auto_pass | needs_review
    review_reason: str
    detail: dict = field(default_factory=dict)


def parse(ann: dict, client: AmapClient) -> GeoParse:
    geo = ann.get("geo") or {}
    gtype = geo.get("geo_type")
    city = geo.get("city", "")
    try:
        if gtype == "poi_buffer":
            return _poi_buffer(geo, city, client)
        if gtype == "poi_buffer_multi":
            return _poi_buffer_multi(geo, city, client)
        if gtype == "admin":
            return _admin(geo, client)
        if gtype == "bbox_roads":
            return _bbox_roads(geo, city, client)
        if gtype in ("area_no_boundary", "fuzzy"):
            return _review_only(geo, city, client, gtype)
    except AmapError as exc:
        return GeoParse(gtype or "unknown", "E", 0.0, "amap_error", None, None, None,
                        "needs_review", f"地理编码失败：{exc}")
    return GeoParse(gtype or "unknown", "E", 0.0, "none", None, None, None,
                    "needs_review", "未知的区域表达类型")


def _poi_buffer(geo: dict, city: str, client: AmapClient) -> GeoParse:
    poi = geo["poi"]
    pt = client.locate(poi, city)
    if not pt:
        return GeoParse("poi_buffer", "E", 0.0, "poi_failed", None, None, None,
                        "needs_review", f"POI 未解析：{poi}")
    explicit = geo.get("radius_m")
    radius = float(explicit or geo.get("radius_estimated") or 500)
    geom = g.polygon_geometry([g.circle_ring(pt.lng, pt.lat, radius)])
    if explicit:
        return GeoParse("poi_buffer", "A", 0.9, pt.method, geom, [pt.lng, pt.lat], radius,
                        "auto_pass", "POI 明确 + 半径明确", {"poi_name": pt.name})
    return GeoParse("poi_buffer", "C", 0.6, pt.method, geom, [pt.lng, pt.lat], radius,
                    "needs_review", f"公告未明示半径，按 {radius:.0f}m 估计，需人工核验",
                    {"poi_name": pt.name, "radius_estimated": True})


def _poi_buffer_multi(geo: dict, city: str, client: AmapClient) -> GeoParse:
    radius = float(geo.get("radius_m") or 500)
    polys: list = []
    resolved: list = []
    failed: list = []
    for name in geo.get("poi_list", []):
        pt = client.locate(name, city)
        if pt:
            polys.append([g.circle_ring(pt.lng, pt.lat, radius)])
            resolved.append({"name": name, "resolved": pt.name, "lng": pt.lng, "lat": pt.lat})
        else:
            failed.append(name)
    if not polys:
        return GeoParse("poi_buffer_multi", "E", 0.0, "poi_failed", None, None, radius,
                        "needs_review", "考点全部未解析")
    geom = g.multipolygon_geometry(polys)
    center = [resolved[0]["lng"], resolved[0]["lat"]]
    detail = {"resolved": resolved, "failed": failed}
    if geo.get("roster_status") == "candidate_needs_verification":
        return GeoParse("poi_buffer_multi", "B", 0.62, "poi", geom, center, radius,
                        "needs_review",
                        "考点名单未在通告中列出，当前为候选点位，需招考院/教育局名单核验", detail)
    return GeoParse("poi_buffer_multi", "B", 0.85, "poi", geom, center, radius,
                    "auto_pass", "多考点 + 半径明确", detail)


def _admin(geo: dict, client: AmapClient) -> GeoParse:
    res = client.district_rings(geo["district"])
    if not res:
        return GeoParse("admin", "E", 0.0, "district_failed", None, None, None,
                        "needs_review", f"行政区未解析：{geo['district']}")
    rings, center = res
    geom = g.multipolygon_geometry([[r] for r in rings])
    return GeoParse("admin", "D", 0.8, "district", geom, [center.lng, center.lat], None,
                    "auto_pass", "行政区边界明确（大范围提示）", {"district": center.name})


def _expand_bbox(ring: list[list[float]], buffer_m: float) -> list[list[float]]:
    """将外接矩形向外扩 buffer_m 米（四至外延）。"""
    lats = [p[1] for p in ring]
    lngs = [p[0] for p in ring]
    mid_lat = (min(lats) + max(lats)) / 2
    dlat = buffer_m / g.M_PER_DEG_LAT
    dlng = buffer_m / (g.M_PER_DEG_LAT * math.cos(math.radians(mid_lat)))
    w, e, s, n = min(lngs) - dlng, max(lngs) + dlng, min(lats) - dlat, max(lats) + dlat
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]


def _bbox_roads(geo: dict, city: str, client: AmapClient) -> GeoParse:
    pts: list = []
    failed: list = []
    for road in geo.get("roads", []):
        pt = client.locate(road, city)
        if pt:
            pts.append((pt.lng, pt.lat))
        else:
            failed.append(road)
    if len(pts) < 3:
        return GeoParse("bbox_roads", "E", 0.0, "roads_failed", None, None, None,
                        "needs_review", f"四至道路解析不足，已解析 {len(pts)} 条，失败 {failed}")
    ring = g.bbox_ring(pts)
    if geo.get("outer_buffer_m"):
        ring = _expand_bbox(ring, float(geo["outer_buffer_m"]))
    geom = g.polygon_geometry([ring])
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return GeoParse("bbox_roads", "C", 0.45, "roads_bbox", geom, [cx, cy], None,
                    "needs_review", "道路合围为近似外接矩形，存在误差，需人工核验",
                    {"resolved_roads": len(pts), "failed": failed})


def _review_only(geo: dict, city: str, client: AmapClient, gtype: str) -> GeoParse:
    poi = geo.get("poi")
    pt = client.locate(poi, city) if poi else None
    center = [pt.lng, pt.lat] if pt else None
    geom = {"type": "Point", "coordinates": center} if center else None
    reason = geo.get("note") or "区域描述模糊，无可靠边界，需人工核验"
    return GeoParse(gtype, "E", 0.2 if center else 0.0, "review_point", geom, center, None,
                    "needs_review", reason, {"poi_name": pt.name if pt else None})
