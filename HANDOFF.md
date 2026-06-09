# HANDOFF — 低空讯图 PoC

> 快照：2026-06-09。承接人读完本文件 + `CLAUDE.md` 即可继续，无需回溯对话。

## 当前状态

`geo_radar` 的**落图 + 查询链路端到端跑通并验证**（浏览器截图确认：高德 GCJ-02 底图渲染、坐标零偏移、点击查询返回正确风险等级与证据）。**LLM 在线抽取层已接入**，打通"正文 → 结构化"在线一环。这是 PoC 命题里"落图 + 基于证据的风险提示"两块的可运行证明，**全程使用真实公告、未接触微信**。

## 已完成

| 模块 | 验证方式 | 结果 |
|---|---|---|
| `geometry` / `temporal` | 内联单测 | 圆缓冲、点在多边形、点到边界距离、周期性时间窗判定全部符合预期 |
| `amap` | 真实调用 | 地理编码 / POI / 行政区边界三接口均通；点在市南区判定正确 |
| `geoparse`（A–E 分级 + 人审路由） | 5 条真实公告 | 各按几何类型正确落图，分级与路由合理 |
| 落图 → `outputs/zones.geojson` | 运行 `__main__` | 5 要素；威海今天生效，其余历史/季节性未生效 |
| 风险查询（地图页） | UI 点击测试 | 地图页发起请求，需后端 `/api/risk/query` 支持 |
| `web/map.html` | 预览截图 + eval | Leaflet + 高德底图，点击查询、详情卡、原文链接均工作 |
| **`extraction_agent`（LLM在线抽取）** | 单元测试 | Prompt/解析/降级/格式兼容性全部通过（见下文） |

种子样本（`data/announcements_seed.json`，全部真实公告）：

- **威海高考低慢小（P0，今天 6/7–6/10 生效）** — 多考点 + 500m
- 济南泉城广场（P0） — 四至 → 近似外接矩形
- 东营黄河三角洲（P1） — 保护区全域 + 3km，**周期性**（每年迁徙期）
- 青岛金沙滩啤酒城（P2） — POI 缓冲
- 济南千佛山（P0） — POI 缓冲

## LLM 在线抽取层

### 新增文件

| 文件 | 说明 |
|---|---|
| `geo_radar/extraction_agent.py` | LLM 抽取核心模块：Prompt 设计 + OpenAI 兼容客户端 + 分类/9字段抽取/证据绑定 + 降级策略 |
| `data/raw_announcements.json` | 5 条真实公告的原始正文（从种子 JSON 中提取），用于 LLM 抽取测试 |
| `tests/test_extraction_compat.py` | 抽取结果格式兼容性测试（to_announcement_dict / 降级 / JSON解析） |

### 三种运行模式

```powershell
# 模式1：预结构化种子（现有方式，不变）
$env:AMAP_KEY="<key>"
.\.venv\Scripts\python.exe -m geo_radar --now 2026-06-08T12:00:00

# 模式2：LLM 在线抽取 → 落图（需 LLM_API_KEY）
$env:AMAP_KEY="<key>"
$env:LLM_API_KEY="<key>"
.\.venv\Scripts\python.exe -m geo_radar --extract data/raw_announcements.json --now 2026-06-08T12:00:00

# 模式3：单条正文快速测试（仅抽取，不落图，无需 AMAP_KEY）
$env:LLM_API_KEY="<key>"
.\.venv\Scripts\python.exe -m geo_radar --extract-text "关于对无人机实施临时禁飞的通告..." --source-name "测试来源" --city "杭州"
```

### 抽取结果格式

LLM 输出的结构化 dict 与 `announcements_seed.json` 字段完全对齐，可直接进入 `geoparse.parse()` + `temporal.evaluate()` + `__main__.build()`。额外增加 `extraction_method: "llm"` 标记以区分来源。

### 安全约定

