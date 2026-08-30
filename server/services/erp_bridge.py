"""
店小秘 ERP 自动化上件桥接服务
将商品库中录入的结构化商品、变体矩阵和图片路径，直接映射并调用 BrowserEngine 执行真实自动化上件
"""
import time
from typing import Dict, Any
from server.services.product_service import ProductService

try:
    from browser_engine import BrowserEngine
except ImportError:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from browser_engine import BrowserEngine


class ERPBridgeService:
    """店小秘 ERP 自动化上件调度桥接器"""

    @staticmethod
    def publish_product_to_erp(product_id: int) -> Dict[str, Any]:
        """
        根据商品 ID 读取全部数据，并执行全流程自动化上件
        """
        product = ProductService.get_product_by_id(product_id)
        if not product:
            return {"success": False, "msg": f"未找到商品 ID: {product_id}"}

        ProductService.update_product_status(product_id, "publishing", "🚀 开始连接浏览器并执行店小秘 ERP 自动化上件...")

        engine = BrowserEngine(port=9222)
        ok, msg = engine.connect(activate=True)
        if not ok:
            ProductService.update_product_status(product_id, "failed", f"连接浏览器失败: {msg}")
            return {"success": False, "msg": f"连接浏览器失败: {msg}"}

        logs = []
        try:
            # 步骤 1: 店铺账号
            store_account = product["store_account"]
            logs.append(f"正在选择【店铺账号】 ➔ 【{store_account}】...")
            engine.select("店铺账号", store_account)
            engine.wait_for_value("站点选择", product.get("site", "日本"), timeout_ms=10000)
            logs.append(f"站点【{product.get('site', '日本')}】加载就绪！")
            time.sleep(0.5)

            # 步骤 2: 产品 ID
            if product.get("product_id_value"):
                engine.select(".form-card-content .ant-select", product.get("product_id_type", "EAN"))
                engine.fill(".form-card-content input.ant-input", product["product_id_value"])
                logs.append(f"配置产品 ID: {product.get('product_id_type')} = {product['product_id_value']}")
                time.sleep(0.5)

            # 步骤 3: 产品标题
            engine.fill("产品标题", product["title"])
            logs.append(f"填入产品标题: {product['title'][:30]}...")
            time.sleep(0.5)

            # 步骤 4: 自动识别产品类型
            if engine.click_button("自动识别产品类型"):
                engine.confirm_modal("确定", timeout_ms=8000)
                logs.append("完成产品分类自动识别与确认！")
            time.sleep(0.5)

            # 步骤 5: 售卖形式 (多变体)
            if product.get("sale_type") == "variation":
                engine.click_radio("多变体")
                logs.append("已勾选【多变体】！")
                time.sleep(0.5)

            # 步骤 6: 品牌
            if product.get("brand"):
                engine.select("品牌", product["brand"])
                logs.append(f"配置品牌: {product['brand']}")
                time.sleep(0.5)

            # 步骤 7: 变种主题
            if product.get("variation_theme"):
                engine.select("变种主题", product["variation_theme"])
                logs.append(f"选择变种主题: {product['variation_theme']}")
                time.sleep(0.8)

            # 步骤 8: 动态添加颜色与尺寸属性选项
            attributes = product.get("attributes", {})
            for color_val in attributes.get("color", []):
                engine.add_variation_option("カラー", color_val)
                logs.append(f"添加颜色选项: {color_val}")
                time.sleep(0.3)

            for size_val in attributes.get("size", []):
                engine.add_variation_option("サイズ", size_val)
                logs.append(f"添加尺寸选项: {size_val}")
                time.sleep(0.3)

            # 步骤 9: 变体表格设置 EAN
            engine.select("#variationInfo table thead th:nth-child(4) .ant-select", "EAN")
            time.sleep(0.5)

            # 步骤 10: 遍历填写变体表格明细
            for var in product.get("variations", []):
                color = var.get("color")
                size = var.get("size")
                if color and size:
                    engine.fill_variation_row(
                        filter_criteria={"颜色": color, "尺寸": size},
                        row_data={
                            "sku": var.get("sku", ""),
                            "ean": var.get("ean", ""),
                            "price": var.get("price_jpy", 0),
                            "quantity": var.get("quantity", 0)
                        }
                    )
                    logs.append(f"填写变体行【{color} / {size}】: SKU={var.get('sku')} 价格={var.get('price_jpy')}")
                    time.sleep(0.2)

            # 步骤 11: 遍历上传变体图片
            for var in product.get("variations", []):
                color = var.get("color")
                size = var.get("size")
                main_img = var.get("main_image")
                swatch_img = var.get("swatch_image")
                extra_imgs = var.get("extra_images", [])

                if (main_img or swatch_img or extra_imgs) and color and size:
                    engine.set_variation_images(
                        filter_criteria={"颜色": color, "尺寸": size},
                        main_image=main_img,
                        swatch_image=swatch_img,
                        extra_images=extra_imgs
                    )
                    logs.append(f"完成变体【{color} / {size}】图片上传！")
                    time.sleep(0.3)

            final_log = "\n".join(logs)
            ProductService.update_product_status(product_id, "published", final_log)
            return {"success": True, "msg": "商品成功全自动发布到店小秘 ERP！", "logs": logs}

        except Exception as e:
            err_msg = f"上件过程中发生异常: {str(e)}"
            logs.append(err_msg)
            ProductService.update_product_status(product_id, "failed", "\n".join(logs))
            return {"success": False, "msg": err_msg, "logs": logs}
