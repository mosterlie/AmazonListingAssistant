# 跨境电商商品录入系统：精简版父子 SKU 单表数据库设计方案
> **设计原则**：严格仅保留页面 1~10 模块及变体表格中**肉眼可见的输入与上传字段**，剔除所有未在页面展示的冗余字段，父子共用单表。
> **图片存储规范**：表内**不存二进制照片**，但**必须存储照片的相对路径**（例如父主图 `1/main.jpg`、附图清单 `["1/extra1.jpg"]`、变体属性图映射 `{"黑":"1/1.jpg"}`、子变体图 `1/1.jpg`）。
> **变体与图片配置归属**：Card 5 维护的各属性维度选项清单（颜色列表、尺寸列表）以及 **Card 6 变体图片维度与映射配置** 作为父级属性完整保存在**父节点**。
> **审计与追溯**：增加**添加用户（`created_by`）**记录维护人，增加**创建时间（`created_at`）**与**维护时间（`updated_at`）**。
> **SKU-EAN 资产管理**：每次新增/分配变体 SKU 与 EAN 时，同步在独立的 **`sku_ean_mappings`** 映射表中追加一条记录。

---

## 一、主表：页面可见字段与相对路径映射表（表名：`product_items`）

| 序号 | 页面所属卡片 / 区域 | 页面可见字段名 / 控件 | 数据库字段名 | 字段类型 | 适用对象 | 相对路径 / 页面示例值 |
| :---: | :--- | :--- | :--- | :--- | :---: | :--- |
| 1 | **主键** | *(系统自增)* | **`id`** | `INTEGER PRIMARY KEY AUTOINCREMENT` | 父 & 子 | `1`, `2`, `3` |
| 2 | **层级识别** | *(系统自动识别)* | **`is_parent`** | `INTEGER` | 父 & 子 | `1`=父商品，`0`=子变体 |
| 3 | **2. 产品信息** | Parent SKU (父SKU) | **`parent_sku`** | `TEXT` | 父 & 子 | `DOG-TOILET-PARENT` |
| 4 | **7. 变体表格** | SKU 编码 | **`sku`** | `TEXT UNIQUE` | 父 & 子 | 父为自身SKU，子为 `DOG-TOILET-BK-L` |
| 5 | **1. 店铺与基础** | 店铺账号 | **`store_account`** | `TEXT` | **父** (子留空) | `金梧汇辰` |
| 6 | **1. 店铺与基础** | 产品标题 | **`title`** | `TEXT` | **父** (子留空) | `犬 トイレ トレー 囲い付き人工芝...` |
| 7 | **1. 店铺与基础** | 售卖形式 (单选) | **`sale_type`** | `TEXT` | **父** (子留空) | `variation` (多变体) / `single` (单品) |
| 8 | **3. 产品属性** | 品番・型番(型号) | **`model_number`** | `TEXT` | **父** (子留空) | `DOG-TLT-2026` |
| 9 | **3. 产品属性** | モデル名(型号名称) | **`model_name`** | `TEXT` | **父** (子留空) | `囲い付き人工芝トイレトレー` |
| 10 | **3. 产品属性** | 品目寸法-长 | **`item_length`** | `REAL` | **父** (子留空) | `50.0` |
| 11 | **3. 产品属性** | 品目寸法-宽 | **`item_width`** | `REAL` | **父** (子留空) | `40.0` |
| 12 | **3. 产品属性** | 品目寸法-高 | **`item_height`** | `REAL` | **父** (子留空) | `18.0` |
| 13 | **3. 产品属性** | 品目寸法单位 (下拉) | **`item_dim_unit`** | `TEXT` | **父** (子留空) | `cm` |
| 14 | **3. 产品属性** | パッケージ寸法-长 (包装长) | **`package_length`**| `REAL` | **父** (子留空) | `55.0` |
| 15 | **3. 产品属性** | パッケージ寸法-宽 (包装宽) | **`package_width`** | `REAL` | **父** (子留空) | `45.0` |
| 16 | **3. 产品属性** | パッケージ寸法-高 (包装高) | **`package_height`**| `REAL` | **父** (子留空) | `20.0` |
| 17 | **3. 产品属性** | パッケージ寸法单位 (下拉) | **`package_dim_unit`**| `TEXT` | **父** (子留空) | `cm` |
| 18 | **3. 产品属性** | 包装重量 | **`package_weight`**| `REAL` | **父** (子留空) | `2.15` |
| 19 | **3. 产品属性** | 包装重量单位 (下拉) | **`package_weight_unit`**| `TEXT`| **父** (子留空) | `kg` |
| 20 | **4. 产品图片** | **★ 产品主图 (相对路径)** | **`main_image`** | `TEXT` | **父** (子留空) | `1/main.jpg` |
| 21 | **4. 产品图片** | **📷 产品附图列表 (相对路径JSON)** | **`extra_images_json`**| `TEXT` | **父** (子留空) | `["1/extra1.jpg", "1/extra2.jpg"]` |
| 22 | **5. 变体属性** | 变种主题 (下拉) | **`variation_theme`**| `TEXT` | **父** (子留空) | `カラー/サイズ(颜色/尺寸)` |
| 23 | **5. 变体属性** | 颜色维度维护选项列表 | **`color_options_json`**| `TEXT` | **父** (子留空) | `["ブラック", "ホワイト", "グレー"]` |
| 24 | **5. 变体属性** | 尺寸维度维护选项列表 | **`size_options_json`**| `TEXT` | **父** (子留空) | `["S", "M", "L", "XL"]` |
| 25 | **6. 变体图片录入** | **图片录入维度 (单选)** | **`variant_image_dimension`**| `TEXT` | **父** (子留空) | `color` (按颜色) / `size` (按尺寸) |
| 26 | **6. 变体图片录入** | **各属性图片相对路径映射 (JSON字典)** | **`variant_dimension_images_json`**| `TEXT` | **父** (子留空) | `{"ブラック": "1/1.jpg", "グレー": "2/1.jpg"}` |
| 27 | **7. 变体表格** | **变体图片 (相对路径)** | **`variant_image`**| `TEXT` | **子** (父留空) | `1/1.jpg` |
| 28 | **7. 变体表格** | 颜色 | **`color`** | `TEXT` | **子** (父留空) | `ブラック` |
| 29 | **7. 变体表格** | 尺寸 | **`size`** | `TEXT` | **子** (父留空) | `L` |
| 30 | **7. 变体表格** | 长(cm) | **`length_cm`** | `REAL` | **子** (父留空) | `50.0` |
| 31 | **7. 变体表格** | 宽(cm) | **`width_cm`** | `REAL` | **子** (父留空) | `40.0` |
| 32 | **7. 变体表格** | 高(cm) | **`height_cm`** | `REAL` | **子** (父留空) | `18.0` |
| 33 | **7. 变体表格** | 重量(kg) | **`weight_kg`** | `REAL` | **子** (父留空) | `1.8` |
| 34 | **7. 变体表格** | 采购价(¥) | **`purchase_price`**| `REAL` | **子** (父留空) | `40.0` |
| 35 | **7. 变体表格** | 系数 | **`profit_coefficient`**| `REAL`| **子** (父留空) | `1.0` |
| 36 | **7. 变体表格** | 快递选择 (下拉) | **`shipping_channel`**| `TEXT` | **子** (父留空) | `佐川急便` / `未核算` |
| 37 | **7. 变体表格** | 价格(JPY) | **`price_jpy`** | `REAL` | **子** (父留空) | `3980.0` |
| 38 | **7. 变体表格** | 库存 | **`quantity`** | `INTEGER` | **子** (父留空) | `40` |
| 39 | **7. 变体表格** | EAN 条码 | **`ean`** | `TEXT` | **子** (父留空) | `4589930123456` |
| 40 | **8. 描述信息** | 商品描述 (带1.2.3.序号) | **`description`** | `TEXT` | **父** (子留空) | `1. オス犬の足上げ...\n2. 人工芝...` |
| 41 | **8. 描述信息** | 五点描述 (1~10项) | **`bullet_points_json`**| `TEXT` | **父** (子留空) | `["オス犬の...", "人工芝..."]` |
| 42 | **8. 描述信息** | 中文翻译参考 (1~10项) | **`chinese_translations_json`**| `TEXT`| **父** (子留空) | `["带围栏托盘...", "吸水力..."]` |
| 43 | **9. 运输信息** | 配送渠道 (FBM) | **`fulfillment_channel`**| `TEXT` | **父** (子留空) | `FBM` |
| 44 | **10. 关键词** | Search Terms (搜索关键词) | **`search_terms`** | `TEXT` | **父** (子留空) | `犬 トイレ トレー 囲い付き...` |
| 45 | **用户审计** | **添加用户 (维护人)** | **`created_by`** | `TEXT` | 父 & 子 | `admin` |
| 46 | **时间审计** | **创建时间** | **`created_at`** | `TIMESTAMP` | 父 & 子 | `2026-08-30 16:00:00` |
| 47 | **时间审计** | **维护时间 (最后更新)** | **`updated_at`** | `TIMESTAMP` | 父 & 子 | `2026-08-30 16:20:00` |

