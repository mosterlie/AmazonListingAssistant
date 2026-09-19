#!/usr/bin/env python3
"""
ERP 全能桌面助手 (统一版) — 商品上件 + 赛狐广告批量投放

整合要点:
- 「📢 广告投放」面板: 与 mac 独立版 (sellfox_ad_gui.py + gui/index.html) 完全一致 ——
  直接复用 sellfox_ad_gui.Bridge (内部调用 core/sellfox_ad_operator.py /
  core/browser_manager.py), JS 桥接方法名保持原名 (poll_logs / confirm_run /
  modal_ok / stop / ...), 广告前端代码零改动。
- 「📦 商品上件」面板: tkinter 版上件助手 (desktop_app.py) 的 Web 复刻 ——
  复用其常量、RemoteSQLiteConnection (远程 SQLite 桥接)、配置读写与错误日志,
  业务逻辑 (数据库连接 / 远程图片下载缓存 / Chrome 启动 / 上件管线 / 强制终止)
  与其逐条对应, 行为一致。
- 单窗口双面板 (pywebview 原生窗口): Windows 走 WebView2 (EdgeChromium),
  macOS 走系统 WKWebView; 全程数据不落库。

运行:
    python unified_app.py           # 桌面窗口
    python unified_app.py --serve   # 浏览器模式 (http://127.0.0.1:8317, 调试/备用)
    python unified_app.py --selftest
"""
import os
import sys
import json
import time
import queue
import sqlite3
import tempfile
import threading
import subprocess
import urllib.request
from datetime import datetime

# ──────────────────────────────────────────────────────────────
# 路径与环境准备 (必须在导入项目模块之前)
# ──────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 复用上件助手 (desktop_app) 的常量与工具 —— 上件逻辑与其保持单一来源
import desktop_app as _pub_core  # noqa: E402
# 复用 mac 独立版广告桥接 —— 投广告逻辑完全复刻
from sellfox_ad_gui import Bridge as AdsBridge  # noqa: E402

SERVE_PORT = 8317
APP_TITLE = "ERP 全能助手 · 上件 + 广告投放"
CODE_STAMP = "2026-09-19.2"   # 打包一致性标记 (selftest 输出, 用于确认 exe 与源码同步)


def _gui_dir():
    """gui/app.html 多路径探测: PyInstaller(MEIPASS) / .app BUNDLE / 源码"""
    cands = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(os.path.join(meipass, "gui"))
    cands.append(os.path.join(BASE_DIR, "..", "Resources", "gui"))
    cands.append(os.path.join(BASE_DIR, "gui"))
    for c in cands:
        if os.path.exists(os.path.join(c, "app.html")):
            return c
    return cands[-1]


GUI_DIR = _gui_dir()

_PUB_BRIDGE = None


def _get_pub_bridge():
    """惰性导入上件管线 (playwright 导入耗时 8~15 秒, 延迟到首次上件时加载)"""
    global _PUB_BRIDGE
    if _PUB_BRIDGE is None:
        from server.services.erp_bridge import ERPBridgeService
        _PUB_BRIDGE = ERPBridgeService
    return _PUB_BRIDGE


def _guard():
    """惰性导入 Playwright 驱动守护 (core 包会连带导入 playwright, 避免拖慢窗口显示)"""
    from core import driver_guard
    return driver_guard


