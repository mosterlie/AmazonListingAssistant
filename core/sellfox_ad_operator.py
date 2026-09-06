"""赛狐ERP SP批量创建广告 - 分批向导式自动化

录入规则:
  - 搜索轮询等待(loading→结果行/暂无数据), 禁止固定sleep读结果
  - 「添加」与「添加变体」同时出现时优先点「添加变体」; 点击后轮询按钮态翻转
    确认生效, 未生效自动补点(最多3次)
  - 点击后校验「已添加 N 个产品」计数区域严格增长, 未增长视为假添加并跳过
  - 单个ASIN连带产品超过 MAX_VARIANTS(5) 时, 右栏裁剪保留前5个(裁剪后复核计数)
  - 弹窗归属校验 + el-dialog 确定按钮真实鼠标点击, 完成后立即提交弹窗
  - 跳过的ASIN活动回池复用, 收尾统一清除未配置活动

流程 (每批 = 一次完整三步向导):
  Step0 访问页面(已登录) → Step1 基本信息(店铺/创建方式/预算/竞价/起止日期, 不加产品)
  → Step2 选广告结构模板 → 生成预览 → Step3 移除手动投放
  → 自动活动复制校齐到本批条数k → 逐ASIN经「设置广告产品」弹窗搜索录入
  → 清除未配置活动 → 终态对账 → 提交(--submit)

服务端调用:
  run_batch() 返回结构化结果 dict (成功/中断/录入数/跳过明细/终态对账/完整日志),
  供 server/services/ad_service.py 登记到 ad_task_runs 表。
  默认 submit=False: 每批执行到提交前停止; 多批时通过 open_new_page 逐批开
  新标签页执行, 上一批页面原样保留, 结束后由人工逐个标签页检查提交。
  注意: close() 只断开本地 Playwright 驱动, 不会关闭用户的 CDP 浏览器。

用法:
  python -m core.sellfox_ad_operator --asins B0xxx,B0yyy --batch-size 10 \
      --shop 金梧汇辰 --budget 300 --bid 15
  (不加 --submit 时跑完第一批停在提交前)
"""
import argparse
import asyncio
import sys
import time

from playwright.async_api import async_playwright

# 全选快捷键修饰键: macOS 为 Meta, Windows/Linux 为 Control
SELECT_ALL = "Meta" if sys.platform == "darwin" else "Control"

CDP_URL = "http://127.0.0.1:9222"
PAGE_URL = ("https://www.sellfox.com/amzup-web-main/amzup-web-cpc"
            "?amzup-web-cpc=%2Fcpc%2Fweb%2FcpcManage%2FspBatchCreate%2FspBatchCreatePage%2Findex.html")
PAGE_KEY = "spBatchCreate"
IFRAME_KEY = "spBatchCreatePage/index.html"
MAX_VARIANTS = 5  # 单个ASIN最多录入的产品数(含主ASIN)

# 可见的「设置广告产品」弹窗
DLG = """[...document.querySelectorAll('.el-dialog')].find(d => d.offsetParent!==null
    && (d.querySelector('.el-dialog__title')?.textContent||'').includes('设置广告产品')
    && d.getBoundingClientRect().width>0)"""

# 可见的「批量复制」弹窗 (文本含"将生成"或头部含"批量复制")
COPY_DLG = """[...document.querySelectorAll('.el-dialog')].find(d =>
    d.offsetParent!==null && ((d.textContent||'').includes('将生成')
        || (d.querySelector('.el-dialog__header')?.textContent||'').includes('批量复制')))"""

STEP1 = "基本信息填写"
STEP2 = "选择广告结构"
STEP3 = "预览并提交广告"

# ASIN 级失败原因: 活动本身仍是"未配置+可用"状态, 名额不烧毁, 由后续 ASIN 回补
ASIN_LEVEL_REASONS = {
    "not_found", "already_added", "invalid_button",
    "add_unconfirmed", "add_count_no_increase", "add_count_zero",
    "trim_failed",
}


class OperatorStopped(Exception):
    """用户请求终止任务 (由服务端 request_stop 触发)"""


class SkipRecord:
    """跳过/异常记录 (同步写入算子日志, 便于服务端登记执行结果)"""

    def __init__(self, sink=None):
        self.items = []
        self._sink = sink

    def _emit(self, line):
        print(line)
        if self._sink:
            try:
                self._sink(line)
            except Exception:
                pass

    def add(self, asin, campaign, reason, detail=""):
        self.items.append({"asin": asin, "campaign": campaign, "reason": reason, "detail": detail})
        self._emit(f"  [跳过] {asin} @ {campaign}: {reason} {detail}")

    def report(self):
        if not self.items:
            self._emit("跳过记录: 无")
            return
        self._emit(f"跳过记录 共{len(self.items)}条:")
        for it in self.items:
            self._emit(f"  - {it['asin']} @ {it['campaign']}: {it['reason']} {it['detail']}")


