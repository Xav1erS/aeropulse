"""web/api/ingestion.py 辅助函数单元测试。"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 仅 mock store 避免 SQLite 初始化
mock_store = MagicMock()
mock_store.get_announcement_by_task.return_value = None
sys.modules["web.api.store"] = mock_store

from web.api.ingestion import (
    _build_extracted_fields,
    _build_temporal,
    _build_geo,
    _evidence_counts,
    _evidence_items,
    _time_parse_status,
    _geo_parse_status,
    _map_layer_status,
    _publication_gate,
    _enrich_task_quality,
)


class TestBuildExtractedFields:
    """_build_extracted_fields(extracted)"""

    def test_basic_fields(self):
        extracted = {
            "title": "公告标题",
            "publish_unit": "公安局",
            "control_type": "临时管控",
            "area_text": "某区域",
            "parse_confidence": 0.85,
            "time": {"start": "2026-06-01T00:00", "end": "2026-06-15T23:59"},
            "evidence": {
                "title_evidence": "原文标题",
                "time_evidence": "原文时间",
                "control_type_evidence": "原文管控类型",
                "area_evidence": "原文区域",
            },
        }
        fields = _build_extracted_fields(extracted)
        assert fields["title"]["value"] == "公告标题"
        assert fields["title"]["confidence"] == 0.85
        assert fields["title"]["evidence"] == "原文标题"
        assert fields["area_text"]["value"] == "某区域"

    def test_empty_extracted(self):
        fields = _build_extracted_fields({})
        assert fields["title"]["value"] is None
        assert fields["title"]["confidence"] == 0


class TestBuildTemporal:
    """_build_temporal(extracted)"""

    def test_with_time(self):
        extracted = {
            "time": {"mode": "single", "note": "节假日管控"},
        }
        result = _build_temporal(extracted)
        assert result["time_mode"] == "single"
        assert result["validity_basis"] == "节假日管控"

    def test_empty(self):
        result = _build_temporal({})
        assert result["time_mode"] == "unknown"


class TestBuildGeo:
    """_build_geo(extracted)"""

    def test_with_poi(self):
        extracted = {
            "geo": {"geo_type": "poi_buffer", "poi": "五四广场", "radius_m": 500},
            "parse_confidence": 0.8,
        }
        result = _build_geo(extracted)
        assert result["geo_type"] == "poi_buffer"
        assert result["center_poi"] == "五四广场"
        assert result["radius_meters"] == 500

    def test_fallback_to_poi_list_first(self):
        extracted = {
            "geo": {"poi_list": ["考点A", "考点B"]},
            "parse_confidence": 0.7,
        }
        result = _build_geo(extracted)
        assert result["center_poi"] == "考点A"


class TestEvidenceCounts:
    """_evidence_counts(extracted)"""

    def test_complete(self):
        extracted = {
            "evidence": {
                "title_evidence": "t",
                "time_evidence": "t",
                "area_evidence": "t",
                "control_type_evidence": "t",
            }
        }
        result = _evidence_counts(extracted)
        assert result["status"] == "complete"
        assert result["bound"] == 4

    def test_partial(self):
        extracted = {"evidence": {"title_evidence": "t"}}
        result = _evidence_counts(extracted)
        assert result["status"] == "partial"
        assert result["bound"] == 1

    def test_missing(self):
        extracted = {"evidence": {}}
        result = _evidence_counts(extracted)
        assert result["status"] == "missing"
        assert result["bound"] == 0

    def test_evidence_text_fallback(self):
        """evidence_text 有内容但没有细项时计 1"""
        extracted = {
            "evidence": {},
            "evidence_text": "long evidence text...",
        }
        result = _evidence_counts(extracted)
        assert result["bound"] == 1
        assert result["status"] == "partial"


class TestEvidenceItems:
    """_evidence_items(extracted)"""

    def test_all_items(self):
        extracted = {
            "evidence": {
                "title_evidence": "标题原文",
                "publish_unit_evidence": "单位原文",
                "time_evidence": "时间原文",
                "area_evidence": "区域原文",
                "control_type_evidence": "类型原文",
            },
        }
        items = _evidence_items(extracted)
        assert len(items) == 5
        assert items[0]["label"] == "标题"
        assert items[0]["text"] == "标题原文"

    def test_empty(self):
        items = _evidence_items({})
        assert all(item["text"] == "" for item in items)


class TestTimeParseStatus:
    """_time_parse_status(extracted)"""

    def test_long_term(self):
        assert _time_parse_status({"time": {"mode": "long_term"}}) == "success"

    def test_recurring_seasonal(self):
        assert _time_parse_status({"time": {"mode": "recurring_seasonal"}}) == "success"

    def test_single_success(self):
        assert _time_parse_status({"time": {"mode": "single", "start": "t", "end": "t"}}) == "success"

    def test_single_conflict(self):
        assert _time_parse_status({"time": {"mode": "single", "start": "t"}}) == "conflict"

    def test_missing(self):
        assert _time_parse_status({"time": {"mode": "single"}}) == "missing"
        assert _time_parse_status({}) == "missing"


class TestGeoParseStatus:
    """_geo_parse_status(task, extracted)"""

    def test_has_geo_json(self):
        assert _geo_parse_status({"geo_json": {"type": "Polygon"}}, {}) == "success"

    def test_needs_review(self):
        assert _geo_parse_status({}, {"geo": {"geo_type": "area_no_boundary"}}) == "needs_review"
        assert _geo_parse_status({}, {"geo": {"geo_type": "bbox_roads"}}) == "needs_review"
        assert _geo_parse_status({"review_reason": "test"}, {}) == "needs_review"

    def test_has_confidence(self):
        assert _geo_parse_status({"geo_confidence": 0.5}, {}) == "preview"

    def test_missing(self):
        assert _geo_parse_status({}, {}) == "missing"


class TestMapLayerStatus:
    """_map_layer_status(task)"""

    def test_generated(self):
        assert _map_layer_status({"map_preview_status": "generated"}) == "unpublished"

    def test_generating(self):
        assert _map_layer_status({"map_preview_status": "generating"}) == "previewing"

    def test_not_generated(self):
        assert _map_layer_status({}) == "not_generated"


class TestPublicationGate:
    """_publication_gate(task, extracted)"""

    def test_all_passing(self):
        extracted = {
            "evidence": {
                "title_evidence": "t", "time_evidence": "t",
                "area_evidence": "t", "control_type_evidence": "t",
            },
            "time": {"mode": "single", "start": "t", "end": "t"},
        }
        task = {
            "source_name": "公安局", "source_url": "http://example.com",
            "geo_json": {}, "map_preview_status": "generated",
            "is_relevant": True,
        }
        gate = _publication_gate(task, extracted)
        assert gate["can_publish"] is True
        assert len(gate["blockers"]) == 0

    def test_missing_source(self):
        gate = _publication_gate(
            {"source_name": "", "source_url": ""},
            {"evidence": {"title_evidence": "t", "time_evidence": "t", "area_evidence": "t", "control_type_evidence": "t"}},
        )
        assert gate["can_publish"] is False
        assert any("来源" in b for b in gate["blockers"])

    def test_incomplete_evidence(self):
        gate = _publication_gate(
            {"source_name": "x", "source_url": "http://x"},
            {"evidence": {"title_evidence": "t"}},
        )
        assert gate["can_publish"] is False
        assert any("证据" in b for b in gate["blockers"])

    def test_time_parse_failed(self):
        extracted = {
            "evidence": {"title_evidence": "t", "time_evidence": "t", "area_evidence": "t", "control_type_evidence": "t"},
            "time": {},
        }
        task = {"source_name": "x", "source_url": "http://x"}
        gate = _publication_gate(task, extracted)
        assert gate["can_publish"] is False
        assert any("时间" in b for b in gate["blockers"])

    def test_not_relevant(self):
        extracted = {
            "evidence": {"title_evidence": "t", "time_evidence": "t", "area_evidence": "t", "control_type_evidence": "t"},
            "time": {"mode": "single", "start": "t", "end": "t"},
        }
        task = {
            "source_name": "x", "source_url": "http://x",
            "geo_json": {}, "is_relevant": False,
        }
        gate = _publication_gate(task, extracted)
        assert gate["can_publish"] is False
        assert any("无关" in b for b in gate["blockers"])

    def test_no_geo_preview(self):
        extracted = {
            "evidence": {"title_evidence": "t", "time_evidence": "t", "area_evidence": "t", "control_type_evidence": "t"},
            "time": {"mode": "single", "start": "t", "end": "t"},
        }
        task = {"source_name": "x", "source_url": "http://x"}
        gate = _publication_gate(task, extracted)
        assert gate["can_publish"] is False
        assert any("地理" in b for b in gate["blockers"])


class TestEnrichTaskQuality:
    """_enrich_task_quality(item, task, extracted)"""

    def test_basic_enrichment(self):
        item = {}
        task = {
            "id": "T1",
            "extracted_json": {
                "title": "test",
                "evidence": {
                    "title_evidence": "t", "area_evidence": "t",
                },
                "time": {"mode": "single", "start": "t", "end": "t"},
            },
            "geo_confidence": 0.5,
        }
        _enrich_task_quality(item, task=task)
        assert "time_parse_status" in item
        assert "geo_parse_status" in item
        assert "evidence_status" in item
        assert item["evidence_status"] in ("partial", "complete")

    def test_extracted_json_string(self):
        """extracted_json 是 JSON 字符串时需正确解析"""
        import json
        item = {}
        task = {
            "id": "T2",
            "extracted_json": json.dumps({
                "title": "test",
                "evidence": {
                    "title_evidence": "t", "time_evidence": "t",
                    "area_evidence": "t", "control_type_evidence": "t",
                },
                "time": {"mode": "long_term"},
            }),
            "map_preview_status": "generated",
        }
        _enrich_task_quality(item, task=task)
        assert item["evidence_status"] == "complete"
        assert item["time_parse_status"] == "success"
        assert item["map_layer_status"] == "unpublished"
