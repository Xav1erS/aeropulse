"""完整分析 KML 下载的认证流程。"""
import requests
from urllib.parse import quote

s = requests.Session()
s.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
})

# 1. 获取列表
print("=== 1. 获取列表 ===")
list_resp = s.post(
    'https://webapi.u-care.net.cn/web/geoQuery/getAirResourceQuery',
    json={'typeName': 'airport_xzm', 'key': '', 'pageIndex': 1, 'pageSize': 1},
    timeout=15
)
print(f"Status: {list_resp.status_code}")
print(f"Cookies: {dict(s.cookies)}")

# 2. 获取下载链接
print("\n=== 2. 获取下载链接 ===")
dl_resp = s.get(
    'https://webapi.u-care.net.cn/web/geoQuery/getAirResourceFileByName',
    params={'name': '怀化_芷江机场', 'type': 'airport_xzm'},
    timeout=15
)
print(f"Status: {dl_resp.status_code}")
print(f"Cookies: {dict(s.cookies)}")
data = dl_resp.json()
print(f"Response: {data}")

# 3. 尝试用相同 session 下载
kml_path = data.get('data', [{}])[0].get('path', '')
if kml_path:
    print(f"\n=== 3. 下载 KML ===")
    print(f"URL: {kml_path}")
    kml_resp = s.get(kml_path, timeout=15)
    print(f"Status: {kml_resp.status_code}")
    print(f"Content-Type: {kml_resp.headers.get('Content-Type')}")
    print(f"Size: {len(kml_resp.content)}")
    print(f"First 300: {kml_resp.text[:300]}")
