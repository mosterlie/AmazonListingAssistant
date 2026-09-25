"""
告警任务注册表 + 告警中心聚合服务 (AlertService)

统一收敛当前两路监控任务的配置入口与告警展示:
  1. 货代文档采集 (ForwarderDocService): 轮询规则 daily/interval + 告警阈值;
     邮件由每日汇总任务 (DailyDigestService) 独立发送, 本页只管采集与告警规则
  2. 店小秘订单采集 (DxmOrderService): 每自然小时一次 (固定规则) + 黄/红阈值 + 红色即时邮件

告警中心: 将 forwarder_ship_alerts 与 dxm_order_deadlines 聚合为统一格式
[{source, source_name, type, level, title, detail, biz_date, ts}] 供 /alerts 页面展示。
"""
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.database import get_db_connection, get_setting, set_setting
from server.services.forwarder_doc_service import ForwarderDocService
from server.services.dxm_order_service import DxmOrderService

# ══════════ 配置表单统一模板 (唯一事实源) ══════════
# 每个任务按 sections → fields 声明可编辑配置项, /api/alert-tasks 原样下发 form,
# 前端 (alert_tasks.js) 通用渲染 + 收集; 新增任务类型只需在此登记, 无需改前端。
# field 键: key / type(text|password|number|time|select|switch) / label / def /
#   min|max|step(number) / placeholder(text) / options(select, [[value,label],...]) /
#   actions(toggle|test_login|test_email) / title(switch提示) / hint(行内说明) /
#   switch_text(grid内开关文案); section 键: title / cols(数字或"auto 1fr 1fr", 缺省=开关行) / help
TASK_FORMS = {
    "forwarder_doc": {
        "sections": [
            {"title": "⏱️ 轮询规则", "cols": 3, "fields": [
                {"key": "sync_mode", "type": "select", "label": "调度模式", "def": "daily",
                 "options": [["daily", "每天定时"], ["interval", "间隔轮询"]]},
                {"key": "sync_time", "type": "time", "label": "每日采集时间 (daily)", "def": "08:00"},
                {"key": "interval_hours", "type": "number", "label": "轮询间隔 (interval, 小时)",
                 "def": 24, "min": 1, "max": 720},
            ]},
            {"title": "🚨 告警规则", "cols": 4,
             "help": "告警 = 采购日期可解析 + 发货列为空 + 超期天数 ≥ 阈值; 每日数据快照存入数据库 (重跑自动先删当天)。",
             "fields": [
                {"key": "alert_days", "type": "number", "label": "未发货告警阈值 (天, ≥)",
                 "def": 7, "min": 1, "max": 365},
                {"key": "date_column", "type": "text", "label": "采购日期列名", "def": "采购日期"},
                {"key": "ship_column", "type": "text", "label": "发货日期列名 (空=未发货)", "def": "仓库发货日期"},
                {"key": "sheet_name", "type": "text", "label": "告警 sheet 名", "def": "发货数据"},
             ]},
        ],
    },
    "dxm_order": {
        "sections": [
            {"title": "⏱️ 轮询规则", "fields": [
                {"key": "scan_enabled", "type": "switch", "label": "定时采集开启", "def": True,
                 "title": "关闭后停止定时采集 (仍可手动执行)",
                 "hint": "频率固定: 每自然小时一次 (整点后首个心跳触发, 失败自动重试; 保证每天有 8 点批次供汇总邮件取数)"},
            ]},
            {"title": "🔐 店小秘账号", "cols": 2, "fields": [
                {"key": "dxm_account", "type": "text", "label": "登录账号 (未登录时自动模拟登录)",
                 "placeholder": "如: mosterlike"},
                {"key": "dxm_password", "type": "password", "label": "登录密码 (留空=保持原值)",
                 "actions": ["toggle", "test_login"]},
            ]},
            {"title": "🚨 告警规则", "cols": 2, "fields": [
                {"key": "warn_hours", "type": "number", "label": "🟡 黄色阈值 (剩余小时, 默认24)",
                 "def": 24, "min": 0.5, "step": 0.5},
                {"key": "danger_hours", "type": "number", "label": "🔴 红色阈值 (剩余小时, 默认6)",
                 "def": 6, "min": 0, "step": 0.5},
            ]},
        ],
    },
}

