#!/usr/bin/env python3
"""
赛狐广告批量投放助手 (mac · pywebview 版)

- 浅色 Web 界面 (与 ERP 广告管理页同风格), pywebview 原生窗口 + 系统 WKWebView
- 一键调起 Chrome 调试实例 (9222, 用户数据目录 ~/ChromeDebugUser)
- 表单输入投放参数 (店铺手输, 全程数据不落库) → 驱动赛狐批量创建广告向导
- 实时日志 / 随时终止 (当前 ASIN 录入环节结束后停止)

运行:
    python3 sellfox_ad_gui.py          # 桌面窗口
    python3 sellfox_ad_gui.py --serve  # 浏览器模式 (http://127.0.0.1:8317)
    python3 sellfox_ad_gui.py --selftest
"""
import os
import sys
import json
import queue
import threading
import asyncio
from datetime import datetime, timedelta

# PyInstaller 打包后支持 core 包导入
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

CREATE_MODES = ["所有产品合并创建广告", "每个产品单独创建广告"]
BID_STRATEGIES = ["动态竞价-只降低", "动态竞价-提高和降低", "固定竞价"]
SELLFOX_URL = ("https://www.sellfox.com/amzup-web-main/amzup-web-cpc/index.html"
               "#/spBatchCreate?source=leftMenu_cpc_advertisement")
DEFAULT_USER_DATA_DIR = os.path.expanduser("~/ChromeDebugUser")
CDP_PORT = 9222
SERVE_PORT = 8317


def _gui_dir():
    """gui/index.html 多路径探测: onedir(BUNDLE 进 Resources) / onedir 平铺 / 源码"""
    cands = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(os.path.join(meipass, "gui"))
    cands.append(os.path.join(BASE_DIR, "..", "Resources", "gui"))   # .app BUNDLE
    cands.append(os.path.join(BASE_DIR, "gui"))
    for c in cands:
        if os.path.exists(os.path.join(c, "index.html")):
            return c
    return cands[-1]


GUI_DIR = _gui_dir()


