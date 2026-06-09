# 低空讯图 (AeroPulse) PoC 开发计划

> 派生自 `docs/SPEC.md` v1.0 (2026-06-09)，基于当前实现状态矩阵制定。
> 目标：在现有 `geo_radar` + `source_audit` 基础上，完成 PoC 全部验收项。

---

## 一、现状回顾

| 维度 | 已完成 | 未完成 |
|------|--------|--------|
| **后端核心管线** | 落图+查询+LLM抽取+地理编码全部跑通 | API 服务层 0% |
| **前端** | Leaflet 地图 + 点击查询 + 详情卡 | 时间轴、数据源管理页、入库管理页 0% |
| **数据** | 5条种子公告 + 原始正文 | Golden Dataset 未沉淀 |
| **发现层** | `source_audit` 基础版可用 | 全国搜索扩展未做 |

**关键判断**：当前瓶颈在 **API 服务层** 和 **前端管理页面**。后端核心能力（抽取/落图/查询）已验证，需通过 API 暴露并配合前端完成交互闭环。

---

## 二、总体分期

### Phase 1：API 服务层（后端基建） — 预计 2-3 天

> 目标：将现有能力封装为 RESTful API，支撑前后端分离架构。

| # | 任务 | 文件 | 优先级 | 说明 |
|---|------|------|--------|------|
| 1.1 | **FastAPI 项目骨架** | `web/api/` | P0 | 新建 FastAPI 应用，CORS 配置，静态文件挂载 |
| 1.2 | **数据源 API** | `web/api/data_sources.py` | P0 | `GET /api/v1/data-sources` + `PATCH` + `POST crawl` |
| 1.3 | **入库任务 API** | `web/api/ingestion.py` | P0 | `GET/POST` 任务列表 + 手动提交 + 审批/驳回 |
| 1.4 | **地图图层 API** | `web/api/map_layers.py` | P0 | `GET /api/v1/map/layers`（时间轴+筛选） + 公告详情 |
| 1.5 | **质量概览 API** | `web/api/stats.py` | P1 | `GET /api/v1/stats/overview` |
| 1.6 | **数据存储层** | `web/api/store.py` | P0 | SQLite 数据访问层（DataSource / IngestionTask / Announcement CRUD） |
| 1.7 | **AI 管线集成** | `web/api/pipeline.py` | P0 | 将 `extraction_agent` + `geoparse` + `temporal` 串联为异步任务 |
| 1.8 | **种子数据迁移脚本** | `scripts/seed_db.py` | P0 | 将 `data/announcements_seed.json` 迁移到 SQLite，生成 DataSource + IngestionTask + Announcement 记录 |

### Phase 2：前端地图与时间轴（核心用户页面） — 预计 2-3 天

> 目标：完善 `web/map.html`，补齐时间轴交互和详情卡片，达到 US-01~US-03 验收标准。

| # | 任务 | 文件 | 优先级 | 说明 |
|---|------|------|--------|------|
| 2.1 | **时间轴组件** | `web/map.html` | P0 | 底部时间轴滑块，拖动后调用 `/api/v1/map/layers` 刷新图层 |
| 2.2 | **图层状态实时切换** | `web/map.html` | P0 | active/not_started/expired/long_term/unknown 五种状态渲染 |
| 2.3 | **快捷按钮** | `web/map.html` | P1 | 现在 / 未来24h / 未来7天 / 历史公告 |
| 2.4 | **详情卡片完善** | `web/map.html` | P0 | 按 spec 展示完整字段：标题/单位/时间/区域/来源/证据/置信度/核验提示 |
| 2.5 | **图层类型开关** | `web/map.html` | P1 | 禁飞/管控/备案提醒/待核验/历史 筛选开关 |
| 2.6 | **区域筛选器** | `web/map.html` | P1 | 省/市/区县三级联动筛选 |
| 2.7 | **状态统计栏** | `web/map.html` | P1 | 时间轴上方展示：生效中N条、即将生效N条、已过期N条 |
| 2.8 | **地点搜索** | `web/map.html` | P2 | 搜索地名 → 定位地图视野（不触发 Agent 问答） |

### Phase 3：数据源与入库管理页（运营后台） — 预计 2-3 天

> 目标：新建管理页面，完成 US-04~US-07 验收标准。

| # | 任务 | 文件 | 优先级 | 说明 |
|---|------|------|--------|------|
| 3.1 | **管理页骨架** | `web/admin.html` | P0 | 新建单文件管理页，Tab 切换（数据源/入库任务/关键词） |
| 3.2 | **质量概览指标卡** | `web/admin.html` | P1 | 顶部 6-8 个指标卡，对接 `/api/v1/stats/overview` |
| 3.3 | **数据源列表 Tab** | `web/admin.html` | P0 | 表格展示 + 启用/暂停 + 手动触发采集 + 新增数据源 |
| 3.4 | **入库任务列表 Tab** | `web/admin.html` | P0 | 表格展示解析状态/置信度/审核状态 + 筛选 |
| 3.5 | **手动提交公告 Drawer** | `web/admin.html` | P0 | 支持粘贴链接(URL) / 正文(text)，对接 `POST /api/v1/ingestion-tasks/manual-submit` |
| 3.6 | **解析详情 Drawer** | `web/admin.html` | P0 | 字段级证据展示 + 地图预览 + 时间轴预览 + 确认发布/驳回按钮 |
| 3.7 | **确认发布 / 驳回操作** | `web/admin.html` | P0 | 对接 approve/reject API，发布后地图可见 |
| 3.8 | **关键词/规则 Tab** | `web/admin.html` | P2 | 展示当前配置的关键词和分类规则 |

### Phase 4：集成测试与验收 — 预计 1-2 天

