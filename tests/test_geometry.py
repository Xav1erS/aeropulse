"""geo_radar.geometry 单元测试 — 纯几何函数（零三方依赖）。"""

import math
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geo_radar.geometry import (
    M_PER_DEG_LAT,
    _m_per_deg_lng,
    circle_ring,
    bbox_ring,
    parse_amap_polyline,
    polygon_geometry,
    multipolygon_geometry,
    feature,
    feature_collection,
)


class TestMPerDegLng:
    """_m_per_deg_lng()  — 经度每度米数 = M_PER_DEG_LAT * cos(lat)"""

    def test_equator(self):
        """赤道处 cos(0)=1，应等于基准值"""
        assert _m_per_deg_lng(0) == M_PER_DEG_LAT

    def test_north_pole(self):
        """极点处 cos(90°)=0，经度每度米数应为 0"""
        assert round(_m_per_deg_lng(90), 6) == 0.0

    def test_mid_latitude(self):
        """中纬度 should be ~ cos(lat) * M_PER_DEG_LAT"""
        lat = 36  # 青岛纬度
        expected = M_PER_DEG_LAT * math.cos(math.radians(lat))
        assert _m_per_deg_lng(lat) == expected

    def test_southern_hemisphere(self):
        """南半球 cos 对称"""
        lat = -30
        assert _m_per_deg_lng(lat) == M_PER_DEG_LAT * math.cos(math.radians(30))


class TestCircleRing:
    """circle_ring(lng, lat, radius_m, segments=N)"""

    def test_basic_circle(self):
        """基本圆形：返回 segments+1 个点，首尾闭合"""
        ring = circle_ring(120.0, 36.0, 1000, segments=36)
        assert len(ring) == 37  # segments + 1（闭合点）
        assert ring[0] == ring[-1]  # 首尾闭合

    def test_zero_radius(self):
        """半径为 0：所有点与圆心相同"""
        ring = circle_ring(120.0, 36.0, 0, segments=4)
        for pt in ring:
            assert pt[0] == 120.0
            assert pt[1] == 36.0

    def test_center_preserved(self):
        """圆心大致在 ring 的质心"""
        ring = circle_ring(120.0, 36.0, 500, segments=360)
        avg_lng = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        avg_lat = sum(p[1] for p in ring[:-1]) / (len(ring) - 1)
        assert abs(avg_lng - 120.0) < 1e-4
        assert abs(avg_lat - 36.0) < 1e-4

    def test_radius_proportionality(self):
        """半径翻倍 -> 坐标范围翻倍"""
        r1 = circle_ring(120.0, 36.0, 500, segments=360)
        r2 = circle_ring(120.0, 36.0, 1000, segments=360)
        lngs1 = [p[0] for p in r1]
        lngs2 = [p[0] for p in r2]
        # 范围比例约 2
        ratio = (max(lngs2) - min(lngs2)) / (max(lngs1) - min(lngs1))
        assert 1.9 < ratio < 2.1

    def test_pole_nearby_circle(self):
        """高纬度区域圆形：经度/纬度比例不同"""
        ring = circle_ring(0.0, 80.0, 1000, segments=72)
        lngs = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        lng_range = max(lngs) - min(lngs)
        lat_range = max(lats) - min(lats)
        # 高纬处 lng_range 应该远大于 lat_range
        assert lng_range > lat_range * 2


