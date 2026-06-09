"""尝试从主站获取 session cookie 再下载 KML。"""
import requests
from urllib.parse import quote

s = requests.Session()

# 1. 先访问主站获取 cookie
print("Step 1: 访问主站...")
resp = s.get('http://xianfei.u-care.net.cn/', timeout=15)
print(f"  Status: {resp.status_code}")
print(f"  Cookies: {dict(s.cookies)}")

# 2. 尝试访问 KML
name = '怀化_芷江机场'
encoded_name = quote(name)
url = f'http://mapservices.u-care.net.cn/airresource/download/airport_xzm/{encoded_name}.kml'
print(f"\nStep 2: 下载 KML...")
resp = s.get(url, timeout=15)
print(f"  Status: {resp.status_code}")
print(f"  Content-Type: {resp.headers.get('Content-Type')}")
print(f"  Size: {len(resp.content)}")
print(f"  First 500: {resp.text[:500]}")