---

## 二、从表：SKU 与 EAN 映射表（表名：`sku_ean_mappings`）

| 序号 | 字段名 | 数据类型 | 允许为空 | 字段说明 | 示例值 |
| :---: | :--- | :--- | :---: | :--- | :--- |
| 1 | **`id`** | `INTEGER PRIMARY KEY AUTOINCREMENT` | 否 | 自增主键 ID | `1`, `2` |
| 2 | **`sku`** | `VARCHAR(64) NOT NULL UNIQUE` | 否 | 子 SKU 编码 | `DOG-TOILET-BK-L` |
| 3 | **`ean`** | `VARCHAR(32) NOT NULL` | 否 | 分配的 EAN-13 条码 | `4589930123456` |
| 4 | **`parent_sku`** | `VARCHAR(64) DEFAULT ''` | 是 | 归属父 SKU | `DOG-TOILET-PARENT` |
| 5 | **`store_account`**| `VARCHAR(64) DEFAULT ''` | 是 | 店铺账号 | `金梧汇辰` |
| 6 | **`created_by`** | `VARCHAR(64) DEFAULT ''` | 是 | **添加用户 (维护人)** | `admin` |
| 7 | **`created_at`** | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | 否 | **创建与维护时间** | `2026-08-30 16:15:00` |

