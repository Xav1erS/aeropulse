"""web/api/layers.py 单元测试 — 图层管理 API（mock store）。"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 仅 mock store 模块避免 SQLite 初始化；不能 mock web / web.api 包本身
mock_store = MagicMock()
sys.modules["web.api.store"] = mock_store

from fastapi.testclient import TestClient
from fastapi import FastAPI
from web.api.layers import router

app = FastAPI()
app.include_router(router, prefix="/api/v1")
client = TestClient(app)


class TestListLayers:
    """GET /api/v1/layers"""

    def test_basic_list(self):
        mock_store.list_layers.return_value = (
            [{"id": "layer-1", "layer_name": "test layer"}],
            1,
        )
        resp = client.get("/api/v1/layers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "layer-1"

    def test_with_filters(self):
        mock_store.list_layers.return_value = ([], 0)
        resp = client.get("/api/v1/layers?layer_status=published&control_type=临时管控&city=青岛")
        assert resp.status_code == 200
        mock_store.list_layers.assert_called_with(
            layer_status="published",
            control_type="临时管控",
            geo_grade=None,
            province=None,
            city="青岛",
            limit=100,
            offset=0,
        )

    def test_limit_exceeds_max(self):
        resp = client.get("/api/v1/layers?limit=999")
        assert resp.status_code == 422  # validation error

    def test_negative_offset(self):
        resp = client.get("/api/v1/layers?offset=-1")
        assert resp.status_code == 422


class TestGetLayerDetail:
    """GET /api/v1/layers/{layer_id}"""

    def test_found(self):
        mock_store.get_layer.return_value = {"id": "L1", "announcement_id": "A1"}
        mock_store.get_announcement.return_value = {"id": "A1", "title": "test"}
        resp = client.get("/api/v1/layers/L1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["layer"]["id"] == "L1"
        assert data["announcement"]["title"] == "test"

    def test_not_found(self):
        mock_store.get_layer.return_value = None
        resp = client.get("/api/v1/layers/nonexistent")
        assert resp.status_code == 404


class TestPreviewLayer:
    """GET /api/v1/layers/{layer_id}/preview"""

    def test_with_geo_json_dict(self):
        geom = {"type": "Polygon", "coordinates": [[[1, 2]]]}
        mock_store.get_layer.return_value = {
            "id": "L1", "announcement_id": "A1", "geo_json": geom
        }
        mock_store.get_announcement.return_value = {"title": "test", "control_type": "管控"}
        resp = client.get("/api/v1/layers/L1/preview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["geo_json"] == geom

    def test_with_geo_json_string(self):
        geom = {"type": "Point", "coordinates": [120, 36]}
        mock_store.get_layer.return_value = {
            "id": "L2", "announcement_id": "A2",
            "geo_json": json.dumps(geom),
        }
        mock_store.get_announcement.return_value = {"title": "test"}
        resp = client.get("/api/v1/layers/L2/preview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["geo_json"] == geom

    def test_not_found(self):
        mock_store.get_layer.return_value = None
        resp = client.get("/api/v1/layers/nonexistent/preview")
        assert resp.status_code == 404


class TestPublishLayer:
    """POST /api/v1/layers/{layer_id}/publish"""

    def test_publish_draft(self):
        mock_store.get_layer.return_value = {
            "id": "L1", "layer_status": "draft", "announcement_id": "A1",
        }
        mock_store.update_layer.return_value = {"id": "L1", "layer_status": "published"}
        resp = client.post("/api/v1/layers/L1/publish")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "published"

    def test_publish_already_published(self):
        mock_store.get_layer.return_value = {
            "id": "L1", "layer_status": "published", "announcement_id": "A1",
        }
        resp = client.post("/api/v1/layers/L1/publish")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_published"

    def test_publish_not_found(self):
        mock_store.get_layer.return_value = None
        resp = client.post("/api/v1/layers/nonexistent/publish")
        assert resp.status_code == 404


class TestPauseLayer:
    """POST /api/v1/layers/{layer_id}/pause"""

    def test_pause_draft(self):
        mock_store.get_layer.return_value = {
            "id": "L1", "layer_status": "draft", "announcement_id": "A1",
        }
        mock_store.update_layer.return_value = {"id": "L1", "layer_status": "paused"}
        resp = client.post("/api/v1/layers/L1/pause")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        # verify announcement updated (at least once)
        assert mock_store.update_announcement.called

    def test_pause_already_paused(self):
        mock_store.get_layer.return_value = {
            "id": "L1", "layer_status": "paused", "announcement_id": "A1",
        }
        resp = client.post("/api/v1/layers/L1/pause")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_paused"


class TestArchiveLayer:
    """POST /api/v1/layers/{layer_id}/archive"""

    def test_archive(self):
        mock_store.get_layer.return_value = {
            "id": "L1", "layer_status": "published", "announcement_id": "A1",
        }
        mock_store.update_layer.return_value = {"id": "L1", "layer_status": "archived"}
        resp = client.post("/api/v1/layers/L1/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "archived"

    def test_archive_already_archived(self):
        mock_store.get_layer.return_value = {
            "id": "L1", "layer_status": "archived", "announcement_id": "A1",
        }
        resp = client.post("/api/v1/layers/L1/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_archived"