# 可编辑键白名单由表单模板派生 (save_task_config 仅接受这些键)
TASK_WHITELIST = {
    key: [f["key"] for sec in form["sections"] for f in sec["fields"]]
    for key, form in TASK_FORMS.items()
}

# ══════════ 提醒任务统一模板 (邮件提醒, 与轮询采集解耦) ══════════
# 两种提醒类型: daily_digest=每日定时提醒 (含店小秘订单+货代超期汇总) / dxm_realtime=实时预警提醒 (红色/超时即发)
# field 额外约定: "role": "mail_to"(收件人输入框, 测试邮件取值) / "enable"(提醒总开关, 测试时强制置真)
REMINDER_FORMS = {
    "daily_digest": {
        "sections": [
            {"title": "⏱️ 提醒规则", "fields": [
                {"key": "email_enabled", "type": "switch", "label": "每日定时提醒", "def": False, "role": "enable",
                 "title": "关闭后不再发送每日汇总提醒",
                 "hint": "每天固定时间发送一次汇总提醒, 内容包含: 店小秘订单预警 (橘/红/超时未发货) + 货代超期未发货告警明细"},
            ]},
            {"title": "🕐 发送时间与收件人", "cols": 2, "fields": [
                {"key": "digest_time", "type": "time", "label": "每日发送时间", "def": "08:15"},
                {"key": "digest_mail_to", "type": "text",
                 "label": "提醒收件人 (多个用英文逗号分隔; 留空=用系统管理 → 邮件通知的默认收件人)",
                 "placeholder": "you@qq.com, boss@qq.com", "actions": ["test_email"], "role": "mail_to"},
            ]},
            {"title": "✉️ 邮件主题", "cols": 1, "fields": [
                {"key": "subject_prefix", "type": "text", "label": "主题前缀", "def": "[货代发货提醒]"},
            ]},
        ],
    },
    "dxm_realtime": {
        "sections": [
            {"title": "⚡ 触发规则", "fields": [
                {"key": "alert_email_enabled", "type": "switch", "label": "红色/超时实时提醒", "def": False,
                 "role": "enable", "title": "开启后店小秘订单出现红色/超时立即发邮件",
                 "hint": "采集轮询 (每自然小时) 发现红色或超时未发货订单时实时发送; 验证码识别失败会自动换图重试 3 次"},
                {"key": "repeat_red_alert", "type": "switch", "label": "重复提醒",
                 "def": True, "switch_text": "每轮重复", "title": "关闭后同一订单只提醒一次"},
            ]},
            {"title": "📧 收件人与主题", "cols": 2, "fields": [
                {"key": "alert_mail_to", "type": "text", "label": "提醒收件人 (多个用英文逗号分隔)",
                 "placeholder": "you@qq.com, boss@qq.com", "actions": ["test_email"], "role": "mail_to"},
                {"key": "subject_prefix", "type": "text", "label": "主题前缀", "def": "[店小秘发货预警]"},
            ]},
        ],
    },
}

# 提醒任务可编辑键白名单
REMINDER_WHITELIST = {
    key: [f["key"] for sec in form["sections"] for f in sec["fields"]]
    for key, form in REMINDER_FORMS.items()
}


