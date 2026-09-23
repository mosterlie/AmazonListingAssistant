# 店小秘订单剩余发货时间采集与预警 — 实施方案

> 目标页面: `https://www.dianxiaomi.com/web/order/all?go=m1-1&timeOut=1&index=1`（所有订单·临期筛选）
> 需求: 定时获取订单的剩余发货时间 → 入库 → 页面可视化预警 + 邮件预警；未登录时用配置的账密模拟登录。

## 一、总体思路

```
dxm_order_scheduler (独立心跳, 沿用 forwarder_doc_scheduler 模式)
   │ 每 N 分钟
   ▼
DxmOrderService.run_batch ──────────────────────────────────────┐
   1. 打开/复用 9222 Chrome 独立 tab → 目标 URL                 │
   2. 登录态检测: 跳到登录页? ──是──▶ 模拟登录(账密配置) ────────┤
   │      └─ 遇验证码/滑块 → 本轮跳过 + 标记需人工登录           │
   3. 抓订单列表(含翻页): 优先内部接口, 兜底 DOM 解析            │
   4. 入库 dxm_order_deadlines (快照幂等)                       │
   5. 预警判定: 剩余时间跨阈值(黄/红) → 邮件 + 页面红黄标        │
   ▼                                                            │
订单预警页 (新导航页) + 系统管理配置面板                          │
```

**采集通道选型：复用 9222 CDP Chrome（现有上件同通道），不用独立无头实例。**
理由：店小秘有登录态与风控，`C:\ChromeDebugUser` 配置文件里 session 长期有效（现有惯例：登录一次长期复用）；独立无头实例每次要重新登录且触发风控概率高。模拟登录仅作为登录态失效时的兜底。

## 二、数据获取设计

1. **打开方式**：`BrowserEngine(port=9222)` + `open_or_focus_url(目标URL)`（独立 tab，按 URL 复用已有 tab，与上件页互不干扰）；9222 未启动则按 erp_bridge 同款逻辑自动拉起专属 Chrome。
2. **登录态检测**：页面 URL 跳到 `login` / 存在登录表单 → 视为未登录。
3. **模拟登录**（兜底路径）：
   - 填入系统设置里的 `dxm_account` / `dxm_password` → 点击登录
   - **验证码自动识别输入**（不跳过、不依赖人工）：
     - **图形验证码**：截取验证码 `<img>` 元素 → base64 → **ddddocr 本地 OCR** 识别 → 填入验证码框 → 提交；识别错误导致登录失败 → 刷新验证码重试（最多 3 次，每次换新图）
     - **滑块验证码**：ddddocr `slide_match` 计算缺口 x 偏移 → 按人手轨迹（加速-减速+微抖动）模拟拖拽
     - **复杂行为验证（极验 v3/v4 点选等）**：本地无法可靠破解 → 本轮跳过 + 状态标记「需人工登录」+ 预警页横幅提示（session 持久化后长期有效，仅极端情况需要人工）
   - 依赖：`pip install ddddocr`（纯本地离线推理，无打码平台费用；首次安装自带 onnxruntime）
   - 登录成功判定：URL 离开登录页 / 出现订单列表特征元素；失败原因与验证码识别结果写入采集日志
   - 具体表单/验证码选择器与登录页 URL 在实施第一步实测确认
4. **列表抓取**（含翻页，两版并存）：
   - **首选**：在已登录页面上下文 `page.evaluate` 调用店小秘内部列表接口拿结构化 JSON（订单号/店铺/状态/发货截止时间/剩余时间）
   - **兜底**：解析渲染后的表格 DOM（接口变更时不失效）
   - 实施第一步：真实抓包确认接口路径、参数（`timeOut=1` 临期筛选、页码）、剩余时间字段格式（时间戳 or 文本），形成字段映射表
5. **与上件自动化互斥**：任务管理中有上件批次运行时跳过本轮采集（避免驱动线程竞争）；采集用独立 tab，其余时间可并行。

## 三、存储设计

新表 `dxm_order_deadlines`（database.py init_db 第 13 节）：

