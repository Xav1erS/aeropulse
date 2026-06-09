"""检查 mapservices 需要的认证类型。"""
from playwright.sync_api import sync_playwright
import requests
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def check_auth():
    # 1. 检查 mapservices 响应的 headers
    print("=== 检查 mapservices 响应头 ===")
    resp = requests.get('http://mapservices.u-care.net.cn/airresource/download/airport_xzm/test.kml', timeout=10)
    print(f"Status: {resp.status_code}")
    print(f"Headers: {dict(resp.headers)}")

    # 2. 检查 webapi 响应的 cookies
    print("\n=== 检查 webapi 响应头和 cookies ===")
    webapi_resp = requests.post(
        'https://webapi.u-care.net.cn/web/geoQuery/getAirResourceQuery',
        json={'typeName': 'airport_xzm', 'key': '', 'pageIndex': 1, 'pageSize': 1},
        timeout=10
    )
    print(f"Status: {webapi_resp.status_code}")
    print(f"Set-Cookie headers: {webapi_resp.headers.get('Set-Cookie', 'None')}")
    print(f"Headers: {dict(webapi_resp.headers)}")

    # 3. 尝试带 referer 访问
    print("\n=== 尝试带 Referer 访问 ===")
    resp2 = requests.get(
        'http://mapservices.u-care.net.cn/airresource/download/airport_xzm/%E6%80%80%E5%8C%96_%E8%8A%9C%E6%B1%9F%E6%9C%BA%E5%9C%BA.kml',
        headers={'Referer': 'http://xianfei.u-care.net.cn/'},
        timeout=10
    )
    print(f"Status: {resp2.status_code}, Size: {len(resp2.content)}")

    # 4. 尝试带 webapi 的 cookie
    print("\n=== 尝试带 webapi cookies 访问 ===")
    s = requests.Session()
    s.post(
        'https://webapi.u-care.net.cn/web/geoQuery/getAirResourceQuery',
        json={'typeName': 'airport_xzm', 'key': '', 'pageIndex': 1, 'pageSize': 1},
        timeout=10
    )
    resp3 = s.get(
        'http://mapservices.u-care.net.cn/airresource/download/airport_xzm/%E6%80%80%E5%8C%96_%E8%8A%9C%E6%B1%9F%E6%9C%BA%E5%9C%BA.kml',
        timeout=10
    )
    print(f"Status: {resp3.status_code}, Size: {len(resp3.content)}")

    # 5. 检查 Playwright 是否有额外 cookies
    print("\n=== Playwright 完整 cookies ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(5000)

        cookies = context.cookies()
        for c in cookies:
            print(f"  {c['domain']}: {c['name']} = {c['value']}")

        # 尝试访问 mapservices
        resp = context.request.get(
            'http://mapservices.u-care.net.cn/airresource/download/airport_xzm/%E6%80%80%E5%8C%96_%E8%8A%9C%E6%B1%9F%E6%9C%BA%E5%9C%BA.kml'
        )
        print(f"\nmapservices response: {resp.status}")

        browser.close()

if __name__ == '__main__':
    check_auth()