class AlertService:

    # ───────────────── 任务注册表 ─────────────────
    @staticmethod
    def get_tasks() -> List[Dict[str, Any]]:
        """全部告警任务: 名称/描述/启用状态/可编辑配置/运行状态"""
        fwd = ForwarderDocService.get_status()
        dxm = DxmOrderService.get_status()
        fwd_cfg = ForwarderDocService.get_config()
        dxm_cfg = DxmOrderService.get_config()
        tasks = []

        # 任务1: 货代文档采集 (邮件走每日汇总, 无独立启用开关 → 按轮询规则常开)
        tasks.append({
            "key": "forwarder_doc",
            "name": "货代文档采集",
            "icon": "🚢",
            "desc": "轮询采集全部货代「在线链接」登记文档, 分析「发货数据」sheet 中未发货超期记录并落库告警",
            "has_switch": False,
            "enabled": True,
            "poll_desc": "daily=每日定时 / interval=按小时间隔轮询",
            "form": TASK_FORMS["forwarder_doc"],
            "config": {k: fwd_cfg.get(k) for k in TASK_WHITELIST["forwarder_doc"]},
            "status": {
                "running": fwd.get("running", False),
                "running_trigger": fwd.get("running_trigger"),
                "last_log": fwd.get("last_log"),
                "today_alert_count": fwd.get("today_alert_count", 0),
                "today_doc_count": fwd.get("today_doc_count", 0),
            },
            "email_note": "本任务不发即时邮件; 采集结果与告警明细由「📧 提醒任务」的每日定时提醒邮件发送",
        })

        # 任务2: 店小秘订单采集 (每自然小时一次, scan_enabled 总开关)
        dxm_cfg_masked = {k: ("" if "password" in k else v) for k, v in dxm_cfg.items()}
        tasks.append({
            "key": "dxm_order",
            "name": "店小秘订单采集",
            "icon": "📦",
            "desc": "每自然小时采集一次店小秘待发货订单剩余发货时间, 黄/红分级预警, 红/超时可即时邮件 (已取消订单不采集)",
            "has_switch": True,
            "enabled": bool(dxm_cfg.get("scan_enabled")),
            "poll_desc": "每自然小时一次 (整点后首个心跳触发, 失败自动重试; 固定规则不可改)",
            "form": TASK_FORMS["dxm_order"],
            "config": {k: dxm_cfg_masked.get(k) for k in TASK_WHITELIST["dxm_order"]},
            "status": {
                "running": dxm.get("running", False),
                "running_trigger": dxm.get("running_trigger"),
                "last_log": dxm.get("last_log"),
                "counts": dxm.get("counts", {}),
            },
            "email_note": "红色/超时即时邮件规则已迁往「📧 提醒任务」; 本页只管采集轮询与告警判定",
        })
        return tasks

    @staticmethod
    def save_task_config(key: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        """按白名单过滤后委托对应服务保存配置"""
        if key not in TASK_WHITELIST:
            raise ValueError(f"未知告警任务: {key}")
        allowed = set(TASK_WHITELIST[key])
        filtered = {k: v for k, v in (patch or {}).items() if k in allowed}
        if key == "forwarder_doc":
            ForwarderDocService.save_config(filtered)
        else:
            # 密码留空 = 保持原值 (前端回显脱敏)
            if "dxm_password" in filtered and not str(filtered.get("dxm_password") or "").strip():
                filtered.pop("dxm_password")
            DxmOrderService.save_config(filtered)
        for t in AlertService.get_tasks():
            if t["key"] == key:
                return t
        return {}

    @staticmethod
    def run_task(key: str) -> Dict[str, Any]:
        """后台线程触发一次采集批次 (非阻塞)"""
        target = {"forwarder_doc": ForwarderDocService, "dxm_order": DxmOrderService}.get(key)
        if target is None:
            raise ValueError(f"未知告警任务: {key}")
        if target.is_running():
            return {"started": False, "msg": "采集批次运行中, 请稍后"}
        threading.Thread(target=target.run_batch, kwargs={"trigger": "manual"},
                         daemon=True).start()
        return {"started": True, "msg": "采集批次已启动"}

    @staticmethod
    def test_dxm_login(patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return DxmOrderService.test_login(patch)

    # ───────────────── 提醒任务 (邮件提醒, 与轮询采集解耦) ─────────────────
    _DXM_REALTIME_KEYS = ["alert_email_enabled", "repeat_red_alert", "alert_mail_to", "subject_prefix"]

    @staticmethod
    def get_reminders() -> List[Dict[str, Any]]:
        """全部提醒任务: 名称/模板/可编辑配置/状态 (与告警任务轮询配置完全解耦)"""
        from server.services.daily_digest_service import DailyDigestService

        cfg = ForwarderDocService.get_config()
        digest_last = get_setting("daily_digest_last", None)
        dxm_status = DxmOrderService.get_status()
        dxm_cfg = DxmOrderService.get_config()
        dxm_last_email = (dxm_status.get("last_log") or {}).get("email_status")
        return [
            {
                "key": "daily_digest",
                "name": "每日定时提醒",
                "icon": "📅",
                "desc": "每天固定时间发送一次汇总提醒邮件, 内容包含两个区块: 店小秘订单预警 (橘/红/超时未发货) + 货代超期未发货告警明细",
                "enabled": bool(cfg.get("email_enabled")),
                "form": REMINDER_FORMS["daily_digest"],
                "config": {
                    "email_enabled": bool(cfg.get("email_enabled")),
                    "digest_time": cfg.get("digest_time") or "08:15",
                    "digest_mail_to": str(get_setting("fwd_doc_digest_mail_to", "") or ""),
                    "subject_prefix": cfg.get("subject_prefix") or "[货代发货提醒]",
                },
                "status": {"last": digest_last if isinstance(digest_last, dict) else None,
                           "next_check": DailyDigestService.next_run_time()},
                "email_note": "发送通道 (SMTP 账号) 复用系统管理 → 邮件通知; 收件人留空时发送给默认收件人",
            },
            {
                "key": "dxm_realtime",
                "name": "店小秘实时预警提醒",
                "icon": "⚡",
                "desc": "采集轮询发现店小秘订单出现红色/超时未发货时, 实时发送单独预警邮件 (可关闭每轮重复提醒)",
                "enabled": bool(dxm_cfg.get("alert_email_enabled")),
                "form": REMINDER_FORMS["dxm_realtime"],
                "config": {k: dxm_cfg.get(k) for k in AlertService._DXM_REALTIME_KEYS},
                "status": {"counts": dxm_status.get("counts", {}), "last_email_status": dxm_last_email},
                "email_note": "发送通道 (SMTP 账号) 复用系统管理 → 邮件通知",
            },
        ]

    @staticmethod
    def save_reminder_config(key: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        """按白名单过滤后保存提醒配置 (digest_mail_to 独立存键, 其余委托各服务)"""
        if key not in REMINDER_WHITELIST:
            raise ValueError(f"未知提醒任务: {key}")
        allowed = set(REMINDER_WHITELIST[key])
        filtered = {k: v for k, v in (patch or {}).items() if k in allowed}
        if key == "daily_digest":
            digest_mail_to = str(filtered.pop("digest_mail_to", "") or "").strip()
            set_setting("fwd_doc_digest_mail_to", digest_mail_to)
            ForwarderDocService.save_config(filtered)
        else:
            DxmOrderService.save_config(filtered)
        for r in AlertService.get_reminders():
            if r["key"] == key:
                return r
        return {}

    @staticmethod
    def test_reminder_email(key: str, patch: Optional[Dict[str, Any]] = None) -> str:
        """发送提醒测试邮件 (表单当前值不落库)"""
        from server.services.daily_digest_service import DailyDigestService

        patch = patch if isinstance(patch, dict) else {}
        if key == "daily_digest":
            override = {"email_enabled": True}
            for k in ("digest_time", "subject_prefix"):
                if patch.get(k):
                    override[k] = patch[k]
            dmt = str(patch.get("digest_mail_to") or "").strip()
            if dmt:
                override["digest_mail_to"] = dmt
            return DailyDigestService.send_test_email(override)
        if key == "dxm_realtime":
            return DxmOrderService.send_test_email(patch)
        raise ValueError(f"未知提醒任务: {key}")

    # ───────────────── 告警中心 ─────────────────
    @staticmethod
    def get_alert_summary() -> Dict[str, Any]:
        """顶部统计: 货代今日告警 / 店小秘黄红超时取消 / 汇总邮件最近发送"""
        today = datetime.now().strftime("%Y-%m-%d")
        conn = get_db_connection()
        try:
            fwd_today = conn.execute(
                "SELECT COUNT(*) c FROM forwarder_ship_alerts WHERE biz_date = ?",
                (today,)).fetchone()["c"]
            fwd_last = conn.execute(
                "SELECT id, biz_date, status, docs_total, docs_ok, docs_failed, alert_rows, "
                "started_at, finished_at FROM forwarder_doc_sync_logs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            dxm_cnt = conn.execute(
                """SELECT
                     SUM(CASE WHEN alert_level = 1 AND order_status NOT LIKE 'Shipped%' THEN 1 ELSE 0 END) yellow,
                     SUM(CASE WHEN alert_level = 2 AND remaining_minutes > 0 THEN 1 ELSE 0 END) red,
                     SUM(CASE WHEN alert_level = 2 AND remaining_minutes <= 0 THEN 1 ELSE 0 END) expired,
                     SUM(CASE WHEN alert_level = -1 THEN 1 ELSE 0 END) cancelled
                   FROM dxm_order_deadlines""").fetchone()
            dxm_last = conn.execute(
                "SELECT id, trigger_type, status, started_at, finished_at, orders_total "
                "FROM dxm_order_sync_logs ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        digest_last = get_setting("daily_digest_last", None)
        return {
            "forwarder": {
                "today_alerts": fwd_today,
                "last_log": dict(fwd_last) if fwd_last else None,
            },
            "dxm": {
                "yellow": dxm_cnt["yellow"] or 0,
                "red": dxm_cnt["red"] or 0,
                "expired": dxm_cnt["expired"] or 0,
                "cancelled": dxm_cnt["cancelled"] or 0,
                "last_log": dict(dxm_last) if dxm_last else None,
            },
            "digest": {"last": digest_last if isinstance(digest_last, dict) else None},
        }

    @staticmethod
    def _forwarder_title(row_json: str, sheet_name: str) -> str:
        try:
            data = json.loads(row_json or "{}")
        except Exception:
            data = {}
        for col in ("产品名称及备注", "国际单号", "订单号", "产品名称"):
            v = str(data.get(col, "") or "").strip()
            if v:
                return v[:60]
        return sheet_name or "货代未发货记录"

    @staticmethod
    def _fmt_remaining(minutes: Any) -> str:
        try:
            m = int(minutes)
        except (TypeError, ValueError):
            return "未知"
        if m is None or m < 0:
            return "未知"
        if m <= 0:
            return "已超时"
        d, rem = divmod(m, 1440)
        h, mi = divmod(rem, 60)
        return f"{d}天{h}小时" if d else (f"{h}小时{mi}分" if h else f"{mi}分钟")

    @staticmethod
    def _query_forwarder(biz_date: Optional[str], keyword: str) -> List[Dict[str, Any]]:
        where, params = ["1=1"], []
        if biz_date:
            where.append("biz_date = ?")
            params.append(biz_date)
        if keyword:
            where.append("(forwarder_name LIKE ? OR link_label LIKE ? OR row_json LIKE ?)")
            kw = f"%{keyword.strip()}%"
            params += [kw, kw, kw]
        wsql = " AND ".join(where)
        conn = get_db_connection()
        try:
            rows = conn.execute(
                f"SELECT * FROM forwarder_ship_alerts WHERE {wsql} "
                "ORDER BY biz_date DESC, days_elapsed DESC LIMIT 2000", params).fetchall()
        finally:
            conn.close()
        items = []
        for r in rows:
            d = dict(r)
            items.append({
                "source": "forwarder",
                "source_name": "货代文档采集",
                "type": "未发货超期",
                "level": 2,
                "title": AlertService._forwarder_title(d.get("row_json", ""), d.get("sheet_name", "")),
                "detail": {"forwarder_name": d.get("forwarder_name", ""),
                           "link_label": d.get("link_label", ""),
                           "sheet_name": d.get("sheet_name", ""),
                           "purchase_date": d.get("purchase_date", ""),
                           "days_elapsed": d.get("days_elapsed", 0)},
                "biz_date": d.get("biz_date", ""),
                "ts": d.get("biz_date", ""),
            })
        return items

    @staticmethod
    def _query_dxm(biz_date: Optional[str], alert_level: Optional[int], keyword: str) -> List[Dict[str, Any]]:
        where, params = ["alert_level != -1", "order_status NOT LIKE 'Shipped%'", "order_status != 'shipped'"], []
        if alert_level is not None:
            where.append("alert_level = ?")
            params.append(int(alert_level))
        if biz_date:
            where.append("deadline_at LIKE ?")
            params.append(f"{biz_date}%")
        if keyword:
            where.append("(order_no LIKE ? OR shop_name LIKE ? OR site LIKE ?)")
            kw = f"%{keyword.strip()}%"
            params += [kw, kw, kw]
        wsql = " AND ".join(where)
        conn = get_db_connection()
        try:
            rows = conn.execute(
                f"SELECT * FROM dxm_order_deadlines WHERE {wsql} "
                "ORDER BY CASE WHEN remaining_minutes < 0 THEN 1 ELSE 0 END, remaining_minutes "
                "LIMIT 2000", params).fetchall()
        finally:
            conn.close()
        now_ts = datetime.now().timestamp()
        items = []
        for r in rows:
            d = dict(r)
            try:
                dl = datetime.strptime(d["deadline_at"], "%Y-%m-%d %H:%M:%S").timestamp()
                remaining = int((dl - now_ts) // 60)
            except Exception:
                remaining = d.get("remaining_minutes", -1)
            level = 2 if remaining <= 0 else (d.get("alert_level") or 0)
            items.append({
                "source": "dxm",
                "source_name": "店小秘订单采集",
                "type": "已超时" if remaining <= 0 else ("红色预警" if level == 2 else "黄色预警"),
                "level": level if level >= 1 else 1,
                "title": d.get("order_no", ""),
                "detail": {"shop_name": d.get("shop_name", ""), "site": d.get("site", ""),
                           "order_status": d.get("order_status", ""),
                           "deadline_at": d.get("deadline_at", ""),
                           "remaining": AlertService._fmt_remaining(remaining)},
                "biz_date": (d.get("deadline_at") or "")[:10],
                "ts": d.get("deadline_at") or d.get("first_seen_at") or "",
            })
        return items

    @staticmethod
    def list_alerts(source: Optional[str] = None, biz_date: Optional[str] = None,
                    alert_level: Optional[int] = None, keyword: str = "",
                    page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """统一告警列表: source=forwarder/dxm/None(合并按时间倒序), 分页"""
        if source == "forwarder":
            items = AlertService._query_forwarder(biz_date, keyword)
        elif source == "dxm":
            items = AlertService._query_dxm(biz_date, alert_level, keyword)
        else:
            items = AlertService._query_forwarder(biz_date, keyword) + \
                AlertService._query_dxm(biz_date, alert_level, keyword)
            items.sort(key=lambda x: x.get("ts") or "", reverse=True)
        total = len(items)
        page = max(1, page)
        page_size = min(200, max(1, page_size))
        start = (page - 1) * page_size
        return {"total": total, "page": page, "page_size": page_size,
                "items": items[start:start + page_size]}
