"""调试页面结构，找到下载按钮。"""
from playwright.sync_api import sync_playwright

def debug_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Loading page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(8000)

        # 截图
        page.screenshot(path='debug_page.png')
        print("Screenshot saved to debug_page.png")

        # 获取页面内容
        html = page.content()
        print(f"HTML length: {len(html)}")

        # 查找表格行
        rows = page.query_selector_all('tr')
        print(f"Table rows: {len(rows)}")

        # 查找可能的下载按钮
        buttons = page.query_selector_all('button')
        print(f"Buttons found: {len(buttons)}")
        for btn in buttons[:10]:
            text = btn.inner_text()
            if text:
                print(f"  Button: {text[:50]}")

        # 查找可能的下载链接
        links = page.query_selector_all('a')
        print(f"Links found: {len(links)}")
        for link in links[:10]:
            href = link.get_attribute('href')
            text = link.inner_text()
            if href:
                print(f"  Link: {href[:80]} | {text[:30]}")

        # 查找所有网络请求
        print("\nAll network requests (first 20):")
        # These are already captured in the page's network log

        browser.close()

if __name__ == '__main__':
    debug_page()
