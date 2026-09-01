import sys
import os
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from server.services.erp_bridge import ERPBridgeService
from browser_engine import BrowserEngine

def log_cb(line):
    print("[ERP-LOG]", line, flush=True)

if __name__ == "__main__":
    print("🚀 启动 Product 49 自动化上件与 SKU 图片批量测试...")
    res = ERPBridgeService.publish_product_to_erp(49, log_callback=log_cb)
    print("Result:", res)
