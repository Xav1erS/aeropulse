"""使用 Playwright 拦截并获取实际 KML 内容。"""
from playwright.sync_api import sync_playwright
import json

def intercept_download():
    kml_content = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            accept_downloads=True,
        )
        page = context.new_page()

        # 拦截 mapservices 响应
        def handle_response(response):
            nonlocal kml_content
            url = response.url
            if 'mapservices' in url and ('kml' in url or 'geojson' in url):
                print(f"Intercepted: {url[:80]}")
                print(f"  Status: {response.status}")
                try:
                    body = response.body()
                    print(f"  Body size: {len(body)}")
                    print(f"  Body preview: {body[:300]}")
                    kml_content = body
                except Exception as e:
                    print(f"  Error reading body: {e}")

        page.on('response', handle_response)

        # 也监听请求失败
        def handle_request_failed(request):
            print(f"FAILED: {request.url[:80]}")
        page.on('requestfailed', handle_request_failed)

        print("Loading xianfei page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(6000)

        # 滚动页面让表格可见
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        # 尝试 JS 方式点击
        print("\nClicking via JS...")
        try:
            # 找表格
            table = page.query_selector('.ant-table')
            if table:
                print("Found ant-table")
                rows = table.query_selector_all('tbody tr')
                print(f"Table rows: {len(rows)}")
                if rows:
                    # 尝试点击第一个可点击元素
                    row = rows[0]
                    cells = row.query_selector_all('td')
                    print(f"Cells: {len(cells)}")
                    if cells:
                        cells[0].click(force=True)
                        page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Click error: {e}")

        # 直接执行 JS 调用 API 获取下载链接
        print("\nCalling API via JS...")
        api_result = page.evaluate("""
            async () => {
                const resp = await fetch('https://webapi.u-care.net.cn/web/geoQuery/getAirResourceFileByName?name=怀化_芷江机场&type=airport_xzm');
                return await resp.json();
            }
        """)
        print(f"API result: {json.dumps(api_result, ensure_ascii=False)[:200]}")

        # 尝试触发下载
        download_paths = []
        def handle_download(download):
            print(f"Download started: {download.suggested_filename}")
            download_paths.append(download.path())

        page.on('download', handle_download)

        # 用 JS 触发点击
        print("\nTrying to trigger download via JS...")
        try:
            page.evaluate("""
                const btn = document.querySelector('a[href*="kml"], a[href*="download"]');
                if (btn) {
                    btn.click();
                    console.log('Clicked download link');
                } else {
                    console.log('No download link found');
                    // 列出所有链接
                    const links = document.querySelectorAll('a');
                    links.forEach(l => console.log('Link:', l.href, l.textContent));
                }
            """)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"JS error: {e}")

        print(f"\nDownloads: {download_paths}")
        browser.close()

    return kml_content

if __name__ == '__main__':
    content = intercept_download()
    if content:
        with open('intercepted.kml', 'wb') as f:
            f.write(content)
        print(f"\nSaved KML to intercepted.kml ({len(content)} bytes)")
