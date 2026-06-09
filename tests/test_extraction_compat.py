"""验证 extraction_agent.ExtractionResult.to_announcement_dict() 格式与现有管线兼容。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geo_radar.extraction_agent import ExtractionResult


def test_to_announcement_dict_compat():
    """模拟 LLM 返回的抽取结果，验证 to_announcement_dict() 输出格式。"""
    result = ExtractionResult(
        is_relevant=True,
        classification_result="TEMP_CONTROL",
        classification_reason="公告明确包含管控、严禁飞行等表达",
        title="关于高考期间对无人机等低慢小航空器实施临时管控的通告",
        publish_unit="威海市公安局",
        control_type="临时管控",
        risk_class="control",
        aircraft_types=["无人机", "航空模型", "滑翔伞", "动力伞", "热气球", "飞艇", "空飘气球", "孔明灯"],
        time={"mode": "single", "start": "2026-06-07T06:00:00", "end": "2026-06-10T18:00:00", "windows": None, "note": None},
        area_text="全市各高考考点及周边500米范围内",
        geo={
            "geo_type": "poi_buffer_multi",
            "city": "威海",
            "poi": None,
            "poi_list": ["威海市第一中学", "威海市第二中学", "威海市实验高级中学"],
            "radius_m": 500,
            "district": None,
            "roads": [],
            "note": "考点名单为候选，需招考院核验",
            "roster_status": "candidate_needs_verification",
        },
        evidence={
            "time_evidence": "管控时段：2026年6月7日6时至6月10日18时",
            "area_evidence": "管控区域：全市各高考考点及周边500米范围内",
            "control_type_evidence": "严禁任何单位和个人在管控区域内飞行",
        },
        parse_confidence=0.92,
        needs_review=True,
        review_reason="考点名单未在通告中明确列出，需招考院/教育局名单核验",
        source_name="威海市人民政府网",
        source_url="https://www.weihai.gov.cn/",
        source_level="P0",
        publish_time="2026-06-03",
        city="威海市",
    )

    ann = result.to_announcement_dict("test_weihai")
    print("=== to_announcement_dict 输出 ===")
    print(json.dumps(ann, ensure_ascii=False, indent=2))

    # 验证关键字段
    required_keys = [
        "id", "title", "publish_unit", "source_name", "source_url", "source_level",
        "publish_time", "city", "control_type", "risk_class", "aircraft_types",
        "time", "area_text", "geo", "evidence_text", "confidence_score",
    ]
    missing = [k for k in required_keys if k not in ann]
    assert not missing, f"缺少字段: {missing}"
    print(f"\nOK: 所有 {len(required_keys)} 个必要字段存在")

    # 验证 geo 子字段
    geo_required = ["geo_type", "city"]
    geo_missing = [k for k in geo_required if k not in ann["geo"]]
    assert not geo_missing, f"geo 缺少字段: {geo_missing}"
    print("OK: geo 字段兼容")

    # 验证 time 子字段
    assert "mode" in ann["time"], "time 缺少 mode"
    print("OK: time 字段兼容")

    # 验证证据文本生成
    assert ann["evidence_text"], "evidence_text 不应为空"
    print(f"evidence_text: {ann['evidence_text']}")

    # 验证 extraction_method 标记
    assert ann.get("extraction_method") == "llm", "缺少 extraction_method 标记"
    print("OK: extraction_method=llm 标记正确")

    print("\n=== 兼容性验证通过 ===")


def test_fallback_result():
    """验证 LLM 调用失败时的降级结果格式。"""
    from geo_radar.extraction_agent import _fallback_result

    result = _fallback_result(
        body_text="测试正文",
        source_name="测试来源",
        source_url="http://example.com",
        source_level="P0",
        publish_time="2026-06-01",
        city="测试市",
        error="模拟网络超时",
    )
    ann = result.to_announcement_dict("test_fallback")
    assert result.is_relevant is False
    assert ann["needs_review"] is True
    assert ann["confidence_score"] == 0.0
    assert ann["classification_result"] == "NON_RELEVANT"
    assert "模拟网络超时" in ann["review_reason"]
    print("OK: 降级结果格式正确")


def test_json_parse():
    """验证 LLM 响应 JSON 解析鲁棒性。"""
    from geo_radar.extraction_agent import _parse_llm_response

    # 正常 JSON
    r1 = _parse_llm_response('{"is_relevant": true, "title": "测试"}')
    assert r1["is_relevant"] is True
    assert r1["title"] == "测试"
    print("OK: 正常JSON解析")

    # Markdown code block 包裹
    r2 = _parse_llm_response('```json\n{"is_relevant": false}\n```')
    assert r2["is_relevant"] is False
    print("OK: Markdown包裹解析")

    # 非 JSON 降级
    r3 = _parse_llm_response("这是一段非JSON文本")
    assert r3["is_relevant"] is False
    assert r3["needs_review"] is True
    print("OK: 非JSON降级")

    # 含前后文本的 JSON
    r4 = _parse_llm_response('分析结果：\n{"is_relevant": true, "title": "测试"}\n以上为结果。')
    assert r4["is_relevant"] is True
    print("OK: 含前后文本JSON提取")


if __name__ == "__main__":
    test_to_announcement_dict_compat()
    print()
    test_fallback_result()
    print()
    test_json_parse()
    print()
    print("=== 全部测试通过 ===")
