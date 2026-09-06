#!/usr/bin/env python3
"""
赛狐广告批量投放助手 (mac 独立版)

功能:
  1. 一键调起 Chrome 调试实例 (9222 端口, 默认用户数据目录 ~/ChromeDebugUser)
  2. 表单输入投放参数 (店铺手动输入, 全程数据不落库)
  3. 开始投放 → 驱动赛狐批量创建广告向导 (逻辑与中台广告管理一致)
     - 「添加」与「添加变体」同时出现时优先「添加变体」
     - 「已添加 N 个产品」计数增长校验 → 超5变体裁剪 → 弹窗确定
     - 不提交: 每批停在提交前, 多批各占一个新标签页, 最后统一清除空活动
  4. 实时日志 + 随时终止 (当前 ASIN 录入环节结束后停止)

运行:
    python3 sellfox_ad_gui.py
"""
import os
import sys
import json
import queue
import threading
import asyncio
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime

# PyInstaller 打包后支持 core 包导入
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 重模块 (playwright/node driver) 惰性导入: 加快窗口显示速度

CREATE_MODES = ["所有产品合并创建广告", "每个产品单独创建广告"]
BID_STRATEGIES = ["动态竞价-只降低", "动态竞价-提高和降低", "固定竞价"]
# 与 core/sellfox_ad_operator.py 的 PAGE_URL 保持一致
SELLFOX_URL = ("https://www.sellfox.com/amzup-web-main/amzup-web-cpc/index.html"
               "#/spBatchCreate?source=leftMenu_cpc_advertisement")
DEFAULT_USER_DATA_DIR = os.path.expanduser("~/ChromeDebugUser")
CDP_PORT = 9222
ASIN_HINT_TEXT = "输入格式：逗号/空格/换行分隔，如 B0HHRWYPTD,B0HHWJB3X9,B0HHWM14MF"


class RadioRow(ttk.Frame):
    """横向单选组"""

    def __init__(self, parent, options, default, **kw):
        super().__init__(parent, **kw)
        self.var = tk.StringVar(value=default)
        for opt in options:
            ttk.Radiobutton(self, text=opt, value=opt, variable=self.var).pack(
                side="left", padx=(0, 12))


class AdGuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("赛狐广告批量投放助手")
        self.root.geometry("920x740")
        self.root.minsize(760, 680)

        self.log_q: "queue.Queue[str]" = queue.Queue()
        self.op = None
        self.worker: threading.Thread = None
        self.bm = None          # 惰性: 首次点浏览器按钮时才拉起 playwright
        self._bm_dir = None

        self._build_ui()
        self.root.after(150, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.log("提示: 先点「① 启动调试浏览器」, 在打开的 Chrome 里登录赛狐后回到本窗口投放。")
        # 打包后的 windowed 应用在 mac 上可能不接收键盘事件: 抢焦点并短暂置顶
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))

    # ────────────────── UI ──────────────────

    def _build_ui(self):
        pad = {"padx": 8, "pady": 2}
        top = ttk.Frame(self.root)
        # fill="both" + expand=True: 让日志区吃掉窗口全部剩余高度, 否则底部留大片空白
        top.pack(fill="both", expand=True, **pad)

        # 浏览器控制行
        row0 = ttk.Frame(top)
        row0.pack(fill="x", pady=(0, 3))
        ttk.Button(row0, text="① 启动调试浏览器 (9222)",
                   command=self.on_launch_browser).pack(side="left")
        ttk.Button(row0, text="② 打开赛狐批量创建页",
                   command=self.on_open_sellfox).pack(side="left", padx=8)
        self.chrome_lbl = ttk.Label(row0, text="Chrome: 未检测", foreground="#888")
        self.chrome_lbl.pack(side="right")

        row_dir = ttk.Frame(top)
        row_dir.pack(fill="x", pady=(0, 3))
        ttk.Label(row_dir, text="用户数据目录:").pack(side="left")
        self.dir_var = tk.StringVar(value=DEFAULT_USER_DATA_DIR)
        tk.Entry(row_dir, textvariable=self.dir_var, relief="solid", bg="white").pack(
            side="left", fill="x", expand=True, padx=8)

        # 表单区
        box = ttk.LabelFrame(top, text="投放参数")
        box.pack(fill="x", pady=(0, 3))
        frm = ttk.Frame(box)
        frm.pack(fill="x", padx=8, pady=4)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="店铺名称 *:").grid(row=0, column=0, sticky="e", pady=1)
        self.shop_var = tk.StringVar()
        tk.Entry(frm, textvariable=self.shop_var, width=26, relief="solid",
                 bg="white", font=("PingFang SC", 13)).grid(
            row=0, column=1, sticky="w", pady=1)

        ttk.Label(frm, text="ASIN 列表 *:").grid(
            row=1, column=0, sticky="w", pady=(1, 0))
        asin_col = ttk.Frame(frm)
        asin_col.grid(row=2, column=0, columnspan=4, sticky="we", pady=1)
        self.asins_text = tk.Text(asin_col, height=8, wrap="char", font=("Menlo", 12),
                                  fg="#999")
        self.asins_text.pack(fill="x")
        self.asins_text.insert("1.0", ASIN_HINT_TEXT)   # 默认格式提醒 (占位符)
        self._asin_hint_on = True
        self.asins_text.bind("<FocusIn>", self._asin_hint_clear)
        self.asins_text.bind("<FocusOut>", self._asin_hint_restore)
        self.asins_text.bind("<KeyRelease>", lambda e: self._count_asins())
        cnt_row = ttk.Frame(asin_col)
        cnt_row.pack(fill="x", pady=(2, 0))
        self.asin_cnt_lbl = ttk.Label(cnt_row, text="已识别 0 个 ASIN", foreground="#555")
        self.asin_cnt_lbl.pack(side="left")
        self.dedup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cnt_row, text="自动去重",
                        variable=self.dedup_var,
                        command=self._count_asins).pack(side="left", padx=10)
        self.trim_var = tk.BooleanVar(value=True)          # 裁剪变体(默认开)
        ttk.Checkbutton(cnt_row, text="裁剪变体",
                        variable=self.trim_var,
                        command=self._sync_trim).pack(side="left", padx=10)
        ttk.Label(cnt_row, text="保留").pack(side="left")
        self.trim_keep_var = tk.StringVar(value="5")
        self.trim_keep_spin = tk.Spinbox(cnt_row, from_=1, to=50, width=4,
                                         textvariable=self.trim_keep_var,
                                         justify="center")
        self.trim_keep_spin.pack(side="left", padx=3)
        ttk.Label(cnt_row, text="个(超出按顺序保留前N, 其余裁掉)").pack(side="left")

        ttk.Label(frm, text="批次数量:").grid(row=3, column=0, sticky="e", pady=1)
        batch_cell = ttk.Frame(frm)
        batch_cell.grid(row=3, column=1, sticky="w", pady=1)
        self.batch_var = tk.StringVar(value="20")
        tk.Entry(batch_cell, textvariable=self.batch_var, width=6, relief="solid",
                 bg="white").pack(side="left")
        ttk.Label(batch_cell, text="每批最多录入的 ASIN 数", foreground="#888").pack(
            side="left", padx=(6, 0))

        ttk.Label(frm, text="创建方式:").grid(row=3, column=2, sticky="e", padx=(14, 2), pady=1)
        self.create_mode_row = RadioRow(frm, CREATE_MODES, CREATE_MODES[0])
        self.create_mode_row.grid(row=3, column=3, sticky="w", pady=1)

        ttk.Label(frm, text="开始时间 *:").grid(row=4, column=0, sticky="e", pady=1)
        self.start_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.start_cb = ttk.Combobox(frm, textvariable=self.start_var, width=12,
                                     state="readonly",
                                     values=self._date_options(60))
        self.start_cb.grid(row=4, column=1, sticky="w", pady=1)
        ttk.Label(frm, text="结束时间:").grid(row=4, column=2, sticky="e", padx=(14, 2), pady=1)
        self.end_var = tk.StringVar()
        self.end_cb = ttk.Combobox(frm, textvariable=self.end_var, width=12,
                                   state="readonly",
                                   values=["不填"] + self._date_options(120))
        self.end_cb.grid(row=4, column=3, sticky="w")

        ttk.Label(frm, text="每日预算 *:").grid(row=5, column=0, sticky="e", pady=1)
        budget_cell = ttk.Frame(frm)
        budget_cell.grid(row=5, column=1, sticky="w", pady=1)
        self.budget_var = tk.StringVar(value="300")
        tk.Entry(budget_cell, textvariable=self.budget_var, width=6, relief="solid",
                 bg="white").pack(side="left")

        ttk.Label(frm, text="默认竞价 *:").grid(row=5, column=2, sticky="e", padx=(14, 2), pady=1)
        bid_cell = ttk.Frame(frm)
        bid_cell.grid(row=5, column=3, sticky="w", pady=1)
        self.bid_var = tk.StringVar(value="15")
        tk.Entry(bid_cell, textvariable=self.bid_var, width=6, relief="solid",
                 bg="white").pack(side="left")

        ttk.Label(frm, text="竞价策略:").grid(row=6, column=0, sticky="e", pady=1)
        self.bid_strategy_row = RadioRow(frm, BID_STRATEGIES, BID_STRATEGIES[0])
        self.bid_strategy_row.grid(row=6, column=1, columnspan=3, sticky="w", pady=1)

        # 操作行
        row_act = ttk.Frame(top)
        row_act.pack(fill="x", pady=(0, 3))
        self.run_btn = ttk.Button(row_act, text="▶ 开始投放", command=self.on_run)
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(row_act, text="⏹ 终止", command=self.on_stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        ttk.Label(row_act, text="全程数据不落库; 不提交, 跑完停在提交前待人工确认",
                  foreground="#b45309").pack(side="right")

        # 日志区
        log_box = ttk.LabelFrame(top, text="执行日志")
        log_box.pack(fill="both", expand=True)
        self.log_box = scrolledtext.ScrolledText(log_box, height=9, font=("Menlo", 11),
                                                 state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=4, pady=3)

    # ────────────────── 工具 ──────────────────

    def log(self, line):
        self.log_q.put(str(line))

    def _drain_log_queue(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", line + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(150, self._drain_log_queue)

    def _asin_hint_clear(self, *_):
        """获得焦点时清掉占位提醒"""
        if self._asin_hint_on:
            self.asins_text.delete("1.0", "end")
            self.asins_text.configure(fg="#111")
            self._asin_hint_on = False

    def _asin_hint_restore(self, *_):
        """失焦且为空时恢复占位提醒"""
        if not self.asins_text.get("1.0", "end").strip():
            self.asins_text.insert("1.0", ASIN_HINT_TEXT)
            self.asins_text.configure(fg="#999")
            self._asin_hint_on = True

    @staticmethod
    def _date_options(days):
        """生成最近 days 天 ~ 今天 的日期下拉选项 (倒序)"""
        from datetime import timedelta
        today = datetime.now()
        return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    def _parse_asins(self):
        raw = self.asins_text.get("1.0", "end")
        if self._asin_hint_on:   # 占位提醒不算输入
            raw = ""
        parts = [p.strip().upper() for p in
                 __import__("re").split(r"[,，;；\s\r\n\t]+", raw.strip()) if p.strip()]
        if self.dedup_var.get():
            out, seen = [], set()
            for a in parts:
                if a not in seen:
                    seen.add(a)
                    out.append(a)
            return out
        return parts

    def _sync_trim(self):
        """裁剪开关联动: 不裁剪时禁用数量"""
        self.trim_keep_spin.configure(state=("disabled" if not self.trim_var.get() else "normal"))

    def _count_asins(self):
        lst = self._parse_asins()
        seen, dup = set(), 0
        for a in lst:
            if a in seen:
                dup += 1
            seen.add(a)
        bad = [a for a in seen if len(a) != 10 or not a.isalnum()]
        msg = f"已识别 {len(lst)} 个 ASIN"
        if dup:
            msg += f" · 重复 {dup} 个"
        if bad:
            msg += f" · ⚠ {len(bad)} 个格式异常: {', '.join(list(bad)[:3])}"
        self.asin_cnt_lbl.configure(text=msg)

    def _collect_fields(self):
        """收集并校验表单, 返回 (params, error)"""
        shop = self.shop_var.get().strip()
        if not shop:
            return None, "店铺名称不能为空"
        asins = self._parse_asins()
        if not asins:
            return None, "ASIN 列表不能为空"
        bad = [a for a in asins if len(a) != 10 or not a.isalnum()]
        if bad:
            return None, f"存在非法 ASIN (需10位字母数字): {', '.join(bad[:3])}..."
        try:
            batch = int(self.batch_var.get() or "0")
            if batch < 0:
                raise ValueError
        except ValueError:
            return None, "批次数量必须为非负整数"
        try:
            budget = float(self.budget_var.get())
            if budget <= 0:
                raise ValueError
        except ValueError:
            return None, "每日预算必须大于 0"
        try:
            bid = float(self.bid_var.get())
            if bid <= 0:
                raise ValueError
        except ValueError:
            return None, "默认竞价必须大于 0"
        try:
            trim_keep = int(self.trim_keep_var.get() or "5")
            if not (1 <= trim_keep <= 50):
                raise ValueError
        except ValueError:
            return None, "裁剪保留数量需为 1~50 的整数"
        start = self.start_var.get().strip()
        if not start:
            return None, "开始时间不能为空"
        try:
            datetime.strptime(start, "%Y-%m-%d")
        except ValueError:
            return None, "开始时间格式需为 YYYY-MM-DD"
        end = self.end_var.get().strip()
        if end == "不填":
            end = ""
        if end:
            try:
                datetime.strptime(end, "%Y-%m-%d")
            except ValueError:
                return None, "结束时间格式需为 YYYY-MM-DD"
        return {
            "shop": shop,
            "asins": asins,
            "batch_size": batch or None,
            "create_mode": self.create_mode_row.var.get(),
            "bid_strategy": self.bid_strategy_row.var.get(),
            "budget": ("%d" % int(budget)) if budget == int(budget) else ("%g" % budget),
            "bid": ("%d" % int(bid)) if bid == int(bid) else ("%g" % bid),
            "start_date": start,
            "end_date": end or None,
            "trim_variants": self.trim_var.get(),
            "trim_keep": trim_keep,
        }, None

    # ────────────────── 动作 ──────────────────

    def _ensure_browser_manager(self):
        """按输入框的用户数据目录重建 BrowserManager (首次调用/目录变更时)"""
        d = os.path.expanduser(self.dir_var.get().strip() or DEFAULT_USER_DATA_DIR)
        if self.bm is None or d != self._bm_dir:
            from core.browser_manager import BrowserManager   # 惰性导入
            self.bm = BrowserManager(port=CDP_PORT, user_data_dir=d)
            self._bm_dir = d
        return self.bm

    def on_launch_browser(self):
        def work():
            bm = self._ensure_browser_manager()
            self.log(f"正在启动调试浏览器 (用户数据目录: {self._bm_dir})...")
            try:
                ok, msg = bm.launch_browser("about:blank")
                if not ok:
                    self.log("❌ " + msg)
                    return
                self.log("✅ " + msg)
                # 与 ERP 中台同步: 启动后直接打开赛狐批量创建页 (已开则聚焦)
                try:
                    bm.open_or_focus_url(SELLFOX_URL)
                    self.log("✅ 已打开赛狐批量创建页 (首次需在该 Chrome 中登录赛狐)")
                except Exception as e:
                    self.log(f"⚠ 打开赛狐页失败: {str(e)[:80]} (可手动在 Chrome 里打开)")
            except Exception as e:
                self.log(f"❌ 启动浏览器失败: {e}")
        threading.Thread(target=work, daemon=True).start()

    def on_open_sellfox(self):
        def work():
            try:
                bm = self._ensure_browser_manager()
                ok, msg = bm.launch_browser("about:blank")
                if not ok:
                    self.log("❌ " + msg)
                    return
                # 浏览器已就绪: 在已有标签页间检索/复用/新开, 确保跳转到赛狐页
                bm.open_or_focus_url(SELLFOX_URL)
                self.log("✅ 已打开赛狐批量创建页 (若未自动跳转, 请在 Chrome 里手动打开)")
            except Exception as e:
                self.log(f"❌ 打开赛狐页面失败: {e}")
        threading.Thread(target=work, daemon=True).start()

    def on_run(self):
        params, err = self._collect_fields()
        if err:
            messagebox.showwarning("参数有误", err)
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("执行中", "投放任务正在执行中")
            return
        if not messagebox.askyesno(
                "确认投放",
                f"店铺: {params['shop']}\nASIN: {len(params['asins'])} 个"
                f" (批次上限 {params['batch_size'] or '不分批'})\n"
                f"预算 {params['budget']} / 竞价 {params['bid']}\n\n"
                "将驱动赛狐向导录入, 不提交, 停在提交前供人工检查。\n"
                "执行期间请勿操作该 Chrome 窗口。确认开始?"):
            return
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.worker = threading.Thread(target=self._run_worker, args=(params,), daemon=True)
        self.worker.start()

    def _run_worker(self, p):
        def on_log(line):
            self.log(line)

        async def job():
            from core.sellfox_ad_operator import SellfoxAdOperator   # 惰性导入
            op = SellfoxAdOperator(on_log=on_log)
            self.op = op
            try:
                # 连接调试浏览器并附加赛狐 iframe (等价 CLI 的 connect 步骤)
                # 浏览器未启动/未登录时在此给出可读日志而非裸异常
                try:
                    await op.connect(visit=True, login_timeout=90)
                except Exception as e:
                    msg = str(e)
                    on_log(f"❌ 连接浏览器失败: {msg[:160]}")
                    if "ERR_CONNECTION_REFUSED" in msg or "TimeoutError" in type(e).__name__:
                        on_log("   提示: 请先点「① 启动调试浏览器」并在打开的 Chrome 里登录赛狐。")
                    return
                result = await op.run_batch(
                    asins=p["asins"], batch_size=p["batch_size"], submit=False,
                    shop=p["shop"], budget=p["budget"], bid=p["bid"],
                    bid_strategy=p["bid_strategy"], create_mode=p["create_mode"],
                    start_date=p["start_date"], end_date=p["end_date"],
                    trim_variants=p["trim_variants"], trim_keep=p["trim_keep"])
                skipped = result.get("skipped_count", 0)
                audit = result.get("audit") or {}
                on_log("\n════════ 执行汇总 ════════")
                on_log(f"录入 {result.get('entered_count', 0)} 条 / "
                       f"跳过 {skipped} 条 / 批次 {result.get('batch_count', 0)} 个")
                on_log(f"终态对账: 已配置 {audit.get('configured')} / "
                       f"期望 {audit.get('expected')} "
                       f"{'✓ 一致' if audit.get('match') else '✗ 不一致'}")
                if result.get("aborted"):
                    on_log(f"⚠ {result.get('fail_stage')}")
                if skipped:
                    on_log("跳过明细:")
                    for s in result.get("skips", []):
                        on_log(f"  · {s['asin']} @ {s['campaign']}: {s['reason']} {s['detail']}")
                if not result.get("submitted"):
                    on_log("已全部停在提交前, 请在赛狐各标签页人工检查后手动提交。")
            except Exception as e:
                on_log(f"❌ 执行异常: {type(e).__name__}: {e}")
            finally:
                self.op = None
                self.root.after(0, lambda: (
                    self.run_btn.configure(state="normal"),
                    self.stop_btn.configure(state="disabled")))

        try:
            asyncio.run(job())
        except Exception as e:
            self.log(f"❌ 执行异常: {e}")

    def on_stop(self):
        if self.op:
            self.op.request_stop()
            self.log("⏹ 已发出终止请求, 当前 ASIN 录入环节结束后停止...")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("确认退出",
                                       "投放任务正在执行中, 退出将断开连接(已录入数据保留在页面上)。确定退出?"):
                return
            if self.op:
                self.op.request_stop()
        try:
            if self.bm:
                self.bm.close()
        except Exception:
            pass
        try:
            from core.browser_manager import cleanup_stale_drivers   # 清理本进程登记的驱动
            cleanup_stale_drivers()
        except Exception:
            pass
        self.root.destroy()
        os._exit(0)   # 确保全部子进程退出, 无终端/后台残留


def selftest():
    """打包产物自检: 验证 playwright 驱动/CDP 连接在 frozen 环境可用。
    结果写入 /tmp/sellfox_gui_selftest.txt (windowed 程序无 stdout)"""
    out = []

    async def _t():
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        try:
            try:
                b = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}", timeout=15000)
                out.append("direct connect OK")
            except Exception as e1:
                # 与算子 connect() 一致的代理降级 (Chrome 152 兼容)
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
    out.append("tkinter import OK")
    with open("/tmp/sellfox_gui_selftest.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    root = tk.Tk()
    try:
        from ctypes import cdll
        cdll.LoadLibrary("/System/Library/Frameworks/Quartz.framework/Quartz")
    except Exception:
        pass
    AdGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
