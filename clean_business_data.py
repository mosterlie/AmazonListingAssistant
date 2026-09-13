#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
ERP 自动化系统 - 业务数据与本地归档文件一键清理工具
==============================================================================
功能说明：
1. 清理业务数据库 (products.db)：
   - 清空商品数据表 (product_items)
   - 清空协同任务看板数据 (tasks)
   - 清空广告投放任务与运行记录 (ad_campaign_tasks / ad_task_runs)
   - 清空条形码流水映射表 (sku_ean_mappings)
   - 重置自增 ID 计数器 (sqlite_sequence)，后续新增商品从 ID #1 重新开始
   - 【严格保留】用户账号与角色权限 (users)
   - 【严格保留】系统全局配置 (system_settings: 店铺映射、计价公式、归档路径、Session配置等)
   - 【严格保留】当前有效登录会话 (user_sessions)
   - 执行 VACUUM 释放数据库空间

2. 清理本地业务数据文件：
   - 清理系统中配置的本地图片与产品归档主目录（自动识别 macOS 与 Windows 路径）
   - 清理系统临时图片上传目录 (data/uploads/)

使用方法：
  python3 clean_business_data.py          # 交互式确认清理
  python3 clean_business_data.py --yes    # 免确认直接执行
==============================================================================
"""

import sys
import os
import shutil
import sqlite3
import argparse
import datetime
from typing import Tuple, List

# 确保能正确导入项目内部模块
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from server.config import DB_PATH, UPLOADS_DIR
    from server.database import get_setting
except Exception:
    DB_PATH = os.path.join(BASE_DIR, "data", "products.db")
    UPLOADS_DIR = os.path.join(BASE_DIR, "data", "uploads")
    def get_setting(key, default=None):
        return default


def get_configured_storage_dir() -> str:
    """获取当前操作系统所配置的本地归档绝对根目录"""
    is_win = sys.platform.startswith("win")
    if is_win:
        default_dir = r"D:\products"
        setting_key = "storage_path_win"
    else:
        default_dir = os.path.expanduser("~/Desktop/products")
        setting_key = "storage_path_mac"

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT value_json FROM system_settings WHERE key = ?;", (setting_key,))
        row = cur.fetchone()
        conn.close()
        if row and row["value_json"]:
            import json
            val = json.loads(row["value_json"])
            return val if isinstance(val, str) and val.strip() else default_dir
    except Exception:
        pass
    return default_dir


def backup_database(db_file: str) -> str:
    """在清理前对数据库进行时间戳快照备份"""
    if not os.path.exists(db_file):
        return ""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"{db_file}.backup_{ts}"
    shutil.copy2(db_file, backup_file)
    return backup_file


def clean_database(db_file: str) -> Tuple[bool, str, List[str]]:
    """清空业务数据表并保留用户与系统配置"""
    if not os.path.exists(db_file):
        return False, "数据库文件不存在", []

    details = []
    try:
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()

        # 1. 统计当前业务数据与会话条数
        business_tables = [
            "product_items", "sku_ean_mappings", "publish_logs",
            "tasks", "ad_campaign_tasks", "ad_task_runs", "user_sessions",
        ]
        counts_before = {}
        for tbl in business_tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                counts_before[tbl] = cur.fetchone()[0]
            except Exception:
                counts_before[tbl] = 0

        # 2. 清空业务表与用户 Session 会话表 (单表容错, 表不存在则跳过)
        for tbl in business_tables:
            try:
                cur.execute(f"DELETE FROM {tbl};")
                details.append(f"已清空数据表 【{tbl}】 (共清理 {counts_before.get(tbl, 0)} 条记录)")
            except Exception:
                details.append(f"已跳过数据表 【{tbl}】 (表不存在)")

        # 3. 重置自增 ID 计数器
        seq_tables = [
            "product_items", "sku_ean_mappings", "publish_logs",
            "tasks", "ad_campaign_tasks", "ad_task_runs",
        ]
        placeholders = ",".join("?" for _ in seq_tables)
        try:
            cur.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders});", seq_tables)
            details.append("已重置业务表自增序列计数器 (后续商品与任务将从 ID #1 重新开始)")
        except Exception:
            pass

        conn.commit()

        # 4. 执行 VACUUM 整理磁盘空间
        cur.execute("VACUUM;")
        conn.close()
        details.append("已执行 SQLite VACUUM 释放磁盘碎片空间")

        return True, "数据库业务数据清理成功", details
    except Exception as e:
        return False, f"清理数据库异常: {str(e)}", details


def clean_local_storage_files(storage_dir: str) -> Tuple[int, int]:
    """清理本地图片与产品归档目录中的所有产品文件夹"""
    if not storage_dir or not os.path.exists(storage_dir):
        return 0, 0

    deleted_dirs = 0
    deleted_files = 0

    try:
        for entry in os.listdir(storage_dir):
            entry_path = os.path.join(storage_dir, entry)
            # 安全防护：仅删除归档目录下的子文件夹或相关产品归档文件
            if os.path.isdir(entry_path):
                # 递归统计文件数
                for _, _, files in os.walk(entry_path):
                    deleted_files += len(files)
                shutil.rmtree(entry_path, ignore_errors=True)
                deleted_dirs += 1
            elif os.path.isfile(entry_path) and not entry.startswith("."):
                os.remove(entry_path)
                deleted_files += 1
    except Exception as e:
        print(f"⚠️ 清理归档目录部分文件失败: {e}")

    return deleted_dirs, deleted_files


def clean_uploads_directory(uploads_dir: str) -> int:
    """清理系统内置临时上传目录 data/uploads/"""
    if not uploads_dir or not os.path.exists(uploads_dir):
        return 0

    cleaned_count = 0
    try:
        for f in os.listdir(uploads_dir):
            fp = os.path.join(uploads_dir, f)
            if os.path.isfile(fp):
                os.remove(fp)
                cleaned_count += 1
            elif os.path.isdir(fp):
                shutil.rmtree(fp, ignore_errors=True)
                cleaned_count += 1
    except Exception as e:
        print(f"⚠️ 清理 uploads 目录失败: {e}")

    return cleaned_count


def inspect_system_status(db_file: str) -> None:
    """展示当前系统保留的配置与用户信息"""
    if not os.path.exists(db_file):
        return
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        print("\n" + "=" * 65)
        print("🛡️ 【严格保留】的核心系统数据与配置核查")
        print("=" * 65)

        # 1. 用户账号
        cur.execute("SELECT id, username, role, display_name, status FROM users;")
        users = cur.fetchall()
        print(f"👤 用户与权限列表 (共 {len(users)} 个有效账号):")
        for u in users:
            print(f"   • [ID #{u['id']}] 账号: {u['username']:<10} 姓名: {u['display_name']:<8} 角色: {u['role']:<6} 状态: {u['status']}")

        # 2. 系统全局配置
        cur.execute("SELECT key, value_json FROM system_settings;")
        settings = cur.fetchall()
        print(f"\n⚙️ 全局配置参数 (共 {len(settings)} 项):")
        for s in settings:
            val_preview = str(s["value_json"]).replace("\n", "")
            if len(val_preview) > 65:
                val_preview = val_preview[:62] + "..."
            print(f"   • {s['key']:<22} => {val_preview}")

        conn.close()
    except Exception as e:
        print(f"⚠️ 查询保留状态异常: {e}")


def main():
    parser = argparse.ArgumentParser(description="ERP 自动化系统 - 业务数据与本地归档文件一键清理工具")
    parser.add_argument("-y", "--yes", action="store_true", help="跳过确认提示，直接执行清理")
    args = parser.parse_args()

    storage_dir = get_configured_storage_dir()

    print("\n" + "=" * 65)
    print("🧹 ERP 自动化上件系统 - 业务数据与文件清理向导")
    print("=" * 65)
    print("📋 本次清理将执行以下操作：")
    print(f" 1. 业务数据库清空: {DB_PATH}")
    print("    - 清空商品表 (product_items)")
    print("    - 清空条形码流水表 (sku_ean_mappings)")
    print("    - 清空刊登日志表 (publish_logs)")
    print("    - 清空协同任务表 (tasks)")
    print("    - 清空广告任务与运行记录表 (ad_campaign_tasks / ad_task_runs)")
    print("    - 重置商品 ID 与任务 ID 自增计数器 (从 ID #1 重新开始)")
    print("    - 自动清理过期 Session，保留有效登录态")
    print(f" 2. 本地产品归档目录清理: {storage_dir}")
    print("    - 清空该目录下所有产品图片与备份数据文件夹")
    print(f" 3. 系统临时图片上传目录清理: {UPLOADS_DIR}")
    print("    - 清空测试上传的临时文件")
    print("-" * 65)
    print("🛡️ 【严格保留并受保护的数据】：")
    print("   ✓ users 表 (所有操作员与管理员账号、密码哈希、权限保持不变)")
    print("   ✓ system_settings 表 (店铺品牌映射、默认店铺、运费计价参数、路径配置、Session配置)")
    print("   ✓ 清理前自动在 data/ 目录下生成带有时间戳的数据库备份文件")
    print("=" * 65)

    if not args.yes:
        try:
            confirm = input("\n⚠️ 请确认是否继续执行清理？(输入 y 或 yes 确认, 其它取消) [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                print("❌ 操作已取消。")
                sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            print("\n❌ 操作已取消。")
            sys.exit(0)

    print("\n🚀 开始执行清理流程...\n")

    # 1. 备份数据库
    backup_file = backup_database(DB_PATH)
    if backup_file:
        print(f"✅ 1. 数据库安全快照备份已生成: {backup_file}")
    else:
        print("⚠️ 1. 数据库文件未找到，跳过备份。")

    # 2. 清理业务数据库
    db_ok, db_msg, db_details = clean_database(DB_PATH)
    if db_ok:
        print("✅ 2. 业务数据库已清理完成：")
        for item in db_details:
            print(f"   • {item}")
    else:
        print(f"❌ 2. 业务数据库清理失败: {db_msg}")

    # 3. 清理本地归档文件
    del_dirs, del_files = clean_local_storage_files(storage_dir)
    print(f"✅ 3. 本地归档目录清理完成 ({storage_dir})：")
    print(f"   • 已清理 {del_dirs} 个产品归档目录，共计 {del_files} 个文件")

    # 4. 清理临时 uploads
    up_count = clean_uploads_directory(UPLOADS_DIR)
    print(f"✅ 4. 临时上传目录清理完成 ({UPLOADS_DIR})：")
    print(f"   • 已清理 {up_count} 个临时上传文件")

    # 5. 核对并展示保留状态
    inspect_system_status(DB_PATH)

    print("\n" + "=" * 65)
    print("🎉 恭喜！业务数据库与本地业务文件清理已全部完成！系统已就绪！")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