class SellfoxAdOperator:

    def __init__(self, cdp_url=CDP_URL, on_log=None):
        self.cdp_url = cdp_url
        self.pw = None
        self.browser = None
        self.page = None
        self.frame = None
        self.on_log = on_log
        self.log_lines = []
        self.stop_requested = False
        self.skips = SkipRecord(sink=self._record_log)
        self._t = time.monotonic()

    def request_stop(self):
        """请求终止 (线程安全: 仅置布尔标志, 由事件循环内各检查点消费)"""
        self.stop_requested = True

    def _check_stop(self):
        """终止检查点: 在长轮询循环与关键步骤间调用"""
        if self.stop_requested:
            raise OperatorStopped("用户请求终止任务")

    def _record_log(self, line):
        """日志落内存 (供服务端登记执行结果), 并透传给外部回调"""
        self.log_lines.append(str(line))
        if self.on_log:
            try:
                self.on_log(str(line))
            except Exception:
                pass

    def log(self, line):
        print(line)
        self._record_log(line)

    def lap(self, label):
        """阶段耗时打点"""
        now = time.monotonic()
        self.log(f"  [计时] {label}: {now - self._t:.1f}s")
        self._t = now

    # ================= 基础 =================

    async def connect(self, visit=True, login_timeout=120):
        self.pw = await async_playwright().start()
        try:
            self.browser = await self.pw.chromium.connect_over_cdp(self.cdp_url, timeout=20000)
        except Exception as e:
            es = str(e)
            # Chrome 152+ 移除了 browser-level Browser.setDownloadBehavior,
            # Playwright 握手必调该命令 → 走本地 CDP 代理吞掉该命令后重连
            if "setDownloadBehavior" in es or "context management" in es:
                from core.cdp_proxy import get_proxy
                self.log("⚠ 检测到 Chrome 与 Playwright 的 CDP 握手兼容问题, 切换代理模式重连...")
                proxy = get_proxy(self.cdp_url)
                self.browser = await self.pw.chromium.connect_over_cdp(
                    proxy.ws_endpoint, timeout=20000)
                self.log("✅ 代理模式握手成功")
            else:
                raise
        ctx = self.browser.contexts[0]
        self.page = next((pg for pg in ctx.pages if PAGE_KEY in pg.url), None)
        if self.page is None and visit:
            self.page = await ctx.new_page()
            await self.page.goto(PAGE_URL, wait_until="domcontentloaded")
        if self.page is None:
            raise RuntimeError("未找到赛狐广告页面, 且 visit=False")
        await self._wait_login(timeout=login_timeout)
        await self._attach_frame()

    async def _wait_login(self, timeout=120):
        """若跳到登录页, 等待人工登录"""
        for _ in range(int(timeout / 2)):
            self._check_stop()
            if PAGE_KEY in self.page.url:
                return True
            self.log(f"  等待登录中... 当前: {self.page.url[:80]}")
            await asyncio.sleep(2)
        raise RuntimeError("登录等待超时, 请先在浏览器中完成登录")

    async def _attach_frame(self):
        for _ in range(20):
            self.frame = next((f for f in self.page.frames
                               if IFRAME_KEY in f.url and f != self.page.main_frame), None)
            if self.frame:
                return
            await asyncio.sleep(0.5)
        raise RuntimeError("未找到 spBatchCreate iframe")

    async def reload_page(self):
        await self.page.goto(PAGE_URL, wait_until="domcontentloaded")
        # 轮询等 iframe 就绪, 替代固定 2s
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            self.frame = next((f for f in self.page.frames
                               if IFRAME_KEY in f.url and f != self.page.main_frame), None)
            if self.frame:
                return
            await asyncio.sleep(0.2)
        raise RuntimeError("刷新后未找到 spBatchCreate iframe")

    async def open_new_page(self, timeout=40):
        """在新标签页打开批量创建向导。

        不提交模式下批间切换使用本方法 (而非 reload_page): 刷新会丢弃当前页
        已录入但未提交的数据; 新开标签页则让上一批保留在原页面, 供人工检查提交。
        """
        ctx = self.browser.contexts[0]
        self.page = await ctx.new_page()
        await self.page.goto(PAGE_URL, wait_until="domcontentloaded")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.frame = next((f for f in self.page.frames
                               if IFRAME_KEY in f.url and f != self.page.main_frame), None)
            if self.frame:
                return
            await asyncio.sleep(0.2)
        raise RuntimeError("新页面未找到 spBatchCreate iframe")

    async def close(self):
        """仅断开本地 Playwright 驱动, 不关闭浏览器。

        注意: 通过 connect_over_cdp 连接的是用户真实在用的 Chrome,
        此处若调用 browser.close() 会直接杀掉整个浏览器进程(含用户其它标签页),
        因此只停止本地 driver。
        """
        try:
            if self.pw:
                await self.pw.stop()
        except Exception:
            pass
        self.pw = None
        self.browser = None
        self.page = None
        self.frame = None

    # ================= 通用工具 =================

    async def js(self, script, arg=None):
        return await self.frame.evaluate(script, arg) if arg is not None \
            else await self.frame.evaluate(script)

    async def click_at(self, pos):
        await self.page.mouse.click(pos['x'], pos['y'])

    async def current_step(self):
        """按页面特征元素判断当前步骤 (el-step 状态条是静态的, 不可信)"""
        return await self.js("""() => {
            if ([...document.querySelectorAll('.el-form-item')].some(i =>
                (i.querySelector('.el-form-item__label')?.textContent||'').trim()==='店铺'
                && i.offsetParent!==null)) return 'STEP1';
            if ([...document.querySelectorAll('div.item')].some(c =>
                c.offsetParent!==null && c.getBoundingClientRect().width>100)) return 'STEP2';
            if (document.querySelector('.vxe-body--row')
                || [...document.querySelectorAll('button')].some(b =>
                    (b.textContent||'').trim()==='提交' && b.getBoundingClientRect().width>0)) return 'STEP3';
            return 'UNKNOWN';
        }""")

    STEP_MAP = {STEP1: 'STEP1', STEP2: 'STEP2', STEP3: 'STEP3'}

    async def wait_step(self, step_title, timeout=20):
        want = self.STEP_MAP[step_title]
        for _ in range(int(timeout / 0.2)):
            self._check_stop()
            if await self.current_step() == want:
                await asyncio.sleep(0.15)
                return True
            await asyncio.sleep(0.2)
        return False

    # ================= Step1 =================

    async def step1_fill(self, shop="金梧汇辰", budget="300", bid="15",
                         bid_strategy="动态竞价-只降低",
                         create_mode="每个产品单独创建广告",
                         start_date=None, end_date=None):
        """Step1: 店铺 → 创建方式 → 预算 → 竞价策略 → 默认竞价 → [起止日期] → 下一步 (不加产品)"""
        if not await self.wait_step(STEP1):
            self.log("✗ 不在Step1")
            return False

        # 1. 店铺下拉: 点开后轮询下拉项出现, 选中后轮询input值变化
        pos = await self.js("""() => {
            const it = [...document.querySelectorAll('.el-form-item')].find(i =>
                (i.querySelector('.el-form-item__label')?.textContent||'').trim()==='店铺');
            const sel = it.querySelector('.el-select');
            const r = sel.getBoundingClientRect();
            return {x: r.x + r.width/2, y: r.y + r.height/2};
        }""")
        await self.click_at(pos)
        # 轮询下拉项出现
        for _ in range(20):
            ok = await self.js("""(shop) => [...document.querySelectorAll('.el-select-dropdown__item')]
                .some(o => o.getBoundingClientRect().width>0 && (o.textContent||'').includes(shop))""", shop)
            if ok:
                break
            await asyncio.sleep(0.2)
        ok = await self.js("""(shop) => {
            for (const d of document.querySelectorAll('.el-select-dropdown')) {
                for (const o of d.querySelectorAll('.el-select-dropdown__item')) {
                    if (o.getBoundingClientRect().width>0 && (o.textContent||'').includes(shop)) {
                        o.click();
                        return true;
                    }
                }
            }
            return false;
        }""", shop)
        if not ok:
            self.log(f"✗ 店铺选项未找到: {shop}")
            return False
        # 轮询 input 值变化
        shop_val = None
        for _ in range(20):
            shop_val = await self.js("""() => {
                const it = [...document.querySelectorAll('.el-form-item')].find(i =>
                    (i.querySelector('.el-form-item__label')?.textContent||'').trim()==='店铺');
                return it.querySelector('input')?.value;
            }""")
            if shop_val:
                break
            await asyncio.sleep(0.2)
        if not shop_val:
            self.log("✗ 店铺未选上")
            return False
        # 校验选中值确实是目标店铺 (仅判非空会放过残留的旧店铺值)
        if shop and shop not in shop_val:
            self.log(f"✗ 店铺选中值不符: 期望「{shop}」实际「{shop_val}」")
            return False
        self.log(f"  Step1 店铺: {shop_val} ✓")
        # 店铺切换会异步加载该店铺产品池(ASIN), 等加载完成再继续
        await self._wait_pool_loaded()

        # 2. 创建方式 radio
        if not await self._click_radio(create_mode):
            self.log(f"✗ 创建方式radio未找到: {create_mode}")
            return False

        # 3. 每日预算
        if not await self._fill_number_field("每日预算", budget):
            return False
        # 4. 竞价策略 radio
        if not await self._click_radio(bid_strategy):
            self.log(f"✗ 竞价策略radio未找到: {bid_strategy}")
            return False
        # 5. 默认竞价
        if not await self._fill_number_field("默认竞价", bid):
            return False

        # 6. 起止时间 (可选: 页面无对应表单项时跳过, 不阻断主流程)
        if start_date:
            await self._fill_date_field(["开始时间", "开始日期", "投放开始时间"], start_date)
        if end_date:
            await self._fill_date_field(["结束时间", "结束日期", "投放结束时间"], end_date)

        # 7. 下一步 → 轮询 Step2 特征出现
        await self._click_button("下一步", settle=0.2)
        self.log("  Step1 完成 → 下一步")
        return await self.wait_step(STEP2)

    async def _fill_date_field(self, labels, value, timeout=8):
        """填写日期控件 (el-date-picker)。

        - 页面无对应表单项 → 跳过并返回 None (不阻断, 各店铺页面字段可能不同)
        - 命中但回填值校验失败 → 返回 False (仅告警)
        """
        hit = False
        for label in labels:
            pos = await self.js("""(label) => {
                const it = [...document.querySelectorAll('.el-form-item')].find(i =>
                    i.offsetParent!==null
                    && (i.querySelector('.el-form-item__label')?.textContent||'').includes(label));
                if (!it) return null;
                const inp = it.querySelector('input');
                if (!inp) return null;
                it.scrollIntoView({block: 'center'});
                const r = inp.getBoundingClientRect();
                return {x: r.x + r.width/2, y: r.y + r.height/2};
            }""", label)
            if not pos:
                continue
            hit = True
            await asyncio.sleep(0.25)
            await self.click_at(pos)
            await asyncio.sleep(0.2)
            await self.page.keyboard.press(f"{SELECT_ALL}+A")
            await self.page.keyboard.press("Backspace")
            await self.page.keyboard.type(str(value), delay=40)
            await self.page.keyboard.press("Enter")
            v = None
            for _ in range(int(timeout / 0.2)):
                v = await self.js("""(label) => {
                    const it = [...document.querySelectorAll('.el-form-item')].find(i =>
                        i.offsetParent!==null
                        && (i.querySelector('.el-form-item__label')?.textContent||'').includes(label));
                    return it ? (it.querySelector('input')?.value || '') : '';
                }""", label)
                if v and str(value) in v:
                    break
                await asyncio.sleep(0.2)
            ok = bool(v and str(value) in v)
            self.log(f"  {label} = {v or '(空)'} {'✓' if ok else '✗'}")
            if ok:
                return True
        if not hit:
            self.log(f"  ⚠ 未找到日期表单项 ({'/'.join(labels)}), 跳过日期填写")
            return None
        return False

    async def _wait_pool_loaded(self, timeout=20):
        """等「添加推广的产品」列表加载完成: loading mask 消失且有数据行
        (店铺切换触发异步加载ASIN, 实测约1.2s; 未加载时显示「暂无数据」)"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = await self.js("""() => {
                const it = [...document.querySelectorAll('.el-form-item')].find(i =>
                    (i.querySelector('.el-form-item__label')?.textContent||'').includes('添加推广'));
                if (!it) return {ok: false};
                const vis = el => el.getBoundingClientRect().width>0;
                const mask = [...it.querySelectorAll('.el-loading-mask')].some(vis);
                const rows = it.querySelectorAll('.vxe-body--row').length;
                return {ok: !mask && rows>0, mask, rows};
            }""")
            if st.get('ok'):
                self.log(f"  产品池已加载 ({st.get('rows')}行)")
                return True
            await asyncio.sleep(0.2)
        self.log("  ⚠ 产品池加载等待超时, 继续执行")
        return False

    async def _click_radio(self, text):
        pos = await self.js("""(text) => {
            const r = [...document.querySelectorAll('.el-radio')].find(x =>
                x.offsetParent!==null && (x.textContent||'').trim()===text);
            if (!r) return null;
            r.scrollIntoView({block: 'center'});
            const b = r.getBoundingClientRect();
            return {x: b.x + 10, y: b.y + b.height/2};
        }""", text)
        if not pos:
            return False
        await asyncio.sleep(0.2)
        await self.click_at(pos)
        # 轮询选中态(超时也放行, 与旧行为一致不阻塞)
        for _ in range(10):
            await asyncio.sleep(0.2)
            if await self.js("""(text) => [...document.querySelectorAll('.el-radio')]
                .some(x => x.offsetParent!==null && (x.textContent||'').trim()===text
                    && x.className.includes('is-checked'))""", text):
                break
        return True

    async def _fill_number_field(self, label, value):
        pos = await self.js("""(label) => {
            const it = [...document.querySelectorAll('.el-form-item')].find(i =>
                (i.querySelector('.el-form-item__label')?.textContent||'').includes(label));
            const inp = it.querySelector('input');
            if (!inp) return null;
            it.scrollIntoView({block: 'center'});
            const r = inp.getBoundingClientRect();
            return {x: r.x + r.width/2, y: r.y + r.height/2};
        }""", label)
        if not pos:
            self.log(f"✗ {label}输入框未找到")
            return False
        await asyncio.sleep(0.25)
        await self.click_at(pos)
        await asyncio.sleep(0.2)
        # 焦点校验
        focused = await self.js("""(label) => {
            const it = [...document.querySelectorAll('.el-form-item')].find(i =>
                (i.querySelector('.el-form-item__label')?.textContent||'').includes(label));
            return document.activeElement === it.querySelector('input');
        }""", label)
        if not focused:
            self.log(f"✗ {label}输入框未获得焦点")
            return False
        await self.page.keyboard.press(f"{SELECT_ALL}+A")
        await self.page.keyboard.press("Backspace")
        await self.page.keyboard.type(str(value), delay=40)
        await self.page.keyboard.press("Tab")
        # 轮询校验值
        v = None
        for _ in range(15):
            v = await self.js("""(label) => {
                const it = [...document.querySelectorAll('.el-form-item')].find(i =>
                    (i.querySelector('.el-form-item__label')?.textContent||'').includes(label));
                return it.querySelector('input')?.value;
            }""", label)
            if v == str(value):
                break
            await asyncio.sleep(0.2)
        ok = v == str(value)
        self.log(f"  {label} = {v} {'✓' if ok else '✗'}")
        return ok

    # ================= Step2 =================

    async def step2_pick_template(self, template="新品推广低预算"):
        if not await self.wait_step(STEP2):
            self.log("✗ 不在Step2")
            return False
        pos = await self.js("""(tpl) => {
            const card = [...document.querySelectorAll('div.item')].find(c =>
                c.offsetParent!==null && (c.textContent||'').includes(tpl));
            if (!card) return null;
            const r = card.getBoundingClientRect();
            return {x: r.x + r.width/2, y: Math.min(r.y + 40, r.y + r.height/2)};
        }""", template)
        if not pos:
            self.log(f"✗ 模板卡片未找到: {template}")
            return False
        await self.click_at(pos)
        # 轮询卡片选中态(0.2s步进); 1.5s未选中补点一次
        active = False
        for i in range(15):
            await asyncio.sleep(0.2)
            active = await self.js("""(tpl) => {
                const card = [...document.querySelectorAll('div.item')].find(c =>
                    c.offsetParent!==null && (c.textContent||'').includes(tpl));
                return card ? card.className.includes('active') : false;
            }""", template)
            if active:
                break
            if i == 7:
                await self.click_at(pos)
        if not active:
            self.log("✗ 模板卡片未选中")
            return False
        # Step2 的确认按钮是「生成预览」(直接生成并进入第3步)
        await self._click_button("生成预览", settle=0.2)
        self.log(f"  Step2 模板「{template}」→ 生成预览")
        return await self.wait_step(STEP3, timeout=40)

    # ================= Step3 =================

    async def step3_prepare(self, k):
        """(预览已由step2生成) 移除全部手动投放 → 校验自动活动数"""
        if not await self.wait_step(STEP3):
            self.log("✗ 不在Step3")
            return False
        self.log("  预览已生成")
        # 移除全部手动投放活动 (失败直接中断: 残留手动活动会占用预算与投放位)
        if not await self._remove_manual_campaigns():
            self.log("✗ 手动投放活动未清除干净, 中断")
            return False
        # 校验自动活动数, 不足则复制补齐到本批条数k
        names = await self.list_campaigns()
        autos = [n for n in names if '自动投放' in n]
        self.log(f"  自动活动 {len(autos)} 条 / 期望 {k} 条")
        if len(autos) < k:
            need = k - len(autos)
            ok = await self.copy_campaigns(need)
            if not ok:
                self.log("  ✗ 复制广告活动流程未完成, 中断")
                return False
            # 轮询副本行渲染到位
            autos2 = []
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                names2 = await self.list_campaigns()
                autos2 = [n for n in names2 if '自动投放' in n]
                if len(autos2) >= k:
                    break
                await asyncio.sleep(0.3)
            self.log(f"  不足, 补复制 x{need}: {ok} → 自动活动 {len(autos2)} 条")
            if len(autos2) < k:
                self.log("  ✗ 复制后自动活动仍不足")
                return False
        elif len(autos) > k:
            self.log(f"  ⚠ 自动活动多于期望 {len(autos)}>{k}")
        return True

    async def _remove_manual_campaigns(self):
        """移除所有名称含「手动投放」的活动 (点击+轮询确认)"""
        for round_ in range(5):
            manual = [n for n in await self.list_campaigns() if '手动投放' in n]
            if not manual:
                self.log("  手动投放活动已全部移除")
                return True
            for name in manual:
                await self.remove_campaign(name)
            # 行删除是异步的, 轮询确认清零(0.25s步进, 最长5s)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                left = [n for n in await self.list_campaigns() if '手动投放' in n]
                if not left:
                    break
                await asyncio.sleep(0.25)
        leftover = [n for n in await self.list_campaigns() if '手动投放' in n]
        if leftover:
            self.log(f"  ⚠ 仍有手动投放活动未移除: {leftover}")
            return False
        self.log("  手动投放活动已全部移除")
        return True

    async def submit_batch(self):
        """第3步提交 (默认不调用)"""
        pos = await self.js("""() => {
            const btn = [...document.querySelectorAll('button')]
                .find(b => (b.textContent||'').trim()==='提交' && b.getBoundingClientRect().width>0);
            if (!btn) return null;
            const r = btn.getBoundingClientRect();
            return {x: r.x + r.width/2, y: r.y + r.height/2};
        }""")
        if not pos:
            return False
        await self.click_at(pos)
        await asyncio.sleep(2)
        # 确认弹窗
        await self.js("""() => {
            for (const box of document.querySelectorAll('.el-message-box')) {
                if (box.offsetParent===null) continue;
                const btn = [...box.querySelectorAll('button')]
                    .find(b => ['确定','确认','是'].includes((b.textContent||'').trim()));
                if (btn) { btn.click(); break; }
            }
        }""")
        await asyncio.sleep(3)
        return True

    # ---------- 按钮工具 ----------

    async def _click_button(self, text, settle=0.3):
        pos = await self.js("""(text) => {
            const btn = [...document.querySelectorAll('button')]
                .find(b => (b.textContent||'').trim()===text && b.getBoundingClientRect().width>0);
            if (!btn) return null;
            const r = btn.getBoundingClientRect();
            return {x: r.x + r.width/2, y: r.y + r.height/2};
        }""", text)
        if pos:
            await self.click_at(pos)
            await asyncio.sleep(settle)
        return pos is not None

    # ================= 表格/弹窗工具 (第3步) =================

    async def scroll_top(self):
        await self.js("""() => {
            window.scrollTo(0,0);
            document.querySelectorAll('.vxe-table--body-wrapper').forEach(w => w.scrollTop = 0);
        }""")
        await asyncio.sleep(0.2)

    async def scroll_down(self, px=600):
        await self.js(f"""() => {{
            document.querySelectorAll('.vxe-table--body-wrapper').forEach(w => w.scrollTop += {px});
            window.scrollTo(0, window.scrollY + {px});
        }}""")
        await asyncio.sleep(0.2)

    async def collect_rows(self):
        return await self.js("""() => {
            const rows = [...document.querySelectorAll('.vxe-body--row')].filter(r=>r.offsetParent!==null);
            const out = [];
            let cur = '';
            for (const row of rows) {
                const cn = row.querySelector('.campaign-name');
                if (cn) { cur = (cn.textContent||'').trim(); out.push({type:'campaign', name:cur}); }
                else {
                    const btn = [...row.querySelectorAll('button')]
                        .find(b => (b.textContent||'').trim()==='设置广告产品');
                    out.push({type:'group', owner:cur, has_set_btn: !!btn});
                }
            }
            return out;
        }""")

    async def locate_campaign(self, name, need_group_btn=True, max_steps=40, from_bottom=False):
        """定位指定活动行 (顺序填模型下目标活动在前段, 默认从表头向下找)"""
        await self.scroll_bottom() if from_bottom else await self.scroll_top()
        for _ in range(max_steps):
            self._check_stop()
            rows = await self.collect_rows()
            idx = next((i for i, r in enumerate(rows)
                        if r['type'] == 'campaign' and r['name'] == name), None)
            if idx is not None:
                nxt = rows[idx + 1] if idx + 1 < len(rows) else None
                if nxt and nxt['type'] == 'group' and (nxt['has_set_btn'] or not need_group_btn):
                    return True
                return 'folded'
            if not await self._scroll_table(up=from_bottom):
                return None
            await asyncio.sleep(0.2)
        return None

    async def expand_campaign(self, name):
        """展开广告活动行: 先 scrollIntoView 滚入可视区(真实鼠标对视口外
        元素点击无效), 再点行首三角 .vxe-table--expand-btn"""
        found = await self.js("""(campaign) => {
            const rows = [...document.querySelectorAll('.vxe-body--row')].filter(r=>r.offsetParent!==null);
            for (const row of rows) {
                const cn = row.querySelector('.campaign-name');
                if (cn && (cn.textContent||'').indexOf(campaign)===0) {
                    const el = row.querySelector('.vxe-table--expand-btn')
                            || row.querySelector('td[class*=col--expand]');
                    if (!el) return false;
                    el.scrollIntoView({block: 'center'});
                    return true;
                }
            }
            return false;
        }""", name)
        if not found:
            return False
        await asyncio.sleep(0.35)
        pos = await self.js("""(campaign) => {
            const rows = [...document.querySelectorAll('.vxe-body--row')].filter(r=>r.offsetParent!==null);
            for (const row of rows) {
                const cn = row.querySelector('.campaign-name');
                if (cn && (cn.textContent||'').indexOf(campaign)===0) {
                    const el = row.querySelector('.vxe-table--expand-btn')
                            || row.querySelector('td[class*=col--expand]');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {x: r.x + r.width/2, y: r.y + r.height/2};
                }
            }
            return null;
        }""", name)
        if not pos or pos['y'] < 0 or pos['y'] > 950:
            return False
        await self.click_at(pos)
        # 轮询展开生效(该活动行后出现组行), 替代固定1.2s
        for _ in range(14):
            rows = await self.collect_rows()
            for i, r in enumerate(rows):
                if r['type'] == 'campaign' and r['name'].startswith(name):
                    nxt = rows[i + 1] if i + 1 < len(rows) else None
                    if nxt and nxt['type'] == 'group':
                        return True
                    break
            await asyncio.sleep(0.15)
        return True  # 超时放行, 由上层 locate 复查兜底

    async def expand_visible_collapsed(self, visited=None):
        """展开当前视口内收起的广告活动行(收起的组行不进DOM, 无法配置)。
        visited 记录已点过的活动, 避免重复点击/展开收起循环"""
        rows = await self.collect_rows()
        for i, r in enumerate(rows[:-1]):  # 末行可能组行在视口外, 留给下轮滚动后处理
            if r['type'] != 'campaign':
                continue
            if rows[i + 1]['type'] == 'group':
                continue  # 已展开
            if visited is not None:
                if r['name'] in visited:
                    continue
                visited.add(r['name'])
            await self.expand_campaign(r['name'])

    async def scroll_bottom(self):
        """滚动到页面与表格底部"""
        await self.js("""() => {
            window.scrollTo(0, document.body.scrollHeight);
            document.querySelectorAll('.vxe-table--body-wrapper')
                .forEach(w => w.scrollTop = w.scrollHeight);
        }""")
        await asyncio.sleep(0.2)

    async def _scroll_table(self, up=False, px=600):
        """表格滚动一步: up=False 向下, up=True 向上。返回 False 表示已到边"""
        return await self.js(f"""(up) => {{
            const ws = [...document.querySelectorAll('.vxe-table--body-wrapper')];
            const w = ws.find(w => w.scrollHeight > w.clientHeight) || ws[0];
            if (!w) return false;
            if (up) {{
                if (w.scrollTop <= 5) return false;
                w.scrollTop = Math.max(0, w.scrollTop - {px});
            }} else {{
                if (w.scrollTop + w.clientHeight >= w.scrollHeight - 5) return false;
                w.scrollTop += {px};
            }}
            window.scrollTo(0, window.scrollY + (up ? -{px} : {px}));
            return true;
        }}""", up)

    async def find_unset_campaign(self, max_steps=60, from_bottom=False, exclude=None):
        """扫描找首个未配置活动 (组行带「设置广告产品」按钮)。

        - 默认从表头向下扫: 顺序填活动模型下, 已配置区集中在表头前段,
          首个未配置活动即"下一个序号" (等价于进度指针, 已配置数即指针值)
        - exclude: 本批已烧毁(反复失败)的活动名集合, 扫描时跳过
          (不展开也不返回, 其空位由统一清除环节处理)
        - lazy 展开: 仅当扫描顺序轮到某个收起的活动、需要判定它是否
          未配置时才展开它 (一次一个, 用完即止)
        """
        await self.scroll_bottom() if from_bottom else await self.scroll_top()
        visited = set()
        for _ in range(max_steps):
            self._check_stop()
            rows = await self.collect_rows()
            target, need_expand = None, None
            order = range(len(rows) - 1, -1, -1) if from_bottom else range(len(rows))
            for i in order:
                r = rows[i]
                if r['type'] != 'campaign' or not r['name']:
                    continue
                if exclude and r['name'] in exclude:
                    continue
                nxt = rows[i + 1] if i + 1 < len(rows) else None
                if nxt and nxt['type'] == 'group':
                    if nxt['has_set_btn']:
                        target = r['name']
                        break
                    continue  # 已展开且已配置
                if r['name'] not in visited:
                    need_expand = r['name']
                    break
            if target:
                return target
            if need_expand:
                visited.add(need_expand)
                await self.expand_campaign(need_expand)
                continue  # 展开后重扫当前视口
            if not await self._scroll_table(up=from_bottom):
                return None
            await asyncio.sleep(0.25)
        return None

    async def list_campaigns(self):
        await self.scroll_top()
        names = []
        for _ in range(60):
            self._check_stop()
            rows = await self.collect_rows()
            for r in rows:
                if r['type'] == 'campaign' and r['name'] not in names:
                    names.append(r['name'])
            has_more = await self.js("""() => {
                const ws = [...document.querySelectorAll('.vxe-table--body-wrapper')];
                const w = ws.find(w => w.scrollHeight > w.clientHeight) || ws[0];
                if (!w) return false;
                if (w.scrollTop + w.clientHeight >= w.scrollHeight - 5) return false;
                w.scrollTop += 800;
                return true;
            }""")
            if not has_more:
                break
            await asyncio.sleep(0.25)
        return names

    # ---------- 设置广告产品弹窗 ----------

    async def wait_dialog(self, campaign, timeout=15):
        for _ in range(int(timeout / 0.25)):
            self._check_stop()
            st = await self.js(f"""(campaign) => {{
                const d = {DLG};
                if (!d) return {{state:'none'}};
                const t = (d.textContent||'').replace(/\\s+/g,' ');
                return t.includes(campaign) ? {{state:'match'}} : {{state:'mismatch'}};
            }}""", campaign)
            if st['state'] == 'match':
                return True
            if st['state'] == 'mismatch':
                return False
            await asyncio.sleep(0.25)
        return False

    async def _close_dialog_any(self):
        await self.js(f"""() => {{
            const d = {DLG};
            if (!d) return;
            const btn = [...d.querySelectorAll('button')]
                .find(b => (b.textContent||'').trim()==='取消' && b.getBoundingClientRect().width>0);
            if (btn) btn.click();
        }}""")
        # 轮询弹窗关闭, 替代固定1.2s
        for _ in range(10):
            if not await self.js(f"() => !!({DLG})"):
                return
            await asyncio.sleep(0.2)

    async def open_product_dialog(self, campaign, retries=3):
        for attempt in range(retries):
            await self._close_dialog_any()
            st = await self.locate_campaign(campaign, from_bottom=False)
            if st == 'folded':
                await self.expand_campaign(campaign)
                st = await self.locate_campaign(campaign)
            if st is not True:
                return False
            r = await self.js("""(campaign) => {
                const rows = [...document.querySelectorAll('.vxe-body--row')].filter(r=>r.offsetParent!==null);
                let cur = '';
                for (const row of rows) {
                    const cn = row.querySelector('.campaign-name');
                    if (cn) cur = (cn.textContent||'').trim();
                    const btn = [...row.querySelectorAll('button')]
                        .find(b => (b.textContent||'').trim()==='设置广告产品');
                    if (btn && cur === campaign) { btn.click(); return {ok:true}; }
                }
                return {ok:false};
            }""", campaign)
            if not r['ok']:
                continue
            # wait_dialog 自身轮询, 不再固定等待
            if await self.wait_dialog(campaign):
                return True
        return False

    async def search_asin(self, asin, timeout=30):
        pos = await self.js(f"""() => {{
            const d = {DLG};
            const inp = [...d.querySelectorAll('input')].find(i => i.placeholder==='搜索内容');
            if (!inp) return null;
            const r = inp.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }}""")
        if not pos:
            return {'state': 'no_dialog'}
        await self.click_at(pos)
        await asyncio.sleep(0.3)
        await self.page.keyboard.press(f"{SELECT_ALL}+A")
        await self.page.keyboard.press("Backspace")
        await self.page.keyboard.type(asin, delay=80)
        await asyncio.sleep(0.25)
        await self.page.keyboard.press("Enter")

        for _ in range(int(timeout / 0.4)):
            self._check_stop()
            st = await self.js(f"""(asin) => {{
                const d = {DLG};
                if (!d) return {{state:'no_dialog'}};
                if ([...d.querySelectorAll('.el-loading-mask')].some(m => m.offsetParent!==null))
                    return {{state:'loading'}};
                const btns = [];
                for (const b of d.querySelectorAll('button')) {{
                    const t = (b.textContent||'').trim();
                    if (!['添加','添加变体','已添加'].includes(t)) continue;
                    if (b.getBoundingClientRect().width===0) continue;
                    let el = b.parentElement;
                    for (let i=0;i<14 && el && el!==d; i++) {{
                        if ((el.textContent||'').includes(asin)) {{ btns.push(t); break; }}
                        el = el.parentElement;
                    }}
                }}
                if (btns.length) return {{state:'found', btns}};
                const t = (d.textContent||'').replace(/\\s+/g,'');
                const iAdd = t.indexOf('添加全部'), iRm = t.indexOf('移除全部');
                if (iAdd >= 0 && t.slice(iAdd, iRm>=0?iRm:undefined).includes('暂无数据'))
                    return {{state:'empty'}};
                return {{state:'unknown'}};
            }}""", asin)
            if st['state'] in ('found', 'empty', 'no_dialog'):
                return st
            await asyncio.sleep(0.4)
        return {'state': 'timeout'}

    async def click_add_for_asin(self, asin):
        """点击该 ASIN 行的添加按钮。

        规则:
        - 「添加」与「添加变体」同时出现时, 优先点「添加变体」
        - 点击后采用正向判定: 行内出现「已添加」按钮即视为生效 (150ms×8),
          而非等待候选按钮全部消失 (多 SKU 行候选永远存在, 会导致误判超时)
        - 未生效自动补点(最多3次), 避免单次 JS click 无响应造成假添加
        返回: {result: '添加变体'|'添加'|'already'|'invalid', confirmed: bool}
        """
        return await self.js(f"""async (asin) => {{
            const d = {DLG};
            if (!d) return {{result:'invalid', confirmed:false}};
            const sleep = ms => new Promise(r => setTimeout(r, ms));
            const rowBtns = () => {{
                const out = [];
                for (const b of d.querySelectorAll('button')) {{
                    const t = (b.textContent||'').trim();
                    if (!['添加','添加变体','已添加'].includes(t)) continue;
                    if (b.getBoundingClientRect().width===0) continue;
                    let el = b.parentElement;
                    for (let i=0;i<14 && el && el!==d; i++) {{
                        if ((el.textContent||'').includes(asin)) {{ out.push({{btn:b, txt:t}}); break; }}
                        el = el.parentElement;
                    }}
                }}
                return out;
            }};
            const hasAdded = () => rowBtns().some(x => x.txt==='已添加');
            let btns = rowBtns();
            if (!btns.length) return {{result:'invalid', confirmed:false}};
            if (btns.some(x => x.txt==='已添加')) return {{result:'already', confirmed:true}};
            // 「添加变体」优先于「添加」(同时出现时)
            const pickOf = () => btns.find(x=>x.txt==='添加变体') || btns.find(x=>x.txt==='添加');
            const firstPick = pickOf();
            const pickedTxt = firstPick ? firstPick.txt : '';
            let confirmed = false;
            for (let i=0; i<3 && !confirmed; i++) {{
                const p = pickOf();
                if (!p) {{ confirmed = hasAdded(); break; }}
                p.btn.click();
                // 正向轮询: 行内出现「已添加」即成功
                for (let j=0; j<8; j++) {{
                    await sleep(150);
                    if (hasAdded()) {{ confirmed = true; break; }}
                    btns = rowBtns();
                    if (!btns.some(x => x.txt==='添加' || x.txt==='添加变体')) {{
                        confirmed = hasAdded();
                        break;
                    }}
                }}
            }}
            return {{result: pickedTxt || 'invalid', confirmed}};
        }}""", asin)

    async def wait_added(self, asin, timeout=8):
        """等待该 ASIN 行出现「已添加」状态 (仅在点击未确认时作兜底, 正常路径不会进入)"""
        for _ in range(int(timeout / 0.25)):
            self._check_stop()
            ok = await self.js(f"""(asin) => {{
                const d = {DLG};
                for (const b of d.querySelectorAll('button')) {{
                    if ((b.textContent||'').trim()!=='已添加' || b.getBoundingClientRect().width===0) continue;
                    let el = b.parentElement;
                    for (let i=0;i<14 && el && el!==d; i++) {{
                        if ((el.textContent||'').includes(asin)) return true;
                        el = el.parentElement;
                    }}
                }}
                return false;
            }}""", asin)
            if ok:
                return True
            await asyncio.sleep(0.25)
        return False

    async def added_count(self):
        """读取弹窗「已添加 N 个产品」计数区域。

        匹配优先级: 「已添加 N 个产品」>「已选 N 个」> 右栏「移除」按钮数兜底。
        弹窗丢失或区域不存在返回 None。
        """
        return await self.js(f"""() => {{
            const d = {DLG};
            if (!d) return null;
            const t = (d.textContent||'').replace(/\\s+/g,'');
            let m = t.match(/已添加(\\d+)个产品/) || t.match(/已选(\\d+)个/);
            if (m) return parseInt(m[1]);
            const rm = [...d.querySelectorAll('button')].filter(b =>
                (b.textContent||'').trim()==='移除' && b.getBoundingClientRect().width>0);
            return rm.length || null;
        }}""")

    async def trim_selection(self, keep=MAX_VARIANTS):
        """裁剪右栏已选到 keep 个 (方案B, 单次evaluate内):
        ① 探测发: 判定删除是否弹确认框
        ② 无确认框 → 一口气批量click超出按钮, 统一轮询计数(引用失效则重试)
        ③ 有确认框/批量失效 → 退回逐个删(80ms步进)保底"""
        return await self.js(f"""async (keep) => {{
            const d = {DLG};
            if (!d) return null;
            const sleep = ms => new Promise(r => setTimeout(r, ms));
            const rmBtns = () => [...d.querySelectorAll('button')].filter(b =>
                (b.textContent||'').trim()==='移除' && b.getBoundingClientRect().width>0);
            const confirmBox = () => {{
                for (const box of document.querySelectorAll('.el-message-box')) {{
                    if (box.offsetParent===null) continue;
                    const btn = [...box.querySelectorAll('button')].find(b =>
                        ['确定','确认','是'].includes((b.textContent||'').trim()));
                    if (btn) {{ btn.click(); return true; }}
                }}
                return false;
            }};
            const count = () => rmBtns().length;
            let n = count();
            if (n <= keep) return n;

            // ① 探测发
            let needConfirm = false;
            rmBtns()[rmBtns().length-1].click();
            let settled = false;
            for (let i=0; i<25; i++) {{
                await sleep(80);
                if (confirmBox()) needConfirm = true;
                const n2 = count();
                if (n2 < n) {{ n = n2; settled = true; break; }}
            }}
            if (!settled) return n;   // 单发失败, 交由③保底

            // ② 批量阶段 (仅无确认框时)
            if (!needConfirm) {{
                let guard = 0;
                while (count() > keep && guard++ < 8) {{
                    const btns = rmBtns();
                    const excess = btns.length - keep;
                    if (excess <= 0) break;
                    for (const b of btns.slice(-excess)) b.click();  // 一口气点
                    let prev = count();
                    for (let i=0; i<60; i++) {{
                        await sleep(50);
                        const n2 = count();
                        if (n2 <= keep) {{ break; }}
                        if (n2 < prev) prev = n2;
                        if (i>15 && n2===prev) break;   // 停滞: 引用失效, 下一轮重查
                    }}
                    n = count();
                }}
            }}

            // ③ 保底: 逐个删
            let fails = 0;
            n = count();
            while (count() > keep && fails < 3) {{
                const btns = rmBtns();
                if (!btns.length) break;
                btns[btns.length-1].click();
                let ok = false;
                for (let i=0; i<20; i++) {{
                    await sleep(80);
                    confirmBox();
                    const n2 = count();
                    if (n2 < n) {{ n = n2; ok = true; break; }}
                }}
                if (ok) fails = 0; else fails++;
            }}
            return count();
        }}""", keep)

    async def confirm_dialog(self, timeout=15):
        pos = await self.js(f"""() => {{
            const d = {DLG};
            const btn = [...d.querySelectorAll('button')]
                .find(b => (b.textContent||'').trim()==='确定' && b.getBoundingClientRect().width>0);
            if (!btn) return null;
            const r = btn.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }}""")
        if not pos:
            return False
        await self.click_at(pos)
        for _ in range(int(timeout / 0.3)):
            self._check_stop()
            closed = await self.js(f"() => !({DLG})")
            if closed:
                return True
            await asyncio.sleep(0.3)
        return False

    async def _confirm_msgbox(self):
        return await self.js("""() => {
            for (const box of document.querySelectorAll('.el-message-box')) {
                if (box.offsetParent===null) continue;
                const btn = [...box.querySelectorAll('button')]
                    .find(b => ['确定','确认','是'].includes((b.textContent||'').trim()));
                if (btn) { btn.click(); return true; }
            }
            return false;
        }""")

    # ================= ASIN 录入 =================

    async def fill_asin(self, campaign, asin):
        """单 ASIN 录入完整流程:
        ① 开弹窗搜 ASIN → ② 优先「添加变体」点击并验证生效
        → ③ 校验「已添加 N 个产品」计数增长 → ④ 超 5 个变体裁剪
        → ⑤ 点弹窗「确定」提交 (轮询关闭)
        任一环节失败均记录跳过原因并关弹窗。
        """
        try:
            self._check_stop()
            if not await self.open_product_dialog(campaign):
                self.skips.add(asin, campaign, "dialog_failed", "弹窗打开/归属校验失败")
                return 'skipped'
            st = await self.search_asin(asin)
            state = st['state'] if isinstance(st, dict) else st
            if state == 'empty':
                self.skips.add(asin, campaign, "not_found", "搜索暂无数据")
                await self._close_dialog_any()
                return 'skipped'
            if state == 'no_dialog':
                self.skips.add(asin, campaign, "dialog_lost", "搜索时弹窗已关闭")
                return 'skipped'
            if state == 'timeout':
                self.skips.add(asin, campaign, "search_timeout", "搜索结果轮询超时")
                await self._close_dialog_any()
                return 'skipped'

            # ② 添加前计数基线 (通常为 0, 即「已添加 0 个产品」)
            before = await self.added_count()
            act = await self.click_add_for_asin(asin)
            result = act.get('result') if isinstance(act, dict) else act
            confirmed = bool(act.get('confirmed')) if isinstance(act, dict) else False
            if result == 'invalid':
                self.skips.add(asin, campaign, "invalid_button",
                               f"可选按钮={st.get('btns') or '无'}(非添加/添加变体)")
                await self._close_dialog_any()
                return 'skipped'
            if result == 'already':
                self.skips.add(asin, campaign, "already_added", "该ASIN已在本活动产品中")
                await self._close_dialog_any()
                return 'skipped'
            # 点击生效验证: JS 内已补点重试, 此处再以行态长轮询兜底
            if not confirmed and not await self.wait_added(asin):
                self.skips.add(asin, campaign, "add_unconfirmed",
                               f"点击[{result}]后按钮态未翻转(已补点3次)")
                await self._close_dialog_any()
                return 'skipped'

            # ③ 「已添加 N 个产品」计数校验: 必须严格增长
            after = await self.added_count()
            if before is not None and after is not None:
                if after <= before:
                    self.skips.add(asin, campaign, "add_count_no_increase",
                                   f"计数未增长: {before} → {after}")
                    await self._close_dialog_any()
                    return 'skipped'
            elif after is not None and after < 1:
                self.skips.add(asin, campaign, "add_count_zero",
                               "计数区域仍为 0, 未见成功添加")
                await self._close_dialog_any()
                return 'skipped'
            self.log(f"  [验证] {asin} 已添加计数: {before if before is not None else '?'} → {after} ✓")

            # ④ 超 5 个变体裁剪
            n = await self.trim_selection(MAX_VARIANTS)
            if n is not None and n > MAX_VARIANTS:
                self.skips.add(asin, campaign, "trim_failed", f"裁剪后仍{n}个")
                await self._close_dialog_any()
                return 'skipped'
            # 裁剪后复核计数区域 (与右栏按钮数交叉验证)
            n2 = await self.added_count()
            if n2 is not None and n2 > MAX_VARIANTS:
                self.skips.add(asin, campaign, "trim_failed",
                               f"裁剪后计数仍{n2}个(> {MAX_VARIANTS})")
                await self._close_dialog_any()
                return 'skipped'

            # ⑤ 提交: 点弹窗「确定」
            if not await self.confirm_dialog():
                self.skips.add(asin, campaign, "confirm_failed", "确定后弹窗未关闭")
                await self._close_dialog_any()
                return 'skipped'
            cnt = f" (共{n2 if n2 is not None else n}个产品)" if (n2 is not None or n is not None) else ""
            self.log(f"  [录入] {asin} → {campaign}{cnt}")
            return 'added'
        except OperatorStopped:
            # 用户终止: 关闭现场后向上抛出, 由 run_batch 统一收尾
            try:
                await self._close_dialog_any()
            except Exception:
                pass
            raise
        except Exception as e:
            self.skips.add(asin, campaign, "exception", str(e)[:120])
            try:
                await self._close_dialog_any()
            except Exception:
                pass
            return 'skipped'

    # ================= 活动管理 =================

    async def remove_campaign(self, name):
        """按活动名定位行, 直接点行内「移除」(无需展开) → 确认弹窗 → 轮询行消失"""
        await self.scroll_top()
        for _ in range(40):
            r = await self.js("""(campaign) => {
                const rows = [...document.querySelectorAll('.vxe-body--row')].filter(r=>r.offsetParent!==null);
                for (const row of rows) {
                    const cn = row.querySelector('.campaign-name');
                    if (!cn || (cn.textContent||'').trim()!==campaign) continue;
                    const btn = [...row.querySelectorAll('button')]
                        .find(b => (b.textContent||'').trim()==='移除');
                    if (!btn) return 'no_btn';
                    btn.click();
                    return 'clicked';
                }
                return 'not_found';
            }""", name)
            if r == 'clicked':
                # 轮询确认框出现并点掉
                for _ in range(10):
                    await asyncio.sleep(0.2)
                    if await self._confirm_msgbox():
                        break
                # 轮询行消失
                for _ in range(20):
                    await asyncio.sleep(0.25)
                    gone = await self.js("""(campaign) => ![...document.querySelectorAll('.vxe-body--row')]
                        .some(row => row.offsetParent!==null
                            && (row.querySelector('.campaign-name')?.textContent||'').trim()===campaign)""", name)
                    if gone:
                        return True
                return True
            if r == 'no_btn':
                return False
            await self.scroll_down()
        return False

    async def clear_unconfigured(self, max_rounds=50):
        """循环清除未配置产品的广告活动。

        原实现为 while True, 一旦 remove_campaign 声称成功但页面实际未删除,
        会反复定位到同一活动形成死循环, 因此改为有限轮次 + 超限登记。
        """
        removed = 0
        for _ in range(max_rounds):
            # 清除环节从表头向下扫 (从后往前分配后空活动集中在表头)
            target = await self.find_unset_campaign(from_bottom=False)
            if not target:
                break
            ok = await self.remove_campaign(target)
            if not ok:
                self.skips.add("-", target, "clear_failed", "未配置活动移除失败")
                break
            removed += 1
            await asyncio.sleep(0.3)
        else:
            self.skips.add("-", "-", "clear_incomplete",
                           f"清除轮次达到上限 {max_rounds}, 仍存在未配置活动")
        self.log(f"  已清除未配置活动 {removed} 条")

    async def audit_table(self, max_steps=60):
        """终态对账: 滚动扫描全表, 统计广告活动的「已配置 / 未配置」分布。

        判定依据: 活动行之后紧邻的组行若仍带「设置广告产品」按钮 → 未配置。
        """
        await self.scroll_top()
        visited = set()
        campaigns, configured, unconfigured = [], [], []
        for _ in range(max_steps):
            self._check_stop()
            await self.expand_visible_collapsed(visited)
            rows = await self.collect_rows()
            for i, r in enumerate(rows):
                if r['type'] != 'campaign' or r['name'] in campaigns:
                    continue
                campaigns.append(r['name'])
                nxt = rows[i + 1] if i + 1 < len(rows) else None
                if nxt and nxt['type'] == 'group':
                    if nxt['has_set_btn']:
                        unconfigured.append(r['name'])
                    else:
                        configured.append(r['name'])
            has_more = await self.js("""() => {
                const ws = [...document.querySelectorAll('.vxe-table--body-wrapper')];
                const w = ws.find(w => w.scrollHeight > w.clientHeight) || ws[0];
                if (!w) return false;
                if (w.scrollTop + w.clientHeight >= w.scrollHeight - 5) return false;
                w.scrollTop += 600;
                return true;
            }""")
            if not has_more:
                break
            await asyncio.sleep(0.25)
        return {
            "total_campaigns": len(campaigns),
            "configured": len(configured),
            "unconfigured": len(unconfigured),
            "configured_names": configured,
            "unconfigured_names": unconfigured,
        }

    async def copy_campaigns(self, copy_count):
        """复制广告活动 (实测验证的交互路径):
        (1) vxe复选格是span而非input, 须真实鼠标点击+is--checked轮询验证
        (2) 工具栏「复制」须真实鼠标hover; 菜单项须JS el.click()(真实坐标点击无效)
        (3) 弹窗复制类型选「复制广告活动/广告组」→ 副本组不复制投放(空组, 带设置按钮)
        (4) 数量输入框是 .el-input-number 内 type=text, 真实键盘输入
        (5) 弹窗「确定」真实坐标点击 → 轮询弹窗关闭"""
        if copy_count <= 0:
            return True
        await self.scroll_top()

        # 1. 清掉已有选中(防残留多选): 点击后轮询取消生效
        for _ in range(6):
            pos = await self.js("""() => {
                const cb = [...document.querySelectorAll('.vxe-cell--checkbox')]
                    .find(c => c.className.includes('is--checked')
                        && c.getBoundingClientRect().width>0);
                if (!cb) return null;
                const r = cb.getBoundingClientRect();
                return {x: r.x + r.width/2, y: r.y + r.height/2};
            }""")
            if not pos:
                break
            await self.click_at(pos)
            for _ in range(10):
                await asyncio.sleep(0.2)
                if not await self.js("""() => [...document.querySelectorAll('.vxe-cell--checkbox')]
                    .some(c => c.className.includes('is--checked'))"""):
                    break
        # 勾选一个活动行, 轮询 is--checked
        checked = False
        for _ in range(3):
            pos = await self.js("""() => {
                const row = [...document.querySelectorAll('.vxe-body--row')]
                    .find(r => r.getBoundingClientRect().width>0
                        && r.querySelector('.campaign-name')
                        && r.querySelector('.vxe-cell--checkbox'));
                if (!row) return null;
                const rr = row.querySelector('.vxe-cell--checkbox').getBoundingClientRect();
                return {x: rr.x + rr.width/2, y: rr.y + rr.height/2};
            }""")
            if not pos:
                self.log("  ✗ 未找到活动行复选框")
                return False
            await self.click_at(pos)
            for _ in range(15):
                await asyncio.sleep(0.2)
                checked = await self.js("""() => [...document.querySelectorAll('.vxe-cell--checkbox')]
                    .some(c => c.className.includes('is--checked'))""")
                if checked:
                    break
            if checked:
                break
        if not checked:
            self.log("  ✗ 复选框勾选失败")
            return False

        # 2. 真实hover工具栏「复制」→ 轮询菜单出现 → JS点「复制广告活动」
        pos = await self.js("""() => {
            const dd = [...document.querySelectorAll('.el-dropdown')].find(d =>
                (d.textContent||'').trim().startsWith('复制') && d.getBoundingClientRect().width>40);
            if (!dd) return null;
            const r = dd.getBoundingClientRect();
            return {x: r.x + r.width/2, y: r.y + r.height/2};
        }""")
        if not pos:
            self.log("  ✗ 工具栏「复制」下拉未找到")
            return False
        await self.page.mouse.move(pos['x'], pos['y'], steps=8)
        clicked = False
        for _ in range(15):
            await asyncio.sleep(0.2)
            clicked = await self.js("""() => {
                const item = [...document.querySelectorAll('.el-dropdown-menu__item')]
                    .find(i => (i.textContent||'').trim()==='复制广告活动'
                        && i.getBoundingClientRect().width>0);
                if (!item) return false;
                item.click();
                return true;
            }""")
            if clicked:
                break
        if not clicked:
            self.log("  ✗ 「复制广告活动」菜单项未找到")
            return False

        # 3. 轮询等弹窗
        opened = False
        for _ in range(12):
            if await self.js(f"() => !!({COPY_DLG})"):
                opened = True
                break
            await asyncio.sleep(0.5)
        if not opened:
            self.log("  ✗ 批量复制弹窗未弹出")
            return False

        # 4. 复制类型选「复制广告活动/广告组」(不复制投放 → 副本组为空)
        #    点击后必须回读 is-checked 确认选中: 未选中时副本会连带原投放,
        #    导致副本无「设置广告产品」按钮 → 后续整批 ASIN 无处可配。
        picked = False
        for _ in range(12):
            picked = await self.js(f"""() => {{
                const dlg = {COPY_DLG};
                if (!dlg) return false;
                const r = [...dlg.querySelectorAll('.el-radio')].find(x =>
                    (x.textContent||'').trim()==='复制广告活动/广告组');
                if (!r) return false;
                if (!r.className.includes('is-checked')) r.click();
                return true;
            }}""")
            if picked:
                break
            await asyncio.sleep(0.25)
        if not picked:
            self.log("  ✗ 复制类型选项「复制广告活动/广告组」未找到")
            return False
        type_checked = False
        for _ in range(15):
            type_checked = await self.js(f"""() => {{
                const dlg = {COPY_DLG};
                if (!dlg) return false;
                const r = [...dlg.querySelectorAll('.el-radio')].find(x =>
                    (x.textContent||'').trim()==='复制广告活动/广告组');
                return !!r && r.className.includes('is-checked');
            }}""")
            if type_checked:
                break
            await asyncio.sleep(0.2)
        if not type_checked:
            self.log("  ✗ 复制类型未选中(is-checked 校验失败), 中断")
            return False
        self.log("  复制类型: 复制广告活动/广告组 ✓")

        # 5. 数量: .el-input-number 内的 text input, 真实键盘输入 → 轮询值生效
        pos = await self.js(f"""() => {{
            const inp = {COPY_DLG}?.querySelector('.el-input-number input');
            if (!inp) return null;
            const r = inp.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }}""")
        if not pos:
            self.log("  ✗ 复制数量输入框未找到")
            return False
        await self.click_at(pos)
        await asyncio.sleep(0.2)
        await self.page.keyboard.press(f"{SELECT_ALL}+A")
        await self.page.keyboard.press("Backspace")
        await self.page.keyboard.type(str(copy_count), delay=80)
        await self.page.keyboard.press("Tab")
        v = None
        for _ in range(10):
            v = await self.js(f"""() => ({COPY_DLG})?.querySelector('.el-input-number input')?.value""")
            if v == str(copy_count):
                break
            await asyncio.sleep(0.2)
        # 轮询结束后必须复核最终值: 数量输错会直接导致副本条数不符预期
        if v != str(copy_count):
            self.log(f"  ✗ 复制数量回填失败: 期望 {copy_count} 实际 {v}")
            return False
        self.log(f"  复制数量 = {v} ✓")

        # 6. 确定按钮真实坐标点击 → 轮询弹窗关闭
        pos = await self.js(f"""() => {{
            const btn = [...({COPY_DLG}).querySelectorAll('button')]
                .find(b => (b.textContent||'').replace(/\\s/g,'')==='确定');
            if (!btn) return null;
            const r = btn.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }}""")
        if not pos:
            self.log("  ✗ 弹窗「确定」按钮未找到")
            return False
        await self.click_at(pos)
        for _ in range(25):
            await asyncio.sleep(0.3)
            if not await self.js(f"() => !!({COPY_DLG})"):
                return True  # 副本行渲染由 step3_prepare 轮询确认
        self.log("  ✗ 复制弹窗未关闭")
        return False

    # ================= 主流程 =================

    async def run_batch(self, asins, batch_size=None, submit=False,
                        shop="金梧汇辰", budget="300", bid="15",
                        bid_strategy="动态竞价-只降低",
                        create_mode="每个产品单独创建广告",
                        template="新品推广低预算",
                        start_date=None, end_date=None):
        """分批向导式批处理, 返回结构化执行结果 (供服务端登记执行结果)。

        submit=False 时全程不提交, 每批执行到提交前停止。
        批间切换通过 open_new_page 开新标签页进行, 上一批页面原样保留,
        全部批次结束后由人工逐个标签页检查提交。
        submit=True 时每批提交后刷新当前页面继续下一批。
        """
        remaining = [a.strip() for a in asins if a.strip()]
        B = batch_size or len(remaining)
        batch_no = 0
        run_t0 = time.monotonic()
        total_entered = 0
        fail_stage = ""
        aborted = False
        audit = {}
        self._batch_pages = []  # 不提交模式: 各批次页面的 (page, frame) 引用, 供最后统一清除
        try:
            while remaining:
                self._check_stop()
                batch_no += 1
                k = min(len(remaining), B)
                batch = remaining[:k]
                self.log(f"\n===== 第{batch_no}批: {k}个活动名额 (供给ASIN {len(remaining)}个) =====")
                self.log(f"  供给预览: {batch}")
                self._t = time.monotonic()

                # 向导位置校正: 不在Step1则刷新重置
                if not await self.wait_step(STEP1, timeout=3):
                    self.log("  不在Step1, 刷新页面重置向导...")
                    await self.reload_page()
                    if not await self.wait_step(STEP1):
                        self.log("✗ 刷新后仍不在Step1")
                        fail_stage = "向导重置失败(刷新后未回到Step1)"
                        aborted = True
                        break
                self.lap("进入Step1(含刷新)")

                # Step1 (不加产品, ASIN在第3步弹窗录入)
                if not await self.step1_fill(shop, budget, bid, bid_strategy, create_mode,
                                             start_date=start_date, end_date=end_date):
                    self.log("✗ Step1失败, 中断")
                    fail_stage = "Step1 基本信息填写失败(店铺/预算/竞价校验未通过)"
                    aborted = True
                    break
                self.lap("Step1填写+下一步")
                # Step2
                if not await self.step2_pick_template(template):
                    self.log("✗ Step2失败, 中断")
                    fail_stage = "Step2 广告结构模板选择失败"
                    aborted = True
                    break
                self.lap("Step2模板+生成预览")
                # Step3 准备
                if not await self.step3_prepare(k):
                    self.log("✗ Step3准备失败, 中断")
                    fail_stage = "Step3 预览准备失败(手动投放未清除/自动活动数不足)"
                    aborted = True
                    break
                self.lap("Step3准备(移除手动+复制校齐)")

                # 活动驱动录入: k 个活动名额, ASIN 按流水供给 (可越过本批边界)
                # - ASIN 级失败(搜不到/已加过/不能加等): 活动仍是未配置状态, 名额不烧毁,
                #   供给流继续, 空位由后续 ASIN 回补 → 优先把本批活动全部填满
                # - 活动级失败(弹窗打不开/确定失败等): 烧毁该名额并排除该活动,
                #   由下一活动顶上; 残留空活动由批尾清除环节统一处理
                # - 名额全部填满 或 供给耗尽 → 本批结束
                entered = 0
                burned = set()
                pos = 0
                while entered + len(burned) < k and pos < len(remaining):
                    self._check_stop()
                    asin = remaining[pos]
                    pos += 1
                    target = None
                    for _ in range(3):
                        target = await self.find_unset_campaign(exclude=burned)
                        if target:
                            break
                        await asyncio.sleep(0.5)
                    if not target:
                        self.skips.add(asin, "-", "no_campaign",
                                       "无未配置活动可分配(含已烧毁名额)")
                        continue
                    if await self.fill_asin(target, asin) == 'added':
                        entered += 1
                        self.log(f"  名额 {entered + len(burned)}/{k} ← {asin} @ {target}")
                    else:
                        reason = (self.skips.items[-1]['reason'] if self.skips.items else '')
                        if reason in ASIN_LEVEL_REASONS:
                            self.log(f"  ASIN失败({reason}), 名额保留, {target} 由后续 ASIN 回补")
                        else:
                            burned.add(target)
                            self.log(f"  活动级失败({reason}), 烧毁名额 {target}, 由下一活动顶上")
                consumed = pos
                total_entered += entered
                self.lap(f"活动驱动录入({entered}/{k}名额, 消耗{consumed}个ASIN)")

                # 终态对账 (在清除前执行: configured 应等于录入数, unconfigured 即本批空活动清单)
                audit = await self.audit_table()
                audit["expected"] = entered
                audit["match"] = audit.get("configured", 0) == entered
                self.log(f"  [对账] 已配置 {audit.get('configured')} 条 / 本批录入 {entered} 条"
                         f" / 未配置 {audit.get('unconfigured')} 条"
                         f" {'✓' if audit['match'] else '✗ 不一致, 请人工核对'}")
                if audit.get("unconfigured_names"):
                    self.log(f"  ⚠ 未配置活动: {audit['unconfigured_names']}")

                remaining = remaining[consumed:]
                if submit:
                    # 提交模式: 提交前必须清掉空活动 (否则空活动会随批次一起提交)
                    await self.clear_unconfigured()
                    self.lap("清除未配置")
                    if not await self.submit_batch():
                        self.log("✗ 提交失败, 中断")
                        fail_stage = "提交失败"
                        aborted = True
                        break
                    self.log(f"  第{batch_no}批已提交")
                    if remaining:
                        self.log("  刷新页面开始下一轮向导...")
                        await self.reload_page()
                else:
                    # 不提交模式: 本批页面原样保留 (含未配置活动), 清除统一放到全部批次结束后
                    self._batch_pages.append((self.page, self.frame))
                    self.log(f"  第{batch_no}批完成 (不提交, 停留在提交前待人工确认;"
                             f" 未配置活动 {audit.get('unconfigured', 0)} 个留待最后统一清除)")
                    if remaining:
                        self.log("  打开新页面开始下一批 (本批已保留在当前标签页)...")
                        await self.open_new_page()

            # 不提交模式: 全部批次录入完毕, 统一回各批次页面清除未配置活动
            if not submit and self._batch_pages and not aborted:
                self.log("\n── 统一清除未配置活动 ──")
                for pi, (page, frame) in enumerate(self._batch_pages, 1):
                    self._check_stop()
                    self.page, self.frame = page, frame
                    try:
                        await self.clear_unconfigured()
                        self.lap(f"第{pi}批页面清除完成")
                    except OperatorStopped:
                        raise
                    except Exception as e:
                        self.log(f"  ⚠ 第{pi}批页面清除异常: {type(e).__name__}: {str(e)[:100]}")

        except OperatorStopped:
            aborted = True
            fail_stage = "用户请求终止"
            # 终止发生在批次中途: 当前批次已录入的 entered 尚未累加, 必须补记,
            # 否则已成功录入的数据会被误报为 0 (零录入失败)
            total_entered += entered
            self.log("\n⏹ 收到终止请求, 任务已停止 (已录入数据保持现状)")
            try:
                await self._close_dialog_any()
            except Exception:
                pass

        duration = time.monotonic() - run_t0
        self.log(f"\n{'全部批次完成' if not aborted else '任务中断: ' + fail_stage}")
        if not submit and not aborted:
            self.log(f"共 {batch_no} 批已全部执行到提交前, 请在浏览器中逐个标签页人工检查并提交")
        self.log(f"总耗时: {duration:.1f}s, 共录入 {total_entered} 条")
        self.skips.report()

        skipped = len(self.skips.items)
        return {
            "success": (not aborted) and total_entered > 0 and skipped == 0,
            "aborted": aborted,
            "fail_stage": fail_stage,
            "total_asins": len([a for a in asins if str(a).strip()]),
            "entered_count": total_entered,
            "skipped_count": skipped,
            "batch_count": batch_no,
            "submitted": bool(submit and not aborted),
            "audit": audit,
            "skips": list(self.skips.items),
            "logs": list(self.log_lines),
            "duration_sec": round(duration, 1),
        }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asins", required=True, help="逗号分隔ASIN列表")
    ap.add_argument("--batch-size", type=int, default=None, help="每批广告活动数(默认=ASIN总数)")
    ap.add_argument("--shop", default="金梧汇辰")
    ap.add_argument("--budget", default="300")
    ap.add_argument("--bid", default="15")
    ap.add_argument("--bid-strategy", default="动态竞价-只降低")
    ap.add_argument("--create-mode", default="每个产品单独创建广告")
    ap.add_argument("--template", default="新品推广低预算")
    ap.add_argument("--submit", action="store_true",
                    help="自动提交每批(默认全程不提交, 最后一批停在提交前供人工检查)")
    args = ap.parse_args()

    op = SellfoxAdOperator()
    await op.connect()
    try:
        await op.run_batch(
            asins=args.asins.split(","),
            batch_size=args.batch_size,
            submit=args.submit,
            shop=args.shop, budget=args.budget, bid=args.bid,
            bid_strategy=args.bid_strategy, create_mode=args.create_mode,
            template=args.template,
        )
    finally:
        await op.close()


if __name__ == "__main__":
    asyncio.run(main())
