"""U-Care 机场数据爬虫：抓取限制面 / 净空区 / 禁飞区等地理数据。

API 端点：
- 列表：POST https://webapi.u-care.net.cn/web/geoQuery/getAirResourceQuery
- 下载：GET  https://webapi.u-care.net.cn/web/geoQuery/getAirResourceFileByName
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://webapi.u-care.net.cn/web/geoQuery"
DOWNLOAD_BASE = "http://mapservices.u-care.net.cn/airresource/download"

# 支持的数据类型
DATA_TYPES = {
    "airport_xzm": "机场限制面",
    "airport_jkq": "机场净空区",
    "airport_buffer": "机场缓冲区",
    "temporary": "临时禁飞区",
    "no_fly": "禁飞区",
}


@dataclass
class AirportFeature:
    """单个机场要素。"""
    name: str
    type: str  # 数据类型 key
    type_label: str  # 数据类型中文名
    kml_url: str | None = None
    geojson_url: str | None = None
    download_count: int = 0
    gid: str | None = None
    city: str | None = None  # 从名称推断
    province: str | None = None

    def to_geojson_feature(self) -> dict[str, Any]:
        """转为 GeoJSON Feature（几何待后续填充）。"""
        props = {
            "name": self.name,
            "type": self.type,
            "type_label": self.type_label,
            "download_count": self.download_count,
            "gid": self.gid,
            "kml_url": self.kml_url,
            "geojson_url": self.geojson_url,
        }
        return {"type": "Feature", "geometry": None, "properties": props}


@dataclass
class UCareError(RuntimeError):
    pass


class UCareClient:
    """U-Care 机场数据 API 客户端。"""

    def __init__(
        self,
        delay: float = 0.3,
        timeout: int = 15,
        session: requests.Session | None = None,
    ):
        self.delay = delay
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; AeroPulse/0.1)",
            "Content-Type": "application/json",
        })

    # ── 核心请求 ────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{BASE_URL}/{path}"
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise UCareError(f"API 错误: {data.get('msg', '未知')}")
        return data

    def _delay(self):
        if self.delay:
            time.sleep(self.delay)

    # ── 列表 API ─────────────────────────────────────────────────────────────

    def list_airports(
        self,
        type_name: str = "airport_xzm",
        page_size: int = 1000,
        keyword: str = "",
    ) -> list[AirportFeature]:
        """获取机场列表。默认取 airport_xzm（机场限制面）。"""
        payload = {
            "typeName": type_name,
            "key": keyword,
            "pageIndex": 1,
            "pageSize": page_size,
        }
        data = self._post("getAirResourceQuery", payload)

        # 实际结构为 data.list
        inner = data.get("data", {})
        if isinstance(inner, dict):
            records = inner.get("list", [])
            total = inner.get("total", 0)
        else:
            records = inner
            total = len(records)

        # 如果总数超过 page_size，继续翻页
        fetched = len(records)
        page = 1
        while fetched < total:
            page += 1
            payload["pageIndex"] = page
            self._delay()
            data = self._post("getAirResourceQuery", payload)
            inner = data.get("data", {})
            if isinstance(inner, dict):
                batch = inner.get("list", [])
            else:
                batch = inner
            if not batch:
                break
            records.extend(batch)
            fetched += len(batch)

        return [self._parse_record(r, type_name) for r in records]

    def _parse_record(self, r: dict, type_name: str) -> AirportFeature:
        """解析单条记录。"""
        name = r.get("name", "")
        city, province = self._infer_location(name)

        return AirportFeature(
            name=name,
            type=type_name,
            type_label=DATA_TYPES.get(type_name, type_name),
            download_count=r.get("downloadcount", 0) or 0,
            gid=r.get("gid"),
            city=city,
            province=province,
        )

    # ── 下载链接 API ─────────────────────────────────────────────────────────

    def get_download_url(self, name: str, type_name: str = "airport_xzm") -> tuple[str | None, str | None]:
        """获取 KML 和 GeoJSON 下载地址。"""
        params = {"name": name, "type": type_name}
        url = f"{BASE_URL}/getAirResourceFileByName"
        resp = self._session.get(url, params=params, timeout=self.timeout)
        self._delay()

        if resp.status_code != 200:
            return None, None

        try:
            data = resp.json()
        except Exception:
            return None, None

        if not data.get("success"):
            return None, None

        kml_url = None
        geojson_url = None
        for item in data.get("data", []):
            ext = item.get("ext", "").lower()
            path = item.get("path", "")
            if ext == "kml" and not kml_url:
                kml_url = path
            elif ext == "geojson" and not geojson_url:
                geojson_url = path

        return kml_url, geojson_url

    def enrich_features(self, features: list[AirportFeature]) -> list[AirportFeature]:
        """批量补充下载链接。"""
        for feat in features:
            kml, geojson = self.get_download_url(feat.name, feat.type)
            feat.kml_url = kml
            feat.geojson_url = geojson
        return features

    # ── 工具方法 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _infer_location(name: str) -> tuple[str | None, str | None]:
        """从机场名称推断省/市。简单实现，可扩展。"""
        # 格式通常为 "城市_机场名"
        if "_" in name:
            parts = name.split("_", 1)
            city = parts[0]
            province = None
            return city, province
        return None, None

    def to_geojson(
        self,
        features: list[AirportFeature],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """导出为 GeoJSON FeatureCollection。"""
        fc = {
            "type": "FeatureCollection",
            "metadata": {
                "source": "u-care.net.cn",
                "fetched_at": datetime.now().isoformat(),
                "total": len(features),
                **(metadata or {}),
            },
            "features": [f.to_geojson_feature() for f in features],
        }
        return fc

    def save_geojson(
        self,
        features: list[AirportFeature],
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """保存为 GeoJSON 文件。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fc = self.to_geojson(features, metadata)
        with path.open("w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False, indent=2)
        return path


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="U-Care 机场数据爬虫")
    parser.add_argument("--type", "-t", default="airport_xzm",
                        choices=list(DATA_TYPES.keys()),
                        help="数据类型 (默认: airport_xzm)")
    parser.add_argument("--output", "-o", default="data/ucare_airports.geojson",
                        help="输出 GeoJSON 路径")
    parser.add_argument("--enrich", "-e", action="store_true",
                        help="补充下载链接 (会显著增加耗时)")
    parser.add_argument("--delay", "-d", type=float, default=0.3,
                        help="请求间隔秒数 (默认: 0.3)")

    args = parser.parse_args()

    print(f"[U-Care] 正在抓取 {DATA_TYPES[args.type]} ...")
    client = UCareClient(delay=args.delay)

    # 1. 获取列表
    features = client.list_airports(type_name=args.type)
    print(f"  → 获取 {len(features)} 条记录")

    # 2. 补充下载链接 (可选)
    if args.enrich:
        print(f"[U-Care] 正在补充下载链接 ...")
        features = client.enrich_features(features)
        with_url = sum(1 for f in features if f.geojson_url)
        print(f"  → {with_url}/{len(features)} 条含下载链接")

    # 3. 保存
    path = client.save_geojson(
        features,
        args.output,
        metadata={"type": args.type, "type_label": DATA_TYPES[args.type]},
    )
    print(f"[U-Care] 已保存 → {path}")


if __name__ == "__main__":
    main()
