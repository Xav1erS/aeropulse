"""追踪点击下载按钮时的所有网络请求。"""
from playwright.sync_api import sync_playwright
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def trace_requests():
    all_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        # 记录所有请求和响应
        def on_request(request):
            url = request.url
            method = request.method
            all_requests.append(f"{method} {url[:120]}")

        def on_response(response):
            url = response.url
            status = response.status
            ct = response.headers.get('content-type', '')[:50]
            all_requests.append(f"  -> {status} [{ct}] {url[:100]}")

        page.on('request', on_request)
        page.on('response', on_response)

        print("Loading page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(6000)

        print(f"\nInitial requests: {len(all_requests)}")

        # 查找下载按钮
        buttons = page.query_selector_all('button')
        download_btns = [b for b in buttons if '下载' in b.inner_text()]
        print(f"Download buttons: {len(download_btns)}")

        if download_btns:
            before = len(all_requests)
            print("\nClicking download button...")
            download_btns[0].click()
            page.wait_for_timeout(5000)
            after = len(all_requests)

            print(f"\nRequests after click: {after} (+{after-before})")
            for req in all_requests[before:]:
                print(req)

        browser.close()

    # 保存
    with open('trace.log', 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_requests))
    print(f"\nSaved {len(all_requests)} requests to trace.log")

if __name__ == '__main__':
    trace_requests()
