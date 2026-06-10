#!/usr/bin/env python3
"""修复 zones.geojson 中 12 条 admin 类型记录被全国边界污染的 bug。

根因：amap.py district_rings 取 items[0]，但高德返回列表第一项为全国。
修复：将受影响记录的 geometry 替换为城市中心 Point，geo_grade 降为 C，
      标记 needs_review，待有 AMAP_KEY 环境重新运行落图获取正确行政区边界。
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ZONES_PATH = PROJECT_ROOT / "outputs" / "zones.geojson"

# ── 全国边界特征：点数 >50000 且经纬度跨度 >50 度 ──
def _is_national_polygon(ring: list) -> bool:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    lon_range = max(lons) - min(lons)
    lat_range = max(lats) - min(lats)
    return len(ring) > 50000 and lon_range > 50 and lat_range > 30

# ── 受影响的 12 个城市的正确中心坐标 (GCJ-02) ──
CITY_CENTERS = {
    "保定市": [115.465, 38.874],
    "承德市": [117.963, 40.952],
    "邯郸市": [114.539, 36.626],
    "廊坊市": [116.684, 39.538],
    "雄安新区": [115.999, 39.000],      # 约在容城
    "大连": [121.615, 38.914],
    "抚顺": [123.957, 41.881],
    "兰州市": [103.823, 36.061],
    "唐山市": [118.180, 39.630],
    "文昌市": [110.797, 19.543],
    # 备选：带"市"后缀
    "保定": [115.465, 38.874],
    "承德": [117.963, 40.952],
    "邯郸": [114.539, 36.626],
    "廊坊": [116.684, 39.538],
    "兰州": [103.823, 36.061],
    "唐山": [118.180, 39.630],
    "文昌": [110.797, 19.543],
    "秦皇岛市": [119.600, 39.935],
    "秦皇岛": [119.600, 39.935],
    "西宁": [101.778, 36.617],
    "西宁市": [101.778, 36.617],
}


def main():
    print("=" * 64)
    print("  修复全国边界 bug — zones.geojson")
    print("=" * 64)

    zones = json.loads(ZONES_PATH.read_text(encoding="utf-8"))
    fixed_count = 0

    for f in zones["features"]:
        props = f["properties"]
        geo_type = props.get("geo_type")
        geo_grade = props.get("geo_grade")

        # 只处理 admin 类型
        if geo_type != "admin":
            continue

        # 检测是否包含全国边界
        geometry = f.get("geometry")
        if not geometry or geometry["type"] != "MultiPolygon":
            continue

        polys = geometry.get("coordinates", [])
        has_national = False
        for poly in polys:
            if _is_national_polygon(poly[0]):
                has_national = True
                break

        if not has_national:
            continue

        # 获取城市中心
        city = props.get("city", "")
        center = CITY_CENTERS.get(city)
        if center is None:
            print(f"  [SKIP] {props.get('title','unknown')[:40]} — city={city} 无已知中心坐标")
            continue

        # 替换 geometry 为 Point
        f["geometry"] = {
            "type": "Point",
            "coordinates": [center[0], center[1]],
        }
        # 更新属性
        props["center"] = [center[0], center[1]]
        props["geo_grade"] = "C"
        props["geo_confidence"] = 0.5
        props["review_status"] = "needs_review"
        props["review_reason"] = (
            "全国边界污染已修正为城市中心点(待高德重新查询获取正确行政区边界)"
        )
        props["geo_method"] = "city_center_fallback"
        props["layer"] = "已过期/未生效"
        props["geometry_type"] = "Point"

        fixed_count += 1
        print(f"  [FIXED] {props.get('title','unknown')[:50]}… → Point({center[0]:.3f}, {center[1]:.3f})")

    # 写回
    ZONES_PATH.write_text(json.dumps(zones, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共修复 {fixed_count} 条记录")
    print("=" * 64)

    # ── 同时修复 announcements.json ──
    ann_path = PROJECT_ROOT / "outputs" / "announcements.json"
    anns = json.loads(ann_path.read_text(encoding="utf-8"))
    ann_fixed = 0

    for a in anns:
        if a.get("geo_type") != "admin":
            continue
        center = a.get("center")
        if center and abs(center[0] - 116.368) < 0.1 and abs(center[1] - 39.915) < 0.1:
            city = a.get("city", "")
            new_center = CITY_CENTERS.get(city)
            if new_center:
                a["center"] = [new_center[0], new_center[1]]
                a["geo_grade"] = "C"
                a["geo_confidence"] = 0.5
                a["review_status"] = "needs_review"
                a["review_reason"] = "全国边界污染已修正为城市中心点(待高德重新查询)"
                a["geometry_type"] = "Point"
                ann_fixed += 1

    ann_path.write_text(json.dumps(anns, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"announcements.json 共修复 {ann_fixed} 条记录")


if __name__ == "__main__":
    main()
