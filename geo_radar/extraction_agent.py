"""LLM 在线抽取 Agent（方案 §7.2–§7.5）：原始公告正文 → 结构化字段 + 原文证据。

安全约定：
  1. LLM 绝不直接输出坐标 —— 只输出"地点引用文本"（POI名/行政区名/道路名），坐标由高德确定性接口解析。
  2. 所有关键字段必须绑定原文证据（evidence_*）。
  3. 不确定字段返回 null，不凭空补全。
  4. 低置信度结果标记 needs_review，不进自动通过。

输入：原始公告正文（str）或 正文 + 来源元数据（dict）
输出：与 announcements_seed.json 对齐的结构化 dict，可直接进入 geoparse.parse() + temporal.evaluate() + __main__.build()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Prompt 设计（方案 §7.2 分类 + §7.3 字段抽取）
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """你是一个低空飞行管控公告的结构化抽取助手。你的任务是从政府公告、公安通告、景区通知、赛事公告等公开文本中，提取与无人机/低慢小航空器管控相关的结构化信息。

## 核心原则
1. **所有字段必须绑定原文证据**：每个输出的字段值，必须能在原文中找到对应的原文句子作为证据。
2. **不确定就返回 null**：不要猜测、不要推理、不要补全原文中没有的信息。
3. **绝不判断飞行许可**：你的输出只描述"公告说了什么"，不判断"能不能飞"。
4. **坐标绝不自己编**：地理位置只输出"地名引用文本"（如"杭州奥体中心"），不要输出经纬度坐标。

## 输出格式
严格按以下 JSON Schema 输出，不要输出任何其他内容：

{
  "is_relevant": true/false,
  "classification_result": "TEMP_NO_FLY" | "TEMP_CONTROL" | "REGISTRATION_NOTICE" | "SAFETY_REMINDER" | "NON_RELEVANT",
  "classification_reason": "判断依据，引用原文关键句",
  "title": "公告标题" | null,
  "publish_unit": "发布单位" | null,
  "control_type": "临时禁飞" | "临时管控" | "备案通知" | "安全提醒" | "长期规则" | null,
  "risk_class": "no_fly" | "control" | "advisory" | null,
  "aircraft_types": ["无人机", "航空模型", ...] | [],
  "time": {
    "mode": "single" | "long_term" | "recurring_seasonal" | "unknown",
    "start": "2026-06-07T08:00:00" | null,
    "end": "2026-06-10T18:00:00" | null,
    "windows": [{"start": "MM-DD", "end": "MM-DD"}, ...] | null,
    "note": "时间表达说明" | null
  },
  "area_text": "原文中的区域描述" | null,
  "geo": {
    "geo_type": "poi_buffer" | "poi_buffer_multi" | "admin" | "bbox_roads" | "area_no_boundary" | "fuzzy",
    "city": "城市名" | null,
    "poi": "单一POI名称" | null,
    "poi_list": ["POI1", "POI2", ...] | [],
    "radius_m": 数字(米) | null,
    "district": "行政区名称" | null,
    "roads": ["路名1", "路名2", ...] | [],
    "note": "地理表达说明" | null,
    "roster_status": "explicit_from_notice" | "candidate_needs_verification" | null
  },
  "evidence": {
    "title_evidence": "标题对应的原文句子" | null,
    "publish_unit_evidence": "发布单位对应的原文句子" | null,
    "time_evidence": "时间信息对应的原文句子" | null,
    "area_evidence": "区域信息对应的原文句子" | null,
    "control_type_evidence": "管控类型对应的原文句子" | null
  },
  "parse_confidence": 0.0~1.0,
  "needs_review": true/false,
  "review_reason": "需要人工核验的原因" | null
}

## 分类标签说明
- TEMP_NO_FLY：公告明确包含"临时禁飞""禁止飞行""严禁飞行"等表达
- TEMP_CONTROL：公告包含"管控""限制""审批""报备""临时管制"等表达，但不等于全面禁飞
- REGISTRATION_NOTICE：公告关于实名登记、备案要求的通知
- SAFETY_REMINDER：安全提醒、飞行注意事项，不构成禁飞或管控
- NON_RELEVANT：与无人机/低慢小航空器管控无关的内容

## geo_type 选择规则
- poi_buffer：单一明确地点+半径（如"杭州奥体中心周边1000米"）
- poi_buffer_multi：多个明确地点+统一半径（如"全市各高考考点及周边500米"）
- admin：行政区范围（如"西湖区行政区域内"）
- bbox_roads：道路合围区域（如"东至XX路，西至XX路，南至XX路，北至XX路"）
- area_no_boundary：区域描述但无精确边界（如"景区全域""保护区周边"）
- fuzzy：无法可靠定位的区域描述