---

## 三、精简 DDL 建表 SQL 完整脚本

```sql
-- 1. 商品父子合并主表
CREATE TABLE IF NOT EXISTS product_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,            -- 自增主键 ID
    
    -- 层级与 SKU
    is_parent INTEGER NOT NULL DEFAULT 0,            -- 1: 父商品, 0: 子变体
    parent_sku TEXT NOT NULL,                        -- 父 SKU
    sku TEXT NOT NULL UNIQUE,                        -- 当前 SKU (父或子)
    
    -- 页面顶部卡片字段 (父独有，子留空)
    store_account TEXT DEFAULT '',                   -- 1. 店铺账号
    title TEXT DEFAULT '',                           -- 1. 产品标题
    sale_type TEXT DEFAULT 'variation',              -- 1. 售卖形式 (variation / single)
    model_number TEXT DEFAULT '',                    -- 3. 品番・型番(型号)
    model_name TEXT DEFAULT '',                      -- 3. モデル名(型号名称)
    item_length REAL DEFAULT 0,                      -- 3. 品目寸法-长
    item_width REAL DEFAULT 0,                       -- 3. 品目寸法-宽
    item_height REAL DEFAULT 0,                      -- 3. 品目寸法-高
    item_dim_unit TEXT DEFAULT 'cm',                 -- 3. 品目寸法单位
    package_length REAL DEFAULT 0,                   -- 3. パッケージ寸法-长
    package_width REAL DEFAULT 0,                    -- 3. パッケージ寸法-宽
    package_height REAL DEFAULT 0,                   -- 3. パッケージ寸法-高
    package_dim_unit TEXT DEFAULT 'cm',              -- 3. パッケージ寸法单位
    package_weight REAL DEFAULT 0,                   -- 3. 包装重量
    package_weight_unit TEXT DEFAULT 'kg',           -- 3. 包装重量单位
    
    -- 4. 产品图片相对路径 (父独有，不存二进制照片)
    main_image TEXT DEFAULT '',                      -- ★ 产品主图相对路径 (如 1/main.jpg)
    extra_images_json TEXT DEFAULT '[]',             -- 📷 产品附图相对路径列表 (JSON 数组)
    
    -- 5. 变体属性设定 (父独有，子留空)
    variation_theme TEXT DEFAULT '',                 -- 变种主题
    color_options_json TEXT DEFAULT '[]',            -- 颜色各选项 (JSON 数组)
    size_options_json TEXT DEFAULT '[]',             -- 尺寸各选项 (JSON 数组)
    
    -- 6. 变体 SKU 图片录入配置 (父独有，记录维度与属性图片映射)
    variant_image_dimension TEXT DEFAULT 'color',    -- 图片录入维度 (color / size)
    variant_dimension_images_json TEXT DEFAULT '{}', -- 各属性对应的图片相对路径字典 (JSON 格式)
    
    -- 7. 变体表格字段 (子独有，父留空)
    variant_image TEXT DEFAULT '',                   -- 变体表格 - 变体图片相对路径 (如 1/1.jpg)
    color TEXT DEFAULT '',                           -- 变体表格 - 颜色
    size TEXT DEFAULT '',                            -- 变体表格 - 尺寸
    length_cm REAL DEFAULT 0,                        -- 变体表格 - 长(cm)
    width_cm REAL DEFAULT 0,                         -- 变体表格 - 宽(cm)
    height_cm REAL DEFAULT 0,                        -- 变体表格 - 高(cm)
    weight_kg REAL DEFAULT 0,                        -- 变体表格 - 重量(kg)
    purchase_price REAL DEFAULT 0,                   -- 变体表格 - 采购价(¥)
    profit_coefficient REAL DEFAULT 1.0,             -- 变体表格 - 系数
    shipping_channel TEXT DEFAULT '',                -- 变体表格 - 快递选择
    price_jpy REAL DEFAULT 0,                        -- 变体表格 - 价格(JPY)
    quantity INTEGER DEFAULT 0,                      -- 变体表格 - 库存
    ean TEXT DEFAULT '',                             -- 变体表格 - EAN 条码
    
    -- 8~10. 页面底部卡片字段 (父独有，子留空)
    description TEXT DEFAULT '',                     -- 8. 商品描述 (带1.2.3.序号)
    bullet_points_json TEXT DEFAULT '[]',            -- 8. 五点描述 (JSON 数组)
    chinese_translations_json TEXT DEFAULT '[]',     -- 8. 中文翻译参考 (JSON 数组)
    fulfillment_channel TEXT DEFAULT 'FBM',          -- 9. 配送渠道 (FBM)
    search_terms TEXT DEFAULT '',                    -- 10. Search Terms (搜索关键词)
    
    -- 用户与时间审计
    created_by TEXT DEFAULT '',                      -- 添加用户 / 维护人账号
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 创建时间
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP   -- 维护时间 (最后更新)
);

CREATE INDEX IF NOT EXISTS idx_items_parent_sku ON product_items(parent_sku);
CREATE INDEX IF NOT EXISTS idx_items_is_parent ON product_items(is_parent);
CREATE INDEX IF NOT EXISTS idx_items_created_by ON product_items(created_by);


-- 2. SKU 与 EAN 对应映射表
CREATE TABLE IF NOT EXISTS sku_ean_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,            -- 自增主键 ID
    sku VARCHAR(64) NOT NULL UNIQUE,                 -- 子 SKU 编码
    ean VARCHAR(32) NOT NULL,                        -- 分配的 EAN 条码
    parent_sku VARCHAR(64) DEFAULT '',               -- 归属父 SKU
    store_account VARCHAR(64) DEFAULT '',            -- 所属店铺账号
    created_by VARCHAR(64) DEFAULT '',               -- 添加用户 / 维护人
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP   -- 维护时间
);

CREATE INDEX IF NOT EXISTS idx_mapping_ean ON sku_ean_mappings(ean);
CREATE INDEX IF NOT EXISTS idx_mapping_parent_sku ON sku_ean_mappings(parent_sku);
```