> 目标：端到端跑通 10 项功能验收 + 8 项演示验收。

| # | 任务 | 优先级 | 说明 |
|---|------|--------|------|
| 4.1 | **端到端流程测试** | P0 | 数据源 → 采集 → AI解析 → 审核 → 发布 → 地图可见 → 时间轴切换 |
| 4.2 | **手动提交链路测试** | P0 | 粘贴正文 → 生成任务 → AI解析 → 确认发布 → 地图可见 |
| 4.3 | **时间轴闭环测试** | P0 | 同一条公告在未开始/生效中/已过期三个状态正确切换 |
| 4.4 | **产品边界审查** | P0 | 全页面文案无越权许可表达 |
| 4.5 | **性能基线测试** | P1 | 地图加载 <2s，时间轴切换 <500ms，详情加载 <1s |
| 4.6 | **Golden Dataset 沉淀** | P2 | 将验证通过的公告样本整理为 Golden Dataset |

---

## 三、技术决策

| 决策 | 选型 | 理由 |
|------|------|------|
| API 框架 | **FastAPI** | Python 生态，异步支持，自动 OpenAPI 文档，与现有代码无缝集成 |
| 数据存储 | **SQLite** (data/aeropulse.db) | PoC 阶段单文件部署，零配置；生产可迁移至 PostgreSQL |
| 前端架构 | **单文件 HTML + Vanilla JS** | 延续现有 `web/map.html` 风格，零构建工具，PoC 快速迭代 |
| 前端 UI 库 | **无框架，CSS 变量 + Flexbox** | 与现有风格一致，暗色主题 |
| 异步任务 | **FastAPI BackgroundTasks** | PoC 阶段轻量，AI 管线同步调用可接受（单条 <30s） |
| 地图库 | **Leaflet 1.9.4** | 已验证，不变 |
| 坐标系 | **GCJ-02 全链路** | 已约定 |

---

## 四、文件结构规划

```
aeropulse/
├── web/
│   ├── map.html              # [改造] 地图浏览 + 时间轴（页面1）
│   ├── admin.html            # [新建] 数据源与入库管理（页面2）
│   └── api/                  # [新建] FastAPI 后端
│       ├── __init__.py
│       ├── main.py           # FastAPI 应用入口
│       ├── store.py          # SQLite 数据访问层
│       ├── data_sources.py   # 数据源 CRUD 路由
│       ├── ingestion.py      # 入库任务路由
│       ├── map_layers.py     # 地图图层路由
│       ├── stats.py          # 质量概览路由
│       └── pipeline.py       # AI 管线编排
├── scripts/
│   └── seed_db.py            # [新建] 种子数据迁移脚本
├── data/
│   └── aeropulse.db          # [新建] 应用数据库
├── outputs/                  # [已有] 保留现有输出
└── docs/
    ├── SPEC.md               # [已有] 功能规格
    └── DEVELOPMENT_PLAN.md   # [新建] 本文件
```

---

## 五、依赖新增

```txt
# 新增依赖（追加到 requirements.txt）
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
```

---

## 六、验收标准映射

每条 SPEC 验收标准对应开发任务：

| SPEC 验收项 | 对应任务 |
|-------------|----------|
| 1. 数据源可管理 (≥5个) | 1.2 + 1.8 + 3.3 |
| 2. 公告入库可控 | 1.3 + 1.7 + 3.4 |
| 3. AI 稳定结构化 | 1.7（复用已验证的 extraction_agent） |
| 4. 地理解析可落图 | 1.7（复用已验证的 geoparse） |
| 5. 时间状态可视化 | 2.1 + 2.2 |
| 6. 图层可解释 | 2.4 |
| 7. 产品边界清晰 | 4.4 |
| 8. 质量状态可见 | 1.5 + 3.2 + 3.4 |
| 9. 手动提交链路 | 1.3 + 3.5 + 3.6 + 3.7 |
| 10. 时间轴闭环 | 2.1 + 4.3 |

| SPEC 演示步骤 | 对应任务 |
|---------------|----------|
| D1 打开地图页 | 2.1 + 2.2 |
| D2 拖动时间轴 | 2.1 + 2.2 |
| D3 点击图层 | 2.4 |
| D4 进入管理页 | 3.1 + 3.2 + 3.3 |
| D5 手动提交公告 | 3.5 |
| D6 打开解析详情 | 3.6 |
| D7 确认发布 | 3.7 |
| D8 地图验证时间轴 | 4.3 |

---

## 七、风险与依赖

| 风险 | 缓解措施 |
|------|----------|
| LLM API 不稳定 | 降级策略已就绪（规则匹配 + 人工录入），`extraction_agent` 已有 fallback |
| 高德 API 限流 | 每日 5000 次，PoC 用量远低于此；预缓存种子坐标 |
| 前端单文件膨胀 | 当前 `map.html` ~170 行，管理页独立文件 `admin.html` |
| SQLite 并发写入 | PoC 阶段单用户，无需担心；生产可迁移 PostgreSQL |

---

## 八、实施顺序建议

```
Day 1-2:  Phase 1 (1.1 → 1.6 → 1.8 → 1.7)  — API 基建 + 种子数据迁移
Day 3-4:  Phase 2 (2.1 → 2.2 → 2.4 → 2.3 → 2.5 → 2.6 → 2.7)  — 地图时间轴完善
Day 5-6:  Phase 3 (3.1 → 3.3 → 3.4 → 3.5 → 3.6 → 3.7)  — 管理后台
Day 7-8:  Phase 4  — 集成测试 + 验收 + Bug 修复
```

---

> **下一步**：从 Phase 1 Task 1.1 开始，搭建 FastAPI 项目骨架。
