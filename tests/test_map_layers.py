from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from web.api import store
from web.api.main import app


class MapLayersTest(TestCase):
    def setUp(self) -> None:
        self._original_db_path = store.DB_PATH
        self._test_db_path = Path(__file__).resolve().parents[1] / "data" / "_test_map_layers.sqlite"
        self._remove_test_db_files()
        store.DB_PATH = self._test_db_path
        store.init_db()

    def tearDown(self) -> None:
        store.DB_PATH = self._original_db_path
        self._remove_test_db_files()

    def _remove_test_db_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self._test_db_path) + suffix)
            if path.exists():
                path.unlink()

    def test_map_layers_accepts_browser_iso_time(self) -> None:
        store.create_announcement({
            "id": "test_active_layer",
            "source_task_id": "task_test_active_layer",
            "title": "测试临时管控公告",
            "source_name": "测试来源",
            "province": "山东省",
            "city": "威海市",
            "control_type": "临时管控",
            "start_time": "2026-06-09T06:00:00",
            "end_time": "2026-06-10T18:00:00",
            "time_mode": "single",
            "geo_json": {"type": "Point", "coordinates": [122.12, 37.51]},
            "geo_confidence": 0.8,
            "geo_grade": "B",
            "needs_review": False,
            "map_layer_status": "published",
        })

        client = TestClient(app)
        resp = client.get(
            "/api/v1/map/layers",
            params={
                "selected_time": "2026-06-09T04:00:00.000Z",
                "include_expired": "false",
                "include_review": "true",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["summary"]["active_count"], 1)
        self.assertEqual(
            [f["announcement_id"] for f in data["features"]],
            ["test_active_layer"],
        )
