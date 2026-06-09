"""获取点击后的完整 API 响应。"""
from playwright.sync_api import sync_playwright
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def get_full_response():
    api_response = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        def on_response(response):
            nonlocal api_response
            url = response.url
            if 'getAirResourceFileByName' in url:
                print(f"Intercepted API: {url[:100]}")
                api_response = response.json()

        page.on('response', on_response)

        print("Loading page...")
        page.goto('http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD', timeout=30000)
        page.wait_for_timeout(6000)

        # 查找下载按钮
        buttons = page.query_selector_all('button')
        download_btns = [b for b in buttons if '下载' in b.inner_text()]

        if download_btns:
            print("\nClicking download button...")
            download_btns[0].click()
            page.wait_for_timeout(5000)

        browser.close()

    if api_response:
        print(f"\nAPI Response:")
        print(json.dumps(api_response, ensure_ascii=False, indent=2))
        with open('api_full_response.json', 'w', encoding='utf-8') as f:
            json.dump(api_response, f, ensure_ascii=False, indent=2)

        # 尝试用 API 返回的路径下载
        if api_response.get('success'):
            import requests
            for item in api_response.get('data', []):
                path = item.get('path', '')
                ext = item.get('ext', '')
                if path:
                    print(f"\nTrying to download: {path}")
                    resp = requests.get(path, timeout=15)
                    print(f"  Status: {resp.status_code}, Size: {len(resp.content)}")
                    if resp.status_code == 200 and len(resp.content) > 100:
                        fname = f"downloaded.{ext}"
                        with open(fname, 'wb') as f:
                            f.write(resp.content)
                        print(f"  Saved to {fname}")
                    else:
                        print(f"  Content: {resp.text[:200]}")

if __name__ == '__main__':
    get_full_response()
