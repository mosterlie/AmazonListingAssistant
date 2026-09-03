#!/usr/bin/env python3
"""
ERP 桌面上件助手 (Desktop Publishing Assistant) — 支持远程部署

功能：
1. 可配置商品数据库路径：本地文件 / 网络共享 (\\\\server\\share\\xx.db) / 映射盘符 (Z:\\xx.db)
2. 可配置图片存储目录（远程机器上映射同一共享目录，覆盖数据库中的 storage_path_win 设置）
3. 一键启动 Chrome 调试实例 (9222 端口, 用户数据目录 C:\ChromeDebugUser)
4. 输入 Parent SKU → 查询商品 → 一键自动上件到店小秘 ERP

运行方式：
    python desktop_app.py
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
import ssl
import urllib.request
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

# ──────────────────────────────────────────────────────────────
# 路径与环境准备 (必须在导入 server/browser 模块之前)
# ──────────────────────────────────────────────────────────────
# PyInstaller onefile 下 __file__ 指向临时解压目录, 配置/数据必须跟随 exe 所在目录
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

def _app_error_log(stage: str, exc: Exception):
    """把关键失败追加到 exe 同目录 desktop_error.log, 便于远程电脑排查"""
    import traceback
    try:
        with open(os.path.join(BASE_DIR, "desktop_error.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {stage}:\n")
            f.write("".join(traceback.format_exception(exc)).rstrip() + "\n\n")
    except Exception:
        pass


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CONFIG_FILE = os.path.join(BASE_DIR, "desktop_config.json")
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "products.db")

# 远程连接默认值 (SakuraFrp 隧道 → 主机 db_agent), 新环境首次启动直接预填
DEFAULT_REMOTE_HOST = "frp-rib.com"
DEFAULT_REMOTE_PORT = 49063
DEFAULT_REMOTE_TOKEN = "erp2024"
# Chrome 9222 用户数据目录默认值 (C 盘根目录下, 可在界面配置调整)
DEFAULT_CHROME_DIR = r"C:\ChromeDebugUser"
DXM_URL = "https://www.dianxiaomi.com/"
CDP_PORT = 9222
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
]

# 预先固定浏览器自动化使用的用户数据目录 (erp_bridge 内部 BrowserEngine 默认值在导入时绑定)
import config as toolkit_config  # noqa: E402  (项目根目录 config.py)
toolkit_config.USER_DATA_DIR = DEFAULT_CHROME_DIR

_BRIDGE = None


def _get_bridge():
    """惰性加载上件管线 (playwright 导入耗时 8~15 秒, 延迟到启动动画之后再执行)"""
    global _BRIDGE
    if _BRIDGE is None:
        from server.services.erp_bridge import ERPBridgeService
        _BRIDGE = ERPBridgeService
    return _BRIDGE


def load_app_config() -> dict:
    """读取桌面应用配置 (数据库路径、图片存储目录等)"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"db_path": DEFAULT_DB_PATH, "image_root": ""}


def save_app_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# 远程数据库 HTTP 桥接 (配合主机上的 db_agent.py 使用)
# 模拟 sqlite3 连接/游标接口, 底层走 HTTP 调用主库机器执行 SQL
# ──────────────────────────────────────────────────────────────
import urllib.parse  # noqa: E402


class RowLike(dict):
    """兼容 sqlite3.Row: 支持 row['col'] 与 row[0] 两种访问方式"""
    def __getitem__(self, k):
        if isinstance(k, int):
            return list(self.values())[k]
        return super().__getitem__(k)


class RemoteSQLiteCursor:
    def __init__(self, conn: "RemoteSQLiteConnection"):
        self._conn = conn
        self._rows = []
        self._pos = 0
        self.rowcount = -1
        self.lastrowid = None

    def execute(self, sql, params=()):
        read = sql.lstrip().split(None, 1)
        is_read = bool(read) and read[0].upper() in ("SELECT", "PRAGMA", "WITH", "EXPLAIN")
        payload = self._conn._post("/query" if is_read else "/execute",
                                   {"sql": sql, "params": list(params)})
        if is_read:
            cols = payload.get("columns", [])
            self._rows = [RowLike(zip(cols, r)) for r in payload.get("rows", [])]
            self._pos = 0
        else:
            self.rowcount = payload.get("rowcount", -1)
            self.lastrowid = payload.get("lastrowid")
        return self

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def close(self):
        pass


