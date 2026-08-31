#!/usr/bin/env python3
# 步骤3+4+5：
#   3. 第一个 SKU 主图 ➔ 应用「主图-同カラー(颜色)的变种」（覆盖颜色11的全部卡片）
#   4. 下一个无主图的 SKU（颜色22）上传主图 sku2.jpg ➔ 应用「主图-同カラー」
#   5. 下一个无主图的 SKU（颜色33）上传主图 12312321.jpg ➔ 应用「主图-同カラー」
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

from browser_engine import BrowserEngine

UPLOADS = os.path.join(PROJECT_DIR, "data", "uploads")

# 颜色维度: 每个颜色一张主图（尺寸固定 aa 行作为上传锚点）
COLOR_MAIN_PLAN = [
    ("11", os.path.join(UPLOADS, "sku1.jpg")),        # 已上传，只需应用
    ("22", os.path.join(UPLOADS, "sku2.jpg")),        # 步骤4: 上传+应用
    ("33", os.path.join(UPLOADS, "12312321.jpg")),     # 步骤5: 上传+应用
]


def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    for color, main_img in COLOR_MAIN_PLAN:
        filter_crit = {"颜色": color, "尺寸": "aa"}
        print(f"\n===== 处理颜色【{color}】 =====")

        if not os.path.exists(main_img):
            print(f"  ❌ 主图文件不存在: {main_img}，跳过")
            continue

        # 上传主图（内部等待渲染完成；若该行已有主图，重新上传也是安全的幂等操作）
        print(f"  ① 上传主图: {os.path.basename(main_img)} ...")
        up_ok = engine.upload_variation_image(
            filter_criteria=filter_crit,
            image_path=main_img,
            image_type="main",
            timeout_ms=30000
        )
        print(f"     上传: {'✅ 完成并确认渲染' if up_ok else '❌ 失败/超时'}")
        if not up_ok:
            continue

        # 主图 ➔ 同カラー(颜色)的变种
        print(f"  ② 图片应用到 ➔ 主图-同カラー(颜色)的变种 ...")
        apply_ok = engine.apply_variation_image(
            filter_criteria=filter_crit,
            apply_type="main_color",
            timeout_ms=15000
        )
        print(f"     应用: {'✅ 已应用至同颜色的所有变种' if apply_ok else '❌ 应用失败'}")

    print("\n=== 步骤 3/4/5 执行完毕 ===")


if __name__ == "__main__":
    main()