class Bridge:
    """pywebview / 浏览器模式共用的 JS↔Python 桥接层 (复用 core 全部逻辑)"""

    def __init__(self):
        self.bm = None
        self._bm_dir = None
        self.op = None
        self.worker = None
        self.log_q: "queue.Queue" = queue.Queue()
        self._run_params = None

    # ── 供前端轮询的日志流 ──
    def poll_logs(self, seen=0):
        lines = []
        try:
            while True:
                lines.append(self.log_q.get_nowait())
        except queue.Empty:
            pass
        return {"seen": seen, "lines": lines}

    def clear_log(self):
        while True:
            try:
                self.log_q.get_nowait()
            except queue.Empty:
                break
        return "ok"

    def _log(self, line):
        self.log_q.put(str(line))

    # ── 表单元数据 ──
    def get_create_modes(self):
        return CREATE_MODES

    def get_bid_strategies(self):
        return BID_STRATEGIES

    def get_default(self, key):
        return {"cm": CREATE_MODES[0], "bs": BID_STRATEGIES[0]}.get(key, "")

    def get_options(self):
        return {
            "user_dir": DEFAULT_USER_DATA_DIR,
            "shop_names": [],
            "today": datetime.now().strftime("%Y-%m-%d"),
        }

    def trim_toggle(self, _disabled=None):
        return "ok"

    def shop_focus(self):
        return "ok"

    # ── 浏览器 ──
    def check_cdp(self):
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def _ensure_bm(self):
        from core.browser_manager import BrowserManager
        d = os.path.expanduser((self._get_dir() or DEFAULT_USER_DATA_DIR).strip())
        if self.bm is None or d != self._bm_dir:
            self.bm = BrowserManager(port=CDP_PORT, user_data_dir=d)
            self._bm_dir = d
        return self.bm

    def _get_dir(self):
        return getattr(self, "_dir_input", None) or DEFAULT_USER_DATA_DIR

    def set_user_dir(self, d):
        self._dir_input = d
        return "ok"

    def launch_browser(self):
        def work():
            try:
                bm = self._ensure_bm()
                self._log(f"正在启动调试浏览器 (用户数据目录: {self._bm_dir})...")
                ok, msg = bm.launch_browser("about:blank")
                if not ok:
                    self._log("❌ " + msg)
                    return
                self._log("✅ " + msg)
                try:
                    bm.open_or_focus_url(SELLFOX_URL)
                    self._log("✅ 已打开赛狐批量创建页 (首次需在该 Chrome 中登录赛狐)")
                except Exception as e:
                    self._log(f"⚠ 打开赛狐页失败: {str(e)[:80]}")
            except Exception as e:
                self._log(f"❌ 启动浏览器失败: {e}")
        threading.Thread(target=work, daemon=True).start()
        return "started"

    def open_sellfox(self):
        def work():
            try:
                bm = self._ensure_bm()
                ok, msg = bm.launch_browser("about:blank")
                if not ok:
                    self._log("❌ " + msg)
                    return
                bm.open_or_focus_url(SELLFOX_URL)
                self._log("✅ 已打开赛狐批量创建页")
            except Exception as e:
                self._log(f"❌ 打开赛狐页失败: {e}")
        threading.Thread(target=work, daemon=True).start()
        return "started"

    # ── 投放 ──
    def _validate(self, p):
        if not p.get("shop", "").strip():
            return "店铺名称不能为空"
        asins = p.get("asins") or []
        if not asins:
            return "ASIN 列表不能为空"
        bad = [a for a in asins if len(a) != 10 or not a.isalnum()]
        if bad:
            return f"存在非法 ASIN (需10位字母数字): {', '.join(bad[:3])}..."
        try:
            if int(p.get("batch", 0) or 0) < 0:
                raise ValueError
        except ValueError:
            return "批次数量必须为非负整数"
        for k, label in (("budget", "每日预算"), ("bid", "默认竞价")):
            try:
                if float(p.get(k)) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return f"{label}必须大于 0"
        try:
            datetime.strptime(p.get("start_date", ""), "%Y-%m-%d")
        except (TypeError, ValueError):
            return "开始时间格式需为 YYYY-MM-DD"
        end = (p.get("end_date") or "").strip()
        if end and end != "不填":
            try:
                datetime.strptime(end, "%Y-%m-%d")
            except ValueError:
                return "结束时间格式需为 YYYY-MM-DD"
        tk = p.get("trim_keep", 5)
        try:
            if not (1 <= int(tk) <= 50):
                raise ValueError
        except (TypeError, ValueError):
            return "裁剪保留数量需为 1~50 的整数"
        return None

    def confirm_run(self, p):
        err = self._validate(p)
        if err:
            return {"error": err}
        self._run_params = p
        return {"ok": True}

    def modal_ok(self):
        p = self._run_params
        self._run_params = None
        if not p:
            return "no-params"
        if self.worker and self.worker.is_alive():
            self._log("⚠ 投放任务正在执行中")
            return "running"
        self.worker = threading.Thread(target=self._run_worker, args=(p,), daemon=True)
        self.worker.start()
        return "started"

    @staticmethod
    def _num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        return str(int(f)) if f == int(f) else ("%g" % f)

    def _run_worker(self, p):
        asins = p["asins"]
        budget, bid = self._num(p["budget"]), self._num(p["bid"])
        batch = int(p.get("batch") or 0) or None
        end = (p.get("end_date") or "").strip()
        end = None if end in ("", "不填") else end
        trim_keep = int(p.get("trim_keep") or 5)

        def on_log(line):
            self._log(line)

        async def job():
            from core.sellfox_ad_operator import SellfoxAdOperator   # 惰性导入
            op = SellfoxAdOperator(on_log=on_log)
            self.op = op
            try:
                try:
                    await op.connect(visit=True, login_timeout=90)
                except Exception as e:
                    msg = str(e)
                    on_log(f"❌ 连接浏览器失败: {msg[:160]}")
                    if "ERR_CONNECTION_REFUSED" in msg or "TimeoutError" in type(e).__name__:
                        on_log("   提示: 请先「启动调试浏览器」并在打开的 Chrome 里登录赛狐。")
                    return
                on_log(f"▶ 开始投放: 店铺={p['shop']} / ASIN {len(asins)} 个 / "
                       f"裁剪={'开, 保留' + str(trim_keep) if p.get('trim_variants', True) else '关'}")
                result = await op.run_batch(
                    asins=asins, batch_size=batch, submit=False,
                    shop=p["shop"].strip(), budget=budget, bid=bid,
                    bid_strategy=p.get("bid_strategy") or BID_STRATEGIES[0],
                    create_mode=p.get("create_mode") or CREATE_MODES[0],
                    start_date=p["start_date"], end_date=end,
                    trim_variants=bool(p.get("trim_variants", True)),
                    trim_keep=trim_keep)
                audit = result.get("audit") or {}
                on_log("\n════════ 执行汇总 ════════")
                on_log(f"录入 {result.get('entered_count', 0)} 条 / "
                       f"跳过 {result.get('skipped_count', 0)} 条 / "
                       f"批次 {result.get('batch_count', 0)} 个")
                on_log(f"终态对账: 已配置 {audit.get('configured')} / 期望 {audit.get('expected')} "
                       f"{'✓ 一致' if audit.get('match') else '✗ 不一致'}")
                if result.get("aborted"):
                    on_log(f"⚠ {result.get('fail_stage')}")
                if result.get("skipped_count"):
                    on_log("跳过明细:")
                    for s_ in result.get("skips", []):
                        on_log(f"  · {s_['asin']} @ {s_['campaign']}: {s_['reason']} {s_['detail']}")
                on_log("已全部停在提交前, 请在赛狐各标签页人工检查后手动提交。")
            except Exception as e:
                on_log(f"❌ 执行异常: {type(e).__name__}: {e}")
            finally:
                self.op = None

        try:
            asyncio.run(job())
        except Exception as e:
            self._log(f"❌ 执行异常: {e}")

    def stop(self):
        if self.op:
            self.op.request_stop()
            self._log("⏹ 已发出终止请求, 当前 ASIN 录入环节结束后停止...")
            return "stopping"
        return "idle"

    def run_state(self):
        alive = bool(self.worker and self.worker.is_alive())
        return {"running": alive}