class RemoteSQLiteConnection:
    """通过 db_agent.py (主机上的 HTTP 服务) 远程执行 SQL 的 sqlite3 适配器
    支持 http / https (内网穿透隧道, 如 SakuraFrp 自动 HTTPS, 跳过证书校验)"""

    def __init__(self, host: str, port, token: str = "", timeout: float = 15.0, scheme: str = ""):
        host = host.strip()
        if "://" in host:
            scheme, host = host.split("://", 1)
        self.host = host.rstrip("/")
        self.port = int(port)
        self.scheme = (scheme or "http").lower()
        self.token = (token or "").strip()
        self.timeout = timeout
        self.base = f"{self.scheme}://{self.host}:{self.port}"
        # 内网穿透隧道 (SakuraFrp 等) 证书与域名不匹配, https 时跳过证书校验 (令牌仍保证鉴权)
        self._ssl_ctx = ssl._create_unverified_context() if self.scheme == "https" else None

    @staticmethod
    def connect_with_autodetect(host: str, port, token: str = ""):
        """自动探测协议: 依次尝试 http / https, 返回 (连接, scheme)"""
        errors = []
        for scheme in ("http", "https"):
            conn = RemoteSQLiteConnection(host, port, token, scheme=scheme)
            try:
                conn.ping()
                return conn, scheme
            except Exception as e:
                errors.append(f"{scheme}: {e}")
        raise RuntimeError("；".join(errors))

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-DB-Token": self.token},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if isinstance(result, dict) and "error" in result and "columns" not in result and "rowcount" not in result:
            raise RuntimeError(f"远程数据库错误: {result['error']}")
        return result

    def ping(self) -> dict:
        req = urllib.request.Request(self.base + "/ping",
                                     headers={"X-DB-Token": self.token})
        with urllib.request.urlopen(req, timeout=8.0, context=self._ssl_ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_file(self, path: str) -> bytes:
        """从主库机器下载商品图片文件内容 (经 db_agent /file 接口)"""
        req = urllib.request.Request(
            self.base + "/file?" + urllib.parse.urlencode({"path": path}),
            headers={"X-DB-Token": self.token}
        )
        with urllib.request.urlopen(req, timeout=60.0, context=self._ssl_ctx) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return resp.read()

    def cursor(self):
        return RemoteSQLiteCursor(self)

    def commit(self):
        pass  # /execute 在代理端已自动提交

    def rollback(self):
        pass

    def close(self):
        pass


class DesktopApp:
    """桌面上件助手主窗口"""

    def __init__(self, root: tk.Tk, on_ready=None, on_status=None):
        self.root = root
        self.root.title("ERP 桌面上件助手 - 店小秘自动化")
        self.root.geometry("900x680")
        self.root.minsize(800, 600)

        self._on_ready = on_ready      # 初始化完成回调 (用于关闭启动动画)
        self._on_status = on_status    # 启动过程状态文本回调 (更新启动动画提示)
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.publishing = False
        self._stop_requested = False  # 用户点击终止后置 True
        self.current_product = None  # 查询到的商品信息 dict

        self._build_ui()
        self._poll_log_queue()

        # 启动时应用已保存的配置
        cfg = load_app_config()
        self.conn_mode.set(cfg.get("conn_mode", "remote"))
        self.db_path_var.set(cfg.get("db_path", DEFAULT_DB_PATH))
        self.host_var.set(cfg.get("host", DEFAULT_REMOTE_HOST))
        self.port_var.set(str(cfg.get("port", DEFAULT_REMOTE_PORT)))
        self.token_var.set(cfg.get("token", DEFAULT_REMOTE_TOKEN))
        self.remote_scheme = cfg.get("scheme", "")
        self.image_root_var.set(cfg.get("image_root", ""))
        self.chrome_dir_var.set(cfg.get("chrome_user_data_dir", DEFAULT_CHROME_DIR))
        self._on_mode_change()
        # 初始数据库连接放到后台线程, 避免阻塞主线程导致启动动画卡住
        threading.Thread(target=self._initial_connect, daemon=True).start()

    def _initial_connect(self):
        """启动时后台执行数据库初始连接 (不阻塞启动动画)"""
        try:
            if self._on_status:
                self._on_status("正在连接数据库")
            self.apply_db_path(silent=True)
        except Exception as e:
            _app_error_log("初始连接失败", e)
            self._set_db_status(f"数据库: 初始连接异常 ({e})", "#dc2626")
        finally:
            if self._on_ready:
                self._ui(self._on_ready)

    def _set_db_status(self, text: str, fg: str):
        """线程安全更新数据库状态标签"""
        self._ui(lambda: self.lbl_db_status.config(text=text, foreground=fg))

    # ────────────────── UI 构建 ──────────────────
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # 1. 数据库配置区
        frm_db = ttk.LabelFrame(self.root, text=" 1. 商品数据库配置 (本地文件 或 远程 IP/域名) ")
        frm_db.pack(fill="x", **pad)

        self.conn_mode = tk.StringVar(value="remote")
        ttk.Label(frm_db, text="连接方式:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        mode_frm = ttk.Frame(frm_db)
        mode_frm.grid(row=0, column=1, columnspan=3, sticky="w", padx=4)
        ttk.Radiobutton(mode_frm, text="远程 IP/域名 (需主机运行 db_agent.py)", variable=self.conn_mode,
                        value="remote", command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_frm, text="本地 / 共享文件", variable=self.conn_mode,
                        value="local", command=self._on_mode_change).pack(side="left", padx=(16, 0))

        # -- 本地/共享文件行 --
        self.lbl_db_file = ttk.Label(frm_db, text="数据库路径:")
        self.lbl_db_file.grid(row=1, column=0, padx=6, sticky="e")
        self.db_path_var = tk.StringVar(value=DEFAULT_DB_PATH)
        self.ent_db_path = ttk.Entry(frm_db, textvariable=self.db_path_var)
        self.ent_db_path.grid(row=1, column=1, padx=4, sticky="we")
        self.btn_browse_db = ttk.Button(frm_db, text="浏览...", command=self._browse_db, width=8)
        self.btn_browse_db.grid(row=1, column=2, padx=2)

        # -- 远程连接行 (按模式显示/隐藏) --
        self.frm_remote = ttk.Frame(frm_db)
        self.lbl_host = ttk.Label(self.frm_remote, text="主机 (IP/域名):")
        self.lbl_host.pack(side="left")
        self.host_var = tk.StringVar(value=DEFAULT_REMOTE_HOST)
        self.ent_host = ttk.Entry(self.frm_remote, textvariable=self.host_var, width=20)
        self.ent_host.pack(side="left", padx=(2, 8))
        self.lbl_port = ttk.Label(self.frm_remote, text="端口:")
        self.lbl_port.pack(side="left")
        self.port_var = tk.StringVar(value=str(DEFAULT_REMOTE_PORT))
        self.ent_port = ttk.Entry(self.frm_remote, textvariable=self.port_var, width=7)
        self.ent_port.pack(side="left", padx=(2, 8))
        self.lbl_token = ttk.Label(self.frm_remote, text="令牌:")
        self.lbl_token.pack(side="left")
        self.token_var = tk.StringVar(value=DEFAULT_REMOTE_TOKEN)
        self.ent_token = ttk.Entry(self.frm_remote, textvariable=self.token_var, width=12, show="*")
        self.ent_token.pack(side="left", padx=2)

        ttk.Button(frm_db, text="应用", command=self.apply_db_path, width=8).grid(row=1, column=3, padx=(2, 8))

        ttk.Label(frm_db, text="图片存储目录:").grid(row=2, column=0, padx=6, pady=(0, 2), sticky="e")
        self.image_root_var = tk.StringVar()
        ttk.Entry(frm_db, textvariable=self.image_root_var).grid(row=2, column=1, padx=4, pady=(0, 2), sticky="we")
        ttk.Button(frm_db, text="浏览...", command=self._browse_image_root, width=8).grid(row=2, column=2, padx=2)
        ttk.Button(frm_db, text="应用", command=self.apply_image_root, width=8).grid(row=2, column=3, padx=(2, 8))

        ttk.Label(frm_db, text="远程模式: 填主库 IP/域名 + 端口 8765, 图片自动从主库服务器下载缓存后上传店小秘, "
                               "无需共享文件夹；图片目录为可选的本机覆盖路径 (留空即可)",
                  foreground="#64748b", wraplength=820, justify="left").grid(
            row=3, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 4))
        self.lbl_db_status = ttk.Label(frm_db, text="数据库: 未连接", foreground="#64748b")
        self.lbl_db_status.grid(row=4, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))
        frm_db.columnconfigure(1, weight=1)

        # 2. 浏览器区
        frm_browser = ttk.LabelFrame(self.root, text=" 2. 浏览器 (Chrome 9222 调试模式) ")
        frm_browser.pack(fill="x", **pad)
        self.btn_chrome = ttk.Button(frm_browser, text="🔐 登录 ERP 系统", command=self.launch_chrome)
        self.btn_chrome.grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ttk.Label(frm_browser, text="用户数据目录:").grid(row=0, column=1, padx=(8, 2), sticky="w")
        self.chrome_dir_var = tk.StringVar(value=DEFAULT_CHROME_DIR)
        ent_chrome_dir = ttk.Entry(frm_browser, textvariable=self.chrome_dir_var)
        ent_chrome_dir.grid(row=0, column=2, padx=2, sticky="we")
        self.lbl_browser_status = ttk.Label(frm_browser, text="● 未启动", foreground="#94a3b8")
        self.lbl_browser_status.grid(row=0, column=3, padx=8, sticky="e")
        frm_browser.columnconfigure(2, weight=1)
        ttk.Label(frm_browser, text="点击「登录 ERP 系统」自动启动 Chrome 9222 并打开店小秘, 登录一次后长期有效; "
                                   "修改目录后重新点击生效",
                  foreground="#64748b", wraplength=820, justify="left").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))

        # 3. 上件操作区
        frm_pub = ttk.LabelFrame(self.root, text=" 3. 商品上件 (输入 Parent SKU) ")
        frm_pub.pack(fill="x", **pad)
        ttk.Label(frm_pub, text="Parent SKU:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        self.sku_var = tk.StringVar()
        sku_entry = ttk.Entry(frm_pub, textvariable=self.sku_var, width=28)
        sku_entry.grid(row=0, column=1, padx=4, pady=8, sticky="w")
        sku_entry.bind("<Return>", lambda e: self.search_product())
        self.btn_search = ttk.Button(frm_pub, text="查询商品", command=self.search_product, width=12)
        self.btn_search.grid(row=0, column=2, padx=4)
        self.btn_publish = ttk.Button(frm_pub, text="🚀 上件", command=self.start_publish, width=12, state="disabled")
        self.btn_publish.grid(row=0, column=3, padx=(4, 0))
        self.btn_stop = ttk.Button(frm_pub, text="🛑 终止", command=self.stop_publish, width=10, state="disabled")
        self.btn_stop.grid(row=0, column=4, padx=(4, 8))
        self.lbl_product_info = ttk.Label(frm_pub, text="商品信息: (请先查询)", foreground="#64748b", wraplength=800, justify="left")
        self.lbl_product_info.grid(row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))
        frm_pub.columnconfigure(1, weight=1)

        # 4. 日志区
        frm_log = ttk.LabelFrame(self.root, text=" 上件执行日志 ")
        frm_log.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(frm_log, height=15, wrap="word", state="disabled",
                                bg="#0f172a", fg="#e2e8f0", font=("Consolas", 9))
        scroll = ttk.Scrollbar(frm_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)

    # ────────────────── 远程数据源运行时注入 ──────────────────
    def _patch_db_accessor(self):
        """
        根据连接方式注入运行时：
        - 本地: server.database.DB_PATH → 所选文件, 图片按本地/共享路径解析
        - 远程: 将 server.database / product_service / task_service / auth_service
          中的 get_db_connection 替换为 HTTP 桥接适配器 (配合主机 db_agent.py);
          同时接管 FileService.resolve_image_path —— 本地找不到的图片自动从
          主库服务器下载到本地缓存后再上传店小秘
        同时覆盖 get_setting 实现图片存储目录重定向 (storage_path_win)。
        """
        import server.database as appdb
        from server.services import file_service as fs_module

        image_root = self.image_root_var.get().strip()
        orig_get_setting = appdb.get_setting

        def get_setting_with_override(key, default=None):
            if key == "storage_path_win" and image_root:
                return image_root
            return orig_get_setting(key, default)

        appdb.get_setting = get_setting_with_override

        # 首次打补丁前保存原始函数, 供本地/远程模式来回切换
        if not hasattr(appdb, "_orig_get_db_connection"):
            appdb._orig_get_db_connection = appdb.get_db_connection
        if not hasattr(fs_module.FileService, "_orig_resolve_image_path"):
            fs_module.FileService._orig_resolve_image_path = fs_module.FileService.resolve_image_path

        if self.conn_mode.get() == "remote":
            # 保险: 若此前未经过自动探测 (remote_scheme 为空), 此处补一次探测
            scheme = getattr(self, "remote_scheme", "")
            if not scheme:
                try:
                    _, scheme = RemoteSQLiteConnection.connect_with_autodetect(
                        self.host_var.get().strip(),
                        self.port_var.get().strip() or 8765,
                        self.token_var.get())
                    self.remote_scheme = scheme
                except Exception:
                    scheme = "http"
            remote_conn = RemoteSQLiteConnection(
                self.host_var.get().strip(),
                int(self.port_var.get().strip() or 8765),
                self.token_var.get(),
                scheme=scheme,
            )
            self._remote_conn = remote_conn
            appdb.DB_PATH = f"{remote_conn.base} (远程)"
            factory = lambda: remote_conn  # noqa: E731
            # 图片解析: 本地优先 → 远程下载缓存
            fs_module.FileService.resolve_image_path = staticmethod(self._make_remote_image_resolver())
        else:
            self._remote_conn = None
            appdb.DB_PATH = self.db_path_var.get().strip()
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
        生成远程模式的图片解析函数:
        1. 先尝试本地/共享路径解析 (原逻辑)
        2. 失败则从主库服务器 (/file 接口) 下载到本地缓存目录并返回缓存路径
        缓存目录: %TEMP%\\erp_remote_images, 以路径哈希避免同名冲突
        """
        import hashlib
        cache_dir = os.path.join(tempfile.gettempdir(), "erp_remote_images")
        os.makedirs(cache_dir, exist_ok=True)
        remote_conn = self._remote_conn

        def resolve_image_path(path: str) -> str:
            if not path or not isinstance(path, str) or not path.strip():
                return ""
            # 1) 本地/共享路径能解析就直接用
            from server.services import file_service as fs_module
            local = fs_module.FileService._orig_resolve_image_path(path)
            if local:
                return local
            # 2) 远程下载
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

    def _on_mode_change(self):
        remote = (self.conn_mode.get() == "remote")
        if remote:
            self.lbl_db_file.grid_remove()
            self.ent_db_path.grid_remove()
            self.btn_browse_db.grid_remove()
            self.frm_remote.grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=2)
        else:
            self.frm_remote.grid_remove()
            self.lbl_db_file.grid(row=1, column=0, padx=6, sticky="e")
            self.ent_db_path.grid(row=1, column=1, padx=4, sticky="we")
            self.btn_browse_db.grid(row=1, column=2, padx=2)

    # ────────────────── 数据库 ──────────────────
    def _browse_db(self):
        path = filedialog.askopenfilename(
            title="选择商品数据库 (本地或网络共享)",
            filetypes=[("SQLite 数据库", "*.db"), ("所有文件", "*.*")],
            initialdir=os.path.dirname(self.db_path_var.get()) or BASE_DIR
        )
        if path:
            self.db_path_var.set(path)
            self.apply_db_path()

    def _browse_image_root(self):
        path = filedialog.askdirectory(title="选择图片存储根目录 (本机映射的共享目录)")
        if path:
            self.image_root_var.set(path)
            self.apply_image_root()

    def apply_db_path(self, silent: bool = False):
        """应用数据库配置 (远程模式走 db_agent 隧道; 本地模式走文件路径) 并做连通性验证"""
        # 远程模式分发: 连接远程主库 (db_agent), 不做本地文件校验
        if self.conn_mode.get() == "remote":
            return self._apply_remote_db(silent=silent)

        db_path = self.db_path_var.get().strip()
        if not db_path:
            if not silent:
                messagebox.showwarning("提示", "请填写数据库路径！\n\n远程机器可填网络共享路径，例如：\n\\\\192.168.1.10\\share\\products.db")
            return

        if not os.path.exists(db_path):
            # 网络共享路径不存在时给出针对性提示
            if db_path.startswith("\\\\"):
                if not silent:
                    messagebox.showerror(
                        "无法访问网络共享",
                        f"共享路径不可访问:\n{db_path}\n\n请检查：\n"
                        "1. 主机是否在线、共享是否开放\n"
                        "2. 先在文件资源管理器中打开该路径验证权限\n"
                        "3. 或将共享映射为盘符 (如 Z:) 后填 Z:\\...\\products.db"
                    )
                return
            if not silent:
                if not messagebox.askyesno("数据库不存在", f"文件不存在:\n{db_path}\n\n是否新建空数据库？"):
                    return
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
            self._set_db_status(f"数据库: 连接失败 ❌ ({e})", "#dc2626")
            if not silent:
                messagebox.showerror("数据库错误", f"无法连接数据库:\n{e}")
            return

        try:
            self._patch_db_accessor()
            import server.database as appdb
            appdb.init_db()  # 幂等: 表不存在则创建/补齐
        except Exception as e:
            self._set_db_status(f"数据库: 初始化失败 ❌ ({e})", "#dc2626")
            if not silent:
                messagebox.showerror("数据库错误", f"初始化数据库失败:\n{e}")
            return

        self._set_db_status(
            f"数据库: 已连接 ✅ (本地文件, 父级商品 {parent_count} 个)  |  图片目录: "
            f"{self.image_root_var.get().strip() or '(用数据库内配置)'}", "#059669")
        self._save_current_config()
        self._log(f"📦 数据库已连接: {db_path} (父级商品 {parent_count} 个)")

    def _apply_remote_db(self, silent: bool):
        host = self.host_var.get().strip()
        port = (self.port_var.get().strip() or "8765")
        if not host:
            if not silent:
                messagebox.showwarning("提示", "请填写主库机器的 IP 或域名！\n\n并确保主机已运行: python db_agent.py")
            return

        # 自动探测协议 (http / https 内网穿透隧道)
        try:
            probe, detected_scheme = RemoteSQLiteConnection.connect_with_autodetect(
                host, port, self.token_var.get())
            self.remote_scheme = detected_scheme
            info = probe.ping()
        except Exception as e:
            _app_error_log("远程连接探测失败", e)
            self._set_db_status(f"远程数据库: 连接失败 ❌ ({host}:{port} 不可达)", "#dc2626")
            if not silent:
                messagebox.showerror(
                    "远程数据库连接失败",
                    f"无法连接 {host}:{port}\n{e}\n\n请检查：\n"
                    "1. 主机是否已运行 python db_agent.py\n"
                    "2. IP/端口是否正确, 防火墙/穿透隧道是否正常\n"
                    "3. 访问令牌是否与主机 --token 一致"
                )
            return

        try:
            self._patch_db_accessor()
            import server.database as appdb
            appdb.init_db()  # 经 HTTP 代理执行 (表已存在则无操作)
        except Exception as e:
            _app_error_log("远程初始化失败", e)
            self._set_db_status(f"远程数据库: 初始化失败 ❌ ({e})", "#dc2626")
            if not silent:
                messagebox.showerror("数据库错误", f"初始化远程数据库失败:\n{e}")
            return

        self._set_db_status(
            f"数据库: 已连接 ✅ (远程 {host}:{port}, 父级商品 {info.get('parent_count', '?')} 个)  |  图片目录: "
            f"{self.image_root_var.get().strip() or '(用数据库内配置)'}", "#059669")
        self._save_current_config()
        self._log(f"📦 远程数据库已连接: {host}:{port} (父级商品 {info.get('parent_count', '?')} 个)")

    def _save_current_config(self):
        try:
            save_app_config({
                "conn_mode": self.conn_mode.get(),
                "db_path": self.db_path_var.get().strip(),
                "host": self.host_var.get().strip(),
                "port": self.port_var.get().strip(),
                "token": self.token_var.get(),
                "scheme": getattr(self, "remote_scheme", ""),
                "image_root": self.image_root_var.get().strip(),
                "chrome_user_data_dir": self.chrome_dir_var.get().strip(),
            })
        except Exception as e:
            _app_error_log("配置保存失败", e)

    def apply_image_root(self):
        """应用图片存储目录覆盖并重新注入运行时配置"""
        image_root = self.image_root_var.get().strip()
        if image_root and not os.path.exists(image_root):
            messagebox.showwarning(
                "图片目录不可访问",
                f"目录在本机不存在:\n{image_root}\n\n上件时图片将无法上传！\n"
                "请确认已将主机的图片存储目录映射为本机可访问路径 (盘符或 UNC 共享)。"
            )
        if self.conn_mode.get() == "remote" or self.db_path_var.get().strip():
            self.apply_db_path(silent=True)
        else:
            self._save_current_config()
        self._log(f"🖼️ 图片存储目录: {image_root or '(用数据库内配置)'}")

    def _find_product_by_sku(self, parent_sku: str):
        """按 Parent SKU 查询父级商品 (取最新一条)"""
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

    # ────────────────── Chrome 9222 ──────────────────
    @staticmethod
    def _chrome_port_open() -> bool:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{CDP_PORT}/json/version")
            with urllib.request.urlopen(req, timeout=1.0):
                return True
        except Exception:
            return False

    @staticmethod
    def _detect_chrome_exe():
        for p in CHROME_CANDIDATES:
            if os.path.exists(p):
                return p
        return None

    def launch_chrome(self):
        self.btn_chrome.config(state="disabled")
        threading.Thread(target=self._launch_chrome_worker, daemon=True).start()

    def _launch_chrome_worker(self):
        chrome_dir = (self.chrome_dir_var.get().strip() or DEFAULT_CHROME_DIR)
        toolkit_config.USER_DATA_DIR = chrome_dir  # 上件管线同步使用该目录

        if self._chrome_port_open():
            self._ui(lambda: self.lbl_browser_status.config(text="● 运行中 (9222)", foreground="#059669"))
            self._log("🌐 Chrome 9222 已在运行，直接复用现有实例")
            self._open_dxm_tab_cdp()
            self._ui(lambda: self.btn_chrome.config(state="normal"))
            return

        exe = self._detect_chrome_exe()
        if not exe:
            self._log("❌ 未找到 Chrome，请确认已安装")
            self._ui(lambda: self.btn_chrome.config(state="normal"))
            return

        os.makedirs(chrome_dir, exist_ok=True)
        self._log(f"🌐 正在启动 Chrome 并打开店小秘 (数据目录: {chrome_dir})")
        try:
            subprocess.Popen(
                [exe, f"--remote-debugging-port={CDP_PORT}",
                 f"--user-data-dir={chrome_dir}",
                 DXM_URL, "--no-first-run", "--no-default-browser-check"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception as e:
            self._log(f"❌ Chrome 启动失败: {e}")
            self._ui(lambda: self.btn_chrome.config(state="normal"))
            return

        for _ in range(30):
            time.sleep(0.3)
            if self._chrome_port_open():
                break
        if self._chrome_port_open():
            self._log(f"✅ Chrome 9222 启动成功，已打开店小秘 ({DXM_URL})")
            self._log("💡 首次使用请在打开的页面中登录店小秘，登录一次后长期有效")
            self._ui(lambda: self.lbl_browser_status.config(text="● 运行中 (9222)", foreground="#059669"))
        else:
            self._log("❌ Chrome 启动超时，9222 端口未就绪")
            self._ui(lambda: self.lbl_browser_status.config(text="● 启动失败", foreground="#dc2626"))
        self._ui(lambda: self.btn_chrome.config(state="normal"))

    def _open_dxm_tab_cdp(self):
        """Chrome 已运行时, 通过 CDP 在现有实例中新开店小秘标签页"""
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{CDP_PORT}/json/new?{DXM_URL}", method="PUT")
            urllib.request.urlopen(req, timeout=3).read()
            self._log(f"🌐 已在现有 Chrome 中打开店小秘: {DXM_URL}")
        except Exception as e:
            self._log(f"⚠️ 自动打开店小秘页失败 ({e})，请手动在浏览器访问")

    # ────────────────── 商品查询与上件 ──────────────────
    def search_product(self):
        parent_sku = self.sku_var.get().strip()
        if not parent_sku:
            messagebox.showwarning("提示", "请输入 Parent SKU！")
            return
        try:
            product = self._find_product_by_sku(parent_sku)
        except Exception as e:
            messagebox.showerror("查询失败", f"数据库查询出错:\n{e}\n\n请检查数据库路径是否正确！")
            return

        if not product:
            self.current_product = None
            self.btn_publish.config(state="disabled")
            self.lbl_product_info.config(text=f"商品信息: 未找到 Parent SKU「{parent_sku}」", foreground="#dc2626")
            return

        self.current_product = product
        self.btn_publish.config(state="normal")
        info = (f"商品信息: #{product['id']}  [{product['parent_sku']}]  {product['title'] or '未命名'}  |  "
                f"店铺: {product['store_account'] or '-'}  |  变体: {product['variation_count']} 个  |  状态: {product['status']}")
        self.lbl_product_info.config(text=info, foreground="#0f172a")
        self._log(f"🔍 已找到商品: #{product['id']} [{product['parent_sku']}] {product['title'] or ''}")

    def start_publish(self):
        if self.publishing:
            messagebox.showinfo("提示", "当前已有上件任务在执行中，请稍候！")
            return
        if not self.current_product:
            messagebox.showwarning("提示", "请先查询商品！")
            return
        if not self._chrome_port_open():
            if messagebox.askyesno("Chrome 未启动", "Chrome 9222 尚未启动，是否现在启动？"):
                self.launch_chrome()
                messagebox.showinfo("提示", "Chrome 启动中，请等状态变为「运行中」后再点上件！")
            return

        product_id = self.current_product["id"]
        parent_sku = self.current_product["parent_sku"]
        self.publishing = True
        self._stop_requested = False
        self.btn_publish.config(state="disabled")
        self.btn_search.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._log(f"{'=' * 58}")
        self._log(f"🚀 开始上件: #{product_id} [{parent_sku}]  {datetime.now().strftime('%H:%M:%S')}")

        def on_log(line: str):
            self.log_queue.put(line)

        def worker():
            try:
                bridge = _get_bridge()  # 惰性导入 (playwright 导入耗时, 仅在上件时加载)
                chrome_dir = self.chrome_dir_var.get().strip() or None
                res = bridge.publish_product_to_erp(
                    product_id, log_callback=on_log, chrome_user_data_dir=chrome_dir)
                ok = res.get("success", False)
                if self._stop_requested:
                    self.log_queue.put("🛑 上件已被用户终止")
                    self.log_queue.put("__FAILED__")
                    return
                self.log_queue.put(("✅" if ok else "❌") + f" 上件结束: {res.get('msg', '')}")
                self.log_queue.put("__DONE__" if ok else "__FAILED__")
            except Exception as e:
                if self._stop_requested:
                    self.log_queue.put("🛑 上件已被用户终止")
                else:
                    self.log_queue.put(f"❌ 上件异常: {e}")
                self.log_queue.put("__FAILED__")

        threading.Thread(target=worker, daemon=True).start()

    def stop_publish(self):
        """终止当前上件任务: 无条件强杀 Playwright Node 驱动进程, 立即中断自动化流程"""
        if not self.publishing:
            return
        self._stop_requested = True
        self.btn_stop.config(state="disabled")
        self._log("🛑 用户点击终止，正在强制停止上件任务...")
        threading.Thread(target=self._stop_publish_worker, daemon=True).start()

    def _stop_publish_worker(self):
        """后台执行终止: 强杀本进程登记的 Playwright 驱动进程树;
        持续压制最多 60 秒 — 若上件尚未进入自动化阶段或管线重建驱动, 出现一个杀一个 (保证无条件终止)"""
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
                time.sleep(0.5)  # 防止管线刚重建驱动, 继续轮询压制
                continue
            time.sleep(0.5)
        if killed_total:
            self._log(f"🛑 上件任务已终止 (共停止 {killed_total} 个自动化驱动进程)")
        elif self.publishing:
            self._log("⚠️ 未检测到自动化驱动进程，终止结束 (任务可能已完成)")

    # ────────────────── 日志与线程通信 ──────────────────
    def _ui(self, fn):
        """线程安全地在主线程执行 UI 更新"""
        self.root.after(0, fn)

    def _log(self, line: str):
        self.log_queue.put(line)

    def _poll_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item == "__DONE__":
                    self._finish_publish(True)
                elif item == "__FAILED__":
                    self._finish_publish(False)
                else:
                    self.log_text.config(state="normal")
                    self.log_text.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {item}\n")
                    self.log_text.see("end")
                    self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log_queue)

    def _finish_publish(self, ok: bool):
        self.publishing = False
        self.btn_publish.config(state="normal")
        self.btn_search.config(state="normal")
        self.btn_stop.config(state="disabled")
        if self._stop_requested:
            self.lbl_product_info.config(text="上件结果: 🛑 已终止 (详见日志)", foreground="#d97706")
        elif ok:
            self.lbl_product_info.config(text="上件结果: ✅ 成功！", foreground="#059669")
        else:
            self.lbl_product_info.config(text="上件结果: ❌ 失败 (详见日志)", foreground="#dc2626")


# ──────────────────────────────────────────────────────────────
# 启动动画窗口 (双击 exe 后立即展示, 主窗口就绪后关闭)
# ──────────────────────────────────────────────────────────────
SPLASH_BG = "#0f172a"


def _show_splash(root: tk.Tk):
    """显示无边框启动动画窗口 (深色居中, 点点动画 + 不确定进度条)
    返回 (splash, set_status), set_status 用于后台线程更新提示文本"""
    splash = tk.Toplevel(root, bg=SPLASH_BG)
    splash.overrideredirect(True)
    splash.attributes("-topmost", True)
    w, h = 430, 180
    x = (splash.winfo_screenwidth() - w) // 2
    y = (splash.winfo_screenheight() - h) // 2
    splash.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(splash, text="ERP 桌面上件助手", bg=SPLASH_BG, fg="#e2e8f0",
             font=("Microsoft YaHei UI", 16, "bold")).pack(pady=(36, 2))
    tk.Label(splash, text="店小秘自动化上件工具", bg=SPLASH_BG, fg="#94a3b8",
             font=("Microsoft YaHei UI", 9)).pack()
    lbl_status = tk.Label(splash, text="正在启动", bg=SPLASH_BG, fg="#38bdf8",
                          font=("Microsoft YaHei UI", 10))
    lbl_status.pack(pady=(20, 4))
    bar = ttk.Progressbar(splash, mode="indeterminate", length=300)
    bar.pack(pady=(4, 20))
    bar.start(12)

    state = {"custom": None}

    def _animate(i=[0]):
        if not splash.winfo_exists():
            return
        text = state["custom"] or "正在启动"
        lbl_status.config(text=text + "." * (i[0] % 4))
        i[0] += 1
        splash.after(260, _animate)

    def set_status(text: str):
        state["custom"] = text
        try:
            if splash.winfo_exists():
                lbl_status.config(text=text)
        except Exception:
            pass

    _animate()
    return splash, set_status


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    root.withdraw()  # 主窗口就绪前先隐藏, 由启动动画接管

    # 打包模式下关闭 PyInstaller 原生解压画面, 交接到应用内动画
    try:
        import pyi_splash  # noqa: F401
        pyi_splash.close()
    except Exception:
        pass

    splash, set_status = _show_splash(root)
    ready = {"flag": False}

    def _on_ready():
        if ready["flag"]:
            return
        ready["flag"] = True

        def _show_main():
            try:
                splash.destroy()
            except Exception:
                pass
            root.deiconify()
            root.lift()
            root.focus_force()

        # 动画至少展示 0.8 秒, 避免一闪而过
        root.after(800, _show_main)

    def _on_status(text: str):
        # 后台线程调用, 需派发回主线程更新动画文本
        root.after(0, lambda: set_status(text))

    try:
        DesktopApp(root, on_ready=_on_ready, on_status=_on_status)
    except Exception as e:
        _app_error_log("程序初始化失败", e)
        try:
            splash.destroy()
        except Exception:
            pass
        messagebox.showerror("启动失败", f"程序初始化出错:\n{e}")
        root.destroy()
        return

    root.mainloop()


if __name__ == "__main__":
    main()
