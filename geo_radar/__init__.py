"""geo_radar：低空讯图 PoC 的地理解析 / 时间判断模块。

职责对应技术方案：
- Geo Parsing Agent（§6.6）：正文区域描述 → 地图几何对象
- Temporal & Validity Agent（§6.7）：时间归一化与生效状态

坐标系约定：全链路统一 GCJ-02（火星坐标系），与高德 Web 服务返回值、高德底图
瓦片一致；接 PostGIS / GPS 时再做 WGS-84 转换。
"""

__all__ = ["amap", "geometry", "temporal", "geoparse", "extraction_agent"]
