# 日本节假日日历同步 + 大节日邮件提醒

## Context

用户需要：定时同步日本的工作/休假日历，并在日本大节日临近时邮件提醒。项目已有成熟的「独立调度器 + 服务 + 路由 + 页面」模式（daily_digest、forwarder_doc、dxm_order），新功能完全复用该模式。

- 日本节假日数据源：date.nager.at 公共 API（免费、无需密钥，`/api/v3/PublicHolidays/{year}/JP`），用标准库 `urllib.request` 拉取（项目无 requests/httpx 依赖，已有 urllib 先例 product_router.py:109）。日本无调休制度，工作日 = 工作日(周一~五) − 法定节假日。
- 「大节日」判定：自动计算连休长度（节假日 + 相邻周六日的连续区间），连休 ≥3 天视为大节日，邮件中突出显示；提前提醒天数可配置。

## 实现步骤

### 1. 数据库 — `server/database.py` (init_db 内追加)

```sql
CREATE TABLE IF NOT EXISTS jp_holidays (
  date TEXT PRIMARY KEY,          -- '2026-01-01'
  name TEXT NOT NULL,             -- 英文名 (New Year's Day)
  local_name TEXT,                -- 日文名 (元日)
  types TEXT,                     -- API types 逗号分隔 (Public)
  synced_at TEXT                  -- 最后同步时间
);
```

配置键复用 system_settings（`get_setting/set_setting` 已有），前缀 `jp_holiday_`：
`email_enabled`(默认false)、`advance_days`(默认7)、`mail_to`(独立收件人,空=用默认收件人)、`last_sync_date`、`reminder_last`(当天已发标记)。

### 2. 服务 — 新建 `server/services/jp_holiday_service.py`

参照 `DailyDigestService`（daily_digest_service.py）：
- `get_config()` — SMTP 通道复用 `ForwarderDocService.get_config()` 的 fwd_doc_* 键（smtp_host/port/ssl/user/password/mail_from/subject_prefix），叠加 jp_holiday_* 键。
- `sync_year(year)` — urllib 拉 nager API → INSERT OR REPLACE 入库；`sync_due()` — 心跳调用，当年+次年缺数据或 last_sync_date ≠ 今天时同步。
- `break_length(date)` / `upcoming(days)` — 连休计算与临近节日查询。
- `maybe_send_reminder()` — 每天 advance_days 内有节日且当天未发 → 组 HTML（节日列表+连休天数+大节日高亮，样式复用 digest 的内联表格风格）→ smtplib 发送 → 记 `jp_holiday_last`。
- `send_test_email(cfg_override)` — 页面测试按钮用。

### 3. 调度器 — 新建 `server/services/jp_holiday_scheduler.py`

完全照抄 `daily_digest_scheduler.py` 模式：60s 心跳协程，`asyncio.to_thread` 依次执行 `sync_due()` + `maybe_send_reminder()`。

### 4. 路由 — 新建 `server/routers/jp_holiday_router.py`

- `GET /api/jp-holidays/calendar?year&month` — 月历数据（含节假日/周末标记）
- `GET /api/jp-holidays/upcoming` — 未来节日+连休列表（含大节日标记）
- `POST /api/jp-holidays/sync` — 手动立即同步
- `GET/POST /api/jp-holidays/config` — 读取/保存配置
- `POST /api/jp-holidays/test-email` — 测试邮件
- `GET /api/jp-holidays/status` — 同步/提醒状态（页面顶部展示）

在 `server/app.py` 注册：`app.include_router` + `@app.get("/japan-calendar")` 页面路由 + lifespan 启动/取消调度任务（照 app.py:47-64 模式）。

### 5. 前端 — 新建 `templates/japan_calendar.html` + `server/static/js/japan_calendar.js`

- 导航：`base.html` nav 增加 `🇯🇵 日本日历` 链接（/japan-calendar）
- 页面：月历网格（节日红标、周末灰标、大节日连休高亮），上下月切换
- 下方：未来 90 天节日列表（连休天数徽标）
- 设置卡片：邮件开关 / 提前天数 / 独立收件人 / 保存 / 测试邮件 / 立即同步 / 上次同步与上次提醒状态
- 参照现有 forwarder.html / settings.js 的 fetch + 渲染模式，复用 app.css 现有样式类

## 验证

1. 重启服务（先 stopAll 再 startAll，需 dangerouslyDisableSandbox）
2. `curl.exe http://127.0.0.1:8000/api/jp-holidays/upcoming` — 验证首次自动同步入库（jp_holidays 表有 2026/2027 数据）
3. 页面 http://127.0.0.1:8000/japan-calendar — 月历渲染、切换月份、手动同步
4. 配置收件人 + 开关开启 → 测试邮件发送成功 → 把 advance_days 调大覆盖近期节日验证真实触发路径
