import json
import itertools
from typing import List, Dict, Any, Optional
from server.database import get_db_connection
from server.models.product_schemas import ProductCreateSchema, VariationItemSchema, GenerateMatrixRequest
from server.services.ean_service import EANService
from server.services.pricing_service import PricingService


class ProductService:
    """提供商品录入、变体矩阵计算、详情查询、列表获取与状态流转服务"""

    @staticmethod
    def generate_variation_matrix(req: GenerateMatrixRequest) -> List[Dict[str, Any]]:
        """
        根据选中的颜色和尺寸列表，自动计算笛卡尔积组合，生成变体明细矩阵并自动赋予符合规范的唯一 EAN-13 条码与智能核算售价
        """
        colors = req.colors if req.colors else [""]
        sizes = req.sizes if req.sizes else [""]
        base_sku = (req.base_sku or "DOG-TOILET").strip()  # 保持父 SKU 原样 (含大小写), 子 SKU 需与其保持一致

        combinations = list(itertools.product(colors, sizes))
        generated_eans = EANService.generate_batch_eans(len(combinations))
        # 序号宽度: 默认两位 (01、02...), 组合数达到三位数时自动升级为三位 (001、002...), 支持 999 个变体
        seq_width = 3 if len(combinations) >= 100 else 2
        variations = []
        for idx, (color, size) in enumerate(combinations):
            # 子 SKU 生成规则: 父 SKU + "-" + 序号 (如父 SKU 为 admin25-DogToilet -> admin25-DogToilet-01、admin25-DogToilet-02...)
            generated_sku = f"{base_sku}-{idx + 1:0{seq_width}d}"

            ean_val = generated_eans[idx] if idx < len(generated_eans) else EANService.generate_single_ean()

            variations.append({
                "sku": generated_sku,
                "ean": ean_val,
                "color": color,
                "size": size,
                "condition": "新品",
                "description": "",
                "price_jpy": 0,
                "quantity": req.base_quantity or 40,
                "sale_price_jpy": 0.0,
                "length_cm": 0.0,
                "width_cm": 0.0,
                "height_cm": 0.0,
                "weight": 0.0,
                "purchase_price": req.base_purchase_price or 0.0,
                "profit_coefficient": req.base_profit_coefficient or 1.0,
                "optimal_channel": "",
                "optimal_freight": 0.0,
                "selected_channel": "",
                "selected_freight": 0.0,
                "main_image": "",
                "swatch_image": "",
                "extra_images": []
            })
        return variations

    @staticmethod
    def export_and_prepare_product_files(data: ProductCreateSchema) -> Dict[str, Any]:
        """
        在保存入库前，将上传的临时图片归档至系统配置的本地目标存储目录，并返回归档后的相对路径：
        - 根目录：<base_dir>/<clean_title>/
        - 主图：<clean_title>/<rel_main>/main.<ext>
        - 附图：<clean_title>/<rel_main>/pt01.<ext>, pt02.<ext>...
        - SKU/属性图片：<clean_title>/<rel_sku>/颜色-xxx.<ext> 或 尺寸-xxx.<ext>
        """
        import os
        import re
        import shutil
        import platform
        from server.database import get_setting
        from server.services.file_service import FileService

        is_win = (platform.system().lower() == "windows")
        default_path = "D:\\products" if is_win else "/Users/gx/Desktop/products"
        setting_key = "storage_path_win" if is_win else "storage_path_mac"
        base_dir = get_setting(setting_key, default_path)

        rel_main = (get_setting("storage_rel_main", "main") or "main").strip().strip("/\\") or "main"
        rel_sku = (get_setting("storage_rel_sku", "sku") or "sku").strip().strip("/\\") or "sku"

        clean_title = re.sub(r'[\\/*?:"<>|]', '_', data.title).strip() or "untitled_product"
        product_dir = os.path.join(base_dir, clean_title)
        main_dir = os.path.join(product_dir, rel_main)
        sku_dir = os.path.join(product_dir, rel_sku)

        try:
            os.makedirs(main_dir, exist_ok=True)
            os.makedirs(sku_dir, exist_ok=True)
        except Exception as e:
            print(f"⚠️ 创建本地归档目录失败: {e}")

        def safe_copy(src_path, dest_path):
            if not src_path or not os.path.exists(src_path):
                return
            try:
                if os.path.abspath(src_path) != os.path.abspath(dest_path):
                    shutil.copy2(src_path, dest_path)
            except Exception as e:
                print(f"⚠️ 复制文件失败: {e}")

        # 1. 导出主图
        exported_main = ""
        if data.main_image and data.main_image.strip():
            src_main = FileService.resolve_image_path(data.main_image)
            ext = os.path.splitext(data.main_image)[1].lower() or ".jpg"
            dest_main = os.path.join(main_dir, f"main{ext}")
            safe_copy(src_main, dest_main)
            exported_main = f"{clean_title}/{rel_main}/main{ext}"

        # 2. 导出附图
        exported_extra = []
        if data.extra_images:
            for idx, img_path in enumerate(data.extra_images, 1):
                if img_path and img_path.strip():
                    src_extra = FileService.resolve_image_path(img_path)
                    ext = os.path.splitext(img_path)[1].lower() or ".jpg"
                    dest_extra = os.path.join(main_dir, f"pt{idx:02d}{ext}")
                    safe_copy(src_extra, dest_extra)
                    exported_extra.append(f"{clean_title}/{rel_main}/pt{idx:02d}{ext}")

        # 3. 导出 Card 6 属性维度映射图片
        exported_dim_images = {}
        var_dim = (data.variant_image_dimension or "").strip().lower()
        if not var_dim:
            if data.attributes.get("size_images") and not data.attributes.get("color_images"):
                var_dim = "size"
            else:
                var_dim = "color"

        dim_imgs = data.variant_dimension_images if data.variant_dimension_images else (
            data.attributes.get("size_images") if var_dim == "size" else (data.attributes.get("color_images") or {})
        )
        prefix = "颜色" if var_dim == "color" else "尺寸"

        if isinstance(dim_imgs, dict):
            for attr_val, img_path in dim_imgs.items():
                if img_path and str(img_path).strip():
                    src_dim = FileService.resolve_image_path(str(img_path))
                    ext = os.path.splitext(str(img_path))[1].lower() or ".jpg"
                    clean_val = re.sub(r'[\\/*?:"<>|]', '_', str(attr_val)).strip()
                    dest_dim = os.path.join(sku_dir, f"{prefix}-{clean_val}{ext}")
                    safe_copy(src_dim, dest_dim)
                    exported_dim_images[str(attr_val)] = f"{clean_title}/{rel_sku}/{prefix}-{clean_val}{ext}"

        # 4. 导出各个子变体图片
        exported_variation_images = []
        for idx, v in enumerate(data.variations):
            v_img = v.variant_image or v.main_image or ""
            rel_v_img = ""
            if v_img and v_img.strip():
                # 优先匹配维度图片
                if var_dim == "color" and v.color and str(v.color) in exported_dim_images:
                    rel_v_img = exported_dim_images[str(v.color)]
                elif var_dim == "size" and v.size and str(v.size) in exported_dim_images:
                    rel_v_img = exported_dim_images[str(v.size)]
                else:
                    src_v = FileService.resolve_image_path(v_img)
                    ext = os.path.splitext(v_img)[1].lower() or ".jpg"
                    clean_sku = re.sub(r'[\\/*?:"<>|]', '_', str(v.sku)).strip() or f"var_{idx+1}"
                    dest_v = os.path.join(sku_dir, f"{clean_sku}{ext}")
                    safe_copy(src_v, dest_v)
                    rel_v_img = f"{clean_title}/{rel_sku}/{clean_sku}{ext}"
            exported_variation_images.append(rel_v_img)

        # 5. 写入 product_info.json 备份
        try:
            info_path = os.path.join(product_dir, "product_info.json")
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(data.model_dump(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存 product_info.json 异常: {e}")

        return {
            "main_image": exported_main,
            "extra_images": exported_extra,
            "variant_dimension_images": exported_dim_images,
            "variation_images": exported_variation_images,
            "product_dir": product_dir
        }

    @staticmethod
    def create_product(data: ProductCreateSchema, created_by: str = "") -> Dict[str, Any]:
        """创建或保存商品数据到数据库 (支持 product_items 单表层级结构与 sku_ean_mappings，存储导出后的相对路径)"""
        # 1. 先执行本地文件导出归档，生成标准化的导出相对路径
        export_res = ProductService.export_and_prepare_product_files(data)
        saved_main_image = export_res["main_image"] or data.main_image or ""
        saved_extra_images = export_res["extra_images"] if export_res["extra_images"] else (data.extra_images or [])
        var_dim = (data.variant_image_dimension or "").strip().lower()
        if not var_dim:
            if data.attributes.get("size_images") and not data.attributes.get("color_images"):
                var_dim = "size"
            else:
                var_dim = "color"

        saved_dim_images = export_res["variant_dimension_images"] if export_res["variant_dimension_images"] else (
            data.variant_dimension_images or (data.attributes.get("size_images") if var_dim == "size" else (data.attributes.get("color_images") or {}))
        )
        saved_var_images = export_res["variation_images"]

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # 维护人：以登录账号为准 (前端未传时回退请求体或 admin)
            creator = (created_by or data.created_by or "admin").strip() or "admin"

            parent_sku = (data.parent_sku or "").strip()
            if not parent_sku:
                # 默认规则：Parent SKU = 登录账号 + 该账号创建的第几个品 (数字) + "-商品标识翻译"
                identifier = (data.identifier_translation or "").strip().replace(" ", "")
                suffix = f"-{identifier}" if identifier else ""
                cursor.execute(
                    "SELECT COUNT(*) FROM product_items WHERE is_parent = 1 AND created_by = ?",
                    (creator,)
                )
                seq = cursor.fetchone()[0] + 1
                parent_sku = f"{creator}{seq}{suffix}"
                # 防止编号撞车，自动顺延
                while True:
                    cursor.execute(
                        "SELECT COUNT(*) FROM product_items WHERE parent_sku = ? OR sku = ?",
                        (parent_sku, parent_sku)
                    )
                    if cursor.fetchone()[0] == 0:
                        break
                    seq += 1
                    parent_sku = f"{creator}{seq}{suffix}"

            color_opts = data.color_options if data.color_options else data.attributes.get("color", [])
            size_opts = data.size_options if data.size_options else data.attributes.get("size", [])

            # -------------------------------------------------------------
            # 1. 写入精简版单表 product_items
            # -------------------------------------------------------------
            # 先清除同 parent_sku 的旧数据 (便于重复保存/更新)
            cursor.execute("DELETE FROM product_items WHERE parent_sku = ? OR sku = ?", (parent_sku, parent_sku))

            # 1.1 插入父商品记录 (is_parent = 1，保存导出后的相对路径与 brand)
            cursor.execute("""
            INSERT INTO product_items (
                is_parent, parent_sku, sku,
                store_account, brand, title, sale_type,
                model_number, model_name, product_identifier, title_translation, identifier_translation,
                item_length, item_width, item_height, item_dim_unit,
                package_length, package_width, package_height, package_dim_unit,
                package_weight, package_weight_unit,
                main_image, extra_images_json,
                variation_theme, color_options_json, size_options_json,
                variant_image_dimension, variant_dimension_images_json,
                description, bullet_points_json, chinese_translations_json,
                fulfillment_channel, search_terms,
                status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (
                1, parent_sku, parent_sku,
                data.store_account or "", data.brand or "", data.title or "", data.sale_type or "variation",
                data.model_number or "", data.model_name or "", data.product_identifier or "", data.title_translation or "", data.identifier_translation or "",
                float(data.item_length or 0.0), float(data.item_width or 0.0), float(data.item_height or 0.0), data.item_dimension_unit or "cm",
                float(data.package_length or 0.0), float(data.package_width or 0.0), float(data.package_height or 0.0), data.package_dimension_unit or "cm",
                float(data.package_weight or 0.0), data.package_weight_unit or "kg",
                saved_main_image, json.dumps(saved_extra_images, ensure_ascii=False),
                data.variation_theme or "", json.dumps(color_opts, ensure_ascii=False), json.dumps(size_opts, ensure_ascii=False),
                var_dim, json.dumps(saved_dim_images, ensure_ascii=False),
                data.description or "", json.dumps(data.bullet_points or [], ensure_ascii=False), json.dumps(data.chinese_translations or [], ensure_ascii=False),
                data.fulfillment_channel or "FBM", data.search_terms or "",
                "ready", creator
            ))
            parent_item_id = cursor.lastrowid

            # 1.2 插入子变体记录 (is_parent = 0，保存导出后的变体图片相对路径) 与 sku_ean_mappings 映射记录
            for idx, v in enumerate(data.variations):
                v_sku = (v.sku or "").strip()
                v_ean = (v.ean or "").strip()
                v_weight = float(v.weight_kg if v.weight_kg is not None else (v.weight or 0.0))
                v_img = saved_var_images[idx] if idx < len(saved_var_images) and saved_var_images[idx] else (v.variant_image or v.main_image or "")
                v_channel = v.shipping_channel or v.optimal_channel or ""

                cursor.execute("""
                INSERT INTO product_items (
                    is_parent, parent_sku, sku,
                    store_account, brand,
                    variant_image, color, size,
                    length_cm, width_cm, height_cm, weight_kg,
                    purchase_price, profit_coefficient, shipping_channel,
                    price_jpy, quantity, ean,
                    status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    0, parent_sku, v_sku,
                    data.store_account or "", data.brand or "",
                    v_img, v.color or "", v.size or "",
                    float(v.length_cm or 0.0), float(v.width_cm or 0.0), float(v.height_cm or 0.0), v_weight,
                    float(v.purchase_price or 0.0), float(v.profit_coefficient or 1.0), v_channel,
                    float(v.price_jpy or 0.0), int(v.quantity or 0), v_ean,
                    "ready", creator
                ))

                # 插入/更新到 sku_ean_mappings 映射流水表
                if v_sku and v_ean:
                    cursor.execute("""
                    INSERT INTO sku_ean_mappings (sku, ean, parent_sku, store_account, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(sku) DO UPDATE SET
                        ean = excluded.ean,
                        parent_sku = excluded.parent_sku,
                        store_account = excluded.store_account,
                        created_by = excluded.created_by,
                        created_at = CURRENT_TIMESTAMP;
                    """, (v_sku, v_ean, parent_sku, data.store_account or "", creator))

            conn.commit()
            return ProductService.get_product_by_id(parent_item_id)
        finally:
            conn.close()

    @staticmethod
    def update_product(product_id: int, data: ProductCreateSchema) -> Optional[Dict[str, Any]]:
        """更新已有商品及变体数据，保持主键 ID 稳定，更新子变体与关联映射数据"""
        # 1. 先执行本地文件导出归档，生成标准化的导出相对路径
        export_res = ProductService.export_and_prepare_product_files(data)
        saved_main_image = export_res["main_image"] or data.main_image or ""
        saved_extra_images = export_res["extra_images"] if export_res["extra_images"] else (data.extra_images or [])
        var_dim = (data.variant_image_dimension or "").strip().lower()
        if not var_dim:
            if data.attributes.get("size_images") and not data.attributes.get("color_images"):
                var_dim = "size"
            else:
                var_dim = "color"

        saved_dim_images = export_res["variant_dimension_images"] if export_res["variant_dimension_images"] else (
            data.variant_dimension_images or (data.attributes.get("size_images") if var_dim == "size" else (data.attributes.get("color_images") or {}))
        )
        saved_var_images = export_res["variation_images"]

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # 检查父商品是否存在
            cursor.execute("SELECT * FROM product_items WHERE id = ? AND is_parent = 1", (product_id,))
            p_row = cursor.fetchone()
            if not p_row:
                cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
                if not cursor.fetchone():
                    return None

            old_parent = dict(p_row) if p_row else {}
            old_parent_sku = (old_parent.get("parent_sku") or old_parent.get("sku") or "").strip()

            parent_sku = (data.parent_sku or "").strip() or old_parent_sku or "PARENT-SKU"
            color_opts = data.color_options if data.color_options else data.attributes.get("color", [])
            size_opts = data.size_options if data.size_options else data.attributes.get("size", [])

            # 1.1 清理历史子变体 (is_parent = 0)
            if old_parent_sku:
                cursor.execute("DELETE FROM product_items WHERE parent_sku = ? AND is_parent = 0", (old_parent_sku,))
            if parent_sku != old_parent_sku:
                cursor.execute("DELETE FROM product_items WHERE parent_sku = ? AND is_parent = 0", (parent_sku,))

            # 1.2 更新父商品记录 (is_parent = 1)
            if p_row:
                cursor.execute("""
                UPDATE product_items SET
                    parent_sku = ?,
                    sku = ?,
                    store_account = ?,
                    brand = ?,
                    title = ?,
                    sale_type = ?,
                    model_number = ?,
                    model_name = ?,
                    product_identifier = ?,
                    title_translation = ?,
                    identifier_translation = ?,
                    item_length = ?,
                    item_width = ?,
                    item_height = ?,
                    item_dim_unit = ?,
                    package_length = ?,
                    package_width = ?,
                    package_height = ?,
                    package_dim_unit = ?,
                    package_weight = ?,
                    package_weight_unit = ?,
                    main_image = ?,
                    extra_images_json = ?,
                    variation_theme = ?,
                    color_options_json = ?,
                    size_options_json = ?,
                    variant_image_dimension = ?,
                    variant_dimension_images_json = ?,
                    description = ?,
                    bullet_points_json = ?,
                    chinese_translations_json = ?,
                    fulfillment_channel = ?,
                    search_terms = ?,
                    created_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """, (
                    parent_sku, parent_sku,
                    data.store_account or "", data.brand or "", data.title or "", data.sale_type or "variation",
                    data.model_number or "", data.model_name or "", data.product_identifier or "", data.title_translation or "", data.identifier_translation or "",
                    float(data.item_length or 0.0), float(data.item_width or 0.0), float(data.item_height or 0.0), data.item_dimension_unit or "cm",
                    float(data.package_length or 0.0), float(data.package_width or 0.0), float(data.package_height or 0.0), data.package_dimension_unit or "cm",
                    float(data.package_weight or 0.0), data.package_weight_unit or "kg",
                    saved_main_image, json.dumps(saved_extra_images, ensure_ascii=False),
                    data.variation_theme or "", json.dumps(color_opts, ensure_ascii=False), json.dumps(size_opts, ensure_ascii=False),
                    var_dim, json.dumps(saved_dim_images, ensure_ascii=False),
                    data.description or "", json.dumps(data.bullet_points or [], ensure_ascii=False), json.dumps(data.chinese_translations or [], ensure_ascii=False),
                    data.fulfillment_channel or "FBM", data.search_terms or "",
                    data.created_by or old_parent.get("created_by") or "admin",
                    product_id
                ))
            else:
                cursor.execute("""
                INSERT INTO product_items (
                    id, is_parent, parent_sku, sku,
                    store_account, brand, title, sale_type,
                    model_number, model_name, product_identifier, title_translation, identifier_translation,
                    item_length, item_width, item_height, item_dim_unit,
                    package_length, package_width, package_height, package_dim_unit,
                    package_weight, package_weight_unit,
                    main_image, extra_images_json,
                    variation_theme, color_options_json, size_options_json,
                    variant_image_dimension, variant_dimension_images_json,
                    description, bullet_points_json, chinese_translations_json,
                    fulfillment_channel, search_terms,
                    status, created_by, created_at, updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    product_id, parent_sku, parent_sku,
                    data.store_account or "", data.brand or "", data.title or "", data.sale_type or "variation",
                    data.model_number or "", data.model_name or "", data.product_identifier or "", data.title_translation or "", data.identifier_translation or "",
                    float(data.item_length or 0.0), float(data.item_width or 0.0), float(data.item_height or 0.0), data.item_dimension_unit or "cm",
                    float(data.package_length or 0.0), float(data.package_width or 0.0), float(data.package_height or 0.0), data.package_dimension_unit or "cm",
                    float(data.package_weight or 0.0), data.package_weight_unit or "kg",
                    saved_main_image, json.dumps(saved_extra_images, ensure_ascii=False),
                    data.variation_theme or "", json.dumps(color_opts, ensure_ascii=False), json.dumps(size_opts, ensure_ascii=False),
                    var_dim, json.dumps(saved_dim_images, ensure_ascii=False),
                    data.description or "", json.dumps(data.bullet_points or [], ensure_ascii=False), json.dumps(data.chinese_translations or [], ensure_ascii=False),
                    data.fulfillment_channel or "FBM", data.search_terms or "",
                    data.created_by or "admin"
                ))

            # 1.3 插入更新后的子变体记录 (is_parent = 0) 与映射关系
            for idx, v in enumerate(data.variations):
                v_sku = (v.sku or "").strip()
                v_ean = (v.ean or "").strip()
                v_weight = float(v.weight_kg if v.weight_kg is not None else (v.weight or 0.0))
                v_img = saved_var_images[idx] if idx < len(saved_var_images) and saved_var_images[idx] else (v.variant_image or v.main_image or "")
                v_channel = v.shipping_channel or v.optimal_channel or ""

                cursor.execute("""
                INSERT INTO product_items (
                    is_parent, parent_sku, sku,
                    store_account, brand,
                    variant_image, color, size,
                    length_cm, width_cm, height_cm, weight_kg,
                    purchase_price, profit_coefficient, shipping_channel,
                    price_jpy, quantity, ean,
                    status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    0, parent_sku, v_sku,
                    data.store_account or "", data.brand or "",
                    v_img, v.color or "", v.size or "",
                    float(v.length_cm or 0.0), float(v.width_cm or 0.0), float(v.height_cm or 0.0), v_weight,
                    float(v.purchase_price or 0.0), float(v.profit_coefficient or 1.0), v_channel,
                    float(v.price_jpy or 0.0), int(v.quantity or 0), v_ean,
                    "ready", data.created_by or "admin"
                ))

                if v_sku and v_ean:
                    cursor.execute("""
                    INSERT INTO sku_ean_mappings (sku, ean, parent_sku, store_account, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(sku) DO UPDATE SET
                        ean = excluded.ean,
                        parent_sku = excluded.parent_sku,
                        store_account = excluded.store_account,
                        created_by = excluded.created_by,
                        created_at = CURRENT_TIMESTAMP;
                    """, (v_sku, v_ean, parent_sku, data.store_account or "", data.created_by or "admin"))

            conn.commit()
            return ProductService.get_product_by_id(product_id)
        finally:
            conn.close()

    @staticmethod
    def export_product_files(product_id: int, data: ProductCreateSchema):
        """
        当商品保存后，在配置的地址下创建产品名称文件夹，并将图片与信息归档：
        - 根目录：<base_dir>/<产品名称>/
        - 主图：<产品名称>/<rel_main>/main.<ext> (主图命名为 main)
        - 附图：<产品名称>/<rel_main>/pt01.<ext>, pt02.<ext>... (附图按顺序 pt01, pt02...)
        - SKU图片：<产品名称>/<rel_sku>/属性维度-具体属性项.<ext> (如：颜色-红色.jpg, 尺寸-L.jpg)
        - 信息备份：<产品名称>/product_info.json
        """
        try:
            import os
            import re
            import shutil
            import platform
            from server.database import get_setting

            is_win = (platform.system().lower() == "windows")
            default_path = "D:\\products" if is_win else "/Users/gx/Desktop/products"
            setting_key = "storage_path_win" if is_win else "storage_path_mac"
            base_dir = get_setting(setting_key, default_path)

            rel_main = (get_setting("storage_rel_main", "main") or "main").strip().strip("/\\") or "main"
            rel_sku = (get_setting("storage_rel_sku", "sku") or "sku").strip().strip("/\\") or "sku"

            clean_title = re.sub(r'[\\/*?:"<>|]', '_', data.title).strip() or f"product_{product_id}"
            product_dir = os.path.join(base_dir, clean_title)
            main_dir = os.path.join(product_dir, rel_main)
            sku_dir = os.path.join(product_dir, rel_sku)

            os.makedirs(main_dir, exist_ok=True)
            os.makedirs(sku_dir, exist_ok=True)

            if data.main_image and os.path.exists(data.main_image):
                ext = os.path.splitext(data.main_image)[1].lower() or ".jpg"
                dest_main = os.path.join(main_dir, f"main{ext}")
                shutil.copy2(data.main_image, dest_main)

            if data.extra_images:
                for idx, img_path in enumerate(data.extra_images, 1):
                    if img_path and os.path.exists(img_path):
                        ext = os.path.splitext(img_path)[1].lower() or ".jpg"
                        dest_extra = os.path.join(main_dir, f"pt{idx:02d}{ext}")
                        shutil.copy2(img_path, dest_extra)

            color_imgs = data.attributes.get("color_images", {})
            if isinstance(color_imgs, dict):
                for color_val, img_path in color_imgs.items():
                    if img_path and os.path.exists(img_path):
                        ext = os.path.splitext(img_path)[1].lower() or ".jpg"
                        clean_val = re.sub(r'[\\/*?:"<>|]', '_', str(color_val)).strip()
                        dest_sku = os.path.join(sku_dir, f"颜色-{clean_val}{ext}")
                        shutil.copy2(img_path, dest_sku)

            size_imgs = data.attributes.get("size_images", {})
            if isinstance(size_imgs, dict):
                for size_val, img_path in size_imgs.items():
                    if img_path and os.path.exists(img_path):
                        ext = os.path.splitext(img_path)[1].lower() or ".jpg"
                        clean_val = re.sub(r'[\\/*?:"<>|]', '_', str(size_val)).strip()
                        dest_sku = os.path.join(sku_dir, f"尺寸-{clean_val}{ext}")
                        shutil.copy2(img_path, dest_sku)

            for v in data.variations:
                v_img = v.variant_image or v.main_image
                if v_img and os.path.exists(v_img):
                    ext = os.path.splitext(v_img)[1].lower() or ".jpg"
                    if v.color:
                        clean_color = re.sub(r'[\\/*?:"<>|]', '_', str(v.color)).strip()
                        dest_sku = os.path.join(sku_dir, f"颜色-{clean_color}{ext}")
                        if not os.path.exists(dest_sku):
                            shutil.copy2(v_img, dest_sku)
                    elif v.size:
                        clean_size = re.sub(r'[\\/*?:"<>|]', '_', str(v.size)).strip()
                        dest_sku = os.path.join(sku_dir, f"尺寸-{clean_size}{ext}")
                        if not os.path.exists(dest_sku):
                            shutil.copy2(v_img, dest_sku)

            info_path = os.path.join(product_dir, "product_info.json")
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(data.model_dump(), f, ensure_ascii=False, indent=2)

            print(f"✅ 商品资源已成功归档至本地目录: {product_dir} (主图/附图: {rel_main}, SKU: {rel_sku})")
        except Exception as e:
            print(f"⚠️ 本地归档商品文件异常 (不影响主流程): {str(e)}")

    @staticmethod
    def get_product_by_id(product_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 查询完整商品与变体信息 (优先从 product_items 查询，自动加载映射表)"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # 1. 优先在 product_items 表中查找父节点 (is_parent = 1)
            cursor.execute("SELECT * FROM product_items WHERE id = ? AND is_parent = 1", (product_id,))
            p_row = cursor.fetchone()

            if p_row:
                product = dict(p_row)
                parent_sku = product.get("sku") or product.get("parent_sku")

                # 反序列化 JSON 字段
                product["extra_images"] = json.loads(product.get("extra_images_json") or "[]")
                product["color_options"] = json.loads(product.get("color_options_json") or "[]")
                product["size_options"] = json.loads(product.get("size_options_json") or "[]")
                product["variant_dimension_images"] = json.loads(product.get("variant_dimension_images_json") or "{}")
                product["bullet_points"] = json.loads(product.get("bullet_points_json") or "[]")
                product["chinese_translations"] = json.loads(product.get("chinese_translations_json") or "[]")

                # 查询变体子记录 (is_parent = 0)
                cursor.execute("""
                SELECT * FROM product_items 
                WHERE parent_sku = ? AND is_parent = 0 
                ORDER BY id ASC
                """, (parent_sku,))
                v_rows = cursor.fetchall()
                product["variations"] = [dict(v) for v in v_rows]
                product["variation_count"] = len(product["variations"])

                # 查询关联的 SKU-EAN 映射表记录
                cursor.execute("""
                SELECT * FROM sku_ean_mappings
                WHERE parent_sku = ?
                ORDER BY id ASC
                """, (parent_sku,))
                m_rows = cursor.fetchall()
                product["sku_ean_mappings"] = [dict(m) for m in m_rows]

                # 查询关联该商品的任务列表
                cursor.execute("""
                SELECT id, title, status, assigned_to, assigned_to_name, result_url, updated_at
                FROM tasks
                WHERE product_id = ?
                ORDER BY id DESC
                """, (product_id,))
                product["linked_tasks"] = [dict(t) for t in cursor.fetchall()]

                return product

            return None
        finally:
            conn.close()

    @staticmethod
    def list_products(
        limit: int = 50, 
        offset: int = 0,
        keyword: Optional[str] = None,
        store_account: Optional[str] = None,
        brand: Optional[str] = None,
        created_by: Optional[str] = None,
        sale_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取商品列表概览 (支持多条件组合检索与模糊查询)"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clauses = ["p.is_parent = 1"]
            params = []

            if keyword and keyword.strip():
                kw = f"%{keyword.strip()}%"
                where_clauses.append(
                    "(p.title LIKE ? OR p.parent_sku LIKE ? OR p.sku LIKE ? OR p.model_number LIKE ? OR p.model_name LIKE ? OR p.search_terms LIKE ?)"
                )
                params.extend([kw, kw, kw, kw, kw, kw])

            if store_account and store_account.strip():
                where_clauses.append("p.store_account = ?")
                params.append(store_account.strip())

            if brand and brand.strip():
                where_clauses.append("p.brand = ?")
                params.append(brand.strip())

            if created_by and created_by.strip():
                where_clauses.append("p.created_by = ?")
                params.append(created_by.strip())

            if sale_type and sale_type.strip():
                where_clauses.append("p.sale_type = ?")
                params.append(sale_type.strip())

            where_str = " AND ".join(where_clauses)
            query = f"""
            SELECT
                p.id, p.is_parent, p.parent_sku, p.sku, p.store_account, p.brand, p.title,
                p.sale_type, p.model_number, p.model_name, p.main_image,
                p.product_identifier, p.title_translation, p.identifier_translation,
                p.variation_theme, p.fulfillment_channel, p.search_terms,
                p.status, p.created_by, p.created_at, p.updated_at,
                (SELECT COUNT(*) FROM product_items WHERE is_parent = 0 AND parent_sku = p.sku) as variation_count,
                (SELECT MIN(price_jpy) FROM product_items WHERE is_parent = 0 AND parent_sku = p.sku) as min_price,
                (SELECT MAX(price_jpy) FROM product_items WHERE is_parent = 0 AND parent_sku = p.sku) as max_price
            FROM product_items p
            WHERE {where_str}
            ORDER BY p.id DESC
            LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            products = [dict(r) for r in rows]

            # 批量查询各商品关联的任务 (tasks.product_id 指向父商品 id)
            if products:
                pids = [p["id"] for p in products]
                placeholders = ",".join("?" for _ in pids)
                cursor.execute(f"""
                SELECT id, title, status, assigned_to, assigned_to_name, product_id, updated_at
                FROM tasks
                WHERE product_id IN ({placeholders})
                ORDER BY id DESC
                """, tuple(pids))
                tasks_by_pid: Dict[int, List[Dict[str, Any]]] = {}
                for t in cursor.fetchall():
                    tasks_by_pid.setdefault(t["product_id"], []).append(dict(t))
                for p in products:
                    p["linked_tasks"] = tasks_by_pid.get(p["id"], [])

            return products
        finally:
            conn.close()

    @staticmethod
    def get_filter_options() -> Dict[str, List[str]]:
        """获取商品筛选下拉选项 (店铺、品牌、创建人)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT store_account FROM product_items WHERE store_account != '' AND store_account IS NOT NULL ORDER BY store_account")
            stores = [r[0] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT brand FROM product_items WHERE brand != '' AND brand IS NOT NULL ORDER BY brand")
            brands = [r[0] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT created_by FROM product_items WHERE created_by != '' AND created_by IS NOT NULL ORDER BY created_by")
            creators = [r[0] for r in cursor.fetchall()]

            return {
                "stores": stores,
                "brands": brands,
                "creators": creators
            }
        finally:
            conn.close()

    @staticmethod
    def get_next_sequence_numbers(username: str, brand: Optional[str] = "") -> Dict[str, Any]:
        """
        自动计算 Parent SKU 与 型号名称 (モデル名) 序列号
        规则 1: Parent SKU = 登录用户名 + 用户创建的第几个品 (数字)
        规则 2: 品番・型番 = 品牌
        规则 3: モデル名 = 品牌 + 该品牌下的第几个品 (数字)
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # 1. 该用户做的第几个品 (is_parent = 1)
            uname = (username or "admin").strip()
            cursor.execute("SELECT COUNT(*) FROM product_items WHERE is_parent = 1 AND created_by = ?", (uname,))
            user_count = cursor.fetchone()[0]
            user_seq = user_count + 1
            parent_sku = f"{uname}{user_seq}"

            # 2. 该品牌下的第几个品
            brand_str = (brand or "").strip()
            if brand_str:
                cursor.execute("SELECT COUNT(*) FROM product_items WHERE is_parent = 1 AND brand = ?", (brand_str,))
                brand_count = cursor.fetchone()[0]
                brand_seq = brand_count + 1
                model_name = f"{brand_str}{brand_seq}"
                model_number = brand_str
            else:
                brand_seq = 1
                model_name = ""
                model_number = ""

            return {
                "user_seq": user_seq,
                "parent_sku": parent_sku,
                "brand": brand_str,
                "brand_seq": brand_seq,
                "model_number": model_number,
                "model_name": model_name
            }
        finally:
            conn.close()

    @staticmethod
    def update_product_status(product_id: int, status: str, log_content: str = ""):
        """更新商品上件状态并记录日志"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE product_items SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, product_id))
            if log_content:
                cursor.execute("INSERT INTO publish_logs (product_id, status, log_content) VALUES (?, ?, ?)", (product_id, status, log_content))
            conn.commit()
        finally:
            conn.close()
