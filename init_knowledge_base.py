#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库建表与初始数据迁移/同步脚本 (Init & Migrate Knowledge Base)

用途：
- 其他电脑执行 git pull 后，可随时运行此脚本，为本地 products.db 补齐知识库表结构与默认常用网址。
- 采用幂等设计：表已存在不报错，数据已存在不重复插入，支持多次安全执行。
"""
import os
import sys
import sqlite3
import argparse

# 默认知识库初始数据集 (6条常用工具与电商网站)
DEFAULT_KNOWLEDGE_SITES = [
    {
        "title": "亚马逊-以图搜图",
        "url_part1": "https://www.amazon.co.jp/stylesnap",
        "url_part2": "",
        "url_part3": "",
        "url_part4": "",
        "url_part5": "",
        "description": "",
        "sort_order": 1,
        "created_by": "admin"
    },
    {
        "title": "亚马逊-用户端",
        "url_part1": "https://www.amazon.co.jp/",
        "url_part2": "",
        "url_part3": "",
        "url_part4": "",
        "url_part5": "",
        "description": "",
        "sort_order": 2,
        "created_by": "admin"
    },
    {
        "title": "亚马逊-销量榜",
        "url_part1": "https://www.amazon.co.jp/gp/bestsellers",
        "url_part2": "",
        "url_part3": "",
        "url_part4": "",
        "url_part5": "",
        "description": "",
        "sort_order": 3,
        "created_by": "admin"
    },
    {
        "title": "亚马逊-商标品牌端",
        "url_part1": "https://brandregistry.amazon.com.au",
        "url_part2": "",
        "url_part3": "",
        "url_part4": "",
        "url_part5": "",
        "description": "",
        "sort_order": 4,
        "created_by": "admin"
    },
    {
        "title": "亚马逊-通过asin搜",
        "url_part1": "https://www.amazon.co.jp/dp/",
        "url_part2": "{var}",
        "url_part3": "?th=1",
        "url_part4": "",
        "url_part5": "",
        "description": "",
        "sort_order": 5,
        "created_by": "admin"
    },
    {
        "title": "海关编码",
        "url_part1": "www.hsbianma.com",
        "url_part2": "",
        "url_part3": "",
        "url_part4": "",
        "url_part5": "",
        "description": "查看相关抖音介绍：抖音：9.43 :6pm o@D.us kCU:/ 05/02 亚马逊FBM发货实操教程！ # 亚马逊 # 亚马逊运营 # 亚马逊FBM # 跨境电商 # 亚马逊新手开店  https://v.douyin.com/GaSt0cAABZM/ 复制此链接，打开Dou音搜索，直接观看视频！",
        "sort_order": 6,
        "created_by": "admin"
    }
]


def init_knowledge_base(db_path: str):
    """为指定数据库初始化知识库表与初始数据"""
    print("=" * 60)
    print("📚 正在为本地数据库初始化/同步知识库模块...")
    print(f"📁 目标数据库路径: {os.path.abspath(db_path)}")
    print("=" * 60)

    # 确保目标目录存在
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        print(f"📁 已自动创建数据库目录: {db_dir}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. 创建 knowledge_sites 表 (若不存在)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url_part1 TEXT DEFAULT '',
            url_part2 TEXT DEFAULT '',
            url_part3 TEXT DEFAULT '',
            url_part4 TEXT DEFAULT '',
            url_part5 TEXT DEFAULT '',
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_by VARCHAR(64) DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_sort ON knowledge_sites(sort_order, id);")
        print("✅ [1/2] 知识库数据表 `knowledge_sites` 及排序索引已就绪 (CREATE TABLE IF NOT EXISTS)")

        # 2. 幂等补全初始数据 (若同名网址已存在则跳过，绝不重复插入)
        inserted_count = 0
        skipped_count = 0

        for site in DEFAULT_KNOWLEDGE_SITES:
            cursor.execute("SELECT id FROM knowledge_sites WHERE title = ?;", (site["title"],))
            existing = cursor.fetchone()
            if existing:
                skipped_count += 1
                print(f"   ℹ️  跳过已存在条目: 【{site['title']}】 (ID: {existing[0]})")
            else:
                cursor.execute("""
                INSERT INTO knowledge_sites (
                    title, url_part1, url_part2, url_part3, url_part4, url_part5,
                    description, sort_order, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    site["title"],
                    site["url_part1"],
                    site["url_part2"],
                    site["url_part3"],
                    site["url_part4"],
                    site["url_part5"],
                    site["description"],
                    site["sort_order"],
                    site["created_by"]
                ))
                inserted_count += 1
                print(f"   ✨ 新增初始化条目: 【{site['title']}】 -> {site['url_part1']}{site['url_part2']}{site['url_part3']}")

        conn.commit()

        # 统计最终状态
        cursor.execute("SELECT count(*) FROM knowledge_sites;")
        total_records = cursor.fetchone()[0]

        print("-" * 60)
        print("🎉 [2/2] 知识库数据初始化/同步完成！")
        print(f"📊 本次新增: {inserted_count} 条 | 已存在跳过: {skipped_count} 条 | 库内当前总计: {total_records} 条")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"❌ 初始化过程中发生异常: {e}", file=sys.stderr)
        raise e
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="知识库表结构与初始数据同步工具")
    default_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "products.db")
    parser.add_argument("--db", default=default_db, help=f"指定 SQLite 数据库路径 (默认: {default_db})")
    args = parser.parse_args()

    init_knowledge_base(args.db)


if __name__ == "__main__":
    main()
