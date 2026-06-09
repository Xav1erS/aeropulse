# 山东省低空飞行风险信息 Source Audit

这是一个不含前端地图的 Python 小程序，用于验证“山东省低空飞行风险信息供给密度”。它从公开网页入口做轻量同域发现，抽取标题、发布时间、正文和 URL，并用规则把结果初筛为 A/B/C/D/E 五类，最后写入 SQLite、CSV 和 Markdown 报告。

## 目录

```txt
source_audit/
  cli.py          # 命令行入口
  crawler.py      # polite 抓取和同域候选页发现
  extractor.py    # 标题、发布时间、正文抽取
  classifier.py   # 关键词、场景和 A/B/C/D/E 规则分类
  dedup.py        # 轻量去重
  storage.py      # SQLite 落库
  reporting.py    # CSV 和 Markdown 报告
configs/
  example.yaml    # 示例配置
tests/
  ...             # 基础规则测试
```

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行

使用配置文件：

```powershell
python -m source_audit run --config configs/example.yaml
```

扩大样本覆盖的山东省专用配置：

```powershell
python -m source_audit run --config configs/expanded.yaml
```

公众号公开文章和图片 OCR 配置：

```powershell
pip install -r requirements-ocr.txt
python -m source_audit run --config configs/wechat_ocr.yaml
```

也可以直接传参：

```powershell
python -m source_audit run `
  --city 济南 `
  --keyword 无人机 `
  --keyword 低慢小 `
  --keyword 机场净空 `
  --source "P0|济南市人民政府|https://www.jinan.gov.cn/" `
  --start-date 2025-01-01 `
  --end-date 2026-12-31 `
  --max-pages 20 `
  --polite-delay 2
```

临时开启公众号外链发现和图片 OCR：

```powershell
python -m source_audit run `
  --city 威海 `
  --keyword 无人机 `
  --keyword 低慢小 `
  --source "P0|威海市人民政府|https://www.weihai.gov.cn/" `
  --max-depth 1 `
  --follow-wechat-links `
  --image-ocr
```

输出位置：

- SQLite：`data/source_audit.sqlite`
- CSV：`outputs/source_audit_*.csv`
- Markdown：`outputs/source_audit_*.md`

## 输入配置

`configs/example.yaml` 支持：

- `cities`：城市列表。
- `keywords`：补充关键词列表，程序内置了无人机、低慢小、飞行物、空飘物、机场净空、临时管控、适飞空域、赛事/考试管控等场景词。
- `time_range`：报告统计时间范围；发布时间未知页面默认保留。
- `sources`：公开入口页或公告栏目。建议优先填具体栏目页，而不是网站首页。
- `priority`：来源优先级。

来源优先级建议：

- `P0`：政府、公安、民航、机场、应急等正式权威来源。
- `P1`：活动主办方、景区、学校、场馆等组织方来源。
- `P2`：主流媒体、官方媒体、政务媒体转载。
- `P3`：其他公开网页。

## 分类口径

- `A`：正式临时禁飞/管控公告。
- `B`：活动须知、观赛须知、景区提示中的无人机/飞行物限制。
- `C`：长期规则、机场净空、适飞空域、备案提醒。
- `D`：媒体报道线索。
- `E`：不可核验、低质量或弱相关线索。

每条结果都会保留：

- `confidence`
- `reason`
- `evidence_snippets`
- 原始 URL、最终 URL、抓取时间、标题、发布时间、正文摘要和正文文本

## 抓取约束

第一版只做公开网页轻量抓取：

- 默认尊重 `robots.txt`。
- 默认同一 host 间隔 `polite_delay_seconds` 秒。
- 不登录、不处理验证码、不绕过反爬。
- 跳过疑似登录页和常见附件 URL。
- 不调用付费 API 或通用搜索 API。

## 公众号和图片 OCR

程序支持两类非纯文本扩展：

- 从已抓取的公开页面继续发现 `mp.weixin.qq.com/s/...` 公众号文章链接。
- 对页面内图片做本地 OCR，并把识别文本以 `[图片OCR]` 前缀并入正文，再进入同一套分类、去重和报告流程。

边界：

- 不登录微信、公众号后台、视频号或其他平台。
- 不绕过验证码、签名校验、反爬或付费接口。
- 不做微信平台内全量搜索；公众号文章需要来自公开入口页外链，或作为公开 URL 出现在配置来源中。
- 不处理视频抽帧和视频字幕。

OCR 后端优先使用 RapidOCR；如果当前 Python 版本没有可用 wheel，会尝试 Tesseract。Windows 下使用 Tesseract 时，需要另外安装 Tesseract OCR 程序和中文语言包。

## 统计口径

Markdown 报告统计时间范围内、去重后的样本：

- `raw_url_count`
- `unique_url_count`
- `relevant_page_count`
- A/B/C/D/E 数量
- 当前/未来有效样本分类
- 时效性聚焦口径，区分当前/未来有效供给、当前/未来有效 A/B 临时管控和历史 A/B 临时管控
- P0/P1/P2/P3 来源占比
- 城市分布
- 场景分布
- 当前/未来有效样本数
- 可地图化/半自动地图化/不可地图化数量

分类和地图化可行性是规则初筛，不应直接作为正式结论。

临时空域管制、活动/考试/景区限制等 A/B 类样本时效性强。做当前供给密度判断时，应优先使用报告中的 `当前/未来有效供给` 和 `当前/未来有效 A/B 临时管控`，历史 A/B 样本只适合用于来源发现和历史覆盖分析。

## Recall Eval

用于评估已有 SQLite 结果是否找回已知样本，不联网、不重新抓取。

```powershell
py -m source_audit recall-eval --golden data/golden/sd_known_samples.csv --db data/audit.sqlite
```

golden CSV 必填字段：

```txt
id,title,city,url,type
```

可选字段：

```txt
source_level
```

召回判断顺序：

- URL 完全匹配。
- 标题模糊匹配。
- 标题关键词匹配。

输出指标：

- `total_golden_count`
- `recalled_count`
- `recall_rate`
- `A_type_recall_rate`
- `P0/P1_recall_rate`，仅当 golden CSV 有 `source_level` 数据时输出
- `missed_samples`

Markdown 报告默认写入：

```txt
data/outputs/recall_eval_report.md
```
