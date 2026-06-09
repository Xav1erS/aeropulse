#!/usr/bin/env python3
"""分析API完整功能"""
import requests
import json

api_url = "https://webapi.u-care.net.cn/web/geoQuery/getAirResourceQuery"

# 1. 获取总数据量和字段
params = {
    "airTypeName": "airport_xzm",  # 机场限制面
}

resp = requests.post(api_url, json=params, timeout=10)
data = resp.json()

print("=== API响应分析 ===")
print(f"成功: {data.get('success')}")
print(f"总数: {data['data']['total']}")
print(f"\n字段列表: {list(data['data']['list'][0].keys()) if data['data']['list'] else '无数据'}")

# 2. 尝试分页
print("\n=== 测试分页功能 ===")
for page in [1, 2]:
    for pageSize in [5, 10]:
        params_paged = {
            "airTypeName": "airport_xzm",
            "page": page,
            "pageSize": pageSize
        }
        resp = requests.post(api_url, json=params_paged, timeout=10)
        d = resp.json()
        if d['data']['list']:
            print(f"page={page}, pageSize={pageSize}: 返回 {len(d['data']['list'])} 条")
        else:
            print(f"page={page}, pageSize={pageSize}: 无数据")

# 3. 尝试获取下载路径
print("\n=== 测试下载路径字段 ===")
sample = data['data']['list'][0]
print(f"示例数据: {json.dumps(sample, ensure_ascii=False)}")

# 4. 查看所有可用的airTypeName
print("\n=== 所有数据类型 ===")
all_types = set()
for item in data['data']['list']:
    all_types.add(item.get('type', ''))
print(f"发现的数据类型: {all_types}")

# 5. 尝试其他数据类型
print("\n=== 测试其他数据类型 ===")
type_names = [
    "airport_jkq",  # 机场净空区
    "airport_buffer",  # 机场缓冲区
    "temporary",  # 临时禁飞区
    "no_fly",  # 禁飞区
]

for t in type_names:
    params = {"airTypeName": t}
    try:
        resp = requests.post(api_url, json=params, timeout=10)
        d = resp.json()
        total = d['data']['total'] if d.get('data') else 0
        print(f"{t}: 总数={total}")
    except Exception as e:
        print(f"{t}: 错误 - {e}")
