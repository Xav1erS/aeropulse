import requests
from urllib.parse import quote

name = '怀化_芷江机场'
encoded_name = quote(name)
url = f'http://mapservices.u-care.net.cn/airresource/download/airport_xzm/{encoded_name}.kml'
print(f'URL: {url}')
resp = requests.get(url, timeout=15)
print(f'Status: {resp.status_code}')
print(f'Content-Type: {resp.headers.get("Content-Type")}')
print(f'Size: {len(resp.content)}')
print(f'First 500 chars:')
print(resp.text[:500])
