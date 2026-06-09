"""尝试跨域共享 cookies。"""
from playwright.sync_api import sync_playwright
import requests

def try_cross_domain():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True
        )
        page = context.new_page()

        print("Loading xianfei page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(5000)

        # 获取 cookies
        xianfei_cookies = context.cookies('http://xianfei.u-care.net.cn')
        print(f"Xianfei cookies: {[c['name'] for c in xianfei_cookies]}")

        # 尝试设置 mapservices 的 cookie（模拟同一会话）
        # mapservices.u-care.net.cn 需要一个会话标识

        # 尝试直接用 requests 带上所有可能的 cookies
        s = requests.Session()
        for c in xianfei_cookies:
            s.cookies.set(c['name'], c['value'], domain='.u-care.net.cn', path='/')

        print("\nTrying to download KML with cookies...")
        resp = s.get('http://mapservices.u-care.net.cn/airresource/download/airport_xzm/%E6%80%80%E5%8C%96_%E8%8A%9C%E6%B1%9F%E6%9C%BA%E5%9C%BA.kml', timeout=15)
        print(f"Status: {resp.status_code}, Size: {len(resp.content)}")
        print(f"Content: {resp.text[:200]}")

        # 尝试用 webapi cookies
        webapi_cookies = context.cookies('https://webapi.u-care.net.cn')
        print(f"\nWebAPI cookies: {[c['name'] for c in webapi_cookies]}")

        browser.close()

if __name__ == '__main__':
    try_cross_domain()
