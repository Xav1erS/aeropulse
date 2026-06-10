"""web/api/announcements.py 单元测试 — 公告库管理 API（mock store）。"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 仅 mock store 避免 SQLite 初始化
mock_store = MagicMock()
sys.modules["web.api.store"] = mock_store

from fastapi.testclient import TestClient
from fastapi import FastAPI
from web.api.announcements import router

app = FastAPI()
app.include_router(router, prefix="/api/v1")
client = TestClient(app)


class TestListAnnouncements:
    """GET /api/v1/announcements"""

    def test_basic_list(self):
        mock_store.get_announcements_with_ann_status.return_value = (
            [{"id": "ann-1", "title": "测试公告", "ann_status": "pending"}],
            1,
        )
        resp = client.get("/api/v1/announcements")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["ann_status"] == "pending"

    def test_with_filters(self):
        mock_store.get_announcements_with_ann_status.return_value = ([], 0)
        resp = client.get(
            "/api/v1/announcements?ann_status=confirmed&control_type=临时禁飞&city=青岛"
        )
        assert resp.status_code == 200
        mock_store.get_announcements_with_ann_status.assert_called_with(
            ann_status="confirmed",
            control_type="临时禁飞",
            province=None,
            city="青岛",
            limit=100,
            offset=0,
        )

    def test_empty_list(self):
        mock_store.get_announcements_with_ann_status.return_value = ([], 0)
        resp = client.get("/api/v1/announcements")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}


class TestGetAnnouncementDetail:
    """GET /api/v1/announcements/{ann_id}"""

    def test_found_with_layers_and_task(self):
        mock_store.get_announcement.return_value = {
            "id": "A1", "title": "测试", "source_task_id": "T1",
        }
        mock_store.get_layers_by_announcement.return_value = [
            {"id": "L1", "layer_name": "layer1"},
        ]
        mock_store.get_ingestion_task.return_value = {"id": "T1", "task_status": "parsed"}

        resp = client.get("/api/v1/announcements/A1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["announcement"]["id"] == "A1"
        assert len(data["layers"]) == 1
        assert data["source_task"]["id"] == "T1"

    def test_not_found(self):
        mock_store.get_announcement.return_value = None
        resp = client.get("/api/v1/announcements/nonexistent")
        assert resp.status_code == 404

    def test_no_source_task(self):
        mock_store.get_announcement.return_value = {
            "id": "A2", "title": "test", "source_task_id": None,
        }
        mock_store.get_layers_by_announcement.return_value = []
        resp = client.get("/api/v1/announcements/A2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_task"] is None


class TestConfirmAnnouncement:
    """POST /api/v1/announcements/{ann_id}/confirm"""

    def test_confirm_pending(self):
        mock_store.get_announcement.return_value = {
            "id": "A1", "ann_status": "pending",
        }
        resp = client.post("/api/v1/announcements/A1/confirm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"

    def test_confirm_already_confirmed(self):
        mock_store.get_announcement.return_value = {
            "id": "A1", "ann_status": "confirmed",
        }
        resp = client.post("/api/v1/announcements/A1/confirm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_confirmed"

    def test_confirm_not_found(self):
        mock_store.get_announcement.return_value = None
        resp = client.post("/api/v1/announcements/nonexistent/confirm")
        assert resp.status_code == 404


class TestRejectAnnouncement:
    """POST /api/v1/announcements/{ann_id}/reject"""

    def test_reject_with_reason(self):
        mock_store.get_announcement.return_value = {"id": "A1", "ann_status": "pending"}
        resp = client.post(
            "/api/v1/announcements/A1/reject",
            json={"reason": "来源不可信"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"

    def test_reject_not_found(self):
        mock_store.get_announcement.return_value = None
        resp = client.post("/api/v1/announcements/nonexistent/reject")
        assert resp.status_code == 404


class TestGenerateLayers:
    """POST /api/v1/announcements/{ann_id}/generate-layers"""

    def test_already_has_layers(self):
        mock_store.get_announcement.return_value = {"id": "A1", "title": "test"}
        mock_store.get_layers_by_announcement.return_value = [
            {"id": "L1"}, {"id": "L2"},
        ]
        resp = client.post("/api/v1/announcements/A1/generate-layers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_exists"

    def test_with_geo_json(self):
        geom = {"type": "Polygon", "coordinates": [[[1, 2]]]}
        mock_store.get_announcement.return_value = {
            "id": "A1", "title": "test", "geo_json": geom,
            "geo_type": "poi_buffer", "geo_confidence": 0.8, "geo_grade": "A",
            "start_time": "2026-06-01T00:00", "end_time": "2026-06-15T00:00",
        }
        mock_store.get_layers_by_announcement.return_value = []
        mock_store.create_layer.return_value = {"id": "L-new"}

        resp = client.post("/api/v1/announcements/A1/generate-layers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generated"
        assert len(data["layer_ids"]) == 1

    def test_with_poi_list(self):
        mock_store.get_announcement.return_value = {
            "id": "A1", "title": "test", "poi_list": ["考点A", "考点B"],
            "radius_meters": 500,
            "start_time": "2026-06-01T00:00", "end_time": "2026-06-15T00:00",
        }
        mock_store.get_layers_by_announcement.return_value = []
        mock_store.create_layer.return_value = {"id": "L-new"}

        resp = client.post("/api/v1/announcements/A1/generate-layers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generated"
        assert len(data["layer_ids"]) == 2  # 2 POIs

    def test_with_district_name(self):
        mock_store.get_announcement.return_value = {
            "id": "A1", "title": "test", "district_name": "市南区",
            "start_time": "2026-06-01T00:00", "end_time": "2026-06-15T00:00",
        }
        mock_store.get_layers_by_announcement.return_value = []
        mock_store.create_layer.return_value = {"id": "L-new"}

        resp = client.post("/api/v1/announcements/A1/generate-layers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generated"

    def test_with_area_text_only(self):
        mock_store.get_announcement.return_value = {
            "id": "A1", "title": "test", "area_text": "某区域",
        }
        mock_store.get_layers_by_announcement.return_value = []
        mock_store.create_layer.return_value = {"id": "L-new"}

        resp = client.post("/api/v1/announcements/A1/generate-layers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generated"

    def test_not_found(self):
        mock_store.get_announcement.return_value = None
        resp = client.post("/api/v1/announcements/nonexistent/generate-layers")
        assert resp.status_code == 404
