"""使用 Playwright 模拟浏览器下载 KML。"""
from playwright.sync_api import sync_playwright
import json

def download_kml_with_browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        # 监听请求，找到 KML 下载
        def handle_response(response):
            if 'kml' in response.url or 'geojson' in response.url:
                print(f"Response: {response.url}")
                print(f"  Status: {response.status}")
                print(f"  Content-Type: {response.headers.get('content-type', '')}")

        page.on('response', handle_response)

        # 访问主页
        print("Loading page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(5000)

        # 点击第一个条目
        print("\nClicking first item...")
        page.click('.ant-table-row', timeout=5000)
        page.wait_for_timeout(3000)

        # 检查 cookies
        cookies = context.cookies()
        print(f"\nCookies: {json.dumps(cookies, indent=2)}")

        # 尝试直接下载
        print("\nDirect download attempt...")
        resp = context.request.get(
            'http://mapservices.u-care.net.cn/airresource/download/airport_xzm/%E6%80%80%E5%8C%96_%E8%8A%9C%E6%B1%9F%E6%9C%BA%E5%9C%BA.kml'
        )
        print(f"Status: {resp.status}")
        print(f"Content: {resp.text()[:300]}")

        browser.close()

if __name__ == '__main__':
    try:
        download_kml_with_browser()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
