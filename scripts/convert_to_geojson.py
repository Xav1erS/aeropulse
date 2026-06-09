#!/usr/bin/env python3
"""
从 source_audit SQLite 数据库转换数据到 geo_radar 可用的格式
"""
import json
import sqlite3
from pathlib import Path


def convert_audit_to_geojson(db_path: str, output_path: str, run_id: str = None):
    """
    从 audit_pages 表读取数据，转换为 raw_announcements.json 格式
    
    Args:
        db_path: SQLite 数据库路径
        output_path: 输出 JSON 文件路径
        run_id: 可选，指定特定的 run_id，如果为 None 则使用最新的 run
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 如果没有指定 run_id，使用最新的 run
    if run_id is None:
        cursor.execute("SELECT run_id FROM audit_runs ORDER BY created_at DESC LIMIT 1")
        result = cursor.fetchone()
        if result is None:
            print("错误：数据库中没有找到任何运行记录")
            return
        run_id = result['run_id']
    
    print(f"使用 run_id: {run_id}")
    
    # 读取相关页面（relevant=1），优先选择A、B、C类样本
    cursor.execute("""
        SELECT 
            id,
            run_id,
            final_url,
            source_name,
            source_priority,
            city,
            title,
            published_at,
            body_text,
            category,
            confidence
        FROM audit_pages
        WHERE run_id = ? 
            AND relevant = 1 
            AND is_duplicate = 0
        ORDER BY 
            CASE category 
                WHEN 'A' THEN 1
                WHEN 'B' THEN 2
                WHEN 'C' THEN 3
                WHEN 'D' THEN 4
                ELSE 5
            END,
            confidence DESC
    """, (run_id,))
    
    rows = cursor.fetchall()
    print(f"找到 {len(rows)} 个相关页面")
    
    # 转换为 raw_announcements.json 格式
    announcements = []
    for row in rows:
        # 生成 ID：使用表ID和标题前20个字符
        title = row['title']
        id_base = title[:20] if title else f"ann_{row['id']}"
        # 清理ID中的特殊字符
        import re
        id_clean = re.sub(r'[^\w\s-]', '', id_base)
        id_clean = re.sub(r'[-\s]+', '_', id_clean)
        announcement_id = f"{row['city']}_{id_clean}_{row['id']}"
        
        # 城市名称：添加"市"字（如果还没有）
        city = row['city']
        if city and not city.endswith('市'):
            city = city + '市'
        
        announcement = {
            "id": announcement_id,
            "body_text": row['body_text'],
            "source_name": row['source_name'],
            "source_url": row['final_url'],
            "source_level": row['source_priority'],
            "publish_time": row['published_at'],
            "city": city
        }
        announcements.append(announcement)
    
    conn.close()
    
    # 写入输出文件
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(announcements, f, ensure_ascii=False, indent=2)
    
    print(f"已转换 {len(announcements)} 条公告")
    print(f"输出文件: {output_path}")
    
    # 打印统计信息
    categories = {}
    for ann in announcements:
        # 从原始数据中获取分类
        pass
    
    return announcements


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='从 source_audit 数据库转换数据到 geo_radar 格式')
    parser.add_argument('--db', default='data/source_audit.sqlite', help='SQLite 数据库路径')
    parser.add_argument('--output', default='data/raw_announcements.json', help='输出 JSON 文件路径')
    parser.add_argument('--run-id', help='指定 run_id（可选，默认使用最新的 run）')
    
    args = parser.parse_args()
    
    convert_audit_to_geojson(args.db, args.output, args.run_id)
