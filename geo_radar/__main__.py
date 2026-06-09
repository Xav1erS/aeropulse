"""落图运行：加载种子公告 → Geo Parsing + 时间判断 → 写 GeoJSON 图层。

用法：
  # 模式1：使用预结构化种子数据（现有方式）
  python -m geo_radar --seed data/announcements_seed.json --out outputs --now 2026-06-08T12:00:00

  # 模式2：从原始正文出发，LLM 在线抽取 → 落图（需设置 LLM_API_KEY）
  python -m geo_radar --extract data/raw_announcements.json --out outputs --now 2026-06-08T12:00:00

  # 模式3：单条正文快速测试
  python -m geo_radar --extract-text "关于对无人机实施临时禁飞的通告。禁飞时间..." --source-name "测试来源" --city "杭州"

输出：
  outputs/zones.geojson      标准 GeoJSON（可导入任意 GIS）
  outputs/zones.js           window.ZONES=...（供 web/map.html 以 file:// 直接加载）
  outputs/announcements.json 结构化记录（含未落图的待核验项）
  outputs/extracted_announcements.json  LLM抽取的结构化结果（--extract 模式）
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from . import extraction_agent, geoparse, temporal
from . import geometry as g
from .amap import AmapClient

AS_OF_DEFAULT = "2026-06-08T12:00:00"  # PoC 演示基准时刻


def _fmt_time(time: dict) -> str:
    mode = time.get("mode")
    if mode == "single":
        s = (time.get("start") or "").replace("T", " ")[:16]
        e = (time.get("end") or "").replace("T", " ")[:16]
        return f"{s} ~ {e}"
    if mode == "recurring_seasonal":
        return "每年 " + "、".join(f"{w['start']}~{w['end']}" for w in time.get("windows", []))
    if mode == "long_term":
        return "长期有效"
    return "时间未知"


def _style(active: bool, risk_class: str, grade: str, review: bool) -> dict:
    """图层配色（§10.1 / §6.6）：按生效状态 + 管控类型 + 置信度分级。"""
    if not active:
        return {"color": "#9aa0a6", "fillColor": "#9aa0a6", "fillOpacity": 0.12, "dashed": True, "layer": "已过期/未生效"}
    if grade == "E":
        return {"color": "#9aa0a6", "fillColor": "#9aa0a6", "fillOpacity": 0.0, "dashed": True, "layer": "待核验点"}
    palette = {
        "no_fly":  ("#d93025", "临时禁飞/管制"),
        "control": ("#e8710a", "临时管控"),
        "advisory": ("#f9ab00", "提示/备案"),
    }
    color, layer = palette.get(risk_class, palette["control"])
    return {"color": color, "fillColor": color, "fillOpacity": 0.22 if not review else 0.14,
            "dashed": review, "layer": layer + ("（近似/待核验）" if review else "")}


def build(seed_path: str, out_dir: str, now: datetime) -> dict:
    anns = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    client = AmapClient()
    features: list = []
    records: list = []

    for ann in anns:
        gp = geoparse.parse(ann, client)
        val = temporal.evaluate(ann, now)
        review = gp.review_status == "needs_review"
        style = _style(val.active, ann.get("risk_class", "control"), gp.grade, review)
        props = {
            "id": ann["id"],
            "title": ann["title"],
            "publish_unit": ann.get("publish_unit", ""),
            "source_name": ann.get("source_name", ""),
            "source_url": ann.get("source_url", ""),
            "source_level": ann.get("source_level", ""),
            "city": ann.get("city", ""),
            "control_type": ann.get("control_type", ""),
            "risk_class": ann.get("risk_class", "control"),
            "aircraft_types": "、".join(ann.get("aircraft_types", [])),
            "area_text": ann.get("area_text", ""),
            "evidence_text": ann.get("evidence_text", ""),
            "confidence_score": ann.get("confidence_score"),
            "time": ann.get("time"),
            "time_text": _fmt_time(ann.get("time") or {}),
            "status": val.status,
            "status_basis": val.basis,
            "active": val.active,
            "geo_type": gp.geo_type,
            "geo_grade": gp.grade,
            "geo_confidence": gp.confidence,
            "geo_method": gp.method,
            "review_status": gp.review_status,
            "review_reason": gp.review_reason,
            "center": gp.center,
            **style,
        }
        if gp.geometry:
            features.append(g.feature(gp.geometry, props))
        records.append({k: v for k, v in props.items() if k != "time"} | {"geometry_type": gp.geometry["type"] if gp.geometry else None})

    fc = g.feature_collection(features)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "zones.geojson").write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "zones.js").write_text("window.ZONES = " + json.dumps(fc, ensure_ascii=False) + ";\n", encoding="utf-8")
    (out / "announcements.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return fc


def build_from_raw_texts(raw_path: str, out_dir: str, now: datetime, client: extraction_agent.LLMClient | None = None) -> dict:
    """从原始公告正文 JSON 出发：LLM 抽取 → 落图。

    raw_path JSON 格式（数组，每条）：
    {
      "body_text": "公告正文全文...",
      "source_name": "来源名称",
      "source_url": "来源URL（可选）",
      "source_level": "P0/P1/P2/P3（可选）",
      "publish_time": "已知发布时间（可选）",
      "city": "城市名（可选）"
    }
    """
    raw_items = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    if client is None:
        client = extraction_agent.LLMClient()

    print(f"共 {len(raw_items)} 条原始公告正文，开始 LLM 抽取...")
    extracted: list[dict] = []
    skipped: list[dict] = []

    for i, item in enumerate(raw_items):
        body = item.get("body_text", "")
        if not body or not body.strip():
            print(f"  [{i+1}/{len(raw_items)}] 跳过：正文为空")
            skipped.append({"index": i, "reason": "正文为空", "item": item})
            continue

        print(f"  [{i+1}/{len(raw_items)}] 抽取中...", end=" ", flush=True)
        try:
            result = extraction_agent.extract_from_text(
                body_text=body,
                source_name=item.get("source_name", ""),
                source_url=item.get("source_url", ""),
                source_level=item.get("source_level", ""),
                publish_time=item.get("publish_time", ""),
                city=item.get("city", ""),
                client=client,
            )
        except Exception as exc:
            print(f"失败：{exc}")
            skipped.append({"index": i, "reason": str(exc), "item": item})
            continue

        ann_id = item.get("id") or f"extracted_{i+1:03d}"
        ann_dict = result.to_announcement_dict(ann_id)

        status = "[相关]" if result.is_relevant else "[无关]"
        review = "需核验" if result.needs_review else "可自动通过"
        print(f"{status} | 置信度={result.parse_confidence:.2f} | {review} | {result.classification_result}")

        if result.is_relevant:
            extracted.append(ann_dict)
        else:
            skipped.append({"index": i, "reason": f"AI判断为无关：{result.classification_reason}",
                           "announcement": ann_dict, "item": item})

    print(f"\n抽取完成：{len(extracted)} 条有效公告，{len(skipped)} 条跳过/无关")

    # 写出抽取结果供检查
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "extracted_announcements.json").write_text(
        json.dumps({"extracted": extracted, "skipped": skipped}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写出抽取结果：{out / 'extracted_announcements.json'}")

    # 进入落图管线
    if not extracted:
        print("无有效公告可落图")
        return g.feature_collection([])

    # 使用临时 seed 写入 extracted，再走 build()
    temp_seed = out / "_temp_extracted_seed.json"
    temp_seed.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
    fc = build(str(temp_seed), out_dir, now)
    temp_seed.unlink(missing_ok=True)
    return fc


def main() -> None:
    ap = argparse.ArgumentParser(description="低空讯图 PoC：公告落图")
    ap.add_argument("--seed", default="data/announcements_seed.json",
                    help="预结构化种子 JSON 路径（模式1）")
    ap.add_argument("--extract", default=None,
                    help="原始公告正文 JSON 路径，LLM 在线抽取后落图（模式2）")
    ap.add_argument("--extract-text", default=None,
                    help="单条公告正文，快速测试 LLM 抽取（模式3，仅输出抽取结果不落图）")
    ap.add_argument("--source-name", default="手动提交",
                    help="--extract-text 模式下的来源名称")
    ap.add_argument("--source-url", default="",
                    help="--extract-text 模式下的来源URL")
    ap.add_argument("--source-level", default="",
                    help="--extract-text 模式下的来源等级")
    ap.add_argument("--city", default="",
                    help="--extract-text 模式下的城市名")
    ap.add_argument("--publish-time", default="",
                    help="--extract-text 模式下的发布时间")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--now", default=AS_OF_DEFAULT, help="演示基准时刻 ISO，如 2026-06-08T12:00:00")
    args = ap.parse_args()
    now = datetime.fromisoformat(args.now)
    if now.tzinfo is None:
        from datetime import timezone, timedelta
        now = now.replace(tzinfo=timezone(timedelta(hours=8)))

    # 模式3：单条正文快速测试
    if args.extract_text:
        client = extraction_agent.LLMClient()
        print(f"单条正文 LLM 抽取测试...")
        print(f"来源：{args.source_name}  城市：{args.city}")
        print(f"正文前100字：{args.extract_text[:100]}...")
        print()
        result = extraction_agent.extract_from_text(
            body_text=args.extract_text,
            source_name=args.source_name,
            source_url=args.source_url,
            source_level=args.source_level,
            publish_time=args.publish_time,
            city=args.city,
            client=client,
        )
        ann = result.to_announcement_dict("test_001")
        print(json.dumps(ann, ensure_ascii=False, indent=2))
        return

    # 模式2：LLM 在线抽取 → 落图
    if args.extract:
        fc = build_from_raw_texts(args.extract, args.out, now)
        print(f"\nas-of {now.isoformat()}  共 {len(fc['features'])} 个落图要素")
        for f in fc["features"]:
            p = f["properties"]
            flag = "●生效中" if p["active"] else "○未生效"
            method = p.get("extraction_method", "")
            tag = f" [LLM抽取]" if method == "llm" else ""
            print(f"  [{p['geo_grade']}] {flag} {p['status']:<10} {p['layer']:<16}{tag} {p['title'][:24]}")
        print("已写出 outputs/zones.geojson, zones.js, announcements.json, extracted_announcements.json")
        return

    # 模式1：预结构化种子
    fc = build(args.seed, args.out, now)

    print(f"as-of {now.isoformat()}  共 {len(fc['features'])} 个落图要素")
    for f in fc["features"]:
        p = f["properties"]
        flag = "●生效中" if p["active"] else "○未生效"
        print(f"  [{p['geo_grade']}] {flag} {p['status']:<10} {p['layer']:<16} {p['title'][:24]}")
    print("已写出 outputs/zones.geojson, zones.js, announcements.json")


if __name__ == "__main__":
    main()
