"""验证所有地图页面 API 端点是否正常工作。"""
import urllib.request
import json


def get(path, params=None):
    url = "http://127.0.0.1:8010/api/v1" + path
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except Exception as e:
        return 0, str(e)


def post(path, body):
    url = "http://127.0.0.1:8010/api/v1" + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except Exception as e:
        return 0, str(e)


passed = 0
failed = 0

def check(name, status, result, assertions):
    global passed, failed
    ok = True
    for key, expected in assertions.items():
        actual = result.get(key) if isinstance(result, dict) else None
        if isinstance(expected, type):
            if not isinstance(actual, expected):
                ok = False
                print(f"  FAIL: {key} expected type {expected.__name__}, got {type(actual).__name__}")
        elif actual != expected:
            ok = False
            print(f"  FAIL: {key} expected {expected!r}, got {actual!r}")
    if ok:
        passed += 1
        print(f"  PASS")
    else:
        failed += 1
    return ok


# 1. Map Layers
print("1. GET /map/layers (no filter)")
s, d = get("/map/layers", {"selected_time": "2026-06-09T12:00:00"})
check("1", s, d, {"features": list, "summary": dict})

# 2. Map Layers with city filter
print("2. GET /map/layers?city=威海")
s, d = get("/map/layers", {"selected_time": "2026-06-09T12:00:00", "city": "威海"})
check("2", s, d, {"features": list, "summary": dict})

# 3. Map Layers with bounds
print("3. GET /map/layers?bounds=...")
s, d = get("/map/layers", {"selected_time": "2026-06-09T12:00:00", "bounds": "120,36,122,38"})
check("3", s, d, {"features": list, "summary": dict})

# 4. Announcement Detail
print("4. GET /announcements/weihai_gaokao_2026")
s, d = get("/announcements/weihai_gaokao_2026")
check("4", s, d, {"title": str, "id": str})

# 5. Place Search - POI
print("5. GET /place/search?keywords=五四广场")
s, d = get("/place/search", {"keywords": "五四广场", "city": "青岛"})
has_pois = len(d.get("pois", [])) > 0 if isinstance(d, dict) else False
print(f"  pois={len(d.get('pois', [])) if isinstance(d, dict) else 'ERR'}, district={'YES' if (isinstance(d, dict) and d.get('district')) else 'NO'}")
check("5", s, d, {"status": "1", "pois": list})

# 6. Place Search - Geocode fallback
print("6. GET /place/search?keywords=市南区")
s, d = get("/place/search", {"keywords": "市南区", "city": "青岛"})
print(f"  pois={len(d.get('pois', [])) if isinstance(d, dict) else 'ERR'}, district={'YES' if (isinstance(d, dict) and d.get('district')) else 'NO'}")
check("6", s, d, {"status": "1", "pois": list})

# 7. Stats Overview
print("7. GET /stats/overview")
s, d = get("/stats/overview")
check("7", s, d, {})

# 8. 404 handling
print("8. GET /announcements/nonexistent (404)")
s, d = get("/announcements/nonexistent")
check("10", s, d, {})

print()
print(f"Results: {passed} passed, {failed} failed")
