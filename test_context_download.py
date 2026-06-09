"""使用 Playwright context.request (带浏览器 cookies) 下载。"""
from playwright.sync_api import sync_playwright
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def download_with_context():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        # 先访问主站
        print("Loading page to get cookies...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(6000)

        # 点击第一个下载按钮
        buttons = page.query_selector_all('button')
        for btn in buttons:
            if '下载' in btn.inner_text():
                btn.click()
                page.wait_for_timeout(3000)
                break

        # 打印所有 cookies
        print("\nCookies:")
        cookies = context.cookies()
        for c in cookies:
            print(f"  {c['domain']}: {c['name']}={c['value'][:20]}...")

        # 使用 context.request (携带 cookies) 尝试下载
        print("\nTrying download with context.request...")
        resp = context.request.get('http://mapservices.u-care.net.cn/airresource/download/airport_xzm/%E6%80%80%E5%8C%96_%E8%8A%9C%E6%B1%9F%E6%9C%BA%E5%9C%BA.kml')
        print(f"Status: {resp.status}")
        print(f"Content: {resp.text()[:300]}")

        browser.close()

if __name__ == '__main__':
    download_with_context()