class PublishBridge:
    """商品上件桥接层 (逻辑等价 desktop_app.DesktopApp, UI 层换成 Web 面板)"""

    def __init__(self):
        cfg = _pub_core.load_app_config()
        self.log_q: "queue.Queue[str]" = queue.Queue()
        self.conn_mode = cfg.get("conn_mode", "remote")
        self.db_path = cfg.get("db_path", _pub_core.DEFAULT_DB_PATH)
        self.host = cfg.get("host", _pub_core.DEFAULT_REMOTE_HOST)
        self.port = str(cfg.get("port", _pub_core.DEFAULT_REMOTE_PORT))
        self.token = cfg.get("token", _pub_core.DEFAULT_REMOTE_TOKEN)
        self.remote_scheme = cfg.get("scheme", "")
        self.image_root = cfg.get("image_root", "")
        self.chrome_dir = cfg.get("chrome_user_data_dir", _pub_core.DEFAULT_CHROME_DIR)

        self.publishing = False
        self._stop_requested = False
        self.current_product = None
        self.last_result = ""
        self._remote_conn = None
        self._worker = None

        self.db_ok = False
        self.db_status_text = "数据库: 未连接"

    # ────────────────── 日志 ──────────────────
    def _log(self, line):
        self.log_q.put(str(line))

    def poll_logs(self, seen=0):
        lines = []
        while True:
            try:
                lines.append(self.log_q.get_nowait())
            except queue.Empty:
                break
        return {"seen": seen, "lines": lines}

    def clear_log(self):
        while True:
            try:
                self.log_q.get_nowait()
            except queue.Empty:
                break
        return {"ok": True}

    # ────────────────── 配置 ──────────────────
    def get_options(self):
        return {
            "conn_mode": self.conn_mode,
            "db_path": self.db_path,
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "image_root": self.image_root,
            "chrome_dir": self.chrome_dir,
            "default_chrome_dir": _pub_core.DEFAULT_CHROME_DIR,
            "dxm_url": _pub_core.DXM_URL,
            "db_status": self.db_status_text,
            "db_ok": self.db_ok,
            "chrome_running": self._chrome_port_open(),
            "publishing": bool(self._worker and self._worker.is_alive()),
            "product": self.current_product,
            "last_result": self.last_result,
        }

    def _save_config(self):
        try:
            _pub_core.save_app_config({
                "conn_mode": self.conn_mode,
                "db_path": self.db_path.strip(),
                "host": self.host.strip(),
                "port": str(self.port).strip(),
                "token": self.token,
                "scheme": self.remote_scheme,
                "image_root": self.image_root.strip(),
                "chrome_user_data_dir": self.chrome_dir.strip(),
            })
        except Exception as e:
            _pub_core._app_error_log("配置保存失败", e)

    @staticmethod
    def _pick(cfg, key, old, strip=True):
        """从 JS 传入的 dict 中安全取值 (None/缺省 保留旧值)"""
        if not isinstance(cfg, dict) or key not in cfg or cfg.get(key) is None:
            return old
        v = str(cfg.get(key))
        return v.strip() if strip else v

    def set_chrome_dir(self, d):
        self.chrome_dir = (d or "").strip() or _pub_core.DEFAULT_CHROME_DIR
        self._save_config()
        return {"ok": True, "chrome_dir": self.chrome_dir}

    # ────────────────── 数据库连接 ──────────────────
    def apply_db(self, cfg=None, create=False):
        """应用数据库配置: 远程模式走 ERP 内嵌 DB 代理; 本地模式走文件路径"""
        if isinstance(cfg, dict):
            self.conn_mode = self._pick(cfg, "conn_mode", self.conn_mode) or self.conn_mode
            self.db_path = self._pick(cfg, "db_path", self.db_path)
            self.host = self._pick(cfg, "host", self.host)
            self.port = self._pick(cfg, "port", self.port)
            self.token = self._pick(cfg, "token", self.token, strip=False)
            self.image_root = self._pick(cfg, "image_root", self.image_root)
            self.chrome_dir = self._pick(cfg, "chrome_dir", self.chrome_dir)

        if self.conn_mode == "remote":
            return self._apply_remote_db()
        return self._apply_local_db(create=bool(create))

    def _apply_local_db(self, create=False):
        db_path = self.db_path.strip()
        if not db_path:
            return self._db_fail("请填写数据库路径！远程机器可填网络共享路径, 例如 \\\\192.168.1.10\\share\\products.db")
        if not os.path.exists(db_path):
            if db_path.startswith("\\\\"):
                return self._db_fail(
                    f"共享路径不可访问: {db_path} — 请检查主机在线/共享开放, 或先映射为盘符 (如 Z:\\...)")
            if not create:
                return {"ok": False, "need_create": True, "msg": f"数据库文件不存在: {db_path}",
                        "status": self.db_status_text}
            parent_dir = os.path.dirname(db_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

        try:
            conn = sqlite3.connect(db_path, timeout=5)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM product_items WHERE is_parent = 1;")
            parent_count = cursor.fetchone()[0]
            conn.close()
        except Exception as e:
            _pub_core._app_error_log("本地数据库连接失败", e)
            return self._db_fail(f"无法连接数据库: {e}")

        try:
            self._patch_db_accessor()
            import server.database as appdb
            appdb.init_db()  # 幂等: 表不存在则创建/补齐
        except Exception as e:
            _pub_core._app_error_log("本地数据库初始化失败", e)
            return self._db_fail(f"初始化数据库失败: {e}")

        self.db_ok = True
        self.db_status_text = (f"数据库: 已连接 ✅ (本地文件, 父级商品 {parent_count} 个) | "
                               f"图片目录: {self.image_root or '(用数据库内配置)'}")
        self._save_config()
        self._log(f"📦 数据库已连接: {db_path} (父级商品 {parent_count} 个)")
        return {"ok": True, "status": self.db_status_text, "parent_count": parent_count, "msg": "数据库已连接"}

    def _apply_remote_db(self):
        host = self.host.strip()
        port = (self.port or "8000").strip()
        if not host:
            return self._db_fail("请填写主库机器的 IP 或域名！并确保主机已运行 ERP 服务: python -m server.app")

        # 自动探测协议 (http / https 内网穿透隧道)
        try:
            probe, detected_scheme = _pub_core.RemoteSQLiteConnection.connect_with_autodetect(
                host, port, self.token)
            self.remote_scheme = detected_scheme
            info = probe.ping()
        except Exception as e:
            _pub_core._app_error_log("远程连接探测失败", e)
            return self._db_fail(
                f"无法连接 {host}:{port}\n{e}\n\n请检查: 1) 主机是否已运行 ERP 服务 (python -m server.app)  "
                f"2) IP/端口是否正确 (图片服务已合并进 ERP, 端口填 8000 或隧道端口)  3) 访问令牌是否一致")

        try:
            self._patch_db_accessor()
            import server.database as appdb
            appdb.init_db()  # 经 HTTP 代理执行 (表已存在则无操作)
        except Exception as e:
            _pub_core._app_error_log("远程初始化失败", e)
            return self._db_fail(f"初始化远程数据库失败: {e}")

        self.db_ok = True
        self.db_status_text = (f"数据库: 已连接 ✅ (远程 {host}:{port}, 父级商品 {info.get('parent_count', '?')} 个) | "
                               f"图片目录: {self.image_root or '(用数据库内配置)'}")
        self._save_config()
        self._log(f"📦 远程数据库已连接: {host}:{port} (父级商品 {info.get('parent_count', '?')} 个)")
        return {"ok": True, "status": self.db_status_text, "msg": "远程数据库已连接"}

    def _db_fail(self, msg):
        self.db_ok = False
        self.db_status_text = f"数据库: 连接失败 ❌ ({msg.splitlines()[0][:80]})"
        return {"ok": False, "msg": msg, "status": self.db_status_text}

    def apply_image_root(self, cfg=None):
        """应用图片存储目录覆盖并重新注入运行时配置"""
        if isinstance(cfg, dict):
            self.image_root = self._pick(cfg, "image_root", self.image_root)
        warn = ""
        if self.image_root and not os.path.exists(self.image_root):
            warn = (f"目录在本机不存在: {self.image_root}\n上件时图片将无法上传！请确认已将主机图片目录映射为"
                    "本机可访问路径 (盘符或 UNC 共享)。")
        if self.conn_mode == "remote" or self.db_path.strip():
            res = self.apply_db()
        else:
            self._save_config()
            res = {"ok": True, "status": self.db_status_text}
        self._log(f"🖼️ 图片存储目录: {self.image_root or '(用数据库内配置)'}")
        res["warn"] = warn
        return res

    def _patch_db_accessor(self):
        """
        与 desktop_app.DesktopApp._patch_db_accessor 等价:
        - 本地: server.database.DB_PATH → 所选文件, 图片按本地/共享路径解析
        - 远程: 将 server.database / product_service / task_service / auth_service 中的
          get_db_connection 替换为 HTTP 桥接适配器 (配合主机 ERP 服务内嵌的图片服务);
          同时接管 FileService.resolve_image_path —— 本地找不到的图片自动从主库服务器
          下载到本地缓存后再上传店小秘
        同时覆盖 get_setting 实现图片存储目录重定向 (storage_path_win)。
        """
        import server.database as appdb
        from server.services import file_service as fs_module

        image_root = self.image_root.strip()
        orig_get_setting = appdb.get_setting

        def get_setting_with_override(key, default=None):
            if key in ("storage_path_win", "storage_path_mac") and image_root:
                return image_root
            return orig_get_setting(key, default)

        appdb.get_setting = get_setting_with_override

        # 首次打补丁前保存原始函数, 供本地/远程模式来回切换
        if not hasattr(appdb, "_orig_get_db_connection"):
            appdb._orig_get_db_connection = appdb.get_db_connection
        if not hasattr(fs_module.FileService, "_orig_resolve_image_path"):
            fs_module.FileService._orig_resolve_image_path = fs_module.FileService.resolve_image_path

        if self.conn_mode == "remote":
            scheme = self.remote_scheme or ""
            if not scheme:
                try:
                    _, scheme = _pub_core.RemoteSQLiteConnection.connect_with_autodetect(
                        self.host.strip(), (self.port or "8000").strip(), self.token)
                    self.remote_scheme = scheme
                except Exception:
                    scheme = "http"
            remote_conn = _pub_core.RemoteSQLiteConnection(
                self.host.strip(), int((self.port or "8000").strip() or 8000), self.token, scheme=scheme)
            self._remote_conn = remote_conn
            appdb.DB_PATH = f"{remote_conn.base} (远程)"
            factory = lambda: remote_conn  # noqa: E731
            fs_module.FileService.resolve_image_path = staticmethod(self._make_remote_image_resolver())
        else:
            self._remote_conn = None
            appdb.DB_PATH = self.db_path.strip()
            factory = None
            fs_module.FileService.resolve_image_path = fs_module.FileService._orig_resolve_image_path

        # 统一替换各模块中已绑定的 get_db_connection 引用
        import importlib
        targets = [appdb]
        for mod_name in ("server.services.product_service",
                         "server.services.task_service",
                         "server.services.auth_service"):
            try:
                targets.append(importlib.import_module(mod_name))
            except Exception:
                pass
        for mod in targets:
            mod.get_db_connection = factory if factory is not None else appdb._orig_get_db_connection

    def _make_remote_image_resolver(self):
        """
        与 desktop_app 等价: 远程模式图片解析 —— 本地/共享路径优先, 失败则从
        主库服务器 (/file 接口) 下载到本地缓存 (%TEMP%\\erp_remote_images) 后返回缓存路径
        """
        import hashlib
        cache_dir = os.path.join(tempfile.gettempdir(), "erp_remote_images")
        os.makedirs(cache_dir, exist_ok=True)
        remote_conn = self._remote_conn

        def resolve_image_path(path: str) -> str:
            if not path or not isinstance(path, str) or not path.strip():
                return ""
            from server.services import file_service as fs_module
            local = fs_module.FileService._orig_resolve_image_path(path)
            if local:
                return local
            try:
                data = remote_conn.get_file(path.strip())
                if not data:
                    return ""
                filename = os.path.basename(path.strip().replace("\\", "/")) or "image.jpg"
                key = hashlib.md5(path.strip().encode("utf-8")).hexdigest()[:16]
                cache_path = os.path.join(cache_dir, f"{key}_{filename}")
                if not os.path.exists(cache_path) or os.path.getsize(cache_path) != len(data):
                    with open(cache_path, "wb") as f:
                        f.write(data)
                return cache_path
            except Exception as e:
                self._log(f"⚠️ 远程图片获取失败 [{path}]: {e}")
                return ""

        return resolve_image_path

    # ────────────────── 商品查询 ──────────────────
    def _find_product_by_sku(self, parent_sku: str):
        """按 Parent SKU 查询父级商品 (取最新一条) — 与 desktop_app 一致"""
        import server.database as appdb
        conn = appdb.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT p.id, p.parent_sku, p.sku, p.title, p.store_account, p.brand,
                       p.status, p.main_image, p.variation_theme,
                       (SELECT COUNT(*) FROM product_items WHERE is_parent = 0 AND parent_sku = p.sku) AS variation_count
                FROM product_items p
                WHERE p.is_parent = 1 AND (p.parent_sku = ? OR p.sku = ?)
                ORDER BY p.id DESC LIMIT 1
            """, (parent_sku, parent_sku))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def query_product(self, sku):
        sku = (sku or "").strip()
        if not sku:
            return {"ok": False, "msg": "请输入 Parent SKU！"}
        try:
            product = self._find_product_by_sku(sku)
        except Exception as e:
            self.current_product = None
            return {"ok": False, "msg": f"数据库查询出错: {e}\n请检查数据库配置 (点「应用」重新连接)。"}
        if not product:
            self.current_product = None
            return {"ok": False, "msg": f"未找到 Parent SKU「{sku}」"}
        self.current_product = product
        self._log(f"🔍 已找到商品: #{product['id']} [{product['parent_sku']}] {product['title'] or ''}")
        return {"ok": True, "product": product}

    # ────────────────── Chrome 9222 ──────────────────
    @staticmethod
    def _chrome_port_open() -> bool:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{_pub_core.CDP_PORT}/json/version")
            with urllib.request.urlopen(req, timeout=1.0):
                return True
        except Exception:
            return False

    @staticmethod
    def _detect_chrome_exe():
        for p in _pub_core.CHROME_CANDIDATES:
            if os.path.exists(p):
                return p
        return None

    def check_chrome(self):
        return {"running": self._chrome_port_open()}

    def launch_chrome(self, chrome_dir=None):
        if chrome_dir is not None:
            self.chrome_dir = (chrome_dir or "").strip() or _pub_core.DEFAULT_CHROME_DIR
        self._save_config()
        threading.Thread(target=self._launch_chrome_worker, daemon=True).start()
        return {"ok": True, "msg": "starting"}

    def _launch_chrome_worker(self):
        chrome_dir = self.chrome_dir.strip() or _pub_core.DEFAULT_CHROME_DIR
        try:
            import config as toolkit_config
            toolkit_config.USER_DATA_DIR = chrome_dir  # 上件管线同步使用该目录
        except Exception:
            pass

        if self._chrome_port_open():
            self._log("🌐 Chrome 9222 已在运行，直接复用现有实例")
            self._open_dxm_tab_cdp()
            return

        exe = self._detect_chrome_exe()
        if not exe:
            self._log("❌ 未找到 Chrome，请确认已安装")
            return

        os.makedirs(chrome_dir, exist_ok=True)
        self._log(f"🌐 正在启动 Chrome 并打开店小秘 (数据目录: {chrome_dir})")
        try:
            subprocess.Popen(
                [exe, f"--remote-debugging-port={_pub_core.CDP_PORT}",
                 f"--user-data-dir={chrome_dir}",
                 _pub_core.DXM_URL, "--no-first-run", "--no-default-browser-check"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception as e:
            self._log(f"❌ Chrome 启动失败: {e}")
            return

        for _ in range(30):
            time.sleep(0.3)
            if self._chrome_port_open():
                break
        if self._chrome_port_open():
            self._log(f"✅ Chrome 9222 启动成功，已打开店小秘 ({_pub_core.DXM_URL})")
            self._log("💡 首次使用请在打开的页面中登录店小秘，登录一次后长期有效")
        else:
            self._log("❌ Chrome 启动超时，9222 端口未就绪")

    def _open_dxm_tab_cdp(self):
        """Chrome 已运行时, 通过 CDP 在现有实例中新开店小秘标签页"""
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{_pub_core.CDP_PORT}/json/new?{_pub_core.DXM_URL}", method="PUT")
            urllib.request.urlopen(req, timeout=3).read()
            self._log(f"🌐 已在现有 Chrome 中打开店小秘: {_pub_core.DXM_URL}")
        except Exception as e:
            self._log(f"⚠️ 自动打开店小秘页失败 ({e})，请手动在浏览器访问")

    # ────────────────── 上件与终止 ──────────────────
    def start_publish(self):
        if self.publishing:
            return {"ok": False, "msg": "当前已有上件任务在执行中，请稍候！"}
        if not self.current_product:
            return {"ok": False, "msg": "请先查询商品！"}
        if not self._chrome_port_open():
            return {"ok": False, "need_chrome": True, "msg": "Chrome 9222 尚未启动，请先点击「登录 ERP 系统」"}

        product_id = self.current_product["id"]
        parent_sku = self.current_product["parent_sku"]
        self.publishing = True
        self._stop_requested = False
        self.last_result = ""
        self._log("=" * 58)
        self._log(f"🚀 开始上件: #{product_id} [{parent_sku}]  {datetime.now().strftime('%H:%M:%S')}")
        self._worker = threading.Thread(target=self._publish_worker, args=(product_id,), daemon=True)
        self._worker.start()
        return {"ok": True, "msg": "started"}

    def _publish_worker(self, product_id: int):
        result_text = "❌ 上件失败 (详见日志)"
        try:
            bridge = _get_pub_bridge()  # 惰性导入 (playwright 导入耗时, 仅在上件时加载)
            chrome_dir = self.chrome_dir.strip() or None
            res = bridge.publish_product_to_erp(product_id, log_callback=self._log,
                                                chrome_user_data_dir=chrome_dir)
            ok = res.get("success", False)
            if self._stop_requested:
                self._log("🛑 上件已被用户终止")
                result_text = "🛑 已终止 (详见日志)"
                return
            self._log(("✅" if ok else "❌") + f" 上件结束: {res.get('msg', '')}")
            result_text = "✅ 成功！" if ok else "❌ 失败 (详见日志)"
        except Exception as e:
            if self._stop_requested:
                self._log("🛑 上件已被用户终止")
                result_text = "🛑 已终止 (详见日志)"
            else:
                self._log(f"❌ 上件异常: {e}")
        finally:
            self.last_result = result_text
            self.publishing = False

    def stop_publish(self):
        """终止当前上件任务: 无条件强杀 Playwright Node 驱动进程, 立即中断自动化流程"""
        if not self.publishing:
            return {"ok": False, "msg": "当前没有进行中的上件任务"}
        self._stop_requested = True
        self._log("🛑 用户点击终止，正在强制停止上件任务...")
        threading.Thread(target=self._stop_publish_worker, daemon=True).start()
        return {"ok": True, "msg": "stopping"}

    def _stop_publish_worker(self):
        """与 desktop_app 一致: 强杀本进程登记的 Playwright 驱动进程树,
        持续压制最多 60 秒 — 若上件尚未进入自动化阶段或管线重建驱动, 出现一个杀一个"""
        try:
            from core.browser_manager import cleanup_stale_drivers
        except Exception as e:
            self._log(f"⚠️ 终止模块加载失败: {e}")
            return
        killed_total = 0
        deadline = time.time() + 60
        while time.time() < deadline:
            if not self.publishing:  # 任务已结束 (终止生效或自然完成)
                break
            killed = cleanup_stale_drivers()
            if killed:
                killed_total += killed
                self._log(f"🛑 已强制停止自动化驱动进程 ({killed} 个)")
                time.sleep(0.5)
                continue
            time.sleep(0.5)
        if killed_total:
            self._log(f"🛑 上件任务已终止 (共停止 {killed_total} 个自动化驱动进程)")
        elif self.publishing:
            self._log("⚠️ 未检测到自动化驱动进程，终止结束 (任务可能已完成)")

    def run_state(self):
        alive = bool(self._worker and self._worker.is_alive()) or self.publishing
        return {"running": alive, "result": self.last_result}

    # ────────────────── 杂项 ──────────────────
    def browse(self, mode="file"):
        """原生文件/目录选择框 (通过 pywebview 当前窗口)"""
        try:
            import webview
            win = webview.windows[0] if getattr(webview, "windows", None) else None
            if win is None:
                return {"ok": False, "msg": "窗口未就绪 (浏览器模式下请手动输入路径)"}
            # pywebview 6+ 用 webview.FileDialog 枚举, 旧版常量兜底
            fd = getattr(webview, "FileDialog", None)
            dlg_open = getattr(fd, "OPEN", None)
            dlg_folder = getattr(fd, "FOLDER", None)
            if dlg_open is None or dlg_folder is None:
                dlg_open, dlg_folder = webview.OPEN_DIALOG, webview.FOLDER_DIALOG
            if mode == "dir":
                res = win.create_file_dialog(dlg_folder)
            else:
                res = win.create_file_dialog(
                    dlg_open, file_types=("SQLite 数据库 (*.db)", "所有文件 (*.*)"))
            path = res[0] if res else ""
            return {"ok": bool(path), "path": path}
        except Exception as e:
            return {"ok": False, "msg": f"打开选择框失败: {e}"}

    def initial_connect(self):
        """启动时后台自动连接数据库 (与 tkinter 版一致, 不阻塞窗口显示)"""
        self._log("⏳ 正在初始化数据库连接...")
        try:
            res = self.apply_db()
            if not res.get("ok"):
                self._log(f"⚠️ 初始连接失败: {str(res.get('msg', ''))[:120]}")
        except Exception as e:
            _pub_core._app_error_log("初始连接失败", e)
            self._log(f"⚠️ 初始连接异常: {e}")


class UnifiedBridge:
    """pywebview js_api 聚合层

    - 广告方法 (poll_logs / confirm_run / modal_ok / stop / ...) 方法名与行为
      原样转发到 mac 独立版 Bridge (sellfox_ad_gui.Bridge), 广告前端代码零改动;
    - 上件方法统一以 pub_ 前缀命名, 由 PublishBridge 实现。
    """

    def __init__(self):
        self._ads = AdsBridge()
        self._pub = PublishBridge()
        self._ads_log_ts = time.time()   # 广告桥接最近日志时间 (判断浏览器动作是否已静默完成)
        self._detach_token = None        # 闲置驱动下线任务的取消令牌
        self._ads_was_running = False    # 广告投放状态迁移检测 (结束即回收驱动)
        self._tap_ads_log()
        self._install_exit_guard()

    # ════════ 🧹 驱动守护 (新标签页白屏治理) ════════
    def _tap_ads_log(self):
        """旁路监听广告桥接日志: 用于判断「启动浏览器/打开赛狐页」等动作是否已静默完成"""
        try:
            orig = self._ads._log

            def tapped(line):
                self._ads_log_ts = time.time()
                try:
                    orig(line)
                except Exception:
                    pass

            self._ads._log = tapped
        except Exception:
            pass

    @staticmethod
    def _install_exit_guard():
        """进程退出 (含窗口正常关闭之外的情况) 也要回收 playwright 驱动, 防止残留 attach"""
        import atexit

        def _cleanup():
            try:
                _guard().kill_drivers()
            except Exception:
                pass

        try:
            atexit.register(_cleanup)
        except Exception:
            pass

    def _cancel_idle_detach(self):
        if self._detach_token:
            self._detach_token[0] = False
            self._detach_token = None

    def _reset_ads_bm(self):
        """清空常驻 BrowserManager 引用 (其驱动已停止/被杀, 下次浏览器操作会自动重建)"""
        bm = getattr(self._ads, "bm", None)
        if bm is not None:
            try:
                bm._task_queue.put(None)
            except Exception:
                pass
        self._ads.bm = None
        self._ads._bm_dir = None

    @staticmethod
    def _cleanup_drivers(keep=None) -> list:
        """清理残留/闲置的 playwright 驱动 (跨进程 + 同进程), 返回被杀 PID 列表"""
        try:
            return _guard().kill_drivers(keep_pids=keep)
        except Exception:
            return []

    def _schedule_idle_detach(self):
        """浏览器打开动作完成后, 把闲置的常驻驱动优雅下线。

        闲置驱动不再被调用时, 事件 pipe 会逐渐堆满并冻结 node 事件循环 —— 之后任何
        新标签页都会卡在 waitForDebugger 暂停态 (白屏 / goto 超时)。及时下线即可根治
        (只停本地驱动, 不影响用户 Chrome 及其标签页)。
        """
        self._cancel_idle_detach()
        token = [True]
        self._detach_token = token

        def work():
            deadline = time.time() + 90
            while time.time() < deadline:
                time.sleep(1.5)
                if not token[0]:
                    return                                     # 有新的浏览器操作, 让位
                if self._ads.worker and self._ads.worker.is_alive():
                    return                                     # 投放任务运行中, 不动任何驱动
                bm = getattr(self._ads, "bm", None)
                if bm is None:
                    return
                if time.time() - self._ads_log_ts < 5.0:
                    continue                                   # 动作仍在进行 (持续有日志输出)
                info = _guard().detach_browser_manager(bm)
                self._reset_ads_bm()
                note = "🧹 已释放闲置的浏览器自动化驱动 (不影响浏览器, 防止新标签页白屏)"
                if info.get("killed"):
                    note += f" [硬清理 {info['killed']}]"
                try:
                    self._ads._log(note)
                except Exception:
                    pass
                return

        threading.Thread(target=work, daemon=True, name="IdleDriverDetach").start()

    # ════════ 📢 广告投放 (完全复刻 mac 独立版) ════════
    def poll_logs(self, seen=0):
        return self._ads.poll_logs(seen)

    def clear_log(self):
        return self._ads.clear_log()

    def get_create_modes(self):
        return self._ads.get_create_modes()

    def get_bid_strategies(self):
        return self._ads.get_bid_strategies()

    def get_default(self, key):
        return self._ads.get_default(key)

    def get_options(self):
        return self._ads.get_options()

    def get_submit_mode(self):
        """主机端「是否自动提交广告」: 供前端确认框提示 (自动提交时二次确认)"""
        return self._ads.get_submit_mode()

    def desktop_login(self, username, password):
        """桌面端登录 (用户数据从 ERP 服务端取; 角色决定菜单权限: admin=全部, 其它=仅上件)"""
        return self._ads.desktop_login(username, password)

    def trim_toggle(self, _disabled=None):
        return self._ads.trim_toggle(_disabled)

    def shop_focus(self):
        return self._ads.shop_focus()

    def check_cdp(self):
        return self._ads.check_cdp()

    def set_user_dir(self, d):
        return self._ads.set_user_dir(d)

    def launch_browser(self):
        self._cancel_idle_detach()
        self._ads_log_ts = time.time()
        res = self._ads.launch_browser()
        self._schedule_idle_detach()   # 打开动作完成后自动下线闲置驱动
        return res

    def open_sellfox(self):
        self._cancel_idle_detach()
        self._ads_log_ts = time.time()
        res = self._ads.open_sellfox()
        self._schedule_idle_detach()
        return res

    def confirm_run(self, p):
        if self._pub.publishing:
            return {"error": "商品上件任务正在执行中, 请等它完成或点「终止」后再投放广告"}
        return self._ads.confirm_run(p)

    def modal_ok(self):
        if self._pub.publishing:
            return "running"   # 前端统一提示"任务正在执行中"
        self._cancel_idle_detach()
        # 开投前清理一切残留/闲置驱动 (此刻无任务在跑, 清理安全): 避免新标签页白屏
        killed = self._cleanup_drivers()
        if killed:
            self._reset_ads_bm()
            self._ads._log(f"🧹 开投前已清理 {len(killed)} 个残留自动化驱动进程 {killed}")
        return self._ads.modal_ok()

    def stop(self):
        return self._ads.stop()

    def run_state(self):
        st = self._ads.run_state()
        running = bool(st.get("running"))
        if self._ads_was_running and not running:
            self._cleanup_after_ads_job()
        self._ads_was_running = running
        return st

    def _cleanup_after_ads_job(self):
        """广告投放结束: 算子驱动可能未优雅退出, 延时兜底回收 (残留 attach 会阻塞新标签页)"""
        def work():
            time.sleep(3.0)
            if self._pub.publishing:
                return
            if self._ads.worker and self._ads.worker.is_alive():
                return
            killed = self._cleanup_drivers()
            if killed:
                self._reset_ads_bm()
                try:
                    self._ads._log(f"🧹 投放结束, 已回收 {len(killed)} 个自动化驱动进程")
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True, name="AdsJobCleanup").start()

    # ════════ 📦 商品上件 (pub_*) ════════
    def pub_get_options(self):
        return self._pub.get_options()

    def pub_apply_db(self, cfg=None, create=False):
        # 兼容前端单对象调用: {..., "create": true}
        if isinstance(cfg, dict) and "create" in cfg:
            create = bool(cfg.get("create"))
        return self._pub.apply_db(cfg, create=create)

    def pub_apply_image_root(self, cfg=None):
        return self._pub.apply_image_root(cfg)

    def pub_set_chrome_dir(self, d):
        return self._pub.set_chrome_dir(d)

    def sys_set_chrome_dir(self, d):
        """系统配置: 用户数据目录 (上件与广告共用同一份配置)"""
        d = (d or "").strip()
        res = None
        try:
            res = self._pub.set_chrome_dir(d)   # 上件: 持久化到 desktop_config.json
        except Exception as e:
            res = {"ok": False, "msg": str(e)[:120]}
        try:
            self._ads.set_user_dir(d)           # 广告: 同步内存值 (与上件同目录)
        except Exception:
            pass
        return res or {"ok": True}

    def pub_query_product(self, sku):
        return self._pub.query_product(sku)

    def pub_check_chrome(self):
        return self._pub.check_chrome()

    def pub_launch_chrome(self, chrome_dir=None):
        return self._pub.launch_chrome(chrome_dir)

    def pub_start_publish(self):
        if self._ads.worker and self._ads.worker.is_alive():
            return {"ok": False, "msg": "广告投放任务正在执行中, 请等它完成或点「终止」后再上件"}
        self._cancel_idle_detach()
        # 上件前清理一切残留/闲置驱动 (此刻无任务在跑): 避免上件时页面白屏/打不开
        killed = self._cleanup_drivers()
        if killed:
            self._reset_ads_bm()
            self._pub._log(f"🧹 上件前已清理 {len(killed)} 个残留自动化驱动进程 {killed}")
        return self._pub.start_publish()

    def pub_stop_publish(self):
        return self._pub.stop_publish()

    def pub_run_state(self):
        return self._pub.run_state()

    def pub_poll_logs(self, seen=0):
        return self._pub.poll_logs(seen)

    def pub_clear_log(self):
        return self._pub.clear_log()

    def pub_browse(self, mode="file"):
        return self._pub.browse(mode)

    def pub_initial_connect(self):
        self._pub.initial_connect()
        return {"ok": True}


_bridge = None


def get_bridge():
    """惰性构建聚合桥接 (splash 显示后再初始化, 保证启动页尽快出现)"""
    global _bridge
    if _bridge is None:
        _bridge = UnifiedBridge()
    return _bridge


# ══════════════════════════════════════════════════════════════
# 浏览器模式 (调试/备用): gui/app.html + /api/* 桥接
# ══════════════════════════════════════════════════════════════
def _dispatch(fn, body):
    """HTTP body → 桥接方法调用 (兼容 {args:[...]} 位置参数与对象参数两种形态)"""
    if isinstance(body, dict) and set(body.keys()) == {"args"} and isinstance(body.get("args"), list):
        return fn(*body["args"])
    if isinstance(body, dict) and body:
        try:
            return fn(**body)
        except TypeError:
            return fn(body)
    if body in ({}, None, ""):
        return fn()
    return fn(body)


def _serve():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    bridge = get_bridge()   # 浏览器模式无启动页, 直接构建桥接

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/app.html"):
                with open(os.path.join(GUI_DIR, "app.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html")
            if self.path.startswith("/api/state"):
                return self._send(200, bridge.pub_run_state())
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            action = self.path.rsplit("/", 1)[-1]
            fn = getattr(bridge, action, None)
            if not callable(fn):
                return self._send(404, {"error": f"unknown action: {action}"})
            try:
                res = _dispatch(fn, body)
                return self._send(200, res if isinstance(res, dict) else {"result": res})
            except Exception as e:
                return self._send(200, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"})

    srv = ThreadingHTTPServer(("127.0.0.1", SERVE_PORT), H)
    print(f"浏览器模式: http://127.0.0.1:{SERVE_PORT}")
    # 启动即清理上个会话遗留的 playwright 驱动 (残留的冻结驱动会让新标签页白屏)
    threading.Thread(target=lambda: _guard().spawn_background_cleanup(log=bridge._pub._log),
                     daemon=True).start()
    # 后台自动连接数据库
    threading.Thread(target=bridge._pub.initial_connect, daemon=True).start()
    try:
        srv.serve_forever()
    finally:
        try:
            _guard().kill_drivers()
        except Exception:
            pass


def selftest():
    """打包产物自检 (结果写文件, windowed 程序无 stdout)"""
    out = [f"ERP 全能助手 selftest @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | code={CODE_STAMP}"]

    # 0) 运行环境与后端自检 (打包后最容易出问题的一环)
    try:
        import clr  # noqa: F401
        out.append("pythonnet(clr): OK")
    except Exception as e:
        out.append(f"pythonnet(clr) FAIL: {e}")
    try:
        import webview.platforms.winforms  # noqa: F401
        out.append("webview winforms backend: OK")
    except Exception as e:
        out.append(f"webview winforms FAIL: {e}")
    try:
        import playwright  # noqa: F401
        out.append("playwright: OK")
    except Exception as e:
        out.append(f"playwright FAIL: {e}")
    try:
        from core.driver_guard import list_drivers
        out.append(f"driver guard: OK (现有驱动: {list_drivers()})")
    except Exception as e:
        out.append(f"driver guard FAIL: {e}")

    async def _t():
        from playwright.async_api import async_playwright
        from sellfox_ad_gui import CDP_PORT
        pw = await async_playwright().start()
        try:
            try:
                b = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}", timeout=15000)
                out.append("direct connect OK")
            except Exception as e1:
                from core.cdp_proxy import get_proxy
                proxy = get_proxy(f"http://127.0.0.1:{CDP_PORT}")
                b = await pw.chromium.connect_over_cdp(proxy.ws_endpoint, timeout=20000)
                out.append(f"proxy fallback OK (direct fail: {str(e1)[:60]})")
            out.append(f"contexts={len(b.contexts)}")
            await b.close()
        except Exception as e:
            out.append(f"connect FAIL: {str(e)[:150]}")
        await pw.stop()

    try:
        import asyncio
        asyncio.run(_t())
    except Exception as e:
        out.append(f"asyncio FAIL: {e}")
    out.append(f"gui assets: {os.path.exists(os.path.join(GUI_DIR, 'app.html'))}")
    out.append(f"publish bridge: {'ok' if _pub_core is not None else 'fail'}")
    out.append(f"ads bridge: {'ok' if get_bridge()._ads is not None else 'fail'}")
    path = os.path.join(BASE_DIR, "unified_selftest.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    if "--serve" in sys.argv:
        _serve()
        return

    import webview                      # 惰性: --selftest/--serve 不需要
    bridge = get_bridge()
    # 启动即清理上个会话遗留的 playwright 驱动 (残留的冻结驱动会让新标签页白屏)
    threading.Thread(target=lambda: _guard().spawn_background_cleanup(log=bridge._pub._log),
                     daemon=True).start()
    # 启动时后台自动连接数据库 (不阻塞窗口显示)
    threading.Thread(target=bridge._pub.initial_connect, daemon=True).start()
    webview.create_window(
        APP_TITLE, os.path.join(GUI_DIR, "app.html"),
        js_api=bridge, width=1000, height=940, min_size=(880, 800), text_select=True)
    webview.start()
    # 窗口关闭: 进程退出前回收全部 playwright 驱动, 避免残留 attach 导致
    # 下次"打开过网页后再开新标签页白屏"
    try:
        _guard().kill_drivers()
    except Exception:
        pass


if __name__ == "__main__":
    main()
