from __future__ import annotations

import re
from datetime import date

from .models import AuditConfig, Classification, ExtractedPage, FetchResult
from .utils import find_keyword_snippets, normalize_for_match


SCENE_KEYWORDS: dict[str, list[str]] = {
    "无人机": ["无人机", "民用无人驾驶航空器", "无人驾驶航空器", "无人驾驶飞行器"],
    "低慢小": ["低慢小", "低空慢速小目标"],
    "飞行物": ["飞行物", "航空器", "航模", "飞艇", "滑翔伞", "动力伞"],
    "空飘物": ["空飘物", "气球", "孔明灯", "风筝", "系留气球"],
    "机场净空": ["机场净空", "净空保护", "净空保护区", "机场保护区"],
    "临时管控": ["临时管控", "临时管制", "临时禁飞", "临时空域管制", "禁飞", "重点管控"],
    "适飞空域": ["适飞空域", "可飞空域", "飞行空域", "空域申报", "飞行计划"],
    "赛事管控": ["赛事", "比赛", "马拉松", "运动会", "演唱会", "音乐节", "啤酒节", "节会", "大型活动"],
    "考试管控": ["高考", "中考", "考试", "考点"],
    "景区提示": ["景区", "游客须知", "入园须知", "观赛须知", "活动须知"],
}

FORMAL_NOTICE_TERMS = ["公告", "通告", "通知", "管制通告", "禁飞通告", "温馨提示"]
RESTRICTION_TERMS = [
    "禁止",
    "不得",
    "严禁",
    "禁飞",
    "管控",
    "限制",
    "报备",
    "备案",
    "未经批准",
    "停止飞行",
    "主动停止",
]
TEMPORARY_TERMS = [
    "临时",
    "当日",
    "活动期间",
    "考试期间",
    "赛事期间",
    "作业期间",
    "作业时段",
    "防治期间",
    "施药期间",
    "管控时段",
    "重点管控时段",
    "禁飞期间",
]
LONG_TERM_TERMS = ["长期", "常态化", "全年", "管理办法", "条例", "规定", "净空", "备案", "实名登记", "适飞空域", "施行", "有效期"]
MEDIA_TERMS = ["记者", "报道", "新闻", "客户端", "融媒", "晚报", "电视台", "大众网", "齐鲁网"]
LOCATION_TERMS = ["范围", "区域", "路", "街", "镇", "村", "区", "县", "市", "机场", "景区", "场馆", "考点", "四至"]
ACTIVITY_NOTICE_TERMS = ["活动须知", "观赛须知", "游客须知", "入园须知", "景区提示", "重要提醒", "安全提示", "倡议书", "告广大市民书"]
FORMAL_SIGNER_TERMS = ["人民政府", "公安局", "交通运输厅", "气象局", "组委会", "机场", "管理委员会"]
ONGOING_VALIDITY_TERMS = [
    "长期",
    "常态化",
    "全年",
    "即日起施行",
    "即日起执行",
    "自发布之日起",
    "自公布之日起",
    "正式启用",
    "登记备案",
    "实名登记",
    "适飞空域",
    "管制空域",
    "飞行活动申请",
    "管理办法",
    "暂行条例",
    "有效期",
]
COORDINATE_PATTERN = re.compile(r"\d{2,3}\.\d{3,}|\d{2,3}°\d+")