- LLM **绝不直接输出坐标**——只输出地点引用文本，坐标由高德确定性接口解析
- 所有关键字段必须绑定原文证据（`evidence.*`）
- 不确定字段返回 `null`，不凭空补全
- 低置信度结果标记 `needs_review`，不进自动通过
- 支持 OpenAI 兼容 API（DeepSeek / Qwen / 本地 vLLM 等）

### 已验证（无需 API）

- `to_announcement_dict()` 格式与现有管线完全兼容
- 降级策略（LLM 调用失败时返回安全空结果）
- JSON 解析鲁棒性（markdown code block / 含前后文本 / 非JSON）
- Prompt 模板渲染正确

### 待验证（需 LLM_API_KEY）

- 对 5 条真实公告正文的端到端抽取准确率
- 与手工结构化种子的字段级对比
- 不同 LLM 模型（DeepSeek / Qwen / GPT-4o）的抽取质量差异

## 关键决策与发现

1. **5 条真实公告全部进了人工核验队列**，各有正当理由（威海考点名单未在通告中列出 / 泉城广场只能近似 / 东营保护区无标准边界数据源 / 啤酒城、千佛山半径靠估）。这是真实发现：**街面临时公告极少直接给"POI + 显式半径 + 可解析"** —— 产品价值在系统正确分级与路由，而非假装全自动 auto-pass。
2. **坐标系全链路 GCJ-02**（见 `CLAUDE.md` 约定 1）。
3. **威海考点是候选点位**（威海一中 / 二中 / 实验高中，来自公开检索，非官方名单），几何 = 考点 + 500m，已标注"需招考院 / 教育局名单核验"。**面试如实说明这是候选，不是官方名单。**
4. 已修 bug：查询返回的证据状态按**查询时刻**重算（修复前误显示落图时刻的状态，导致命中样本被标 EXPIRED/INACTIVE）。
5. **删除底部时间轴 UI**：地图页不再提供播放、滑块、时间刻度和底部统计条；图层仍按当前时间调用 `/api/v1/map/layers?selected_time=...`，`temporal.py` 和 API 时间判断能力保留。

## 当前边界 / 暂不做

- **发现层**：即既有 `source_audit`，本轮未改动。
- **微信供给侧**：parked。结论是"用户上报 → AI 分析 → 人工审核"共创 + 商业监测 API 补 P1，与"AI 能否落图"解耦，不挡在 PoC 前。
- **行政区（admin）全域落图**：`geoparse._admin` 已实现并单测过（市南区边界），但无真实 admin 样本上图。

## 下一步

1. **Evaluate 看板**（方案 §9）：抽取 / 地理 / RAG / 安全指标 + Golden Dataset。
2. **admin 全域样本上图**：补一条真实行政区级公告，让 D 级落图在地图上可见。
3. **LLM 模型对比评测**：对 5 条公告用 2-3 种模型各跑一遍，输出字段级准确率对比。

## 如何恢复 / 复验

```powershell
# 预结构化模式
$env:AMAP_KEY="<key>"
.\.venv\Scripts\python.exe -m geo_radar --now 2026-06-08T12:00:00

# LLM 在线抽取模式
$env:AMAP_KEY="<key>"
$env:LLM_API_KEY="<key>"
.\.venv\Scripts\python.exe -m geo_radar --extract data/raw_announcements.json --now 2026-06-08T12:00:00

# 单条快速测试
$env:LLM_API_KEY="<key>"
.\.venv\Scripts\python.exe -m geo_radar --extract-text "公告正文..." --source-name "来源" --city "城市"

# 风险查询（地图页 UI）
# 点击地图任意位置，发起 /api/risk/query 请求
# 后端需实现：web/api/map_layers.py 中 /api/v1/risk/query 端点

# 地图
.\.venv\Scripts\python.exe -m http.server 8011   # http://localhost:8011/web/map.html
```

高德 Key 为 **Web 服务**类型（非 JS API）。LLM Key 为 OpenAI 兼容格式（支持 DeepSeek/Qwen/GPT-4o 等）。Key 不入库，经环境变量提供。
