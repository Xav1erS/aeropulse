# CLAUDE.md — 低空讯图（青岛低空公告雷达）

AI PM 面试 PoC。验证命题：**AI 能否自动发现公开低空管控公告，抽取时间/地点/类型，地图化，并对"某地 + 某时能否飞"给出基于证据的风险提示。** 不做飞行审批，不判定"绝对能飞"。

设计依据（先读）：
- `does/低空讯图｜AI PM 面试 PoC 方案_更新版.md`
- `does/青岛市_低慢小_无人机临时禁飞公告地图｜AI 技术方案.md`

当前进度与下一步见 `HANDOFF.md`。

## 两层架构

| 层 | 包 | 职责 | 文档 |
|---|---|---|---|
| 发现 + 分类 | `source_audit/` | 公开网页轻量抓取 → 标题/时间/正文抽取 → A–E 规则分类 → SQLite/CSV/MD 报告 | `README.md` |
| 落图 + 查询 | `geo_radar/` | 公告结构化 → 地理解析（高德）→ GeoJSON 图层 → 地图 + 地点/时间风险查询 | 本文件 |

`geo_radar` 消费"公告结构化结果"：可通过两种方式提供 —— ① `data/announcements_seed.json`（预结构化种子，已验证）；② `extraction_agent.py`（LLM 在线抽取，已接入，输出格式与种子对齐）。接口是 `geoparse.parse(ann)` 的上游。

## geo_radar 模块

- `amap.py` 高德 Web 服务客户端（地理编码 / POI / 行政区边界）。Key 读环境变量 `AMAP_KEY`。返回 GCJ-02。
- `geometry.py` 纯几何（米制圆缓冲、点在多边形、点到边界距离、GeoJSON 组装）。**零三方依赖**。
- `temporal.py` 时间状态机（NOT_STARTED/ACTIVE/EXPIRED/LONG_TERM/INACTIVE/UNKNOWN），含周期性（季节性）公告。
- `geoparse.py` **Geo Parsing Agent**：按 `geo_type` 分派落图（poi_buffer / poi_buffer_multi / admin / bbox_roads / area_no_boundary）+ A–E 置信度分级 + 人审路由。
- `extraction_agent.py` **LLM 在线抽取 Agent**（方案 §7.2–§7.5）：原始公告正文 → 分类 + 9字段抽取 + 证据绑定。OpenAI 兼容 API。LLM 绝不输出坐标。
- `__main__.py` 落图运行：种子 或 LLM抽取 → `outputs/{zones.geojson, zones.js, announcements.json}`。
- `web/map.html` 单文件地图 Demo（Leaflet + 高德底图，点击地图发起风险查询）。

## 运行

```powershell
# 模式1：预结构化种子落图
$env:AMAP_KEY="<高德 Web 服务 Key>"
.\.venv\Scripts\python.exe -m geo_radar --now 2026-06-08T12:00:00

# 模式2：LLM 在线抽取 → 落图
$env:AMAP_KEY="<高德 Key>"
$env:LLM_API_KEY="<LLM Key>"          # 支持 DeepSeek/Qwen/GPT-4o 等 OpenAI 兼容 API
.\.venv\Scripts\python.exe -m geo_radar --extract data/raw_announcements.json --now 2026-06-08T12:00:00

# 模式3：单条正文快速测试（仅抽取，无需 AMAP_KEY）
$env:LLM_API_KEY="<LLM Key>"
.\.venv\Scripts\python.exe -m geo_radar --extract-text "公告正文..." --source-name "来源" --city "城市"

# 查询（通过地图页 UI）
点击地图任意位置，发起风险查询请求。

# 地图
.\.venv\Scripts\python.exe -m http.server 8011   # http://localhost:8011/web/map.html
```

`source_audit` 的运行见 `README.md`。

## 不可违背的约定

1. **坐标系全链路 GCJ-02**（高德编码 / 缓冲 / 底图 / 查询同系），避免 ~500m 偏移。接 PostGIS / GPS 再转 WGS-84。
2. **LLM 绝不直接输出坐标** —— 只输出"地点引用文本"，坐标一律来自高德确定性接口。安全产品红线：防"看似合理"的幻觉坐标 → 错误落图。
3. **安全口径**：永不说"可以飞"；"未命中 ≠ 飞行许可"；所有结论附 UOM / 官方核验提示；不提供规避监管建议。
4. **分级与路由**：来源 P0–P4（见 README）；地理置信度 A–E（方案 §6.6）。边界模糊 / 四至 / 无边界源 / 低置信 → 进人工核验，不强行精确画图。
5. **抓取合规**：尊重 robots，不登录、不绕验证码 / 反爬、不调付费或通用搜索 API，不在微信平台内全量搜索。

## 环境

- Python 3.14，虚拟环境 `.venv`。
- 依赖 `requirements.txt`（requests / beautifulsoup4 / PyYAML / trafilatura）；OCR 可选 `requirements-ocr.txt`。`geo_radar` 仅用 `requests` + 标准库。
- `AMAP_KEY` 必须经环境变量提供；**严禁写入代码或文档**。
- `LLM_API_KEY` 必须经环境变量提供；**严禁写入代码或文档**。可选环境变量：`LLM_API_BASE`（默认 `https://api.deepseek.com/v1`）、`LLM_MODEL`（默认 `deepseek-chat`）。
- 预览 / 截图：`.claude/launch.json`（静态服务，端口 8013）。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/     # 既有规则测试
```
`geo_radar` 各模块以内联脚本自测，记录见 `HANDOFF.md`。