## 时间解析规则
- "即日起" → 结合发布时间推断开始时间
- "活动期间""考试期间" → 如果无法解析具体日期，mode 设为 "unknown"
- "另行通知" → 不自动设结束时间
- "每年X月X日至X月X日" → mode 设为 "recurring_seasonal"
- 长期有效且无明确结束时间 → mode 设为 "long_term"
- 所有时间统一使用 Asia/Shanghai 时区，输出 ISO 8601 格式

## 置信度判断
- parse_confidence：综合评估所有字段的抽取质量，0.0~1.0
  - ≥0.85：所有关键字段（时间、地点、管控类型）有明确原文证据
  - 0.7~0.85：大部分字段有证据，但部分字段需要推断
  - <0.7：多个关键字段缺失或模糊
- needs_review：以下任一情况为 true
  - 时间表达模糊（"即日起""活动期间"等）
  - 地理边界模糊（复杂道路合围、无明确半径）
  - 来源为非政府/公安渠道
  - parse_confidence < 0.8
  - 任何关键字段为 null"""

USER_PROMPT_TEMPLATE = """请从以下低空管控相关公告正文中提取结构化信息。

## 来源信息
- 来源名称：{source_name}
- 来源URL：{source_url}
- 来源等级：{source_level}
- 发布时间（如有）：{publish_time}
- 城市（如有）：{city}

## 公告正文
{body_text}

