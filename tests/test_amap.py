"""geo_radar.amap 单元测试 — 高德 Web 服务客户端（mock requests）。"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geo_radar.amap import AmapClient, AmapError, GeoPoint, BASE


# ─── Fixture helpers ────────────────────────────────────────

def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = lambda: None
    return resp


def _make_client(key="test-key", delay=0):
    return AmapClient(key=key, delay=delay)


# ─── Tests ──────────────────────────────────────────────────


class TestAmapClientInit:
    """AmapClient.__init__()"""

    def test_explicit_key(self):
        client = AmapClient(key="my-key")
        assert client.key == "my-key"

    @patch("geo_radar.amap.os.environ", {"AMAP_KEY": "env-key"})
    def test_env_key(self):
        client = AmapClient()
        assert client.key == "env-key"

    @patch("geo_radar.amap.os.environ", {})
    def test_missing_key_raises(self):
        try:
            AmapClient()
            assert False, "Expected AmapError"
        except AmapError as e:
            assert "缺少高德 Key" in str(e)

    def test_default_delay_timeout(self):
        client = AmapClient(key="k")
        assert client.delay == 0.15
        assert client.timeout == 10


class TestAmapClientGet:
    """AmapClient._get() — HTTP 请求核心"""

    def test_successful_response(self):
        client = _make_client()
        with patch("geo_radar.amap.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"status": "1", "info": "OK"})
            result = client._get("geocode/geo", {"address": "test"})
            assert result["status"] == "1"

    def test_status_not_1_raises(self):
        client = _make_client()
        with patch("geo_radar.amap.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"status": "0", "info": "INVALID_KEY"})
            try:
                client._get("test", {})
                assert False
            except AmapError as e:
                assert "异常" in str(e)

    def test_calls_base_url(self):
        client = _make_client()
        with patch("geo_radar.amap.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"status": "1"})
            client._get("geocode/geo", {"address": "青岛"})
            args = mock_get.call_args
            assert BASE in args[0][0]
            assert args[1]["params"]["key"] == "test-key"


class TestGeoPoint:
    """GeoPoint 数据类"""

    def test_constructor(self):
        pt = GeoPoint(120.1, 36.1, "青岛", "poi")
        assert pt.lng == 120.1
        assert pt.lat == 36.1
        assert pt.name == "青岛"
        assert pt.method == "poi"

    def test_defaults(self):
        pt = GeoPoint(120.0, 36.0)
        assert pt.name == ""
        assert pt.method == ""


class TestGeocode:
    """AmapClient.geocode()"""

    def test_success(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1", "geocodes": [{
                "location": "120.396,36.067",
                "formatted_address": "山东省青岛市市南区"
            }]}
            result = client.geocode("青岛市市南区")
            assert result is not None
            assert result.lng == 120.396
            assert result.lat == 36.067
            assert result.method == "geocode"

    def test_no_results(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1", "geocodes": []}
            result = client.geocode("不存在的地方xyz")
            assert result is None

    def test_no_geocodes_key(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1"}
            result = client.geocode("test")
            assert result is None

    def test_no_location(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1", "geocodes": [{}]}
            result = client.geocode("test")
            assert result is None

    def test_with_city(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1", "geocodes": [{"location": "120.1,36.1"}]}
            client.geocode("市政府", city="青岛")
            assert mock_get.call_args[0][1]["city"] == "青岛"


class TestSearchPoi:
    """AmapClient.search_poi()"""

    def test_success(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1", "pois": [{
                "location": "120.45,36.17",
                "name": "青岛流亭机场"
            }]}
            result = client.search_poi("青岛流亭机场")
            assert result is not None
            assert result.lng == 120.45
            assert result.lat == 36.17
            assert result.name == "青岛流亭机场"
            assert result.method == "poi"

    def test_no_results(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1", "pois": []}
            result = client.search_poi("不存在")
            assert result is None

    def test_no_location_field(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1", "pois": [{"name": "test"}]}
            result = client.search_poi("test")
            assert result is None


class TestLocate:
    """AmapClient.locate() — POI 优先，退回 geocode"""

    def test_poi_returns_first(self):
        client = _make_client()
        with patch.object(client, "search_poi") as mock_poi:
            mock_poi.return_value = GeoPoint(120.0, 36.0, "test", "poi")
            result = client.locate("test", "青岛")
            assert result is not None
            assert result.method == "poi"
            mock_poi.assert_called_once()

    def test_fallback_to_geocode(self):
        client = _make_client()
        with patch.object(client, "search_poi") as mock_poi:
            with patch.object(client, "geocode") as mock_geo:
                mock_poi.return_value = None
                mock_geo.return_value = GeoPoint(120.0, 36.0, "test", "geocode")
                result = client.locate("test", "青岛")
                assert result is not None
                assert result.method == "geocode"

    def test_both_fail(self):
        client = _make_client()
        with patch.object(client, "search_poi") as mock_poi:
            with patch.object(client, "geocode") as mock_geo:
                mock_poi.return_value = None
                mock_geo.return_value = None
                result = client.locate("test", "青岛")
                assert result is None


class TestDistrictRings:
    """AmapClient.district_rings()"""

    def test_exact_match(self):
        client = _make_client()
        polyline = "120.0,36.0;120.1,36.0;120.1,36.1;120.0,36.1"
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {
                "status": "1",
                "districts": [
                    {"adcode": "100000", "name": "中国"},
                    {"adcode": "370200", "name": "青岛市", "polyline": polyline, "center": "120.38,36.07"},
                ]
            }
            result = client.district_rings("青岛市")
            assert result is not None
            rings, center = result
            assert len(rings) == 1
            assert center.name == "青岛市"
            assert center.lng == 120.38

    def test_no_districts(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1", "districts": []}
            result = client.district_rings("不存在")
            assert result is None

    def test_only_national(self):
        """只有全国结果时返回 None"""
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {
                "status": "1",
                "districts": [{"adcode": "100000", "name": "中国"}]
            }
            result = client.district_rings("anything")
            assert result is None

    def test_no_polyline(self):
        """结果有但无 polyline"""
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {
                "status": "1",
                "districts": [{"adcode": "370200", "name": "青岛市"}]
            }
            result = client.district_rings("青岛市")
            assert result is None

    def test_fuzzy_name_match(self):
        """名称包含匹配"""
        client = _make_client()
        polyline = "120.0,36.0;120.1,36.0;120.1,36.1"
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {
                "status": "1",
                "districts": [
                    {"adcode": "100000", "name": "中国"},
                    {"adcode": "370200", "name": "青岛", "polyline": polyline, "center": "120.0,36.0"},
                ]
            }
            result = client.district_rings("青岛市辖区")
            assert result is not None
            assert result[1].name == "青岛"


class TestRegeo:
    """AmapClient.regeo() — 逆地理编码"""

    def test_full_result(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {
                "status": "1",
                "regeocode": {
                    "addressComponent": {
                        "province": "山东省",
                        "city": "青岛市",
                        "district": "市南区",
                        "adcode": "370202",
                    },
                    "formatted_address": "山东省青岛市市南区香港中路"
                }
            }
            result = client.regeo(120.396, 36.067)
            assert result is not None
            assert result["province"] == "山东"
            assert result["city"] == "青岛"
            assert result["district"] == "市南"

    def test_municipality(self):
        """直辖市：city 与 province 相同 → city 用 province"""
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {
                "status": "1",
                "regeocode": {
                    "addressComponent": {
                        "province": "北京市",
                        "city": [],
                        "district": "朝阳区",
                        "adcode": "110105",
                    },
                    "formatted_address": "北京市朝阳区"
                }
            }
            result = client.regeo(116.397, 39.908)
            assert result is not None
            assert result["city"] == "北京"
            assert result["province"] == "北京"

    def test_no_regeocode(self):
        client = _make_client()
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {"status": "1"}
            result = client.regeo(120.0, 36.0)
            assert result is None


class TestAmapError:
    """AmapError 异常类"""

    def test_raise_and_catch(self):
        try:
            raise AmapError("test error")
        except AmapError as e:
            assert str(e) == "test error"

    def test_is_runtime_error(self):
        assert issubclass(AmapError, RuntimeError)
