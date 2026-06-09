"""检查 token 机制。"""
import requests
import sys

sys.stdout.reconfigure(encoding='utf-8')

s = requests.Session()

# 1. 先调用 API 看是否设置 token
print("=== Step 1: 调用列表 API ===")
resp = s.post(
    'https://webapi.u-care.net.cn/web/geoQuery/getAirResourceQuery',
    json={'typeName': 'airport_xzm', 'key': '', 'pageIndex': 1, 'pageSize': 1},
    timeout=10
)
print(f"Status: {resp.status_code}")
print(f"Response headers: {dict(resp.headers)}")

# 检查是否有 token
token = resp.headers.get('token', '')
print(f"Token from headers: {token}")

# 2. 用 token 访问 mapservices
if token:
    print(f"\n=== Step 2: 用 token 访问 mapservices ===")
    resp2 = s.get(
        'http://mapservices.u-care.net.cn/airresource/download/airport_xzm/%E6%80%80%E5%8C%96_%E8%8A%9C%E6%B1%9F%E6%9C%BA%E5%9C%BA.kml',
        headers={'token': token},
        timeout=10
    )
    print(f"Status: {resp2.status_code}, Size: {len(resp2.content)}")
    if len(resp2.content) > 100:
        print(f"Content: {resp2.text[:300]}")
    else:
        print(f"Content: {resp2.text}")
else:
    print("\nNo token in headers")

    # 3. 检查多个 API 调用
    print("\n=== Step 3: 多次调用检查 ===")
    for i in range(3):
        resp = s.post(
            'https://webapi.u-care.net.cn/web/geoQuery/getAirResourceQuery',
            json={'typeName': 'airport_xzm', 'key': '', 'pageIndex': 1, 'pageSize': 1},
            timeout=10
        )
        headers = dict(resp.headers)
        token_val = headers.get('token', 'None')
        print(f"  Call {i+1}: token={token_val[:30] if token_val else 'None'}")
