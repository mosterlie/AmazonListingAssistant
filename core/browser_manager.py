"""
浏览器生命周期管理与 CDP 接管核心模块（多线程安全调度架构）
"""
import os
import sys
import time
import queue
import threading
import subprocess
import urllib.request
import json
from typing import List, Dict, Optional, Tuple, Any, Callable

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

try:
    from .. import config
    from .tab_matcher import TabInfo, TabMatcher
except (ImportError, ValueError):
    try:
        from browser_toolkit import config
        from browser_toolkit.core.tab_matcher import TabInfo, TabMatcher
    except (ImportError, ValueError):
        try:
            import config
            from core.tab_matcher import TabInfo, TabMatcher
        except (ImportError, ValueError):
            import config
            from tab_matcher import TabInfo, TabMatcher


# ---------------------------------------------------------------------------
# Playwright Node 驱动进程登记表: 记录本进程内所有已启动的 playwright 驱动 PID,
# 用于上件异常卡死后的僵尸进程清理 (Node.js JavaScript Runtime 残留问题)
# ---------------------------------------------------------------------------
_DRIVER_PIDS: set = set()
_DRIVER_LOCK = threading.Lock()


def _get_driver_pid(playwright) -> Optional[int]:
    """从 playwright 实例提取底层 Node 驱动进程 PID"""
    try:
        return playwright._connection._transport._proc.pid
    except Exception:
        return None


def _register_driver_pid(playwright):
    pid = _get_driver_pid(playwright)
    if pid:
        with _DRIVER_LOCK:
            _DRIVER_PIDS.add(pid)


def _unregister_driver_pid(playwright):
    pid = _get_driver_pid(playwright)
    if pid:
        with _DRIVER_LOCK:
            _DRIVER_PIDS.discard(pid)


def _kill_driver_proc(playwright):
    """强杀 playwright Node 驱动进程树 (解除工作线程卡死)"""
    pid = _get_driver_pid(playwright)
    _unregister_driver_pid(playwright)
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"],
                           capture_output=True, timeout=5)
        else:
            subprocess.run(["kill", "-9", str(pid)],
                           capture_output=True, timeout=5)
    except Exception:
        pass


def cleanup_stale_drivers():
    """清理本进程内所有遗留的 Playwright Node 驱动进程 (上次上件卡死残留)"""
    with _DRIVER_LOCK:
        pids = list(_DRIVER_PIDS)
        _DRIVER_PIDS.clear()
    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"],
                               capture_output=True, timeout=5)
            else:
                subprocess.run(["kill", "-9", str(pid)],
                               capture_output=True, timeout=5)
        except Exception:
            pass
    return len(pids)