| 字段 | 说明 |
|---|---|
| order_no | 平台订单号（唯一键） |
| shop_name / site | 店铺 / 站点 |
| order_status | 订单状态（待发货/已发货…） |
| deadline_at | 发货截止时间（可解析则为绝对时间，否则 NULL） |
| remaining_minutes | 快照时剩余分钟数 |
| first_seen_at / updated_at | 首次发现 / 最近快照 |
| alert_level | 当前预警级（0无/1黄/2红） |
| alerted_levels | 已发过邮件的级别（避免重复轰炸） |

快照策略：每轮 UPSERT（按 order_no），已发货/消失的订单保留最近快照并标记，不物理删除（保留预警历史）。

## 四、预警设计

| 级别 | 条件（可配） | 动作 |
|---|---|---|
| 🟡 黄 | 剩余 < warn_hours（默认 24h） | 页面黄色标 + 首次触发发邮件 |
| 🔴 红 | 剩余 < danger_hours（默认 6h） | 页面红色标 + 升级邮件（每轮重复，可配） |
| ⚫ 超时 | 剩余 ≤ 0 | 页面置灰标红字 |

- 邮件：**复用** 货代采集的 SMTP 通道配置（smtp_host/port/ssl/user/password），预警独立开关 + 独立收件人 + 独立主题前缀 `[店小秘发货预警]`，正文表格列：订单号/店铺/站点/剩余时间/截止时间/状态
- 页面：新导航页「📦 订单预警」，按剩余时间升序，红黄分级、倒计时列、顶部状态栏（最近采集时间/登录状态/下轮倒计时）、「立即采集」「测试登录」按钮，30s 自动刷新（沿用 forwarder.html 的模式）

## 五、配置设计（系统管理 → 新面板「📦 店小秘订单预警」）

| 配置 | 默认 |
|---|---|
| dxm_account / dxm_password | 空（模拟登录用；存储方式与 smtp_password 一致） |
| scan_enabled / scan_interval_minutes | 开 / 60 |
| warn_hours / danger_hours | 24 / 6 |
| repeat_red_alert | 开（红色级每轮重复提醒） |
| alert_email_enabled / alert_mail_to | 关 / 空 |
| SMTP | 复用货代采集配置，不重复填 |

## 六、文件改动清单

| 文件 | 改动 |
|---|---|
| `server/services/dxm_order_service.py` | **新增**：采集/登录兜底/解析/入库/预警判定/邮件（模式照 forwarder_doc_service） |
| `server/services/dxm_order_scheduler.py` | **新增**：独立心跳（模式照 forwarder_doc_scheduler） |
| `server/routers/dxm_order_router.py` | **新增**：status / run / list / test-login 四个接口（登录鉴权同现有 router） |
| `server/database.py` | init_db 加第 13 节建表 |
| `server/app.py` | lifespan 启动 dxm 调度器 + 注册 router |
| `server/routers/settings_router.py` | schema/GET/POST 透传 dxm_order_* 配置 |
| `server/templates/settings.html` + `settings.js` | 新配置面板 |
| `server/templates/dxm_orders.html` + 静态 js + base.html 导航 | 订单预警页 |

## 七、实施顺序与验证

1. **实测探路**（人工登录态下）：打开目标页确认接口/字段/翻页/登录页结构 → 定字段映射
2. 后端：配置 + 建表 + service + scheduler + router
3. 前端：配置面板 + 预警页
4. **验证清单**：
   - 真实采集一轮 → 订单数与页面一致、剩余时间正确入库
   - 阈值临时调大 → 黄/红分级与邮件触发正确，级别不重复轰炸
   - 手动清除登录态 → 模拟登录成功路径；密码错误/验证码 → 跳过本轮并提示，不死循环
   - 上件任务运行中 → 采集自动跳过；并行时互不干扰
   - 服务重启 → 调度自动恢复，快照幂等不重复

## 八、风险与对策

| 风险 | 对策 |
|---|---|
| 图形验证码 OCR 识别率 | ddddocr 本地识别 + 失败自动刷新重试 3 次；仍失败才标记人工兜底 |
| 复杂行为验证（点选/极验） | 本地不可靠破解 → 跳过 + 人工登录提示（session 持久化后极少触发） |
| 登录内部接口变更 | DOM 解析兜底双通道 |
| 与上件自动化抢浏览器 | 独立 tab + 上件运行中跳过采集 |
| 账密明文存储 | 与现有 smtp_password 同级；如需可后续加密封装 |
