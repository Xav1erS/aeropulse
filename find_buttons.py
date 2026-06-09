"""找到下载按钮并点击，捕获 KML 下载。"""
from playwright.sync_api import sync_playwright
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def download_kml():
    kml_content = None
    download_info = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        # 拦截 mapservices 响应
        def on_response(response):
            nonlocal kml_content
            url = response.url
            if 'mapservices' in url:
                print(f"Intercepted: {url[:80]}")
                try:
                    body = response.body()
                    print(f"  Status: {response.status}, Size: {len(body)}")
                    if len(body) > 100:
                        print(f"  Content: {body[:200]}")
                    if response.status == 200 and len(body) > 100:
                        kml_content = body
                except Exception as e:
                    print(f"  Error: {e}")

        page.on('response', on_response)

        print("Loading page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(6000)

        # 查找所有下载按钮
        print("\nFinding download buttons...")
        buttons = page.query_selector_all('button')
        print(f"Total buttons: {len(buttons)}")

        # 查找包含"下载"文字的按钮
        download_buttons = []
        for btn in buttons:
            text = btn.inner_text()
            if text and '下载' in text:
                download_buttons.append(btn)
                print(f"  Found button: {text.strip()}")

        # 尝试查找下载链接（<a> 标签）
        links = page.query_selector_all('a')
        download_links = []
        for link in links:
            href = link.get_attribute('href')
            text = link.inner_text()
            if href and ('kml' in href.lower() or 'download' in href.lower() or 'geojson' in href.lower()):
                download_links.append((link, href, text))
                print(f"  Found download link: {href[:80]} | {text.strip()}")

        print(f"\nDownload buttons: {len(download_buttons)}, Links: {len(download_links)}")

        # 尝试点击第一个下载按钮
        if download_buttons:
            print("\nClicking first download button...")
            try:
                download_buttons[0].click(timeout=5000)
                page.wait_for_timeout(3000)
                print("Clicked!")

                # 检查是否有弹窗
                modals = page.query_selector_all('[class*="modal"], [class*="dialog"]')
                print(f"Modals: {len(modals)}")

                # 截图
                page.screenshot(path='after_download_click.png')

                # 检查新的下载按钮
                new_links = page.query_selector_all('a')
                for link in new_links:
                    href = link.get_attribute('href')
                    if href and ('kml' in href.lower() or 'geojson' in href.lower()):
                        print(f"  New download link: {href[:100]}")

            except Exception as e:
                print(f"Click error: {e}")

        browser.close()

    # 保存结果
    if kml_content:
        with open('captured_kml.kml', 'wb') as f:
            f.write(kml_content)
        print(f"\nSaved KML: {len(kml_content)} bytes")

if __name__ == '__main__':
    download_kml()
