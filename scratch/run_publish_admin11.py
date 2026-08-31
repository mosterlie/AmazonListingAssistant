#!/usr/bin/env python3
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

if __name__ == "__main__":
    print("🚀 开始执行商品 ID=49 (Parent SKU: admin11) 的全自动录入流程...")
    res = ERPBridgeService.publish_product_to_erp(49)
    print("\n" + "=" * 60)
    print("执行结果:", "✅ 成功" if res.get("success") else "❌ 失败")
    print("信息:", res.get("msg"))
    print("=" * 60)
    for l in res.get("logs", []):
        print(" ", l)
