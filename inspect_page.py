"""深入检查页面结构。"""
from playwright.sync_api import sync_playwright
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def inspect_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        print("Loading page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(8000)
        page.screenshot(path='page_full.png', full_page=True)

        # 检查内容
        text = page.inner_text('body')
        print(f"Body text length: {len(text)}")
        print(f"Body text (first 500): {text[:500]}")

        # 截图
        browser.close()

if __name__ == '__main__':
    inspect_page()
