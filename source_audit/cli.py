from __future__ import annotations

import argparse
import sys

from .config import build_config_from_cli, load_config, validate_config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run_audit_command(args)
    if args.command == "recall-eval":
        return _run_recall_eval_command(args)

    parser.print_help()
    return 1


def _run_audit_command(args) -> int:
    try:
        config = load_config(args.config) if args.config else build_config_from_cli(args)
        _apply_overrides(config, args)
        validate_config(config)
        from .pipeline import run_audit

        result = run_audit(config)
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 2

    stats = result["stats"]
    print(f"run_id: {result['run_id']}")
    print(f"db: {result['db_path']}")
    print(f"csv: {result['csv_path']}")
    print(f"report: {result['report_path']}")
    print(f"raw_url_count: {stats['raw_url_count']}")
    print(f"unique_url_count: {stats['unique_url_count']}")
    print(f"relevant_page_count: {stats['relevant_page_count']}")
    return 0


def _run_recall_eval_command(args) -> int:
    try:
        from .recall_eval import run_recall_eval

        result = run_recall_eval(args.golden, args.db, args.report)
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 2

    print(f"total_golden_count: {result['total_golden_count']}")
    print(f"recalled_count: {result['recalled_count']}")
    print(f"recall_rate: {result['recall_rate']:.4f}")
    print(f"A_type_recall_rate: {result['A_type_recall_rate']:.4f}")
    if "P0/P1_recall_rate" in result:
        print(f"P0/P1_recall_rate: {result['P0/P1_recall_rate']:.4f}")
    print("missed_samples:")
    for sample in result["missed_samples"]:
        print(f"- {sample['id']} | {sample['type']} | {sample['city']} | {sample['title']} | {sample['url']}")
    print(f"report: {result['report_path']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="山东省低空飞行风险信息 Source Audit 小程序")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="执行采集、抽取、分类、去重和报告生成")
    _add_run_arguments(run)

    recall_eval = subparsers.add_parser("recall-eval", help="基于已有 SQLite 评估 golden 样本召回率")
    recall_eval.add_argument("--golden", required=True, help="golden CSV 路径，字段为 id,title,city,url,type")
    recall_eval.add_argument("--db", required=True, help="SQLite 数据库路径")
    recall_eval.add_argument("--report", default="data/outputs/recall_eval_report.md", help="Markdown 报告输出路径")

    return parser


def _add_run_arguments(run: argparse.ArgumentParser) -> None:
    run.add_argument("--config", help="YAML 配置文件路径")
    run.add_argument("--city", action="append", help="城市名，可重复传入")
    run.add_argument("--source", action="append", help='来源，可用 "P0|来源名|https://example.com/" 格式')
    run.add_argument("--keyword", action="append", help="关键词，可重复传入")
    run.add_argument("--start-date", help="起始日期，YYYY-MM-DD")
    run.add_argument("--end-date", help="结束日期，YYYY-MM-DD")
    run.add_argument("--current-date", help="用于判断当前/未来有效样本的日期，默认今天")
    run.add_argument("--db", default="data/source_audit.sqlite", help="SQLite 数据库路径")
    run.add_argument("--out-dir", default="outputs", help="输出目录")
    run.add_argument("--max-pages", type=int, default=30, help="每个来源最多抓取页数")
    run.add_argument("--max-depth", type=int, default=1, help="同域发现深度")
    run.add_argument("--timeout", type=int, default=12, help="请求超时秒数")
    run.add_argument("--polite-delay", type=float, default=2.0, help="同一 host 请求间隔秒数")
    run.add_argument("--exclude-unknown-dates", action="store_true", help="报告统计中排除发布时间未知页面")
    run.add_argument("--ignore-robots-txt", action="store_true", help="不读取 robots.txt；默认尊重 robots.txt")
    run.add_argument("--follow-wechat-links", action="store_true", help="允许从已抓取公开页面继续发现 mp.weixin.qq.com 文章链接")
    run.add_argument("--image-ocr", action="store_true", help="对页面内图片做 OCR；需安装 requirements-ocr.txt")
    run.add_argument("--ocr-max-images", type=int, default=5, help="每页最多 OCR 图片数")


def _apply_overrides(config, args) -> None:
    if not args.config:
        return
    if args.db != "data/source_audit.sqlite":
        config.database_path = args.db
    if args.out_dir != "outputs":
        config.output_dir = args.out_dir
    if args.max_pages != 30:
        config.max_pages_per_source = args.max_pages
    if args.max_depth != 1:
        config.max_depth = args.max_depth
    if args.timeout != 12:
        config.timeout_seconds = args.timeout
    if args.polite_delay != 2.0:
        config.polite_delay_seconds = args.polite_delay
    if args.exclude_unknown_dates:
        config.include_unknown_dates = False
    if args.ignore_robots_txt:
        config.respect_robots_txt = False
    if args.follow_wechat_links:
        config.follow_external_wechat_links = True
    if args.image_ocr:
        config.image_ocr_enabled = True
    if args.ocr_max_images != 5:
        config.image_ocr_max_images_per_page = args.ocr_max_images