---

## 四、入库数据形态示例

### 1. 父商品记录 (`is_parent = 1`, id = 1)
```json
{
  "id": 1,
  "is_parent": 1,
  "parent_sku": "DOG-TOILET-PARENT",
  "sku": "DOG-TOILET-PARENT",
  "store_account": "金梧汇辰",
  "title": "犬 トイレ トレー 囲い付き人工芝足上げ ガード お飛び散り防止",
  "sale_type": "variation",
  "model_number": "DOG-TLT-2026",
  "model_name": "囲い付き人工芝トイレトレー",
  "item_length": 50.0,
  "item_width": 40.0,
  "item_height": 18.0,
  "item_dim_unit": "cm",
  "package_length": 55.0,
  "package_width": 45.0,
  "package_height": 20.0,
  "package_dim_unit": "cm",
  "package_weight": 2.15,
  "package_weight_unit": "kg",
  "main_image": "1/main.jpg",
  "extra_images_json": "[\"1/extra1.jpg\", \"1/extra2.jpg\"]",
  "variation_theme": "カラー/サイズ(颜色/尺寸)",
  "color_options_json": "[\"ブラック (黑色)\", \"グレー (灰色)\"]",
  "size_options_json": "[\"M (中号)\", \"L (大号)\"]",
  "variant_image_dimension": "color",
  "variant_dimension_images_json": "{\"ブラック (黑色)\": \"1/1.jpg\", \"グレー (灰色)\": \"2/1.jpg\"}",
  "variant_image": null,
  "color": null,
  "size": null,
  "length_cm": null,
  "width_cm": null,
  "height_cm": null,
  "weight_kg": null,
  "purchase_price": null,
  "profit_coefficient": null,
  "shipping_channel": null,
  "price_jpy": null,
  "quantity": null,
  "ean": null,
  "description": "1. オス犬の足上げ動作による飛び散りを防ぐ...\n2. 人工芝は吸水力に優れ...",
  "bullet_points_json": "[\"オス犬の足上げ动作...\", \"人工芝は吸水力...\"]",
  "chinese_translations_json": "[\"带围栏托盘能防止公狗抬腿飞溅...\", \"吸水力出色...\"]",
  "fulfillment_channel": "FBM",
  "search_terms": "犬 トイレ トレー 囲い付き人工芝足上げ ガード お飛び散り防止",
  "created_by": "admin",
  "created_at": "2026-08-30 16:00:00",
  "updated_at": "2026-08-30 16:20:00"
}
```