bridge = Bridge()


def _serve():
    """浏览器模式: 本地 HTTP 服务 gui/index.html + /api/* 桥接"""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
            if self.path in ("/", "/index.html"):
                with open(os.path.join(GUI_DIR, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html")
            if self.path.startswith("/api/poll"):
                import urllib.parse
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                seen = int(qs.get("seen", ["0"])[0])
                return self._send(200, bridge.poll_logs(seen))
            if self.path.startswith("/api/state"):
                return self._send(200, bridge.run_state())
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            action = self.path.rsplit("/", 1)[-1]
            fn = getattr(bridge, action, None)
            if not callable(fn):
                return self._send(404, {"error": "unknown action"})
            try:
                if action in ("confirm_run",):
                    res = fn(body)
                elif isinstance(body, dict) and body:
                    try:
                        res = fn(**body)
                    except TypeError:
                        res = fn(body if len(body) == 1 else body)
                else:
                    res = fn()
                return self._send(200, res if isinstance(res, dict) else {"result": res})
            except Exception as e:
                return self._send(200, {"error": f"{type(e).__name__}: {str(e)[:120]}"})

    srv = ThreadingHTTPServer(("127.0.0.1", SERVE_PORT), H)
    print(f"浏览器模式: http://127.0.0.1:{SERVE_PORT}")
    srv.serve_forever()


def selftest():
    """打包产物自检 (结果写文件, windowed 程序无 stdout)"""
    out = []

    async def _t():
        from playwright.async_api import async_playwright
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
        asyncio.run(_t())
    except Exception as e:
        out.append(f"asyncio FAIL: {e}")
    out.append(f"gui assets: {os.path.exists(os.path.join(GUI_DIR, 'index.html'))}")
    out.append("bridge: ok")
    with open("/tmp/sellfox_gui_selftest.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    if "--serve" in sys.argv:
        _serve()
        return

    import webview                      # 惰性: --selftest/--serve 不需要
    webview.create_window(
        "赛狐广告批量投放助手",
        os.path.join(GUI_DIR, "index.html"),
        js_api=bridge, width=960, height=900, min_size=(820, 780))
    webview.start()


if __name__ == "__main__":
    main()
