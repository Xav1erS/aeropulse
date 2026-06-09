"""纯几何工具：米制圆缓冲、GeoJSON 组装。

约定：坐标一律 [经度, 纬度]（GCJ-02）。本模块零三方依赖。
"""
from __future__ import annotations

import math

M_PER_DEG_LAT = 111_320.0  # 每纬度约 111.32 km


def _m_per_deg_lng(lat: float) -> float:
    return M_PER_DEG_LAT * math.cos(math.radians(lat))


def circle_ring(lng: float, lat: float, radius_m: float, segments: int = 72) -> list[list[float]]:
    """以 (lng,lat) 为圆心、radius_m 米为半径生成闭合圆环（米制近似）。"""
    dlat = radius_m / M_PER_DEG_LAT
    dlng = radius_m / _m_per_deg_lng(lat)
    ring = [
        [lng + dlng * math.cos(2 * math.pi * i / segments),
         lat + dlat * math.sin(2 * math.pi * i / segments)]
        for i in range(segments)
    ]
    ring.append(ring[0])
    return ring


def bbox_ring(points: list[tuple[float, float]]) -> list[list[float]]:
    """由若干点取外接矩形闭合环（用于四至近似边界）。"""
    lngs = [p[0] for p in points]
    lats = [p[1] for p in points]
    w, e, s, n = min(lngs), max(lngs), min(lats), max(lats)
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]


def parse_amap_polyline(polyline: str) -> list[list[list[float]]]:
    """解析高德行政区 polyline：'|' 分隔多环，';' 分隔点，',' 分隔经纬度。"""
    rings: list[list[list[float]]] = []
    for part in polyline.split("|"):
        ring: list[list[float]] = []
        for pair in part.split(";"):
            if not pair:
                continue
            lng_s, lat_s = pair.split(",")
            ring.append([float(lng_s), float(lat_s)])
        if len(ring) >= 3:
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            rings.append(ring)
    return rings


def polygon_geometry(rings: list[list[list[float]]]) -> dict:
    return {"type": "Polygon", "coordinates": rings}


def multipolygon_geometry(polys: list[list[list[list[float]]]]) -> dict:
    return {"type": "MultiPolygon", "coordinates": polys}


def feature(geometry: dict | None, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def feature_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}
