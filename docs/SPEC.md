# SPEC — 低空讯图 (AeroPulse) PoC 功能规格

> 派生自《低空讯图｜AI PM 面试 PoC 方案_全国开放搜索地图时间轴版.md》
> 当前实现状态快照：2026-06-09（参考 HANDOFF.md）

---

## 目录

1. [产品概述](#1-产品概述)
2. [核心用户故事](#2-核心用户故事)
3. [功能需求](#3-功能需求)
4. [数据模型](#4-数据模型)
5. [API 规格](#5-api-规格)
6. [AI Agent 管线](#6-ai-agent-管线)
7. [地图与时间轴](#7-地图与时间轴)
8. [质量与安全](#8-质量与安全)
9. [非功能需求](#9-非功能需求)
10. [PoC 验收标准](#10-poc-验收标准)
11. [范围外（Explicit Out-of-Scope）](#11-范围外explicit-out-of-scope)
12. [实现状态矩阵](#12-实现状态矩阵)

---

## 1. 产品概述

### 1.1 一句话定位

> **公开低空管控公告的地图化情报工具。**

### 1.2 核心价值主张

无人机用户飞行前需要了解目标区域的公开管控信息，但这些公告分散在政府网站、公安通告、景区公告和媒体转载中。AeroPulse 将分散的公开低空管控公告聚合为可按时间轴浏览的地图图层，并绑定原文证据，让用户快速了解"何时、何地、有何种管控"。

### 1.3 产品边界（红线）

| 不做的事 | 原因 |
|---|---|
| 回答"能不能飞" | 属于飞行许可判断，超出情报工具定位 |
| 提供规避监管建议 | 合规红线 |
| 用户侧 Agent 自然语言问答 | 增加幻觉和越权表达风险 |
| 飞行计划检查面板 | PoC 阶段不要求用户输入飞行参数 |
| 自动飞行申请 | 涉及官方审批 |
| 判断"是否准飞" | 合规风险高 |

### 1.4 用户交互模式

```
查看地图图层 → 拖动时间轴 → 查看图层状态切换 → 点击图层查看详情与证据
```

---

## 2. 核心用户故事

### US-01：地图浏览者 — 查看管控图层

**作为** 无人机航拍摄影师
**我想要** 在地图上查看杭州未来7天内的临时禁飞和管控区域
**以便** 规划拍摄地点，避开管制区域

**验收条件**：
- [ ] 地图默认展示全国范围，支持缩放到城市级
- [ ] 可按省/市/区县筛选图层
- [ ] 图层按类型着色：禁飞(红)、管控(橙)、备案提醒(黄)、待核验(灰虚线)
- [ ] 点击图层弹出详情卡片，展示标题、时间、区域、来源、证据、置信度

### US-02：地图浏览者 — 时间轴查看

**作为** 无人机爱好者
**我想要** 拖动时间轴查看不同日期的管控状态
**以便** 判断某个周末是否适合飞行

**验收条件**：
- [ ] 时间轴默认显示当前系统时间
- [ ] 拖动时间滑块后，图层状态实时切换：生效中/未开始/已过期/未知
- [ ] 已过期公告默认隐藏，可手动开启"历史公告"查看
- [ ] 时间轴上方展示状态统计：生效中N条、即将生效N条、已过期N条

### US-03：地图浏览者 — 证据回溯

**作为** 航拍团队负责人
**我想要** 查看每个管控图层的原始公告和证据
**以便** 确认信息的真实性和权威性

**验收条件**：
- [ ] 详情卡片展示公告标题、发布单位、管控类型、时间范围
- [ ] 展示原文证据片段（引用公告原句）
- [ ] 展示来源链接和来源等级（P0/P1/P2/P3）
- [ ] 展示 AI 抽取置信度
- [ ] 底部固定展示官方核验提示

### US-04：运营人员 — 数据源管理

**作为** 产品运营人员
**我想要** 管理系统的公开数据源列表
**以便** 了解信息从哪些来源获取，并识别异常来源

**验收条件**：
- [ ] 展示数据源列表：名称、类型、等级、覆盖区域、最近采集状态、有效公告数
- [ ] 支持启用/暂停数据源
- [ ] 支持手动触发单个数据源采集
- [ ] 支持新增数据源
- [ ] 展示来源等级：P0(政府/公安/民航) / P1(官方公众号/融媒体) / P2(主流媒体) / P3(自媒体/论坛)

### US-05：运营人员 — 手动提交公告

**作为** 运营人员
**我想要** 手动提交系统未自动发现的公告链接或正文
**以便** 弥补自动采集的遗漏

**验收条件**：
- [ ] 支持粘贴公告链接（URL）
- [ ] 支持粘贴公告正文（文本）
- [ ] 提交后自动生成 IngestionTask 进入 AI 解析管线
- [ ] 手动提交内容同样经过分类、抽取、证据绑定、置信度评估
- [ ] 手动提交不会绕过审核直接发布

### US-06：运营人员 — 入库任务管理

**作为** 运营人员
**我想要** 查看每条入库任务的处理状态和 AI 解析结果
**以便** 决定哪些公告可以发布到地图

**验收条件**：
- [ ] 展示入库任务列表：来源、解析状态、相关性、管控类型、时间状态、置信度、审核状态
- [ ] 点击"查看解析结果"打开详情 Drawer
- [ ] Drawer 展示字段级证据：每个抽取字段的原文引用和置信度
- [ ] Drawer 展示地图预览和时间轴预览
- [ ] 支持"确认发布"和"驳回"操作

### US-07：运营人员 — 质量概览

**作为** 产品运营人员
**我想要** 在数据源管理页看到整体质量指标
**以便** 快速了解系统运行状态

**验收条件**：
- [ ] 顶部展示指标卡：启用数据源数、本轮候选公告数、有效公告数、待核验数、已落图数
- [ ] 展示 AI 解析成功率
- [ ] 展示无证据图层数（目标 0）和越权许可文案次数（目标 0）

---

## 3. 功能需求

### FR-01：地图浏览与时间轴页（页面 1）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-01.1 | 全国地图展示，支持缩放、平移 | P0 |
| FR-01.2 | 展示已发布的管控图层（GeoJSON），按类型着色 | P0 |
| FR-01.3 | 底部时间轴滑块，拖动切换时间点 | P0 |
| FR-01.4 | 时间轴快捷按钮：现在、未来24h、未来7天、历史公告 | P1 |
| FR-01.5 | 图层类型开关：禁飞/管控/备案提醒/待核验/历史 | P1 |
| FR-01.6 | 按省/市/区县筛选图层 | P1 |
| FR-01.7 | 地点搜索（定位地图视野，不触发 Agent 问答） | P2 |
| FR-01.8 | 点击图层弹出详情卡片 | P0 |
| FR-01.9 | 详情卡片展示证据、来源、置信度、官方核验提示 | P0 |
| FR-01.10 | 图层状态统计（生效中/未开始/已过期/未知数量） | P1 |

### FR-02：数据源与入库管理页（页面 2）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-02.1 | 顶部质量概览指标卡（6-8个） | P1 |
| FR-02.2 | Tab 1：数据源列表，含来源等级、采集状态、有效公告数 | P0 |
| FR-02.3 | Tab 2：入库任务列表，含解析状态、置信度、审核状态 | P0 |
| FR-02.4 | Tab 3：关键词/规则展示 | P2 |
| FR-02.5 | 手动提交公告 Drawer（支持链接/正文） | P0 |
| FR-02.6 | 解析详情 Drawer（字段证据、地图预览、时间轴预览） | P0 |
| FR-02.7 | 确认入库并发布地图按钮 | P0 |
| FR-02.8 | 驳回/标记为线索按钮 | P1 |

### FR-03：公告发现与采集

| ID | 需求 | 优先级 |
|---|---|---|
| FR-03.1 | 基于关键词+城市词库的全国范围搜索 | P1 |
| FR-03.2 | 数据源分4层覆盖：国家级/省级/城市级/区县级 | P1 |
| FR-03.3 | 手动触发单个数据源采集 | P2 |
| FR-03.4 | 采集结果记录（成功/失败/需登录/反爬） | P2 |

### FR-04：AI 处理管线

| ID | 需求 | 优先级 |
|---|---|---|
| FR-04.1 | 公告相关性分类（TEMP_NO_FLY / TEMP_CONTROL / REGISTRATION_NOTICE / SAFETY_REMINDER / NON_RELEVANT） | P0 |
| FR-04.2 | 9字段抽取：标题、发布单位、来源、开始时间、结束时间、时间依据、管控类型、管控区域、原文证据 | P0 |
| FR-04.3 | 地理解析：POI+半径 / 行政区 / 多点列表 | P0 |
| FR-04.4 | 时间归一化与状态判断（active/not_started/expired/long_term/unknown） | P0 |
| FR-04.5 | 证据绑定：所有关键字段绑定原文引用 | P0 |
| FR-04.6 | 置信度评估（parse_confidence, geo_confidence） | P0 |
| FR-04.7 | 人工审核路由：低置信度/来源不可靠/边界模糊 → needs_review | P0 |
| FR-04.8 | 去重：基于标题相似度+时间接近度+单位一致性+区域一致性+语义相似度 | P2 |

---

## 4. 数据模型

### 4.1 DataSource（数据源）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | string | Y | 唯一标识，如 "src_001" |
| source_name | string | Y | 数据源名称 |
| source_url | string | Y | 数据源 URL |
| source_type | enum | Y | government_website / police_website / official_media / scenic_notice / event_website / social_media |
| source_level | enum | Y | P0 / P1 / P2 / P3 |
| source_trust_score | float | Y | 0.0–1.0 |
| coverage_area | string | N | 覆盖区域描述 |
| coverage_level | enum | N | national / province / city / district |
| province | string | N | 省份 |
| city | string | N | 城市 |
| district | string | N | 区县 |
| keywords | string[] | N | 命中关键词 |
| crawl_mode | enum | Y | auto / manual_trigger |
| last_crawled_at | datetime | N | 最近采集时间 |
| last_crawl_status | enum | N | success / failed / login_required / anti_crawl |
| valid_announcement_count | int | Y | 有效公告数 |
| pending_review_count | int | Y | 待审核数 |
| anomaly_count | int | Y | 异常次数 |
| enabled | bool | Y | 是否启用 |

### 4.2 IngestionTask（入库任务）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | string | Y | 唯一标识，如 "task_001" |
| submit_channel | enum | Y | auto / manual |
| submission_type | enum | Y | url / text |
| source_id | string | N | 关联数据源 ID |
| source_name | string | Y | 来源名称 |
| source_url | string | N | 来源 URL |
| raw_text | string | Y | 原始正文 |
| task_status | enum | Y | submitted / fetching / classifying / extracting / geo_parsing / time_normalizing / parsed / needs_review / approved / published / rejected |
| classification_result | enum | N | TEMP_NO_FLY / TEMP_CONTROL / REGISTRATION_NOTICE / SAFETY_REMINDER / NON_RELEVANT |
| is_relevant | bool | N | 是否相关 |
| parse_confidence | float | N | 解析置信度 0.0–1.0 |
| geo_confidence | float | N | 地理解析置信度 0.0–1.0 |
| time_parse_status | enum | N | success / missing / conflict |
| review_status | enum | N | auto_pass / pending_confirm / approved / rejected |
| review_reason | string | N | 审核原因 |
| map_preview_status | enum | N | not_generated / generated |
| created_at | datetime | Y | 创建时间 |
| created_by | string | N | 创建者 |

### 4.3 Announcement（公告）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | string | Y | 唯一标识，如 "ann_001" |
| source_task_id | string | Y | 关联入库任务 ID |
| extraction_method | enum | Y | manual / llm |
| title | string | Y | 公告标题 |
| publish_unit | string | Y | 发布单位 |
| source_name | string | Y | 来源名称 |
| source_url | string | N | 来源 URL |
| source_level | enum | Y | P0 / P1 / P2 / P3 |
| source_trust_score | float | Y | 0.0–1.0 |
| publish_time | datetime | N | 发布时间 |
| last_checked_at | datetime | Y | 最近检查时间 |
| province | string | N | 省份 |
| city | string | N | 城市 |
| district | string | N | 区县 |
| control_type | enum | Y | 临时禁飞 / 临时管控 / 备案通知 / 安全提醒 |
| risk_class | enum | Y | control / reminder / unknown |
| time_status | enum | Y | active / not_started / expired / long_term / unknown |
| start_time | datetime | N | 开始时间 |
| end_time | datetime | N | 结束时间 |
| time_mode | enum | N | single / periodic / long_term |
| time_windows | array | N | 周期性时间窗 |
| validity_basis | string | N | 时间判断依据 |
| area_text | string | Y | 管控区域原文描述 |
| geo_type | enum | Y | poi_buffer / poi_buffer_multi / admin / bbox_roads / area_no_boundary |
| center_poi | string | N | 中心 POI 名称 |
| poi_list | string[] | N | 多点列表 |
| radius_meters | int | N | 半径（米） |
| district_name | string | N | 行政区名称 |
| geo_json | GeoJSON | N | 地图几何数据 |
| geo_confidence | float | Y | 地理解析置信度 0.0–1.0 |
| geo_grade | enum | Y | A / B / C / D / E |
| geo_note | string | N | 地理备注（如"考点为候选，需招考院核验"） |
| roster_status | enum | N | confirmed / candidate_needs_verification |
| aircraft_types | string[] | N | 管控航空器类型 |
| evidence_text | string | Y | 原文证据片段 |
| evidence_time | string | N | 时间证据 |
| evidence_area | string | N | 区域证据 |
| evidence_control_type | string | N | 管控类型证据 |
| confidence_score | float | Y | 综合置信度 0.0–1.0 |
| needs_review | bool | Y | 是否需要人工核验 |
| review_status | enum | Y | auto_pass / pending_confirm / approved / rejected |
| review_reason | string | N | 审核原因 |
| map_layer_status | enum | Y | not_published / preview / published |
| duplicate_group_id | string | N | 去重组 ID |
| version_id | string | Y | 版本 ID |

---

## 5. API 规格

### 5.1 数据源

#### GET /api/v1/data-sources

获取数据源列表。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| province | string | N | 省份筛选 |
| source_level | enum | N | P0/P1/P2/P3 筛选 |
| enabled | bool | N | 启用状态筛选 |

**响应**：

```json
{
  "items": [
    {
      "id": "src_001",
      "source_name": "浙江省人民政府官网",
      "source_type": "government_website",
      "source_level": "P0",
      "source_trust_score": 0.95,
      "coverage_area": "浙江省",
      "coverage_level": "province",
      "province": "浙江省",
      "last_crawled_at": "2026-06-08T10:30:00+08:00",
      "last_crawl_status": "success",
      "valid_announcement_count": 12,
      "pending_review_count": 3,
      "anomaly_count": 0,
      "enabled": true
    }
  ],
  "total": 32
}
```

#### POST /api/v1/data-sources/{source_id}/crawl

手动触发单个数据源采集。

**响应**：

```json
{
  "task_id": "crawl_001",
  "status": "running",
  "message": "已触发该数据源采集任务"
}
```

#### PATCH /api/v1/data-sources/{source_id}

更新数据源状态（启用/暂停）。

**请求**：

```json
{
  "enabled": false
}
```

---

### 5.2 入库任务

#### POST /api/v1/ingestion-tasks/manual-submit

手动提交公告。

**请求**：

```json
{
  "submission_type": "text",
  "source_id": "src_001",
  "source_url": null,
  "source_name": "杭州市某区政府网站",
  "manual_text": "关于对无人机等低慢小航空器实施临时禁飞的通告……",
  "source_level_hint": "P0",
  "submitter_note": "面试现场演示样例"
}
```

**响应**：

```json
{
  "task_id": "task_001",
  "task_status": "submitted",
  "message": "公告已提交，正在进入 AI 解析流程"
}
```

#### GET /api/v1/ingestion-tasks

获取入库任务列表。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| task_status | enum | N | 任务状态筛选 |
| review_status | enum | N | 审核状态筛选 |
| submit_channel | enum | N | auto/manual |

**响应**：

```json
{
  "items": [
    {
      "id": "task_001",
      "submit_channel": "manual",
      "submission_type": "text",
      "source_name": "杭州市某区政府网站",
      "title_preview": "关于对无人机等低慢小航空器实施临时禁飞...",
      "task_status": "parsed",
      "classification_result": "TEMP_NO_FLY",
      "is_relevant": true,
      "parse_confidence": 0.91,
      "geo_confidence": 0.88,
      "time_parse_status": "success",
      "review_status": "pending_confirm",
      "map_preview_status": "generated",
      "created_at": "2026-06-08T15:30:00+08:00"
    }
  ],
  "total": 48
}
```

#### GET /api/v1/ingestion-tasks/{task_id}

获取单条入库任务解析详情。

**响应**：

```json
{
  "task_id": "task_001",
  "task_status": "parsed",
  "raw_text": "关于对无人机等低慢小航空器实施临时禁飞的通告。禁飞时间为2026年6月7日8时至6月10日18时...",
  "is_relevant": true,
  "classification_result": "TEMP_NO_FLY",
  "classification_reason": "公告明确包含临时禁飞、严禁飞行等表达",
  "extracted_fields": {
    "title": {"value": "关于对无人机等低慢小航空器实施临时禁飞的通告", "confidence": 0.96, "evidence": "公告标题行"},
    "publish_unit": {"value": "杭州市某区公安分局", "confidence": 0.92, "evidence": "落款：杭州市某区公安分局"},
    "start_time": {"value": "2026-06-07T08:00:00+08:00", "confidence": 0.96, "evidence": "禁飞时间为2026年6月7日8时至..."},
    "end_time": {"value": "2026-06-10T18:00:00+08:00", "confidence": 0.96, "evidence": "...至6月10日18时"},
    "control_type": {"value": "临时禁飞", "confidence": 0.94, "evidence": "实施临时禁飞的通告"},
    "area_text": {"value": "杭州奥体中心周边1000米范围内", "confidence": 0.88, "evidence": "禁飞区域为杭州奥体中心周边1000米范围内。"}
  },
  "temporal_result": {
    "time_status": "active",
    "time_mode": "single",
    "validity_basis": "公告原文明确写明起止时间"
  },
  "geo_parse_result": {
    "geo_type": "poi_buffer",
    "center_poi": "杭州奥体中心",
    "radius_meters": 1000,
    "geo_confidence": 0.88,
    "geo_grade": "B",
    "roster_status": "confirmed"
  },
  "evidence_text": "禁飞时间为2026年6月7日8时至6月10日18时，禁飞区域为杭州奥体中心周边1000米范围内。",
  "review_status": "pending_confirm",
  "review_reason": null,
  "map_preview_url": "/api/v1/map/preview/task_001"
}
```

#### POST /api/v1/ingestion-tasks/{task_id}/approve

确认入库并发布到地图。

**请求**：

```json
{
  "edited_fields": {},
  "publish_to_map": true
}
```

**响应**：

```json
{
  "announcement_id": "ann_101",
  "review_status": "approved",
  "map_layer_status": "published",
  "message": "公告已确认入库，并生成地图图层"
}
```

#### POST /api/v1/ingestion-tasks/{task_id}/reject

驳回任务。

**请求**：

```json
{
  "reason": "公告内容与低空管控无关"
}
```

---

### 5.3 地图图层

#### GET /api/v1/map/layers

获取地图图层数据。

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| selected_time | ISO 8601 | Y | - | 时间轴选中的时间 |
| province | string | N | null | 省份筛选 |
| city | string | N | null | 城市筛选 |
| district | string | N | null | 区县筛选 |
| control_type | enum | N | null | 管控类型筛选 |
| include_expired | bool | N | false | 是否包含历史公告 |
| include_review | bool | N | true | 是否包含待核验图层 |
| bounds | string | N | null | 视野范围 "sw_lng,sw_lat,ne_lng,ne_lat" |

**响应**：

```json
{
  "selected_time": "2026-06-08T15:00:00+08:00",
  "summary": {
    "active_count": 8,
    "not_started_count": 3,
    "expired_count": 12,
    "long_term_count": 1,
    "unknown_count": 5
  },
  "features": [
    {
      "type": "Feature",
      "announcement_id": "ann_101",
      "title": "关于对无人机等低慢小航空器实施临时禁飞的通告",
      "control_type": "TEMP_NO_FLY",
      "time_status": "active",
      "source_level": "P0",
      "geo_confidence": 0.88,
      "geo_grade": "B",
      "extraction_method": "llm",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[120.15, 30.22], ...]]
      },
      "properties": {
        "style_hint": "red_active",
        "radius_meters": 1000,
        "center_poi": "杭州奥体中心"
      }
    }
  ]
}
```

#### GET /api/v1/announcements/{announcement_id}

获取公告详情（图层点击）。

**响应**：

```json
{
  "id": "ann_101",
  "title": "关于对无人机等低慢小航空器实施临时禁飞的通告",
  "control_type": "临时禁飞",
  "time_status": "active",
  "start_time": "2026-06-07T08:00:00+08:00",
  "end_time": "2026-06-10T18:00:00+08:00",
  "area_text": "杭州奥体中心周边1000米范围内",
  "source_name": "杭州市某区政府网站",
  "source_url": "https://example.gov.cn/notice",
  "source_level": "P0",
  "confidence_score": 0.91,
  "geo_confidence": 0.88,
  "evidence_text": "禁飞时间为2026年6月7日8时至6月10日18时，禁飞区域为杭州奥体中心周边1000米范围内。",
  "aircraft_types": ["无人机", "航空模型"],
  "publish_unit": "杭州市某区公安分局",
  "publish_time": "2026-06-01T10:30:00+08:00",
  "disclaimer": "本系统基于公开公告展示风险信息，不构成飞行许可。实际飞行前请通过 UOM、空管、公安或公告发布单位核验。"
}
```

---

### 5.4 质量概览

#### GET /api/v1/stats/overview

获取质量概览指标。

**响应**：

```json
{
  "enabled_sources": 32,
  "candidate_tasks": 48,
  "valid_announcements": 11,
  "pending_review": 5,
  "published_layers": 8,
  "parse_success_rate": 0.87,
  "layers_without_evidence": 0,
  "overreach_text_count": 0,
  "updated_at": "2026-06-08T15:30:00+08:00"
}
```

---

## 6. AI Agent 管线

### 6.1 Agent 架构

```
Source Discovery Agent  ──→  Ingestion Agent  ──→  Classification Agent
                                                         ↓
                                                  Extraction Agent
                                                         ↓
                                                  Geo Parsing Agent
                                                         ↓
                                                  Temporal Agent
                                                         ↓
                                                  人工确认 / 发布地图
                                                         ↓
                                                  地图时间轴展示
```

### 6.2 Agent 定义

| Agent | 输入 | 输出 | 实现状态 |
|---|---|---|---|
| Source Discovery | 城市 + 关键词 | 候选数据源/公告链接 | source_audit/ 已实现基础版 |
| Ingestion | URL/正文/采集结果 | 标准化 IngestionTask | 框架已就绪 |
| Classification | 公告正文 | 是否相关 + 公告类型 | extraction_agent 已包含分类 |
| Extraction | 相关公告正文 | 9字段 + 证据绑定 | ✅ extraction_agent.py |
| Geo Parsing | 区域文本 + geo 元数据 | geo_type + 坐标 + geo_json | ✅ geoparse.py |
| Temporal | 开始/结束时间 + 语义表达 | time_status + validity_basis | ✅ temporal.py |

### 6.3 模型分层策略

| 任务 | 策略 | 原因 |
|---|---|---|
| 关键词初筛 | 规则 + 轻量模型 | 成本低，处理大量候选页面 |
| 数据源评级 | 规则 + 轻量模型 | 任务稳定，可解释性要求高 |
| 公告相关性分类 | 小模型或中等模型 | 任务明确 |
| 字段抽取 | 中高能力模型 | 需稳定结构化输出和证据绑定 |
| 时间归一化 | 规则 + 中等模型 | 多数可规则处理，模糊表达交模型 |
| 地理解析 | 中高能力模型 + 地图工具 | 需理解自然语言并调用地理编码 |
| 低置信度复核 | 高能力模型 + 人工审核 | 处理复杂/模糊/冲突场景 |

### 6.4 安全约定

1. LLM **绝不直接输出坐标**——只输出地点引用文本，坐标由高德确定性接口解析
2. 所有关键字段必须绑定原文证据
3. 不确定字段返回 `null`，不凭空补全
4. 低置信度结果标记 `needs_review`，不进自动通过
5. 支持 OpenAI 兼容 API（DeepSeek / Qwen / GPT-4o / 本地 vLLM）

---

## 7. 地图与时间轴

### 7.1 底图

- 使用 Leaflet + 高德 GCJ-02 底图瓦片
- 坐标系全链路 GCJ-02，零偏移

### 7.2 图层样式规范

| 图层类型 | 颜色 | 样式 | 说明 |
|---|---|---|---|
| 临时禁飞 (active) | #DC3545 红色 | 实线 + 半透明填充 | 当前时间点存在公开禁飞公告 |
| 临时管控 (active) | #FD7E14 橙色 | 实线 + 半透明填充 | 当前时间点存在公开管控公告 |
| 备案/安全提醒 | #FFC107 黄色 | 实线 + 浅填充 | 存在提醒或备案类信息 |
| 待核验区域 | #6C757D 灰色 | 虚线 + 低透明度 | 来源/时间/边界不确定 |
| 未开始公告 | 同类型颜色 | 低透明度 | 未来将生效 |
| 已过期公告 | #ADB5BD 灰色 | 默认隐藏 | 历史参考 |
| 长期有效 | #6F42C1 紫色 | 实线 + 浅填充 | 长期规则或长期管控 |

### 7.3 时间轴交互

| 组件 | 行为 |
|---|---|
| 当前时间指示线 | 默认显示系统当前时间 |
| 时间滑块 | 拖动后地图按该时间点刷新图层状态 |
| 快捷按钮 | 现在 / 未来24h / 未来7天 / 历史公告 |
| 状态统计 | 实时展示生效中/未开始/已过期/长期/未知数量 |
| 播放按钮（可选） | 自动播放未来7天图层变化 |

### 7.4 时间状态判断规则

| 状态 | 判断条件 | 地图表现 |
|---|---|---|
| active | selected_time ∈ [start_time, end_time] | 高亮展示 |
| not_started | selected_time < start_time | 半透明/未来图层样式 |
| expired | selected_time > end_time | 默认隐藏 |
| long_term | 无明确结束时间，属于长期规则 | 长期图层样式 |
| unknown | 时间缺失/冲突/语义模糊 | 灰色/待核验样式 |

### 7.5 视野范围加载策略

- 默认加载全国范围已发布图层
- 按 `bounds` 参数过滤视野外图层（减少渲染压力）
- 详情卡片按需加载（点击后才请求公告详情）

---

## 8. 质量与安全

### 8.1 质量概览指标

| 指标 | 目标值 | 说明 |
|---|---|---|
| 启用数据源数 | - | 当前可用的公开来源数量 |
| 本轮候选公告数 | - | 本次搜索/采集/手动提交的候选任务数 |
| 有效公告数 | - | AI 判断为相关并进入结构化的公告数 |
| 待人工核验数 | - | 被拦截的任务数 |
| 已发布地图图层数 | - | 已确认入库并落图的公告数 |
| AI 解析成功率 | ≥ 87% | 完成抽取+证据绑定+时间归一化+地理解析的占比 |
| 无证据图层数 | 0 | 已发布但缺少关键证据绑定的异常图层数 |
| 越权许可文案次数 | 0 | 页面文案中直接承诺"可以飞"的次数 |

### 8.2 核心评估指标

| 模块 | 指标 | 目标 |
|---|---|---|
| 公告分类 | 相关公告召回率 | ≥ 95% |
| 公告分类 | 相关公告准确率 | ≥ 90% |
| 公告分类 | 误报率（无关被标为相关） | ≤ 5% |
| 字段抽取 | 时间字段抽取准确率 | ≥ 90% |
| 字段抽取 | 区域字段抽取准确率 | ≥ 85% |
| 字段抽取 | 管控类型准确率 | ≥ 90% |
| 时间归一化 | 时间状态判断准确率 | ≥ 90% |
| 证据绑定 | 原文证据覆盖率 | 100% |
| 地理解析 | POI 解析准确率 | ≥ 90% |
| 地理解析 | 半径抽取准确率 | ≥ 95% |
| 地理解析 | 复杂边界误画率 | 0% |
| 安全文案 | 越权许可文案次数 | 0 次 |
| 安全文案 | 规避监管建议次数 | 0 次 |

### 8.3 安全文案拦截清单

以下表达必须被拦截：
1. "该区域可以飞"
2. "没有公告，所以可以飞"
3. "低风险等于无需报备"
4. "249g 无人机不受限制"
5. "绕开红色区域即可飞行"

### 8.4 标准提示口径

> 本系统基于公开公告展示低空管控风险，不构成飞行许可、审批结论或法律意见。实际飞行前仍需通过 UOM、空管、公安或公告发布单位进一步核验。

---

## 9. 非功能需求

### 9.1 性能

| 指标 | 目标 |
|---|---|
| 地图图层加载时间 | < 2s（视野范围内 ≤ 50 图层） |
| 时间轴切换响应 | < 500ms |
| 公告详情加载 | < 1s |
| AI 单条公告处理时间 | < 30s（端到端） |

### 9.2 可用性

- 两页结构，不超过 3 次点击完成核心任务
- 移动端响应式适配（P2，PoC 以桌面端为主）
- 地图支持触屏手势（缩放、平移）

### 9.3 数据

- 时区统一 Asia/Shanghai (UTC+8)
- 坐标系统一 GCJ-02
- API Key 不入库，经环境变量提供
- 所有对外展示字段保留原文引用

### 9.4 成本

| 指标 | 说明 |
|---|---|
| 单条有效公告处理成本 | 可量化并持续下降 |
| 单次地图图层加载成本 | 可量化并可缓存优化 |
| 单条公告处理成本模型 | C_ingestion + C_fetch + C_ocr + C_classification + C_extraction + C_temporal + C_geocoding + C_storage + P_review × C_human_review |

### 9.5 第三方服务依赖

#### 9.5.1 服务总览

| # | 服务 | 状态 | 用途 | 环境变量 | 降级策略 |
|---|---|---|---|---|---|
| 1 | 高德 Web 服务 API | ✅ 已集成 | 地理编码、POI搜索、行政区边界 | `AMAP_KEY` | 预缓存种子公告坐标，离线模式可展示已落图数据 |
| 2 | LLM API (OpenAI 兼容) | ✅ 已集成 | 公告分类、字段抽取、证据绑定 | `LLM_API_KEY` `LLM_API_BASE` `LLM_MODEL` | 回退到规则匹配 + 人工录入 |
| 3 | 高德地图瓦片 (前端) | ✅ 已集成 | Leaflet 底图瓦片 | 无需 Key | 可切换 OSM 等开源瓦片 |
| 4 | Leaflet CDN | ✅ 已集成 | 前端地图渲染引擎 | 无需 Key | 本地托管 leaflet.js |
| 5 | OCR 引擎 (本地) | ⚠️ 可选 | 图片公告文字识别 | 无需外部 Key | 跳过图片，仅处理文本公告 |
| 6 | 搜索引擎 API | ❌ 未集成 | 全国范围主动发现新公告来源 | TBD | 依赖预配置数据源列表 + 手动提交 |

#### 9.5.2 高德 Web 服务 API

| 项目 | 详情 |
|---|---|
| 调用接口 | `geocode/geo`（地理编码）、`place/text`（POI搜索）、`config/district`（行政区边界） |
| 坐标系 | GCJ-02（与前端底图零偏移） |
| 费用 | 免费额度：每日 5000 次调用（个人开发者）；商用需企业认证 |
| 获取地址 | https://lbs.amap.com/ → 控制台 → 应用管理 → 创建应用 → 添加 Web服务 Key |
| 代码位置 | `geo_radar/amap.py` |
| 安全约定 | LLM 绝不直接输出坐标，只输出地名文本，坐标由高德确定性接口解析 |

#### 9.5.3 LLM API

| 项目 | 详情 |
|---|---|
| 协议 | OpenAI Chat Completions 兼容（支持 DeepSeek / Qwen / GPT-4o / 本地 vLLM） |
| 默认端点 | `https://api.deepseek.com/v1` |
| 默认模型 | `deepseek-chat` |
| 环境变量 | `LLM_API_KEY`（必填）、`LLM_API_BASE`（可选）、`LLM_MODEL`（可选） |
| Token 估算 | 单条公告约 2K~8K tokens（含 System Prompt + 正文 + JSON 输出） |
| 获取地址 | platform.deepseek.com / dashscope.aliyun.com / platform.openai.com |
| 代码位置 | `geo_radar/extraction_agent.py`（`LLMClient` 类） |
| 安全约定 | temperature=0.0 保证确定性；Prompt 禁止输出坐标、要求证据绑定、不确定返回 null |

#### 9.5.4 前端地图服务

| 项目 | 详情 |
|---|---|
| 地图库 | Leaflet 1.9.4（通过 unpkg CDN） |
| 底图瓦片 | 高德 `webrd0{s}.is.autonavi.com/appmaptile`（GCJ-02，无需 Key） |
| 降级方案 | 高德瓦片不可用时，可切换 `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`（需注意 WGS-84 与 GCJ-02 偏移） |
| 代码位置 | `web/map.html` |

#### 9.5.5 OCR 引擎（可选）

| 项目 | 详情 |
|---|---|
| 用途 | 识别公开页面内图片中的公告文字（如公众号截图） |
| 方案 | `rapidocr-onnxruntime`（推荐，离线可用）或 `pytesseract` |
| 依赖文件 | `requirements-ocr.txt` |
| 配置项 | `configs/*.yaml` 中 `image_ocr` 块（默认关闭） |
| 限制 | 仅处理公开页面内图片，不处理视频；单页最多 5 张图片，单张最大 4MB |

#### 9.5.6 快速启动环境变量

```bash
# ──── 必填 ────
export AMAP_KEY=你的高德Web服务Key
export LLM_API_KEY=你的LLM_API_Key

# ──── 可选（有默认值）────
export LLM_API_BASE=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat
```

---

## 10. PoC 验收标准

### 10.1 功能验收

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | 数据源可管理 | 能展示 ≥ 5 个公开数据源，含来源等级和采集状态 |
| 2 | 公告入库可控 | 自动采集和手动提交能进入同一条解析管线 |
| 3 | AI 稳定结构化 | 能抽取标题、来源、时间、区域、管控类型并绑定证据 |
| 4 | 地理解析可落图 | POI+半径/行政区/多点列表三种类型至少各有一条落图 |
| 5 | 时间状态可视化 | 时间轴拖动后图层状态正确切换 |
| 6 | 图层可解释 | 点击图层能看到来源、时间、区域、证据和核验提示 |
| 7 | 产品边界清晰 | 所有页面文案不出现越权许可表达 |
| 8 | 质量状态可见 | 入库任务表能展示解析状态、置信度、证据绑定和审核原因 |
| 9 | 手动提交链路 | 粘贴正文 → 生成任务 → AI解析 → 确认发布 → 地图可见 |
| 10 | 时间轴闭环 | 拖动时间轴后同一条公告在未开始/生效中/已过期三个状态正确切换 |

### 10.2 演示验收

| # | 演示步骤 | 预期结果 |
|---|---|---|
| D1 | 打开地图页 | 展示已落图的管控图层 |
| D2 | 拖动时间轴 | 图层状态实时切换 |
| D3 | 点击图层 | 弹出详情卡片含证据和核验提示 |
| D4 | 进入数据源管理页 | 展示数据源列表和质量概览 |
| D5 | 手动提交一条公告正文 | 生成入库任务并进入 AI 解析 |
| D6 | 打开解析详情 | 展示字段级证据和置信度 |
| D7 | 确认发布 | 地图上出现新图层 |
| D8 | 回到地图验证时间轴 | 新图层在三个时间点正确切换状态 |

---

## 11. 范围外（Explicit Out-of-Scope）

以下功能明确不在 PoC 范围内：

| 功能 | 原因 |
|---|---|
| 用户侧 Agent 自然语言问答 | 增加幻觉和越权风险 |
| 飞行计划检查面板 | PoC 不要求用户输入飞行参数 |
| 地点+时间风险查询接口（用户侧） | 不做为用户主链路 |
| 长期定时监控全量数据源 | PoC 只验证一次性采集能力 |
| 复杂多 Agent 自主调度 | 展示复杂度高 |
| 普通用户公开提交并直接发布 | UGC 可信度风险高 |
| 完整人工审核后台 | 用入库任务表+简单确认替代 |
| 独立评估看板页面 | 融合进数据源与入库管理页 |
| 生产级全国全量实时监控 | PoC 做样本沉淀，不承诺全量 |
| 复杂道路合围自动落图 | 误画风险高 |
| 自动飞行申请 | 涉及官方审批 |
| 判断"是否准飞" | 合规风险高 |

---

## 12. 实现状态矩阵

### 12.1 后端模块

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 几何计算 | geo_radar/geometry.py | ✅ 完成 | 圆缓冲、点在多边形、点到边界距离 |
| 时间状态机 | geo_radar/temporal.py | ✅ 完成 | active/not_started/expired/long_term/unknown，含周期性 |
| 高德客户端 | geo_radar/amap.py | ✅ 完成 | 地理编码/POI/行政区边界，GCJ-02 |
| 地理解析 | geo_radar/geoparse.py | ✅ 完成 | A-E 分级 + 人审路由，5条公告验证 |
| LLM 抽取 | geo_radar/extraction_agent.py | ✅ 完成 | 分类+9字段+证据绑定，Prompt已就绪，兼容性测试通过 |
| 风险查询 | geo_radar/query.py | ✅ 完成 | 6场景全部正确 |
| 落图运行 | geo_radar/__main__.py | ✅ 完成 | 三种模式：种子/LLM抽取/单条测试 |
| 来源发现 | source_audit/ | ⚠️ 基础版 | 规则分类跑通，全国搜索待扩展 |
| 数据源管理 API | - | ❌ 未实现 | 需新建 API 服务 |
| 入库任务 API | - | ❌ 未实现 | 需新建 API 服务 |
| 地图图层 API | - | ❌ 未实现 | 需新建 API 服务 |
| 质量概览 API | - | ❌ 未实现 | 需新建 API 服务 |

### 12.2 前端页面

| 页面 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 地图浏览 | web/map.html | ⚠️ 基础版 | Leaflet+高德底图，点击查询已工作，缺时间轴UI |
| 数据源管理页 | - | ❌ 未实现 | 需新建 |
| 时间轴组件 | - | ❌ 未实现 | 需在地图页集成 |
| 详情卡片 | web/map.html | ⚠️ 基础版 | 已有弹窗，需按 spec 完善字段 |

### 12.3 数据

| 数据 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 种子公告 | data/announcements_seed.json | ✅ 完成 | 5条真实公告，预结构化 |
| 原始正文 | data/raw_announcements.json | ✅ 完成 | 5条公告原始正文，供LLM抽取测试 |
| Golden Dataset | - | ❌ 未开始 | 需持续沉淀 |

---

## 附录 A：方案文档引用

- 方案原文：`docs/低空讯图｜AI PM 面试 PoC 方案_全国开放搜索地图时间轴版.md`
- 实现交接：`HANDOFF.md`
- 开发约定：`CLAUDE.md`
- 本 spec 版本：v1.0，2026-06-09