### 2. 子变体记录 (`is_parent = 0`, id = 2)
```json
{
  "id": 2,
  "is_parent": 0,
  "parent_sku": "DOG-TOILET-PARENT",
  "sku": "DOG-TOILET-BK-L",
  "store_account": null,
  "title": null,
  "sale_type": null,
  "model_number": null,
  "model_name": null,
  "item_length": null,
  "item_width": null,
  "item_height": null,
  "item_dim_unit": null,
  "package_length": null,
  "package_width": null,
  "package_height": null,
  "package_dim_unit": null,
  "package_weight": null,
  "package_weight_unit": null,
  "main_image": null,
  "extra_images_json": null,
  "variation_theme": null,
  "color_options_json": null,
  "size_options_json": null,
  "variant_image_dimension": null,
  "variant_dimension_images_json": null,
  "variant_image": "1/1.jpg",
  "color": "ブラック (黑色)",
  "size": "L (大号)",
  "length_cm": 50.0,
  "width_cm": 40.0,
  "height_cm": 18.0,
  "weight_kg": 1.8,
  "purchase_price": 40.0,
  "profit_coefficient": 1.0,
  "shipping_channel": "佐川急便",
  "price_jpy": 3980.0,
  "quantity": 40,
  "ean": "4589930123456",
  "description": null,
  "bullet_points_json": null,
  "chinese_translations_json": null,
  "fulfillment_channel": null,
  "search_terms": null,
  "created_by": "admin",
  "created_at": "2026-08-30 16:00:00",
  "updated_at": "2026-08-30 16:20:00"
}
```
