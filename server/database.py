"""
SQLite 数据库初始化与访问层
"""
import sys
import sqlite3
import json
from typing import Dict, Any, List, Optional
from server.config import DB_PATH

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def get_db_connection() -> sqlite3.Connection:
    """获取 SQLite 连接并配置行字典解析

    timeout=30: 后台自动化线程写库持锁时, 前台请求等待锁上限从默认 5s 提升到 30s;
    WAL 模式: 读写不互斥, 后台写入不再阻塞前台页面查询。
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 0. 精简版父子 SKU 单表商品结构 (Single-Table Hierarchy)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        is_parent INTEGER NOT NULL DEFAULT 0,
        parent_sku TEXT NOT NULL,
        sku TEXT NOT NULL UNIQUE,
        store_account TEXT DEFAULT '',
        brand TEXT DEFAULT '',
        title TEXT DEFAULT '',
        sale_type TEXT DEFAULT 'variation',
        model_number TEXT DEFAULT '',
        model_name TEXT DEFAULT '',
        product_identifier TEXT DEFAULT '',
        title_translation TEXT DEFAULT '',
        identifier_translation TEXT DEFAULT '',
        item_length REAL DEFAULT 0,
        item_width REAL DEFAULT 0,
        item_height REAL DEFAULT 0,
        item_dim_unit TEXT DEFAULT 'cm',
        package_length REAL DEFAULT 0,
        package_width REAL DEFAULT 0,
        package_height REAL DEFAULT 0,
        package_dim_unit TEXT DEFAULT 'cm',
        package_weight REAL DEFAULT 0,
        package_weight_unit TEXT DEFAULT 'kg',
        main_image TEXT DEFAULT '',
        extra_images_json TEXT DEFAULT '[]',
        variation_theme TEXT DEFAULT '',
        color_options_json TEXT DEFAULT '[]',
        size_options_json TEXT DEFAULT '[]',
        variant_image_dimension TEXT DEFAULT 'color',
        variant_dimension_images_json TEXT DEFAULT '{}',
        variant_image TEXT DEFAULT '',
        color TEXT DEFAULT '',
        size TEXT DEFAULT '',
        length_cm REAL DEFAULT 0,
        width_cm REAL DEFAULT 0,
        height_cm REAL DEFAULT 0,
        weight_kg REAL DEFAULT 0,
        purchase_price REAL DEFAULT 0,
        profit_coefficient REAL DEFAULT 1.0,
        shipping_channel TEXT DEFAULT '',
        price_jpy REAL DEFAULT 0,
        quantity INTEGER DEFAULT 0,
        ean TEXT DEFAULT '',
        description TEXT DEFAULT '',
        bullet_points_json TEXT DEFAULT '[]',
        chinese_translations_json TEXT DEFAULT '[]',
        fulfillment_channel TEXT DEFAULT 'FBM',
        search_terms TEXT DEFAULT '',
        status TEXT DEFAULT 'draft',
        created_by TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_parent_sku ON product_items(parent_sku);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_is_parent ON product_items(is_parent);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_created_by ON product_items(created_by);")
    # 动态检查并添加 product_items 新增字段 (brand 字段等向下兼容)
    cursor.execute("PRAGMA table_info(product_items);")
    existing_items_cols = [col["name"] for col in cursor.fetchall()]
    if "brand" not in existing_items_cols:
        cursor.execute("ALTER TABLE product_items ADD COLUMN brand TEXT DEFAULT '';")
    if "product_identifier" not in existing_items_cols:
        cursor.execute("ALTER TABLE product_items ADD COLUMN product_identifier TEXT DEFAULT '';")
    if "title_translation" not in existing_items_cols:
        cursor.execute("ALTER TABLE product_items ADD COLUMN title_translation TEXT DEFAULT '';")
    if "identifier_translation" not in existing_items_cols:
        cursor.execute("ALTER TABLE product_items ADD COLUMN identifier_translation TEXT DEFAULT '';")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_brand ON product_items(brand);")

    # 0.0.1 大模型调用日志表 (记录每次五点描述调用的请求与回复, 用于 token 统计)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS llm_call_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scene TEXT DEFAULT 'bullets',
        source TEXT DEFAULT '',
        model TEXT DEFAULT '',
        title TEXT DEFAULT '',
        prompt TEXT DEFAULT '',
        response TEXT DEFAULT '',
        status TEXT DEFAULT 'success',
        error_detail TEXT DEFAULT '',
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        created_by TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_logs_created_at ON llm_call_logs(created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_logs_scene ON llm_call_logs(scene);")
    # 旧库向下兼容: 补充缺失字段
    cursor.execute("PRAGMA table_info(llm_call_logs);")
    existing_llm_cols = [col["name"] for col in cursor.fetchall()]
    for col_def, col_name in [
        ("title TEXT DEFAULT ''", "title"),
        ("prompt_tokens INTEGER DEFAULT 0", "prompt_tokens"),
        ("completion_tokens INTEGER DEFAULT 0", "completion_tokens"),
        ("total_tokens INTEGER DEFAULT 0", "total_tokens"),
        ("duration_ms INTEGER DEFAULT 0", "duration_ms"),
        ("created_by TEXT DEFAULT ''", "created_by"),
    ]:
        if col_name not in existing_llm_cols:
            cursor.execute(f"ALTER TABLE llm_call_logs ADD COLUMN {col_def};")


    # 0.1 SKU 与 EAN 对应流水映射表 (每新增一个 SKU+EAN 自动新增一条)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sku_ean_mappings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku VARCHAR(64) NOT NULL UNIQUE,
        ean VARCHAR(32) NOT NULL,
        parent_sku VARCHAR(64) DEFAULT '',
        store_account VARCHAR(64) DEFAULT '',
        created_by VARCHAR(64) DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mapping_ean ON sku_ean_mappings(ean);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mapping_parent_sku ON sku_ean_mappings(parent_sku);")

    # 1. 自动化上件任务日志表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS publish_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        log_content TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES product_items (id) ON DELETE CASCADE
    );
    """)

    # 2. 系统全局配置表 (店铺列表、快递费与计价参数、本地归档存储目录等)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value_json TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 初始化默认店铺账号配置 (支持店铺-品牌 1对1 必填映射)
    cursor.execute("SELECT value_json FROM system_settings WHERE key = 'store_accounts';")
    if not cursor.fetchone():
        default_stores = [
            {"store_name": "金梧汇辰", "brand_name": "JINWU"},
            {"store_name": "店小秘通用测试", "brand_name": "DXM"}
        ]
        cursor.execute("INSERT INTO system_settings (key, value_json) VALUES (?, ?);", 
                       ("store_accounts", json.dumps(default_stores, ensure_ascii=False)))

    # 初始化默认物流计价参数配置
    cursor.execute("SELECT value_json FROM system_settings WHERE key = 'pricing_config';")
    if not cursor.fetchone():
        default_pricing = {
            "tax_rate": 0.17,
            "exchange_rate": 23.0,
            "price_coefficient": 26.0,
            "default_profit_coeff": 1.0
        }
        cursor.execute("INSERT INTO system_settings (key, value_json) VALUES (?, ?);", 
                       ("pricing_config", json.dumps(default_pricing, ensure_ascii=False)))

    # 初始化默认本地图片与产品归档目录配置 (分 Mac 和 Windows)
    cursor.execute("SELECT value_json FROM system_settings WHERE key = 'storage_path_mac';")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO system_settings (key, value_json) VALUES (?, ?);", 
                       ("storage_path_mac", json.dumps("/Users/gx/Desktop/products", ensure_ascii=False)))

    cursor.execute("SELECT value_json FROM system_settings WHERE key = 'storage_path_win';")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO system_settings (key, value_json) VALUES (?, ?);", 
                       ("storage_path_win", json.dumps("D:\\products", ensure_ascii=False)))

    # 初始化默认相对路径 (main 文件夹与 sku 文件夹)
    cursor.execute("SELECT value_json FROM system_settings WHERE key = 'storage_rel_main';")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO system_settings (key, value_json) VALUES (?, ?);", 
                       ("storage_rel_main", json.dumps("main", ensure_ascii=False)))

    cursor.execute("SELECT value_json FROM system_settings WHERE key = 'storage_rel_sku';")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO system_settings (key, value_json) VALUES (?, ?);", 
                       ("storage_rel_sku", json.dumps("sku", ensure_ascii=False)))

    # 初始化默认 Session 有效期 (小时，默认 1.0h)
    cursor.execute("SELECT value_json FROM system_settings WHERE key = 'session_expire_hours';")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO system_settings (key, value_json) VALUES (?, ?);", 
                       ("session_expire_hours", json.dumps(1.0, ensure_ascii=False)))

    # 5. 用户表 (RBAC 角色鉴权: admin / user)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        display_name TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 6. 用户登录 Session 表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """)

    # 7. 任务管理表 (tasks)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT DEFAULT '',
        reference_url TEXT DEFAULT '',
        instructions TEXT DEFAULT '',
        assigned_by TEXT NOT NULL,
        assigned_to TEXT NOT NULL,
        assigned_to_name TEXT DEFAULT '',
        assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        result_url TEXT DEFAULT '',
        submitted_at DATETIME,
        product_id INTEGER DEFAULT 0,
        product_title TEXT DEFAULT '',
        product_parent_sku TEXT DEFAULT '',
        product_main_image TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 8. 广告投放任务表 (赛狐 SP 批量创建广告 - 任务参数落库)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ad_campaign_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_name TEXT NOT NULL DEFAULT '',
        shop_name TEXT NOT NULL DEFAULT '',
        create_mode TEXT NOT NULL DEFAULT '所有产品合并创建广告',
        start_date TEXT DEFAULT '',
        end_date TEXT DEFAULT '',
        daily_budget REAL NOT NULL DEFAULT 300,
        bid_strategy TEXT NOT NULL DEFAULT '动态竞价-只降低',
        default_bid REAL NOT NULL DEFAULT 15,
        asins_json TEXT NOT NULL DEFAULT '[]',
        asin_count INTEGER NOT NULL DEFAULT 0,
        batch_size INTEGER NOT NULL DEFAULT 0,
        auto_dedup INTEGER NOT NULL DEFAULT 0,
        trim_variants INTEGER NOT NULL DEFAULT 1,
        trim_keep INTEGER NOT NULL DEFAULT 5,
        status TEXT NOT NULL DEFAULT 'pending',
        last_run_id INTEGER DEFAULT 0,
        last_result TEXT DEFAULT '',
        last_run_at DATETIME,
        created_by TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ad_tasks_status ON ad_campaign_tasks(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ad_tasks_shop ON ad_campaign_tasks(shop_name);")
    # 旧库向下兼容: 补充 auto_dedup 字段 (ASIN 自动去重开关, 默认关闭)
    cursor.execute("PRAGMA table_info(ad_campaign_tasks);")
    _ad_cols = [col["name"] for col in cursor.fetchall()]
    if "auto_dedup" not in _ad_cols:
        cursor.execute("ALTER TABLE ad_campaign_tasks ADD COLUMN auto_dedup INTEGER NOT NULL DEFAULT 0;")
    if "trim_variants" not in _ad_cols:
        cursor.execute("ALTER TABLE ad_campaign_tasks ADD COLUMN trim_variants INTEGER NOT NULL DEFAULT 1;")
    if "trim_keep" not in _ad_cols:
        cursor.execute("ALTER TABLE ad_campaign_tasks ADD COLUMN trim_keep INTEGER NOT NULL DEFAULT 5;")

    # 9. 广告任务执行记录表 (每次「自动投放」登记一条执行结果)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ad_task_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        task_name TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'running',
        submitted INTEGER NOT NULL DEFAULT 0,
        batch_count INTEGER DEFAULT 0,
        total_asins INTEGER DEFAULT 0,
        entered_count INTEGER DEFAULT 0,
        skipped_count INTEGER DEFAULT 0,
        skip_detail_json TEXT DEFAULT '[]',
        verify_json TEXT DEFAULT '{}',
        result_msg TEXT DEFAULT '',
        log_text TEXT DEFAULT '',
        operator TEXT DEFAULT '',
        started_at DATETIME,
        finished_at DATETIME,
        duration_ms INTEGER DEFAULT 0
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ad_runs_task_id ON ad_task_runs(task_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ad_runs_started_at ON ad_task_runs(started_at);")

    # 10. 知识库与常用工具网站表 (三部分: 1.网站名称 2.网址5分段 3.说明)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_sites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        url_part1 TEXT DEFAULT '',
        url_part2 TEXT DEFAULT '',
        url_part3 TEXT DEFAULT '',
        url_part4 TEXT DEFAULT '',
        url_part5 TEXT DEFAULT '',
        description TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        created_by VARCHAR(64) DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_sort ON knowledge_sites(sort_order, id);")

    # 初始化默认管理员用户 (admin / admin)
    cursor.execute("SELECT id FROM users WHERE username = 'admin';")
    if not cursor.fetchone():
        import hashlib
        import secrets
        salt = secrets.token_hex(16)
        # PBKDF2-HMAC-SHA256 哈希
        pwd_hash = hashlib.pbkdf2_hmac('sha256', 'admin'.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
        cursor.execute("""
        INSERT INTO users (username, password_hash, salt, role, display_name, status)
        VALUES (?, ?, ?, 'admin', '超级管理员', 'active');
        """, ('admin', pwd_hash, salt))
        print("👤 已初始化默认管理员账号: admin / admin (角色: admin)")

    conn.commit()
    conn.close()
    print("✅ 数据库表结构初始化/升级成功！")


def get_setting(key: str, default: Any = None) -> Any:
    """从数据库读取指定配置项"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value_json FROM system_settings WHERE key = ?;", (key,))
    row = cursor.fetchone()
    conn.close()
    if row and row["value_json"]:
        try:
            return json.loads(row["value_json"])
        except Exception:
            return default
    return default


def set_setting(key: str, value: Any) -> None:
    """保存或更新配置项"""
    conn = get_db_connection()
    cursor = conn.cursor()
    val_json = json.dumps(value, ensure_ascii=False)
    cursor.execute("""
    INSERT INTO system_settings (key, value_json, updated_at) 
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = CURRENT_TIMESTAMP;
    """, (key, val_json))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
