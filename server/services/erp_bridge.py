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

        # 0. 清理上次上件异常卡死后遗留的 Playwright Node 驱动僵尸进程,
        #    否则旧驱动抱着 CDP 连接, 会导致本次上件"打不开页面"
        try:
            from core.browser_manager import cleanup_stale_drivers
            killed = cleanup_stale_drivers()
            if killed:
                emit_log(f"🧹 已清理 {killed} 个上次遗留的浏览器自动化驱动进程 (Node.js 残留)")
        except Exception:
            pass

        # 读取系统管理页配置的 Chrome 9222 用户数据目录 (留空则使用系统默认)
        chrome_user_dir = None
        try:
            from server.database import get_setting
            _dir = (get_setting("chrome_user_data_dir", "") or "").strip()
            if _dir:
                chrome_user_dir = _dir
                emit_log(f"⚙️ 使用系统配置的 Chrome 用户数据目录: {_dir}")
        except Exception:
            pass
        engine = BrowserEngine(port=9222, user_data_dir=chrome_user_dir) if chrome_user_dir else BrowserEngine(port=9222)

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
            # 0.5 关闭店小秘自动弹窗 (公告/活动/提示浮层), 避免遮挡后续表单操作
            try:
                closed_n = engine.close_all_popups()
                if closed_n:
                    emit_log(f"🧹 已自动关闭 {closed_n} 个页面弹窗")
                    time.sleep(0.5)
            except Exception as pop_e:
                print(f"⚠️ 弹窗清理提示: {pop_e}")
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
                
                # 准备图片配置与多源维度图片映射解析
                img_dimension = product.get("variant_image_dimension") or "color"
                dim_images_map = product.get("variant_dimension_images") or {}
                if not dim_images_map and product.get("variant_dimension_images_json"):
                    try:
                        dim_images_map = json.loads(product["variant_dimension_images_json"])
                    except Exception:
                        pass

                # 兜底 1: 尝试从 attributes.color_images / size_images 获取
                if not dim_images_map:
                    attrs = product.get("attributes") or {}
                    if isinstance(attrs, str):
                        try:
                            attrs = json.loads(attrs)
                        except Exception:
                            attrs = {}
                    dim_images_map = (attrs.get("color_images") if img_dimension == "color" else attrs.get("size_images")) or {}

                # 兜底 2: 从变体列表中按维度聚合主图 (同一颜色/尺寸的所有 SKU 提取第一张有效图片)
                if not dim_images_map:
                    dim_images_map = {}
                    for v in product.get("variations", []):
                        d_val = v.get("color") if img_dimension == "color" else v.get("size")
                        v_img = v.get("variant_image") or v.get("main_image")
                        if d_val and v_img and d_val not in dim_images_map:
                            dim_images_map[d_val] = v_img

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

                # 2. 优化后的 SKU 变体图片上传与装配策略 (步骤 1 ➔ 步骤 2 ➔ 步骤 3 ➔ 步骤 4):
                #    步骤 1：先上传第 1 个 SKU 的附图
                #    步骤 2：将第 1 个附图，批量应用到所有 SKU (extra_all)
                #    步骤 3：检查第 2 个 SKU 的附图是否已上传，如果上传则代表附图批量应用成功
                #    步骤 4：从第 1 个 SKU 开始循环检查主图是否为空：
                #           - 如果为空，则上传主图（按照变体选项与对应图片配置，颜色或尺寸上传对应主图）
                #           - 然后批量应用主图到对应的颜色或尺寸的 SKU
                #           - 检查是否批量上传/应用成功
                #           - 然后继续遍历到下一个主图为空的 SKU，直到遍历所有 SKU
                variations = product.get("variations", [])
                if not variations:
                    emit_log("⚠️ 未检测到变体列表，跳过变体图片装配")
                else:
                    has_dim_images = bool(dim_images_map)
                    applied_dim_values = set()
                    extra_applied = False
                    dim_label = "カラー(颜色)" if img_dimension == "color" else "サイズ(尺寸)"
                    main_apply_type = "main_color" if img_dimension == "color" else "main_size"
                    if len(dim_images_map) <= 1:
                        main_apply_type = "main_all"
                    emit_log(f"     ℹ️ 变体 SKU 图片录入维度判定为: 【{dim_label}】，配置有效主图 {len(dim_images_map)} 张")

                    first_card = variations[0]
                    # 获取店小秘页面中实际渲染的变体卡片列表 (保证与店小秘 DOM 顺序严格一致)
                    dxm_cards = engine.get_dianxiaomi_variation_cards()
                    if not dxm_cards:
                        dxm_cards = [{"idx": i, "color": v.get("color", ""), "size": v.get("size", ""), "text": ""} for i, v in enumerate(variations)]
                    
                    first_dxm = dxm_cards[0]
                    first_col = first_dxm.get("color") or first_card.get("color", "")
                    first_sz = first_dxm.get("size") or first_card.get("size", "")
                    first_dim_val = first_col if img_dimension == "color" else first_sz
                    
                    first_crit = {}
                    if first_col:
                        first_crit["颜色"] = first_col
                    if first_sz:
                        first_crit["尺寸"] = first_sz

                    # =========================================================================
                    # 步骤 1：先上传第 1 个 SKU 的附图（按店小秘第 1 个卡片）
                    # =========================================================================
                    if parent_extra_abs_files:
                        emit_log(f"   [步骤 1/4] 正在为店小秘第 1 个 SKU【{first_col} / {first_sz}】上传附图 ({len(parent_extra_abs_files)} 张)...")
                        extra_up_ok = False
                        for up_att in range(2):
                            extra_up_ok = engine.upload_variation_image(first_crit, parent_extra_abs_files, "extra", timeout_ms=60000)
                            if extra_up_ok and engine.verify_variation_image_uploaded(first_crit, "extra", len(parent_extra_abs_files)):
                                extra_up_ok = True
                                break
                            time.sleep(0.5)
                        emit_log(f"      ➔ {'✅ 第 1 个 SKU 附图上传并校验成功' if extra_up_ok else '⚠️ 第 1 个 SKU 附图上传未通过校验'}")

                        # =========================================================================
                        # 步骤 2 & 步骤 3：将第 1 个附图批量应用所有 SKU，并检查第 2 个 SKU 的附图是否已上传生效
                        # =========================================================================
                        emit_log("   [步骤 2/4 & 3/4] 正在执行【附图 ➔ 所有变体】批量应用，并检查第 2 个 SKU 附图生效状态...")
                        for att in range(2):
                            if engine.apply_variation_image(first_crit, "extra_all", timeout_ms=15000, verify_success=True, log_callback=emit_log):
                                extra_applied = True
                                break
                            time.sleep(1.0)
                        
                        if extra_applied:
                            emit_log("      ➔ ✅ 附图批量应用成功（第 2 个 SKU 附图已确认就绪）！")
                        else:
                            emit_log("      ⚠️ 附图批量应用未通过校验")
                    else:
                        emit_log("   [步骤 1~3/4] ℹ️ 未配置商品附图，跳过附图上传与批量应用")

                    # =========================================================================
                    # 步骤 4：按照店小秘中的 SKU 顺序逐个遍历主图：
                    #        - 打印当前是店小秘中第几个 SKU、主图是否已上传
                    #        - 若已上传则直接跳过
                    #        - 若未上传，打印执行上传，然后打印上传后的结果
                    #        - 上传成功后执行批量应用（不检查批量结果），然后进行下一条处理
                    # =========================================================================
                    total_skus = len(dxm_cards)
                    emit_log(f"\n   [步骤 4/4] 正在按店小秘页面顺序逐个遍历所有 SKU (共 {total_skus} 个) 主图状态，按【{dim_label}】上传并批量应用...")
                    
                    for card_idx, card_info in enumerate(dxm_cards):
                        current_sku_num = card_idx + 1
                        target_col = card_info.get("color") or ""
                        target_sz = card_info.get("size") or ""

                        matched_var = next((v for v in variations if (not target_col or v.get("color") == target_col) and (not target_sz or v.get("size") == target_sz)), None)
                        if not matched_var and card_idx < len(variations):
                            matched_var = variations[card_idx]
                        if not target_col and matched_var:
                            target_col = matched_var.get("color", "")
                        if not target_sz and matched_var:
                            target_sz = matched_var.get("size", "")

                        target_sku_code = matched_var.get("sku", "") if matched_var else ""
                        target_dim_val = target_col if img_dimension == "color" else target_sz

                        target_crit = {}
                        if target_col:
                            target_crit["颜色"] = target_col
                        if target_sz:
                            target_crit["尺寸"] = target_sz

                        emit_log(f"\n   -------------------------------------------------------------")
                        emit_log(f"   📌 [店小秘 SKU {current_sku_num}/{total_skus}] 变体属性: 【颜色={target_col or '-'} / 尺寸={target_sz or '-'}】(SKU: {target_sku_code or '-'})")

                        # 检查当前卡片是否已上传主图
                        is_uploaded = engine.is_variation_card_main_uploaded(filter_criteria=target_crit, card_idx=card_idx)
                        
                        if is_uploaded:
                            emit_log(f"      ➔ 当前主图状态: 【已上传】（已存在/同{dim_label}批量应用已同步）➔ 直接跳过，处理下一个 SKU")
                            continue
                        else:
                            emit_log(f"      ➔ 当前主图状态: 【未上传】➔ 准备执行上传...")

                        t_main_path = dim_images_map.get(target_dim_val) or (matched_var.get("variant_image") if matched_var else "") or (matched_var.get("main_image") if matched_var else "") or ""
                        t_abs_main = FileService.resolve_image_path(t_main_path) if t_main_path else ""

                        if not t_abs_main or not os.path.exists(t_abs_main):
                            # 尝试使用商品主图兜底
                            if product.get("main_image"):
                                p_main_abs = FileService.resolve_image_path(product["main_image"])
                                if p_main_abs and os.path.exists(p_main_abs):
                                    t_abs_main = p_main_abs

                        if t_abs_main and os.path.exists(t_abs_main):
                            # ① 执行上传
                            img_filename = os.path.basename(t_abs_main)
                            emit_log(f"      ➔ 执行上传: 正在上传对应【{dim_label}: {target_dim_val}】的主图文件: {img_filename} ...")
                            t_up_ok = False
                            for up_att in range(2):
                                t_up_ok = engine.upload_variation_image(target_crit, t_abs_main, "main", timeout_ms=30000)
                                if t_up_ok and engine.verify_variation_image_uploaded(target_crit, "main", 1):
                                    t_up_ok = True
                                    break
                                time.sleep(0.5)

                            # 打印上传后的结果
                            if t_up_ok:
                                emit_log(f"      ➔ 上传后的结果: ✅ 上传成功")
                                # ② 执行批量应用，启用毫秒级极速抽样校验
                                emit_log(f"      ➔ 执行批量应用: 正在批量应用【主图 ➔ 同{dim_label}的变种】...")
                                apply_ok = engine.apply_variation_image(target_crit, main_apply_type, timeout_ms=8000, verify_success=True, log_callback=emit_log)
                                if apply_ok:
                                    emit_log(f"      ➔ 批量应用已执行生效 ➔ 进行下一条处理")
                                else:
                                    emit_log(f"      ➔ 批量应用执行完成 ➔ 进行下一条处理")
                                if target_dim_val:
                                    applied_dim_values.add(target_dim_val)
                            else:
                                emit_log(f"      ➔ 上传后的结果: ❌ 上传失败（未通过校验）➔ 进行下一条处理")
                        else:
                            emit_log(f"      ➔ 执行上传: ⚠️ 未找到对应的主图文件（{t_main_path}）➔ 跳过并进行下一条处理")
                        time.sleep(0.3)

                    # 3. 最终变体图片装配完整度体检报告与逐卡片清单输出
                    summary = engine.verify_all_variation_images_summary()
                    total_c = summary.get("total", len(variations))
                    with_m = summary.get("withMain", len(applied_dim_values))
                    with_e = summary.get("withExtra", total_c if extra_applied else 0)
                    emit_log(f"\n📊 [变体图片装配完整度检查] 全部变体卡片共 {total_c} 个：已装配主图 {with_m}/{total_c}，已装配附图 {with_e}/{total_c}")
                    emit_log("   📋 全变体图片最终装配明细:")
                    for c in summary.get("cards", []):
                        c_spec = c.get("text", "").replace("变种属性:", "").replace("图片应用到", "").strip()
                        m_status = "✅" if c.get("mainCount", 0) > 0 else "❌"
                        e_status = "✅" if c.get("extraCount", 0) > 0 else "❌"
                        emit_log(f"      • SKU #{c.get('idx', 0):02d}【{c_spec}】: 主图 {c.get('mainCount', 0)} 张 ({m_status}) | 附图 {c.get('extraCount', 0)} 张 ({e_status})")

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

            # 3. 商品长描述 (Description) — 多行描述且无序号时自动按行补 1. 2. 3. 序号
            desc_text = product.get("description", "").strip()
            if desc_text:
                desc_lines = [ln.strip() for ln in desc_text.split("\n") if ln.strip()]
                if len(desc_lines) >= 2:
                    import re as _re
                    numbered = sum(1 for ln in desc_lines if _re.match(r"^\d+[\.、]", ln))
                    if numbered < len(desc_lines) - 1:  # 大部分行没有序号才补
                        desc_text = "\n".join(f"{i}. {ln}" for i, ln in enumerate(desc_lines, 1))
                        emit_log("ℹ️ 描述多行无序号，已自动添加序号 (1. 2. 3. ...)")
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
        finally:
            # 自愈: 上件结束后检测调度线程是否卡死 (页面卡住/驱动失联),
            # 卡死则强杀 Node 驱动并重建线程, 保证下一次上件不再"打不开页面";
            # 正常则优雅关闭, 避免 Playwright 驱动进程残留
            try:
                if engine.manager.is_healthy(timeout=5):
                    engine.manager.close()
                else:
                    emit_log("🧹 检测到浏览器自动化线程卡死，已强制清理残留驱动进程")
                    engine.manager.hard_reset()
            except Exception:
                try:
                    engine.manager.hard_reset()
                except Exception:
                    pass
