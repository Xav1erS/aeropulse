"""调试 KML 下载 - 检查需要什么认证。"""
import requests
from urllib.parse import quote

name = '怀化_芷江机场'
encoded_name = quote(name)

# 尝试不同的方式
urls = [
    f'http://mapservices.u-care.net.cn/airresource/download/airport_xzm/{encoded_name}.kml',
    f'https://webapi.u-care.net.cn/airresource/download/airport_xzm/{encoded_name}.kml',
]

for url in urls:
    print(f'URL: {url}')
    resp = requests.get(url, timeout=15)
    print(f'  Status: {resp.status_code}')
    print(f'  Content-Type: {resp.headers.get("Content-Type")}')
    print(f'  First 200: {resp.text[:200]}')
    print()
