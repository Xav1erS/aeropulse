"""高德 Web 服务客户端：地理编码 / POI 搜索 / 行政区边界。返回坐标为 GCJ-02。

Key 优先读环境变量 AMAP_KEY，也可显式传入。仅用公开 REST 接口（v3）。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

from .geometry import parse_amap_polyline

BASE = "https://restapi.amap.com/v3"


@dataclass
class GeoPoint:
    lng: float
    lat: float
    name: str = ""
    method: str = ""  # geocode | poi | district


class AmapError(RuntimeError):
    pass


class AmapClient:
    def __init__(self, key: str | None = None, delay: float = 0.15, timeout: int = 10):
        self.key = key or os.environ.get("AMAP_KEY", "")
        if not self.key:
            raise AmapError("缺少高德 Key：请设置环境变量 AMAP_KEY 或显式传入。")
        self.delay = delay
        self.timeout = timeout

    def _get(self, path: str, params: dict) -> dict:
        resp = requests.get(f"{BASE}/{path}", params={**params, "key": self.key}, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if str(data.get("status")) != "1":
            raise AmapError(f"高德 {path} 异常: status={data.get('status')} info={data.get('info')}")
        if self.delay:
            time.sleep(self.delay)
        return data

    def geocode(self, address: str, city: str = "") -> GeoPoint | None:
        data = self._get("geocode/geo", {"address": address, "city": city})
        items = data.get("geocodes") or []
        if not items or not items[0].get("location"):
            return None
        lng, lat = items[0]["location"].split(",")
        return GeoPoint(float(lng), float(lat), address, "geocode")

    def search_poi(self, keywords: str, city: str = "") -> GeoPoint | None:
        data = self._get("place/text", {"keywords": keywords, "city": city, "offset": "1", "page": "1"})
        items = data.get("pois") or []
        if not items or not items[0].get("location"):
            return None
        poi = items[0]
        lng, lat = poi["location"].split(",")
        return GeoPoint(float(lng), float(lat), poi.get("name", keywords), "poi")

    def locate(self, keywords: str, city: str = "") -> GeoPoint | None:
        """地标/场馆/学校优先走 POI 搜索，失败回退地理编码。"""
        return self.search_poi(keywords, city) or self.geocode(keywords, city)

    def district_rings(self, keywords: str) -> tuple[list[list[list[float]]], GeoPoint] | None:
        """返回行政区边界多环（每环一个独立多边形）+ 中心点。"""
        data = self._get("config/district", {"keywords": keywords, "subdistrict": "0", "extensions": "all"})
        items = data.get("districts") or []
        if not items or not items[0].get("polyline"):
            return None
        d = items[0]
        rings = parse_amap_polyline(d["polyline"])
        clng, clat = (d.get("center") or "0,0").split(",")
        return rings, GeoPoint(float(clng), float(clat), d.get("name", keywords), "district")

    def regeo(self, lng: float, lat: float) -> dict | None:
        """逆地理编码：坐标 → 省/市/区/街道。返回 addressComponent 字典。"""
        data = self._get("geocode/regeo", {
            "location": f"{lng},{lat}",
            "extensions": "base",
            "radius": "1000",
        })
        regeo = data.get("regeocode")
        if not regeo:
            return None
        ac = regeo.get("addressComponent") or {}
        # 处理直辖市：高德把"北京市"放在 province，city 为空或为 [] 
        province = ac.get("province", "")
        city = ac.get("city", "")
        if isinstance(city, list):
            city = city[0] if city else ""
        if not city or city == province:
            city = province  # 直辖市直接用省名作为城市
        return {
            "province": str(province).rstrip("省市"),
            "city": str(city).rstrip("市"),
            "district": str(ac.get("district", "")).rstrip("区县"),
            "adcode": str(ac.get("adcode", "")),
            "formatted": str(regeo.get("formatted_address", "")),
        }