class BrowserManager:
    """
    负责启动 Chrome/Edge 实例、探测 CDP 端口、管理 Playwright 连接与标签页识别。
    内部维护常驻工作线程，确保所有 Playwright 调用都在同一原生线程中执行，彻底杜绝跨线程异常。
    """

    def __init__(self, port: int = config.DEFAULT_CDP_PORT, user_data_dir: str = config.USER_DATA_DIR):
        self.port = port
        self.cdp_url = f"http://127.0.0.1:{self.port}"
        self.user_data_dir = user_data_dir
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

        self._task_queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="BrowserWorkerThread")
        self._thread.start()

    def _worker_loop(self):
        """Playwright 专属常驻工作线程循环"""
        try:
            self.playwright = sync_playwright().start()
            _register_driver_pid(self.playwright)
        except Exception as e:
            print(f"[BrowserManager] Playwright init failed: {e}", file=sys.stderr)

        while True:
            item = self._task_queue.get()
            if item is None:
                break
            func, args, kwargs, fut = item
            try:
                result = func(*args, **kwargs)
                fut["result"] = result
                fut["success"] = True
            except Exception as e:
                fut["error"] = e
                fut["success"] = False
            finally:
                fut["event"].set()
                self._task_queue.task_done()

    def run_on_browser_thread(self, func: Callable, *args, timeout: Optional[float] = None, **kwargs) -> Any:
        """安全派发函数到 Playwright 专属常驻线程中同步执行"""
        fut = {"result": None, "error": None, "success": False, "event": threading.Event()}
        self._task_queue.put((func, args, kwargs, fut))
        if timeout:
            if not fut["event"].wait(timeout=timeout):
                raise TimeoutError("Playwright thread execution timeout")
        else:
            fut["event"].wait()

        if not fut["success"]:
            raise fut["error"]
        return fut["result"]

    @staticmethod
    def detect_browser_executable() -> Optional[str]:
        """跨平台自动探测系统中已安装的 Chrome 或 Edge 浏览器绝对路径"""
        if sys.platform == "darwin":
            for p in config.CHROME_PATHS_MACOS:
                if os.path.exists(p):
                    return p
        elif sys.platform == "win32":
            for p in config.CHROME_PATHS_WINDOWS:
                if os.path.exists(p):
                    return p
            try:
                import winreg
                keys = [
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
                    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
                ]
                for root_k, sub_k in keys:
                    try:
                        with winreg.OpenKey(root_k, sub_k) as k:
                            val, _ = winreg.QueryValueEx(k, "")
                            if val and os.path.exists(val):
                                return val
                    except Exception:
                        continue
            except Exception:
                pass
        return None

    def is_port_open(self) -> bool:
        """检测 CDP 远程调试端口是否可访问"""
        try:
            req = urllib.request.Request(f"{self.cdp_url}/json/version", headers={"User-Agent": "BrowserToolkit"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def launch_browser(self, target_url: str = "about:blank") -> Tuple[bool, str]:
        """以 CDP 调试模式启动独立 Chrome 浏览器"""
        if self.is_port_open():
            ok, msg = self.connect()
            if ok:
                return True, "已连接至正在运行的浏览器实例！"

        browser_exe = self.detect_browser_executable()
        if not browser_exe:
            return False, "未能在系统中找到 Google Chrome 或 Edge 浏览器，请确认已安装！"

        os.makedirs(self.user_data_dir, exist_ok=True)

        args = [
            browser_exe,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-features=Translate,OptimizationHints",
            "--disable-popup-blocking",
        ]

        if target_url and target_url != "about:blank":
            args.append(target_url)

        try:
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception as e:
            return False, f"启动浏览器进程失败: {e}"

        # 等待端口就绪
        for _ in range(30):
            time.sleep(0.3)
            if self.is_port_open():
                break
        else:
            return False, f"浏览器启动超时，无法在 {self.port} 端口建立 CDP 连接！"

        time.sleep(0.5)
        ok, msg = self.connect()
        if ok:
            return True, "浏览器已成功启动并完成 CDP 接管！"
        return False, msg

    def connect(self, activate: bool = True) -> Tuple[bool, str]:
        """连接并接管已开启 CDP 调试端口的 Chrome 浏览器"""
        return self.run_on_browser_thread(self._connect_impl, activate)

    def _connect_impl(self, activate: bool = True) -> Tuple[bool, str]:
        if not self.is_port_open():
            return False, f"端口 {self.port} 未开启 CDP 调试模式，请先启动浏览器！"

        try:
            if not self.playwright:
                self.playwright = sync_playwright().start()
                _register_driver_pid(self.playwright)

            if self.browser and self.browser.is_connected():
                if activate:
                    self.bring_browser_to_front()
                return True, "已连接至 Chrome 浏览器"

            self.browser = self.playwright.chromium.connect_over_cdp(
                endpoint_url=self.cdp_url,
                timeout=config.DEFAULT_TIMEOUT_MS
            )

            if not self.browser.contexts:
                return False, "浏览器未初始化完成任何上下文"

            self.context = self.browser.contexts[0]
            self.context.on("page", lambda p: self._bind_dialog_handler(p))
            for p in self.context.pages:
                self._bind_dialog_handler(p)

            if activate:
                self.bring_browser_to_front()
            return True, "成功接管 Chrome 浏览器！"
        except Exception as e:
            return False, f"连接 Chrome 失败: {str(e)}"

    def _bind_dialog_handler(self, page: Page):
        """自动绑定弹窗处理器，避免重复绑定与未捕获协议异常"""
        try:
            if getattr(page, "_has_dialog_bound", False):
                return
            page._has_dialog_bound = True
            page.on("dialog", lambda dialog: self._safe_handle_dialog(dialog))
        except Exception:
            pass

    @staticmethod
    def _safe_handle_dialog(dialog):
        """安全处理网页原生弹窗 (alert/confirm/prompt)"""
        try:
            dialog.accept()
        except Exception:
            try:
                dialog.dismiss()
            except Exception:
                pass

    def get_tabs(self) -> List[TabInfo]:
        """获取当前浏览器中打开的所有标签页列表"""
        return self.run_on_browser_thread(self._get_tabs_impl)

    def _get_tabs_impl(self) -> List[TabInfo]:
        if not self.context:
            ok, _ = self._connect_impl(activate=False)
            if not ok or not self.context:
                return []

        active_page = self._probe_front_active_page_impl()
        tabs: List[TabInfo] = []

        for idx, page in enumerate(self.context.pages):
            try:
                url = page.url
                try:
                    title = page.title()
                except Exception:
                    title = "加载中..."

                is_active = (active_page is not None and page == active_page)
                tabs.append(TabInfo(
                    index=idx,
                    title=title,
                    url=url,
                    page=page,
                    is_active=is_active
                ))
            except Exception:
                continue

        return tabs

    def get_active_page(self) -> Optional[Page]:
        """获取当前正在前台显示的活动标签页"""
        return self.run_on_browser_thread(self._get_active_page_impl)

    def _get_active_page_impl(self) -> Optional[Page]:
        if not self.context:
            ok, _ = self._connect_impl(activate=False)
            if not ok or not self.context:
                return None

        # 优先使用 macOS AppleScript + Hash 探针
        active_p = self._probe_front_active_page_impl()
        if active_p:
            return active_p

        # 兜底探测：页面 visibilityState
        for p in reversed(self.context.pages):
            try:
                state = p.evaluate("() => document.visibilityState")
                if state == "visible":
                    return p
            except Exception:
                continue

        # 再次兜底：返回最新打开的标签页
        if self.context.pages:
            return self.context.pages[-1]
        return None

    def _probe_front_active_page_impl(self) -> Optional[Page]:
        """macOS 高精度探针：通过 AppleScript 标记当前 Chrome 前台活动页签"""
        if sys.platform != "darwin":
            return None

        script = '''
        tell application "Google Chrome"
            if not (exists front window) then return ""
            set activeTab to active tab of front window
            set currentUrl to URL of activeTab
            if currentUrl starts with "chrome://" or currentUrl starts with "chrome-extension://" then return ""
            set probeToken to "agyp_" & (do shell script "date +%s%N")
            execute activeTab javascript "(() => { try { location.hash = '" & probeToken & "'; } catch(e){} })();"
            return probeToken
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=1.5)
            token = res.stdout.strip()
            if not token or not token.startswith("agyp_"):
                return None

            for p in self.context.pages:
                try:
                    if f"#{token}" in p.url:
                        # 恢复 hash
                        p.evaluate("() => { history.replaceState(null, null, ' '); }")
                        return p
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def open_or_focus_url(self, target_url: str) -> Optional[Page]:
        """在 Chrome 中打开目标网址或激活已有相同域名的标签页"""
        return self.run_on_browser_thread(self._open_or_focus_url_impl, target_url)

    def _open_or_focus_url_impl(self, target_url: str) -> Optional[Page]:
        if not self.context:
            ok, _ = self._connect_impl()
            if not ok or not self.context:
                return None

        norm_target = TabMatcher.normalize_url(target_url)

        # 1. 检索已有相同 URL/域名的标签页直接激活
        for p in self.context.pages:
            try:
                if TabMatcher.normalize_url(p.url) == norm_target or (target_url != "about:blank" and target_url in p.url):
                    p.bring_to_front()
                    self.bring_browser_to_front()
                    return p
            except Exception:
                continue

        # 2. 复用空白页
        for p in self.context.pages:
            try:
                if p.url in ("about:blank", "") or "newtab" in p.url:
                    self._bind_dialog_handler(p)
                    p.goto(target_url, wait_until="commit", timeout=config.DEFAULT_TIMEOUT_MS)
                    p.bring_to_front()
                    self.bring_browser_to_front()
                    return p
            except Exception:
                continue

        # 3. 新建标签页直达
        try:
            new_p = self.context.new_page()
            self._bind_dialog_handler(new_p)
            new_p.goto(target_url, wait_until="commit", timeout=config.DEFAULT_TIMEOUT_MS)
            new_p.bring_to_front()
            self.bring_browser_to_front()
            return new_p
        except Exception:
            return None

    def bring_browser_to_front(self):
        """将 Chrome 浏览器窗口唤起并置顶到操作系统前台"""
        try:
            if sys.platform == "darwin":
                subprocess.run(
                    ["osascript", "-e", 'tell application "Google Chrome" to activate'],
                    capture_output=True, timeout=2.0
                )
            elif sys.platform == "win32":
                pass
        except Exception:
            pass

    def close(self):
        """关闭 Playwright 连接与后台调度线程"""
        try:
            self._task_queue.put(None)
            if self.browser:
                self.browser.close()
            if self.playwright:
                _unregister_driver_pid(self.playwright)
                self.playwright.stop()
        except Exception:
            pass

    def hard_reset(self):
        """工作线程卡死时的暴力恢复: 杀掉 Playwright Node 驱动进程并重建调度线程"""
        old_pw = self.playwright
        old_queue = self._task_queue
        self.playwright = None
        self.browser = None
        self.context = None
        if old_pw is not None:
            _kill_driver_proc(old_pw)
        try:
            old_queue.put(None)  # 老线程执行完卡死任务(抛错)后自行退出
        except Exception:
            pass
        self._task_queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="BrowserWorkerThread-reset"
        )
        self._thread.start()

    def is_healthy(self, timeout: float = 5.0) -> bool:
        """探测调度线程是否还能响应任务 (卡死返回 False)"""
        try:
            self.run_on_browser_thread(lambda: True, timeout=timeout)
            return True
        except Exception:
            return False
