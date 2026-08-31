#!/usr/bin/env python3
# 用「上件流程 erp_bridge.py 阶段 5」的 SKU 图片上传方法，在当前页面执行一遍
# 代码逐字复用 server/services/erp_bridge.py 的阶段 5 装配逻辑（含超时参数与执行顺序）
import sys
import os
import time
import json

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
from server.services.file_service import FileService

UPLOADS = os.path.join(PROJECT_DIR, "data", "uploads")

# 构造与当前页面变体矩阵一致的商品数据（与 erp_bridge 读取 product_items 后的数据结构相同）
product = {
    "sale_type": "variation",
    "variations": [
        {"color": "11", "size": "aa"},
        {"color": "22", "size": "aa"},
        {"color": "33", "size": "aa"},
        {"color": "11", "size": "qq"},
        {"color": "22", "size": "qq"},
        {"color": "33", "size": "qq"},
    ],
    "variant_image_dimension": "color",
    "variant_dimension_images": {
        "11": os.path.join(UPLOADS, "sku1.jpg"),
        "22": os.path.join(UPLOADS, "sku2.jpg"),
        "33": os.path.join(UPLOADS, "12312321.jpg"),
    },
    "extra_images": [os.path.join(UPLOADS, f"PT{i:02d}.jpg") for i in [1, 2, 3, 5, 6, 7, 8]],
}


def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    def emit_log(line):
        print(line)

    # ============ 以下为 erp_bridge.py 阶段 5 图片装配代码（逐字复用） ============
    # 准备图片配置
    img_dimension = product.get("variant_image_dimension") or "color"
    dim_images_map = product.get("variant_dimension_images") or {}
    if not dim_images_map and product.get("variant_dimension_images_json"):
        try:
            dim_images_map = json.loads(product["variant_dimension_images_json"])
        except Exception:
            pass

    # 解析父商品附图清单 (所有子 SKU 统一复用)
    parent_extras = product.get("extra_images") or []
    if not parent_extras and product.get("extra_images_json"):
        try:
            parent_extras = json.loads(product["extra_images_json"])
        except Exception:
            pass

    parent_extra_abs_files = [
        FileService.resolve_image_path(p)
        for p in parent_extras
        if p and FileService.resolve_image_path(p) and os.path.exists(FileService.resolve_image_path(p))
    ]

    # 2. 「图片应用到」五步装配策略（已在真实页面逐步验证）:
    #    ① 第一个 SKU: 上传主图+附图（等待渲染完成）
    #    ② 第一个 SKU: 附图 ➔ 应用「附图-所有变体」
    #    ③ 第一个 SKU: 主图 ➔ 按维度应用（颜色→同カラー / 尺寸→同サイズ）
    #    ④ 下一个无主图的 SKU: 上传主图并按维度应用
    #    ⑤ 循环直至所有维度主图覆盖完毕
    #    注意: 顺序必须为主图在前、附图在后（重传主图会清空该卡片附图）
    has_dim_images = bool(dim_images_map)
    applied_dim_values = set()   # 已通过「图片应用到」批量覆盖主图的维度值
    extra_applied = False        # 附图是否已应用至所有变体
    dim_label = "カラー(颜色)" if img_dimension == "color" else "サイズ(尺寸)"
    main_apply_type = "main_color" if img_dimension == "color" else "main_size"
    emit_log(f"     ℹ️ 变体 SKU 图片录入维度判定为: 【{dim_label}】")

    for var in product.get("variations", []):
        col = var.get("color", "")
        sz = var.get("size", "")

        filter_crit = {}
        if col:
            filter_crit["颜色"] = col
        if sz:
            filter_crit["尺寸"] = sz
        if not filter_crit:
            continue

        dim_val = col if img_dimension == "color" else sz

        # 该维度主图是否已被批量应用覆盖（步骤⑤的"下一个没有主图的sku"判定）
        covered = has_dim_images and dim_val in applied_dim_values
        if covered:
            continue

        # 确定变体主图 (按颜色/按尺寸维度映射，或独立变体图)
        v_main_img_path = ""
        if has_dim_images and dim_val and dim_val in dim_images_map:
            v_main_img_path = dim_images_map[dim_val]
        elif var.get("variant_image"):
            v_main_img_path = var.get("variant_image")
        elif var.get("main_image"):
            v_main_img_path = var.get("main_image")

        abs_main = ""
        if v_main_img_path:
            resolved = FileService.resolve_image_path(v_main_img_path)
            if resolved and os.path.exists(resolved):
                abs_main = resolved

        # ①/④ 上传该 SKU 主图（等待上传完成；已存在时幂等跳过）
        main_ok = False
        if abs_main:
            main_ok = engine.upload_variation_image(
                filter_criteria=filter_crit,
                image_path=abs_main,
                image_type="main",
                timeout_ms=30000
            )
            emit_log(f"     ➔ {'✅' if main_ok else '⚠️ 上传超时'} 变体主图【{col} / {sz}】: {v_main_img_path}")

        # ① 附图上传（仅第一个 SKU，等待上传完成）
        if not extra_applied and parent_extra_abs_files:
            extra_ok = engine.upload_variation_image(
                filter_criteria=filter_crit,
                image_path=parent_extra_abs_files,
                image_type="extra",
                timeout_ms=60000
            )
            emit_log(f"     ➔ {'✅' if extra_ok else '⚠️ 上传超时'} 附图【{col} / {sz}】({len(parent_extra_abs_files)} 张)")
            # ② 附图 ➔ 所有变体（仅在确认上传完成后才执行批量应用；失败自动重试，首次失败多为上传后页面加载态未散去）
            extra_apply_ok = False
            for attempt in range(3):
                if engine.apply_variation_image(filter_criteria=filter_crit, apply_type="extra_all", timeout_ms=15000):
                    extra_apply_ok = True
                    break
                time.sleep(1.0)
            if extra_ok and extra_apply_ok:
                emit_log("     ➔ 已将附图应用至【附图-所有变体】")
                extra_applied = True
            # 失败时不置位，留待下一个变体重试

        # ③/⑤ 主图按维度批量应用（仅在确认上传完成后才执行；独立变体图不应用以免误扩散；失败自动重试）
        if main_ok and has_dim_images and dim_val:
            main_apply_ok = False
            for attempt in range(3):
                if engine.apply_variation_image(filter_criteria=filter_crit, apply_type=main_apply_type, timeout_ms=15000):
                    main_apply_ok = True
                    break
                time.sleep(1.0)
            if main_apply_ok:
                emit_log(f"     ➔ 已将主图应用至【同{dim_label}的变种】")
                applied_dim_values.add(dim_val)
            else:
                emit_log(f"     ⚠️ 主图应用【同{dim_label}的变种】连续 3 次失败，跳过该维度")
        time.sleep(0.3)

    emit_log(f"✅ 变体图片装配完成：主图覆盖 {len(applied_dim_values)} 个【{dim_label}】维度值，附图已应用至所有变体！")
    # ============ erp_bridge.py 阶段 5 代码结束 ============


if __name__ == "__main__":
    main()
