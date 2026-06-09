"""U-Care 机场数据抓取 → 地图落图流程（测试版：20 条）。

用法：
  python -m geo_radar.ucare_publish --limit 20 --out outputs
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from .ucare import UCareClient, DATA_TYPES
from .geometry import feature_collection, feature, multipolygon_geometry, polygon_geometry

KML_BASE = "http://mapservices.u-care.net.cn/airresource/download"


def _download_kml(name: str, data_type: str) -> dict | None:
    """下载并解析 KML，返回 GeoJSON geometry 或 None。"""
    url = f"{KML_BASE}/{data_type}/{name}.kml"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return None
    except Exception:
        return None

    content = resp.text
    # 简单 KML 解析：提取 Polygon/LineString/Point coordinates
    coords = _parse_kml_coords(content)
    return coords


def _parse_kml_coords(kml_text: str) -> dict | None:
    """从 KML 文本提取坐标，生成 GeoJSON geometry。"""
    import re

    # 优先提取 Polygon
    poly_match = re.search(r'<Polygon[^>]*>(.*?)</Polygon>', kml_text, re.DOTALL | re.IGNORECASE)
    if poly_match:
        outer_match = re.search(r'<outerBoundaryIs[^>]*>(.*?)</outerBoundaryIs>', poly_match.group(1), re.DOTALL | re.IGNORECASE)
        if outer_match:
            coords_text = re.sub(r'<[^>]+>', '', outer_match.group(1)).strip()
            coords = _parse_coord_string(coords_text)
            if coords and len(coords) >= 3:
                return {"type": "Polygon", "coordinates": [coords]}

    # 回退：MultiPolygon (多个 Polygon)
    poly_matches = re.findall(r'<Polygon[^>]*>(.*?)</Polygon>', kml_text, re.DOTALL | re.IGNORECASE)
    if poly_matches:
        rings = []
        for pm in poly_matches:
            outer_match = re.search(r'<outerBoundaryIs[^>]*>(.*?)</outerBoundaryIs>', pm, re.DOTALL | re.IGNORECASE)
            if outer_match:
                coords_text = re.sub(r'<[^>]+>', '', outer_match.group(1)).strip()
                coords = _parse_coord_string(coords_text)
                if coords and len(coords) >= 3:
                    rings.append([coords])
        if rings:
            return {"type": "MultiPolygon", "coordinates": rings}

    # 回退：LineString
    line_match = re.search(r'<LineString[^>]*>(.*?)</LineString>', kml_text, re.DOTALL | re.IGNORECASE)
    if line_match:
        coords_text = re.sub(r'<[^>]+>', '', line_match.group(1)).strip()
        coords = _parse_coord_string(coords_text)
        if coords and len(coords) >= 2:
            return {"type": "LineString", "coordinates": coords}

    # 回退：Point
    pt_match = re.search(r'<Point[^>]*>(.*?)</Point>', kml_text, re.DOTALL | re.IGNORECASE)
    if pt_match:
        coords_text = re.sub(r'<[^>]+>', '', pt_match.group(1)).strip()
        coords = _parse_coord_string(coords_text)
        if coords:
            return {"type": "Point", "coordinates": coords[0]}

    return None


def _parse_coord_string(text: str) -> list:
    """解析 'lon,lat,alt lon,lat,alt ...' 为 [[lon,lat],...]"""
    import re
    parts = re.findall(r'(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)', text)
    return [[float(lon), float(lat)] for lon, lat in parts]


def _build_style(is_permanent: bool = True) -> dict:
    """机场限制面的固定样式（长期有效，红色边框/填充）。"""
    return {
        "color": "#b91c47",       # 深红
        "fillColor": "#fda4af",   # 浅红
        "fillOpacity": 0.25,
        "dashed": False,
        "layer": "机场限制面（永久）",
        "status": "永久有效",
        "active": True,
    }


def fetch_and_publish(
    data_type: str = "airport_xzm",
    limit: int = 20,
    out_dir: str = "outputs",
    delay: float = 0.3,
) -> dict:
    """抓取机场数据 → 下载几何 → 输出 zones.geojson。"""
    client = UCareClient(delay=delay)

    # 1. 获取列表（前 limit 条）
    print(f"[U-Care] 抓取 {DATA_TYPES[data_type]}，前 {limit} 条...")
    features = client.list_airports(type_name=data_type, page_size=limit)
    print(f"  → 获取 {len(features)} 条记录")

    # 2. 下载几何
    geo_features: list = []
    failed = []
    for i, feat in enumerate(features):
        print(f"  [{i+1}/{len(features)}] 下载几何: {feat.name}...", end=" ", flush=True)
        geom = _download_kml(feat.name, data_type)
        if geom:
            style = _build_style()
            props = {
                "id": f"ucare_{feat.type}_{feat.name}",
                "title": f"{feat.name} 限制面",
                "source": "u-care.net.cn",
                "data_type": feat.type,
                "data_type_label": feat.type_label,
                "city": feat.city,
                "geo_method": "kml_download",
                "geometry_type": geom["type"],
                **style,
            }
            geo_features.append(feature(geom, props))
            print("[OK]")
        else:
            failed.append(feat.name)
            print("[FAIL]")
        time.sleep(delay)

    print(f"\n成功 {len(geo_features)} 条，失败 {len(failed)} 条")
    if failed:
        print(f"  失败列表: {', '.join(failed[:5])}" + ("..." if len(failed) > 5 else ""))

    # 3. 写出
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    fc = feature_collection(geo_features)
    fc["metadata"] = {
        "source": "u-care.net.cn",
        "data_type": data_type,
        "data_type_label": DATA_TYPES[data_type],
        "fetched_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "total": len(geo_features),
        "failed": len(failed),
    }

    (out / "zones.geojson").write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "zones.js").write_text("window.ZONES = " + json.dumps(fc, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"\n已写出 → {out / 'zones.geojson'} ({len(geo_features)} 个要素)")

    return fc


def main():
    import argparse
    ap = argparse.ArgumentParser(description="U-Care 机场数据落图")
    ap.add_argument("--type", "-t", default="airport_xzm",
                    choices=list(DATA_TYPES.keys()),
                    help="数据类型 (默认: airport_xzm)")
    ap.add_argument("--limit", "-n", type=int, default=20,
                    help="抓取数量 (默认: 20)")
    ap.add_argument("--out", "-o", default="outputs",
                    help="输出目录 (默认: outputs)")
    ap.add_argument("--delay", "-d", type=float, default=0.3,
                    help="请求间隔秒数 (默认: 0.3)")
    args = ap.parse_args()

    fetch_and_publish(
        data_type=args.type,
        limit=args.limit,
        out_dir=args.out,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
