import sys
import os
sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
import requests

def test_api_publish():
    print("=" * 80)
    print("🚀 【通过 Web API 触发商品 #61 自动化上件并实时打印每个 SKU 的附图核验结果】")
    print("=" * 80)

    # 1. 触发上件接口
    url_publish = "http://localhost:8000/api/automation/publish/61"
    res = requests.post(url_publish, timeout=5)
    print(f"触发响应: {res.json()}")

    # 2. 循环轮询日志与进度
    url_status = "http://localhost:8000/api/automation/publish-status/61"
    since = 0
    start_time = time.time()

    while time.time() - start_time < 300:
        time.sleep(1.0)
        try:
            resp = requests.get(f"{url_status}?since={since}", timeout=5)
            data = resp.json().get("data", {})
            if not data:
                continue

            new_logs = data.get("new_logs", [])
            for line in new_logs:
                print(f"  {line}")
            
            since = data.get("total_log_lines", since)

            if data.get("done"):
                print("\n" + "=" * 80)
                print(f"🏁 任务完成! 结果: success={data.get('success')}, msg={data.get('result_msg')}")
                print("=" * 80)
                break
        except Exception as e:
            print(f"轮询异常: {e}")
            time.sleep(2)

if __name__ == "__main__":
    test_api_publish()
