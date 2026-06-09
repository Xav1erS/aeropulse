"""捕获点击下载时的网络请求。"""
from playwright.sync_api import sync_playwright
import json

def capture_download():
    results = {
        'api_requests': [],
        'download_requests': [],
        'page_info': None
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True
        )
        page = context.new_page()

        # 拦截所有响应
        def on_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get('content-type', '')

            if 'mapservices' in url or 'u-care' in url:
                if 'kml' in url or 'geojson' in url or 'download' in url:
                    results['download_requests'].append({
                        'url': url,
                        'status': status,
                        'content_type': ct,
                    })
                    print(f"[DOWNLOAD] {url[:80]} | {status} | {ct}")

        def on_request(request):
            url = request.url
            if 'geoQuery' in url or 'mapservices' in url:
                print(f"[REQUEST] {url[:100]}")
                results['api_requests'].append({'url': url})

        page.on('response', on_response)
        page.on('request', on_request)

        print("Loading page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(6000)

        # 截图看页面状态
        page.screenshot(path='page_state.png')

        # 尝试点击第一行
        print("\nTrying to click first row...")
        try:
            # 尝试多种选择器
            selectors = [
                'tbody tr:first-child',
                '.ant-table-tbody tr:first-child',
                '[class*="table"] tr:first-child',
                'tr:first-child',
            ]
            for sel in selectors:
                rows = page.query_selector_all(sel)
                if rows:
                    print(f"Found {len(rows)} rows with selector: {sel}")
                    rows[0].click(timeout=3000)
                    page.wait_for_timeout(3000)
                    print("Clicked!")
                    break
        except Exception as e:
            print(f"Click failed: {e}")

        # 再等一下看是否有下载请求
        page.wait_for_timeout(3000)

        # 输出 cookies
        cookies = context.cookies()
        print(f"\nCookies: {json.dumps(cookies, indent=2)}")

        # 截图
        page.screenshot(path='after_click.png')

        # 保存结果
        with open('capture_result.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nSaved results to capture_result.json")

        browser.close()

if __name__ == '__main__':
    capture_download()
