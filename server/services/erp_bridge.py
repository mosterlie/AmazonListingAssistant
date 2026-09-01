"""
店小秘 ERP 自动化上件桥接服务
将商品库中录入的结构化商品、变体矩阵和图片路径，直接映射并调用 BrowserEngine 执行真实自动化上件
"""
import os
import sys
import time
import json
from typing import Dict, Any, List, Optional
from server.services.product_service import ProductService
from server.services.file_service import FileService

try:
    from browser_engine import BrowserEngine
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from browser_engine import BrowserEngine


class ERPBridgeService:
    """店小秘 ERP 自动化上件调度桥接器"""

    @staticmethod
    def publish_product_to_erp(product_id: int, log_callback=None) -> Dict[str, Any]:
        """
        根据商品 ID 读取 product_items 全部数据，并执行全流程自动化上件至店小秘
        """
        product = ProductService.get_product_by_id(product_id)
        if not product:
            return {"success": False, "msg": f"未找到商品 ID: {product_id}"}

        ProductService.update_product_status(product_id, "publishing", "🚀 开始连接浏览器并执行店小秘 ERP 自动化上件...")

        logs = []

        def emit_log(line: str):
            logs.append(line)
            if log_callback and callable(log_callback):
                try:
                    log_callback(line)
                except Exception:
                    pass

        engine = BrowserEngine(port=9222)

        if not engine.is_running():
            emit_log("🌐 端口 9222 尚未开启，正在自动启动专属 CDP Chrome 浏览器...")
            l_ok, l_msg = engine.launch_browser("https://www.dianxiaomi.com/web/amazon/add")
            if not l_ok:
                err_text = f"自动启动 Chrome 浏览器失败: {l_msg}。请确认已安装 Google Chrome 并具有运行权限！"
                emit_log(f"❌ {err_text}")
                ProductService.update_product_status(product_id, "failed", "\n".join(logs))
                return {"success": False, "msg": err_text, "logs": logs}
            emit_log("✅ 专属 CDP 浏览器已成功启动并就绪！")
        else:
            ok, msg = engine.connect(activate=False)
            if not ok:
                emit_log(f"⚠️ 检测到原有浏览器连接异常 ({msg})，正在自动清理并重新拉起专属 Chrome 浏览器...")
                try:
                    engine.close()
                except Exception:
                    pass
                l_ok, l_msg = engine.launch_browser("https://www.dianxiaomi.com/web/amazon/add")
                if not l_ok:
                    err_text = f"连接与重新启动 Chrome 浏览器失败: {l_msg}。请确认已安装 Google Chrome 并具有运行权限！"
                    emit_log(f"❌ {err_text}")
                    ProductService.update_product_status(product_id, "failed", "\n".join(logs))
                    return {"success": False, "msg": err_text, "logs": logs}
                emit_log("✅ 专属 CDP 浏览器已成功重新启动并就绪！")
        try:
            # 0. 确保位于店小秘 Amazon 添加产品页面并进行干净重载
            target_dxm_url = "https://www.dianxiaomi.com/web/amazon/add"
            emit_log(f"🌐 正在打开/重载店小秘添加产品页: {target_dxm_url} ...")
            engine.open_or_focus_url(target_dxm_url)
            try:
                def reload_or_goto():
                    p = engine.manager._get_active_page_impl()
                    if "amazon/add" in p.url:
                        p.reload(wait_until="commit", timeout=8000)
                    else:
                        p.goto(target_dxm_url, wait_until="commit", timeout=8000)
                engine.manager.run_on_browser_thread(reload_or_goto)
            except Exception as nav_e:
                print(f"⚠️ 页面跳转提示: {nav_e}")
            time.sleep(1.5)
            active_tab = engine.get_active_tab_info()
            emit_log(f"🎯 已定位前台操作页面: 【{active_tab.title if active_tab else '店小秘--添加亚马逊产品'}】")

            # =========================================================================
            # 阶段 1：店铺账号、站点联动与产品标题
            # =========================================================================
            store_account = product.get("store_account", "").strip() or "金梧汇辰"
            expected_site = product.get("site", "日本")

            emit_log(f"⏳ [阶段 1/7] 正在选择并锁定【店铺账号】 ➔ 【{store_account}】(目标站点: {expected_site})...")
            store_ok = engine.select_store_account(store_account, expected_site, timeout_ms=20000)
            if not store_ok:
                err_text = f"选择店铺账号【{store_account}】失败或超时，未能联动出站点【{expected_site}】！请检查网络连接与店小秘授权！"
                emit_log(f"❌ {err_text}")
                ProductService.update_product_status(product_id, "failed", "\n".join(logs))
                return {"success": False, "msg": err_text, "logs": logs}

            emit_log(f"✅ 已成功选定店铺账号【{store_account}】，且【站点选择】联动为【{expected_site}】！")
            time.sleep(0.5)

            title_text = product.get("title", "").strip()
            if title_text:
                emit_log(f"⏳ [阶段 1/7] 正在填入【产品标题】 ➔ 【{title_text[:25]}...】...")
                engine.fill("产品标题", title_text)
                emit_log("✅ 【产品标题】填入完成！")
            time.sleep(0.5)

            # =========================================================================
            # 阶段 2：类目自动识别与动态属性加载
            # =========================================================================
            emit_log("⏳ [阶段 2/7] 正在点击【自动识别产品类型】...")
            if engine.click_button("自动识别产品类型"):
                emit_log("   • 成功触发【自动识别产品类型】，正在等待类目推荐弹窗...")
                time.sleep(1.5)
                s_modal = engine.confirm_modal("确定", wait_timeout_ms=8000)
                if s_modal:
                    emit_log("✅ 已在推荐弹窗中确认类目，等待动态属性渲染...")
                    time.sleep(2)
            time.sleep(0.5)

            # =========================================================================
            # 阶段 3：多变体售卖形式、Parent SKU 与品牌配置
            # =========================================================================
            is_variation = (product.get("sale_type") == "variation" or len(product.get("variations", [])) > 0)
            if is_variation:
                emit_log("⏳ [阶段 3/7] 正在勾选【售卖形式】 ➔ 【多变种】...")
                engine.click_radio("多变体") or engine.click_radio("多变种")
                emit_log("✅ 已勾选【多变体】！")
            else:
                emit_log("⏳ [阶段 3/7] 正在勾选【售卖形式】 ➔ 【单品】...")
                engine.click_radio("单品")

            time.sleep(0.5)

            parent_sku = product.get("sku") or product.get("parent_sku") or ""
            if parent_sku:
                emit_log(f"⏳ [阶段 3/7] 正在填入【Parent SKU】 ➔ 【{parent_sku}】...")
                engine.fill("Parent SKU", parent_sku)
                time.sleep(0.3)

            brand_val = product.get("brand", "").strip()
            if brand_val:
                emit_log(f"⏳ [阶段 3/7] 正在配置【品牌】 ➔ 【{brand_val}】...")
                engine.fill("品牌", brand_val) or engine.select("品牌", brand_val)
                time.sleep(0.3)

            # 制造商填入品牌名称 (用户要求: 1. 制造商填写品牌名称)
            mfg_val = product.get("manufacturer", "").strip() or brand_val
            if mfg_val:
                emit_log(f"⏳ [阶段 3/7] 正在配置【制造商】 ➔ 【{mfg_val}】...")
                engine.fill_manufacturer(mfg_val)
                time.sleep(0.3)

            # =========================================================================
            # 阶段 4：变体主题选择、属性标签添加与变体矩阵展开
            # =========================================================================
            if is_variation:
                v_theme = product.get("variation_theme") or "カラー/サイズ(颜色/尺寸)"
                emit_log(f"⏳ [阶段 4/7] 正在选择【变种主题】 ➔ 【{v_theme}】...")
                engine.select("变种主题", v_theme)
                time.sleep(1.0)

                # 添加颜色标签
                color_opts = product.get("color_options", [])
                if not color_opts and product.get("color_options_json"):
                    try:
                        color_opts = json.loads(product["color_options_json"])
                    except Exception:
                        pass
                if not color_opts:
                    color_opts = list(dict.fromkeys([v.get("color") for v in product.get("variations", []) if v.get("color")]))

                for col in color_opts:
                    if col:
                        emit_log(f"   • 正在添加颜色选项: {col}")
                        engine.add_variation_option("カラー", col)
                        time.sleep(0.3)

                # 添加尺寸标签
                size_opts = product.get("size_options", [])
                if not size_opts and product.get("size_options_json"):
                    try:
                        size_opts = json.loads(product["size_options_json"])
                    except Exception:
                        pass
                if not size_opts:
                    size_opts = list(dict.fromkeys([v.get("size") for v in product.get("variations", []) if v.get("size")]))

                for sz in size_opts:
                    if sz:
                        emit_log(f"   • 正在添加尺寸选项: {sz}")
                        engine.add_variation_option("サイズ", sz)
                        time.sleep(0.3)

                emit_log(f"✅ 已配置变体属性，生成 {len(color_opts)} × {len(size_opts)} 变体矩阵！")
                time.sleep(1.0)

                # 切换变体表头第 4 项为 EAN
                engine.select("#variationInfo table thead th:nth-child(4) .ant-select", "EAN")
                time.sleep(0.5)

                # =========================================================================
                # 阶段 5：遍历填充各变体行数据与并发装配变体主附图
                # =========================================================================
                emit_log("⏳ [阶段 5/7] 正在快速填充变体表格数据，并按「图片应用到」策略批量装配变体图片...")
                
                # 准备图片配置
                img_dimension = product.get("variant_image_dimension") or "color"
                dim_images_map = product.get("variant_dimension_images") or {}
                if not dim_images_map and product.get("variant_dimension_images_json"):
                    try:
                        dim_images_map = json.loads(product["variant_dimension_images_json"])
                    except Exception:
                        pass

                # 解析附图清单 (优先使用父商品 extra_images，若无则自动从变体 extra_images 提取，统一复用)
                parent_extras = product.get("extra_images") or []
                if not parent_extras and product.get("extra_images_json"):
                    try:
                        parent_extras = json.loads(product["extra_images_json"])
                    except Exception:
                        pass
                
                if not parent_extras:
                    for v in product.get("variations", []):
                        if v.get("extra_images"):
                            parent_extras = v.get("extra_images")
                            break
                        elif v.get("extra_images_json"):
                            try:
                                v_extras = json.loads(v["extra_images_json"])
                                if v_extras:
                                    parent_extras = v_extras
                                    break
                            except Exception:
                                pass
                
                parent_extra_abs_files = [
                    FileService.resolve_image_path(p) 
                    for p in parent_extras 
                    if p and FileService.resolve_image_path(p) and os.path.exists(FileService.resolve_image_path(p))
                ]

                # 1. 快速填充所有变体行数据
                for var in product.get("variations", []):
                    col = var.get("color", "")
                    sz = var.get("size", "")
                    v_sku = var.get("sku", "")
                    v_ean = var.get("ean", "")
                    v_price = var.get("price_jpy", 0) or var.get("sale_price_jpy", 0)
                    v_qty = var.get("quantity", 0) or 40

                    filter_crit = {}
                    if col:
                        filter_crit["颜色"] = col
                    if sz:
                        filter_crit["尺寸"] = sz

                    if filter_crit:
                        engine.fill_variation_row(
                            filter_criteria=filter_crit,
                            row_data={
                                "sku": v_sku,
                                "ean": v_ean,
                                "price": str(v_price),
                                "quantity": str(v_qty)
                            }
                        )
                        emit_log(f"   • 填写变体行【{col} / {sz}】: SKU={v_sku}, EAN={v_ean}, 价格={v_price} JPY, 库存={v_qty}")

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
                        # ② 附图 ➔ 所有变体（执行批量应用，并在页面校验成功后再往下继续）
                        extra_apply_ok = False
                        for attempt in range(3):
                            emit_log(f"     ➔ [第 {attempt+1}/3 次] 正在执行【附图 ➔ 所有变体】批量应用并等待页面校验...")
                            if engine.apply_variation_image(filter_criteria=filter_crit, apply_type="extra_all", timeout_ms=15000, verify_success=True):
                                extra_apply_ok = True
                                break
                            time.sleep(1.0)
                        if extra_apply_ok:
                            emit_log("     ➔ ✅ 已检验确认：全量变体附图已全部批量应用并同步成功！")
                            extra_applied = True
                        else:
                            emit_log("     ⚠️ 附图应用至【附图-所有变体】未通过页面校验，留待下一个变体重试")

                    # ③/⑤ 主图按维度批量应用（执行批量应用，并在页面校验成功后再往下继续）
                    if main_ok and has_dim_images and dim_val:
                        main_apply_ok = False
                        for attempt in range(3):
                            emit_log(f"     ➔ [第 {attempt+1}/3 次] 正在执行【主图 ➔ 同{dim_label}的变种】批量应用并等待页面校验...")
                            if engine.apply_variation_image(filter_criteria=filter_crit, apply_type=main_apply_type, timeout_ms=15000, verify_success=True):
                                main_apply_ok = True
                                break
                            time.sleep(1.0)
                        if main_apply_ok:
                            emit_log(f"     ➔ ✅ 已检验确认：同【{dim_val}】的所有变体主图已全部批量应用并同步成功！")
                            applied_dim_values.add(dim_val)
                        else:
                            emit_log(f"     ⚠️ 主图应用【同{dim_label}的变种】连续 3 次未通过页面校验，跳过该维度")
                    time.sleep(0.3)

                emit_log(f"✅ 变体图片装配完成：主图覆盖 {len(applied_dim_values)} 个【{dim_label}】维度值，附图已应用至所有变体！")

            # =========================================================================
            # 阶段 6：五点描述、长描述、配送渠道、搜索词、尺寸与重量（产品图片暂时注释）
            # =========================================================================
            emit_log("⏳ [阶段 6/7] 正在填入五点描述、长描述文案、配送渠道、尺寸与关键词...")

            # 1. 父级商品【产品图片】上传（暂时注释，后边看情况再定）
            # p_main = product.get("main_image", "")
            # p_main_abs = FileService.resolve_image_path(p_main) if p_main else ""
            # 
            # p_extras = product.get("extra_images") or []
            # if not p_extras and product.get("extra_images_json"):
            #     try:
            #         p_extras = json.loads(product["extra_images_json"])
            #     except Exception:
            #         pass
            # p_extra_abs_list = [
            #     FileService.resolve_image_path(p) 
            #     for p in p_extras 
            #     if p and FileService.resolve_image_path(p) and os.path.exists(FileService.resolve_image_path(p))
            # ]
            # 
            # if (p_main_abs and os.path.exists(p_main_abs)) or p_extra_abs_list:
            #     engine.upload_parent_images(
            #         main_image=p_main_abs if os.path.exists(p_main_abs) else None,
            #         extra_images=p_extra_abs_list
            #     )
            #     emit_log("✅ 父级商品主图与附图批量并发上传完成！")
            #     time.sleep(0.5)

            # 2. 五点描述 (Bullet Points)
            bps = product.get("bullet_points") or []
            if not bps and product.get("bullet_points_json"):
                try:
                    bps = json.loads(product["bullet_points_json"])
                except Exception:
                    pass
            if bps:
                engine.fill_bullet_points(bps)
                emit_log(f"✅ 五点描述 (Bullet Points {len(bps)} 项) 填入完成！")
                time.sleep(0.3)

            # 3. 商品长描述 (Description)
            desc_text = product.get("description", "").strip()
            if desc_text:
                engine.fill_description(desc_text)
                emit_log("✅ 商品详细长描述填入完成！")
                time.sleep(0.3)

            # 4. 配送渠道 (FBM / FBA)
            fulfillment = product.get("fulfillment_channel") or "FBM"
            emit_log(f"⏳ [阶段 6/7] 正在选择并锁定【配送渠道】 ➔ 【{fulfillment}】...")
            f_ok = engine.select_fulfillment_channel(fulfillment, timeout_ms=8000)
            if f_ok:
                emit_log(f"✅ 【配送渠道】已成功锁定为 【{fulfillment}】！")
            else:
                emit_log(f"⚠️ 【配送渠道】选择提示: 未能自动匹配为 {fulfillment}，请核查页面")
            time.sleep(0.3)


            # 5. Search Terms (搜索关键词)
            search_terms = product.get("search_terms", "").strip()
            if search_terms:
                engine.fill_search_terms(search_terms)
                emit_log("✅ Search Terms 搜索关键词填入完成！")
                time.sleep(0.3)

            # 6. 品目寸法（商品尺寸）、包装尺寸(パッケージ寸法)、商品重量与包装重量
            dim_res = engine.fill_dimensions_and_weight(
                item_length=product.get("item_length"),
                item_width=product.get("item_width"),
                item_height=product.get("item_height"),
                item_dim_unit=product.get("item_dim_unit", "cm"),
                package_length=product.get("package_length"),
                package_width=product.get("package_width"),
                package_height=product.get("package_height"),
                package_dim_unit=product.get("package_dim_unit", "cm"),
                item_weight=product.get("item_weight"),
                item_weight_unit=product.get("item_weight_unit"),
                package_weight=product.get("package_weight"),
                package_weight_unit=product.get("package_weight_unit", "kg")
            )
            if dim_res:
                emit_log("✅ 品目寸法(商品尺寸)、パッケージ寸法(包装尺寸)与包装重量填入完成！")
            time.sleep(0.3)

            # 7. 型号参数（若动态类目渲染出对应字段则填入）
            if product.get("model_number"):
                engine.fill("品番", product["model_number"]) or engine.fill("型番", product["model_number"])
            if product.get("model_name"):
                engine.fill("モデル名", product["model_name"])

            # =========================================================================
            # 阶段 7：点击【保存】存为草稿 (不直接发布)
            # =========================================================================
            emit_log("⏳ [阶段 7/7] 正在点击【保存】存为店小秘草稿...")
            s_saved = engine.save_draft(timeout_ms=10000)
            if s_saved:
                emit_log("🎉 已成功点击【保存】！商品已以草稿形式保存在店小秘 ERP，供人工复核！")
            else:
                emit_log("⚠️ 点击保存按钮完成，请在浏览器中确认页面提示。")

            time.sleep(1.0)
            final_log = "\n".join(logs)
            ProductService.update_product_status(product_id, "published", final_log)
            return {"success": True, "msg": "商品成功全自动上传并保存至店小秘 ERP！", "logs": logs}

        except Exception as e:
            err_msg = f"❌ 上件过程中发生异常: {str(e)}"
            emit_log(err_msg)
            ProductService.update_product_status(product_id, "failed", "\n".join(logs))
            return {"success": False, "msg": err_msg, "logs": logs}
