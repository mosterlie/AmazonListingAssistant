#!/usr/bin/env python3
"""
一键将数据库中 admin12 商品数据自动填入店小秘添加商品页面
"""
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from server.services.erp_bridge import ERPBridgeService
from server.database import get_db_connection

def get_product_id_by_parent_sku(parent_sku: str) -> int:
    """根据 parent_sku 查询 product_items 表中的 id"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM product_items WHERE parent_sku = ? AND is_parent = 1 LIMIT 1", (parent_sku,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"未找到 parent_sku={parent_sku} 的商品记录！")
    return row["id"]


if __name__ == "__main__":
    parent_sku = "admin12"
    print(f"🔍 正在查询 parent_sku={parent_sku} 的数据库记录...")
    product_id = get_product_id_by_parent_sku(parent_sku)
    print(f"✅ 找到商品 ID: {product_id}，开始执行全自动上件到店小秘...")
    print("=" * 60)

    res = ERPBridgeService.publish_product_to_erp(product_id)

    print("\n" + "=" * 60)
    print("执行结果:", "✅ 成功" if res.get("success") else "❌ 失败")
    print("信息:", res.get("msg"))
    print("=" * 60)
    for log_line in res.get("logs", []):
        print(" ", log_line)