def classify_page(page: ExtractedPage, fetch: FetchResult, config: AuditConfig) -> Classification:
    full_text = "\n".join([page.title, page.body_text])
    compact = normalize_for_match(full_text)
    leading_compact = normalize_for_match(" ".join([page.title, page.summary[:500]]))
    scene_hits = _scene_hits(compact)
    if "临时管控" in scene_hits and not _leading_temporary_signal(
        leading_compact, [scene for scene in scene_hits if scene != "临时管控"]
    ):
        scene_hits = [scene for scene in scene_hits if scene != "临时管控"]
    custom_hits = [keyword for keyword in config.keywords if keyword and keyword in compact]
    evidence_terms = _unique_terms(custom_hits + [term for scene in scene_hits for term in SCENE_KEYWORDS.get(scene, [])])
    evidence = find_keyword_snippets(full_text, evidence_terms, max_snippets=5)

    relevant = bool(scene_hits or custom_hits)
    if not relevant:
        return Classification(
            relevant=False,
            category="E",
            confidence=0.1,
            reason="未命中低空飞行风险相关关键词或场景规则。",
            scenes=[],
            evidence_snippets=[],
            mappability="不可地图化",
            validity="未知",
        )

    priority = (fetch.source_priority or "P2").upper()
    is_primary_source = priority in {"P0", "P1"}
    has_notice = _contains_any(compact, FORMAL_NOTICE_TERMS)
    has_restriction = _contains_any(compact, RESTRICTION_TERMS)
    has_long_term = _contains_any(compact, LONG_TERM_TERMS)
    has_activity_notice = _contains_any(compact, ACTIVITY_NOTICE_TERMS) and any(
        scene in scene_hits for scene in ("赛事管控", "考试管控", "景区提示")
    )
    has_formal_signer = _contains_any(compact, FORMAL_SIGNER_TERMS)
    leading_temporary = _leading_temporary_signal(leading_compact, scene_hits)
    is_formal_temporary_notice = has_notice and has_restriction and leading_temporary
    looks_media = priority in {"P2", "P3"} and _contains_any(compact + fetch.source_name, MEDIA_TERMS)

    category = "E"
    confidence = 0.45
    reason_parts: list[str] = []

    if is_primary_source and is_formal_temporary_notice:
        category = "A"
        confidence = 0.88
        reason_parts.append("权威或组织方来源命中公告/通告、限制词和临时管控信号。")
    elif is_formal_temporary_notice and has_formal_signer:
        category = "A"
        confidence = 0.74
        reason_parts.append("页面正文呈现正式临时管控公告特征，并含政府、公安、机场或组委会落款。")
    elif has_activity_notice and has_restriction:
        category = "B"
        confidence = 0.76 if is_primary_source else 0.68
        reason_parts.append("命中活动须知、观赛须知、景区提示等场景中的限制性表述。")
    elif has_long_term and (
        "机场净空" in scene_hits
        or "适飞空域" in scene_hits
        or _contains_any(compact, ["备案", "实名登记", "空域申报", "管制空域", "飞行活动申请", "升放气球"])
    ):
        category = "C"
        confidence = 0.78 if is_primary_source else 0.7
        reason_parts.append("命中长期规则、机场净空、适飞空域或备案提醒信号。")
    elif looks_media:
        category = "D"
        confidence = 0.6
        reason_parts.append("来源或正文呈现媒体报道特征，作为报道线索处理。")
    elif has_restriction:
        category = "E"
        confidence = 0.5
        reason_parts.append("命中限制性表述，但缺少可核验公告、活动须知或长期规则信号。")
    else:
        category = "E"
        confidence = 0.35
        reason_parts.append("仅命中弱相关关键词，证据不足。")

    if scene_hits:
        reason_parts.append("场景命中：" + "、".join(scene_hits) + "。")
    if custom_hits:
        reason_parts.append("自定义关键词命中：" + "、".join(custom_hits[:8]) + "。")

    return Classification(
        relevant=True,
        category=category,
        confidence=round(confidence, 2),
        reason="".join(reason_parts),
        scenes=scene_hits,
        evidence_snippets=evidence,
        mappability=infer_mappability(compact, scene_hits, category),
        validity=infer_validity(compact, page.date_mentions, config.current_date, category),
    )


def infer_city(text: str, cities: list[str]) -> str:
    compact = normalize_for_match(text)
    for city in cities:
        if city and city in compact:
            return city
    return "未识别"


def infer_validity(compact_text: str, dates: list[date], current_date: date, category: str = "") -> str:
    if category == "C" and _contains_any(compact_text, ONGOING_VALIDITY_TERMS):
        return "当前/未来有效"
    if category in {"B", "D"} and _contains_any(compact_text, ["长期", "常态化", "全年", "长期有效"]):
        return "当前/未来有效"
    if any(value >= current_date for value in dates):
        return "当前/未来有效"
    if dates and all(value < current_date for value in dates):
        return "历史样本"
    return "未知"


def infer_mappability(compact_text: str, scenes: list[str], category: str) -> str:
    has_coordinate = bool(COORDINATE_PATTERN.search(compact_text))
    has_area_terms = _contains_any(compact_text, LOCATION_TERMS)
    has_boundary_terms = _contains_any(compact_text, ["四至", "东至", "西至", "南至", "北至", "半径", "公里", "米范围"])

    if has_coordinate or (has_boundary_terms and has_area_terms):
        return "可地图化"
    if has_area_terms and category in {"A", "B", "C"}:
        return "半自动地图化"
    if "机场净空" in scenes or "适飞空域" in scenes:
        return "半自动地图化"
    return "不可地图化"


def _scene_hits(compact_text: str) -> list[str]:
    hits = []
    for scene, keywords in SCENE_KEYWORDS.items():
        if _contains_any(compact_text, keywords):
            hits.append(scene)
    return hits


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term and term in text for term in terms)


def _leading_temporary_signal(leading_text: str, scenes: list[str]) -> bool:
    if _contains_any(leading_text, TEMPORARY_TERMS):
        return True
    if _contains_any(leading_text, ["临时管控", "临时管制", "临时禁飞", "临时空域管制"]):
        return True
    event_or_exam = any(scene in scenes for scene in ("赛事管控", "考试管控", "景区提示"))
    return event_or_exam and _contains_any(leading_text, ["禁飞", "重点管控"])


def _unique_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term and term not in seen:
            unique.append(term)
            seen.add(term)
    return unique