请严格按照 JSON Schema 输出结构化结果。"""

# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────


@dataclass
class ExtractionResult:
    """LLM 抽取的结构化结果，与 announcements_seed.json 字段对齐。"""
    # --- 分类 ---
    is_relevant: bool
    classification_result: str  # TEMP_NO_FLY | TEMP_CONTROL | REGISTRATION_NOTICE | SAFETY_REMINDER | NON_RELEVANT
    classification_reason: str

    # --- 公告元信息 ---
    title: str | None
    publish_unit: str | None
    control_type: str | None
    risk_class: str | None  # no_fly | control | advisory
    aircraft_types: list[str]

    # --- 时间 ---
    time: dict  # {mode, start, end, windows, note}

    # --- 区域 ---
    area_text: str | None
    geo: dict  # {geo_type, city, poi, poi_list, radius_m, district, roads, note, roster_status}

    # --- 证据 ---
    evidence: dict  # {title_evidence, publish_unit_evidence, time_evidence, area_evidence, control_type_evidence}

    # --- 质量 ---
    parse_confidence: float
    needs_review: bool
    review_reason: str | None

    # --- 来源透传 ---
    source_name: str = ""
    source_url: str = ""
    source_level: str = ""
    publish_time: str = ""
    city: str = ""

    # --- 原始数据 ---
    raw_body_text: str = ""
    raw_llm_response: dict = field(default_factory=dict)

    def to_announcement_dict(self, ann_id: str) -> dict:
        """转换为与 announcements_seed.json 兼容的格式，可直接进入 __main__.build()。"""
        ann = {
            "id": ann_id,
            "title": self.title or "",
            "publish_unit": self.publish_unit or "",
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_level": self.source_level,
            "publish_time": self.publish_time,
            "city": self.city,
            "control_type": self.control_type or "",
            "risk_class": self.risk_class or "control",
            "aircraft_types": self.aircraft_types or [],
            "time": self.time,
            "area_text": self.area_text or "",
            "geo": self.geo,
            "evidence_text": self._build_evidence_text(),
            "confidence_score": self.parse_confidence,
            # 抽取特有字段
            "classification_result": self.classification_result,
            "classification_reason": self.classification_reason,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
            "extraction_method": "llm",
        }
        return ann

    def _build_evidence_text(self) -> str:
        """拼接所有证据字段为一个可读的证据文本。"""
        parts = []
        ev = self.evidence or {}
        for key, label in [
            ("time_evidence", "时间"),
            ("area_evidence", "区域"),
            ("control_type_evidence", "管控类型"),
        ]:
            if ev.get(key):
                parts.append(f"【{label}】{ev[key]}")
        return "；".join(parts) if parts else ""


# ──────────────────────────────────────────────
# LLM 调用层（支持 OpenAI 兼容 API）
# ──────────────────────────────────────────────


class LLMClient:
    """OpenAI 兼容的 LLM 客户端。支持任意 OpenAI-compatible API（如 DeepSeek、Qwen、本地 vLLM 等）。"""

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int = 120,
    ):
        self.api_base = api_base or os.environ.get("LLM_API_BASE", "https://api.deepseek.com/v1")
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "deepseek-chat")
        self.timeout = timeout

        if not self.api_key:
            raise RuntimeError("缺少 LLM API Key：请设置环境变量 LLM_API_KEY")

    def chat(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = 4096) -> str:
        """发送一次 chat completion 请求，返回模型响应文本。"""
        url = f"{self.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ──────────────────────────────────────────────
# 抽取入口
# ──────────────────────────────────────────────


def extract_from_text(
    body_text: str,
    source_name: str = "",
    source_url: str = "",
    source_level: str = "",
    publish_time: str = "",
    city: str = "",
    client: LLMClient | None = None,
) -> ExtractionResult:
    """从原始公告正文中抽取结构化字段。

    Args:
        body_text: 公告正文全文
        source_name: 来源名称（如"杭州市某区政府网站"）
        source_url: 来源URL
        source_level: 来源等级（P0/P1/P2/P3）
        publish_time: 已知发布时间（如有）
        city: 已知城市（如有）
        client: LLM 客户端，不传则使用默认配置

    Returns:
        ExtractionResult: 结构化抽取结果
    """
    if client is None:
        client = LLMClient()

    user_prompt = USER_PROMPT_TEMPLATE.format(
        source_name=source_name or "未知来源",
        source_url=source_url or "无",
        source_level=source_level or "未知",
        publish_time=publish_time or "未知",
        city=city or "未知",
        body_text=body_text,
    )

    try:
        raw_response = client.chat(SYSTEM_PROMPT, user_prompt)
        parsed = _parse_llm_response(raw_response)
    except Exception as exc:
        logger.error(f"LLM 抽取失败：{exc}")
        return _fallback_result(body_text, source_name, source_url, source_level, publish_time, city, str(exc))

    return ExtractionResult(
        is_relevant=parsed.get("is_relevant", False),
        classification_result=parsed.get("classification_result", "NON_RELEVANT"),
        classification_reason=parsed.get("classification_reason", ""),
        title=parsed.get("title"),
        publish_unit=parsed.get("publish_unit"),
        control_type=parsed.get("control_type"),
        risk_class=parsed.get("risk_class"),
        aircraft_types=parsed.get("aircraft_types") or [],
        time=parsed.get("time") or {"mode": "unknown", "start": None, "end": None, "windows": None, "note": None},
        area_text=parsed.get("area_text"),
        geo=parsed.get("geo") or {"geo_type": "fuzzy", "city": city, "note": "LLM未解析地理信息"},
        evidence=parsed.get("evidence") or {},
        parse_confidence=float(parsed.get("parse_confidence", 0.0)),
        needs_review=bool(parsed.get("needs_review", True)),
        review_reason=parsed.get("review_reason"),
        source_name=source_name,
        source_url=source_url,
        source_level=source_level,
        publish_time=publish_time,
        city=city,
        raw_body_text=body_text,
        raw_llm_response=parsed,
    )


def extract_from_dict(meta: dict, body_text: str, client: LLMClient | None = None) -> ExtractionResult:
    """从来源元数据 dict + 公告正文中抽取。

    meta 字段：
        - source_name, source_url, source_level, publish_time, city
    """
    return extract_from_text(
        body_text=body_text,
        source_name=meta.get("source_name", ""),
        source_url=meta.get("source_url", ""),
        source_level=meta.get("source_level", ""),
        publish_time=meta.get("publish_time", ""),
        city=meta.get("city", ""),
        client=client,
    )


# ──────────────────────────────────────────────
# 内部工具函数
# ──────────────────────────────────────────────


def _parse_llm_response(raw: str) -> dict:
    """从 LLM 原始响应中提取 JSON。处理 markdown code block 包裹等常见格式。"""
    text = raw.strip()

    # 去除 markdown code block 包裹
    if text.startswith("```"):
        # 找到第一个换行后的内容
        lines = text.split("\n")
        # 去掉开头的 ```json 或 ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        # 去掉结尾的 ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试提取第一个 JSON 对象
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.warning(f"无法解析 LLM 响应为 JSON，原始响应前200字符：{raw[:200]}")
        return {"is_relevant": False, "classification_result": "NON_RELEVANT",
                "classification_reason": "LLM响应解析失败", "parse_confidence": 0.0,
                "needs_review": True, "review_reason": "LLM响应非有效JSON"}


def _fallback_result(
    body_text: str, source_name: str, source_url: str, source_level: str,
    publish_time: str, city: str, error: str,
) -> ExtractionResult:
    """LLM 调用失败时的降级结果。"""
    return ExtractionResult(
        is_relevant=False,
        classification_result="NON_RELEVANT",
        classification_reason=f"LLM调用失败：{error}",
        title=None,
        publish_unit=None,
        control_type=None,
        risk_class=None,
        aircraft_types=[],
        time={"mode": "unknown", "start": None, "end": None, "windows": None, "note": None},
        area_text=None,
        geo={"geo_type": "fuzzy", "city": city, "note": f"LLM抽取失败：{error}"},
        evidence={},
        parse_confidence=0.0,
        needs_review=True,
        review_reason=f"LLM抽取异常：{error}",
        source_name=source_name,
        source_url=source_url,
        source_level=source_level,
        publish_time=publish_time,
        city=city,
        raw_body_text=body_text,
    )