class TestBboxRing:
    """bbox_ring(points) — 外接矩形闭合环"""

    def test_four_points(self):
        """4 个点形成矩形"""
        pts = [(1.0, 2.0), (3.0, 2.0), (3.0, 4.0), (1.0, 4.0)]
        ring = bbox_ring(pts)
        assert len(ring) == 5  # 4 角 + 闭合
        assert ring == [[1.0, 2.0], [3.0, 2.0], [3.0, 4.0], [1.0, 4.0], [1.0, 2.0]]

    def test_unordered_points(self):
        """无序点：自动取 min/max"""
        pts = [(5.0, 10.0), (2.0, 15.0), (8.0, 12.0)]
        ring = bbox_ring(pts)
        assert ring == [[2.0, 10.0], [8.0, 10.0], [8.0, 15.0], [2.0, 15.0], [2.0, 10.0]]

    def test_single_point(self):
        """单点：矩形退化为点"""
        ring = bbox_ring([(1.0, 2.0)])
        assert ring == [[1.0, 2.0], [1.0, 2.0], [1.0, 2.0], [1.0, 2.0], [1.0, 2.0]]

    def test_two_points(self):
        """两点：形成线段的包围盒"""
        ring = bbox_ring([(1.0, 3.0), (5.0, 7.0)])
        assert ring == [[1.0, 3.0], [5.0, 3.0], [5.0, 7.0], [1.0, 7.0], [1.0, 3.0]]


class TestParseAmapPolyline:
    """parse_amap_polyline(polyline) — 高德行政区 polyline 解析"""

    def test_single_ring(self):
        """单环解析"""
        result = parse_amap_polyline("120.0,36.0;120.1,36.0;120.1,36.1;120.0,36.1")
        assert len(result) == 1
        assert len(result[0]) == 5  # 4 points + auto-closed
        assert result[0][0] == [120.0, 36.0]
        assert result[0][0] == result[0][-1]  # closed

    def test_multi_ring(self):
        """多环（如带洞行政区）"""
        result = parse_amap_polyline(
            "120.0,36.0;120.1,36.0;120.1,36.1;120.0,36.1|"
            "120.02,36.02;120.08,36.02;120.08,36.08;120.02,36.08"
        )
        assert len(result) == 2
        assert len(result[0]) == 5
        assert len(result[1]) == 5

    def test_already_closed_ring(self):
        """首尾已闭合的不重复加点"""
        result = parse_amap_polyline("120.0,36.0;120.1,36.0;120.1,36.1;120.0,36.0")
        assert len(result[0]) == 4  # 未追加闭合点

    def test_less_than_3_points(self):
        """不足 3 个点的环被忽略"""
        result = parse_amap_polyline("120.0,36.0;120.1,36.1")
        assert len(result) == 0

    def test_empty_string(self):
        """空字符串"""
        result = parse_amap_polyline("")
        assert result == []

    def test_empty_part(self):
        """跳过空分段"""
        result = parse_amap_polyline(
            "120.0,36.0;120.1,36.0;120.1,36.1|"
            "|"
            "120.5,36.5;120.6,36.5;120.6,36.6"
        )
        assert len(result) == 2


class TestGeoJSONConstructors:
    """polygon_geometry / multipolygon_geometry / feature / feature_collection"""

    def test_polygon_geometry(self):
        rings = [[[1, 2], [3, 2], [3, 4], [1, 2]]]
        geom = polygon_geometry(rings)
        assert geom["type"] == "Polygon"
        assert geom["coordinates"] == rings

    def test_multipolygon_geometry(self):
        polys = [[[[1, 2], [3, 2], [3, 4], [1, 2]]]]
        geom = multipolygon_geometry(polys)
        assert geom["type"] == "MultiPolygon"
        assert geom["coordinates"] == polys

    def test_feature_with_geometry(self):
        geom = {"type": "Point", "coordinates": [120, 36]}
        props = {"name": "test"}
        feat = feature(geom, props)
        assert feat["type"] == "Feature"
        assert feat["geometry"] == geom
        assert feat["properties"] == props

    def test_feature_without_geometry(self):
        feat = feature(None, {"name": "no geometry"})
        assert feat["type"] == "Feature"
        assert feat["geometry"] is None
        assert feat["properties"] == {"name": "no geometry"}

    def test_feature_collection_empty(self):
        fc = feature_collection([])
        assert fc["type"] == "FeatureCollection"
        assert fc["features"] == []

    def test_feature_collection_with_items(self):
        f1 = feature(None, {"id": 1})
        f2 = feature(None, {"id": 2})
        fc = feature_collection([f1, f2])
        assert len(fc["features"]) == 2
        assert fc["features"][0]["properties"]["id"] == 1
