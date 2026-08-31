#!/usr/bin/env python3
# 查询 admin12 商品的图片配置
import sqlite3
import sys
import json
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/products.db")
cur = conn.cursor()
cur.execute("""SELECT id, parent_sku, variant_image_dimension, variant_dimension_images_json, extra_images_json, main_image
               FROM product_items WHERE parent_sku='admin12' AND is_parent=1""")
row = cur.fetchone()
if row:
    print("商品ID:", row[0])
    print("主图:", row[5])
    print("维度:", row[2])
    print("维度图片映射:", row[3])
    print("附图:", row[4])
    # 验证文件存在性
    from server.services.file_service import FileService
    main_abs = FileService.resolve_image_path(row[5])
    print("\n主图绝对路径:", main_abs, "存在:", os.path.exists(main_abs) if main_abs else False)
    extras = json.loads(row[4]) if row[4] else []
    for p in extras:
        abs_p = FileService.resolve_image_path(p)
        print(f"附图: {abs_p} 存在: {os.path.exists(abs_p) if abs_p else False}")
    dims = json.loads(row[3]) if row[3] else {}
    for k, v in dims.items():
        abs_p = FileService.resolve_image_path(v)
        print(f"维度图[{k}]: {abs_p} 存在: {os.path.exists(abs_p) if abs_p else False}")
