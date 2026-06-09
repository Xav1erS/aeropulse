#!/usr/bin/env python3
"""捕获所有网络请求"""
from playwright.sync_api import sync_playwright
import json

url = "http://xianfei.u-care.net.cn/#/downLoadList?airTypeName=airport_xzm&airTypeCH=%E6%9C%BA%E5%9C%BA%E9%9A%9C%E7%A2%8D%E7%89%A9%E9%99%90%E5%88%B6%E9%9D%A2%E6%95%B0%E6%8D%AE%E4%B8%8B%E8%BD%BD"

all_requests = []

def handle_request(request):
    all_requests.append({
        'url': request.url,
        'method': request.method,
        'post_data': request.post_data,
    })

def handle_response(response):
    for item in all_requests:
        if item['url'] == response.url:
            try:
                item['response_status'] = response.status
                item['response_body'] = response.json()
            except:
                pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    page.on("request", handle_request)
    page.on("response", handle_response)
    
    print("访问页面...")
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(5000)
    
    # 打印所有webapi请求
    print("\n=== 所有 webapi.u-care.net.cn 请求 ===")
    for req in all_requests:
        if 'webapi.u-care.net.cn' in req['url']:
            print(f"\n--- 请求 ---")
            print(f"URL: {req['url']}")
            print(f"Method: {req['method']}")
            if req.get('post_data'):
                print(f"POST数据: {req['post_data']}")
            if req.get('response_body'):
                body = req['response_body']
                if isinstance(body, dict):
                    # 只打印前几条数据
                    if 'list' in body.get('data', {}):
                        print(f"响应数据: total={body['data']['total']}, list长度={len(body['data']['list'])}")
                        if body['data']['list']:
                            print(f"  示例: {json.dumps(body['data']['list'][0], ensure_ascii=False)}")
                    else:
                        print(f"响应: {json.dumps(body, ensure_ascii=False)[:300]}")
    
    # 打印所有可能的下载请求
    print("\n=== 所有可能的下载请求 ===")
    for req in all_requests:
        url_lower = req['url'].lower()
        if any(kw in url_lower for kw in ['download', 'kml', 'geojson', 'file', 'export']):
            print(f"URL: {req['url']}")
    
    browser.close()

# 保存
with open("all_requests.json", "w", encoding="utf-8") as f:
    json.dump(all_requests, f, ensure_ascii=False, indent=2)
print("\n已保存到 all_requests.json")
