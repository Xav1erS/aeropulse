# raw_announcements_2026_national 清洗报告

源文件：`docs/20260609 公告采集/raw_announcements_final.json`
输出文件：`data/raw_announcements_2026_national.json`
生成时间：2026-06-09

## 清洗规则

- 保留字段：`id`, `body_text`, `source_name`, `source_url`, `source_level`, `publish_time`, `city`, `verification_notes`。
- 硬过滤：空正文、空 URL、空城市、非 P0-P3 来源等级。
- 不按 URL 粗暴去重：同一聚合 URL 可能对应多条不同城市/公告，改为保留并标记 `duplicate_source_url_kept_for_manual_review`。
- P2/P3 来源保留，但标记 `source_level_requires_review`。
- Deep Research 摘要/摘录型正文保留，但标记 `summary_or_excerpt_body_needs_source_check`。
- 缺发布时间保留，但标记 `missing_publish_time`。

## 统计

- 输入记录数：116
- 输出记录数：116
- 丢弃记录数：0
- 带任意备注：116
- 需人工核验/来源复查：82
- 摘要或摘录型正文：43
- 重复 URL 保留项：10
- 缺发布时间：1

## 来源等级分布

- P0: 73
- P1: 23
- P2: 8
- P3: 12

## 丢弃记录

- 无
