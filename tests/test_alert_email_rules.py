"""预警邮件规则 (解耦版): ①小时轮询红/超时即时发邮件 ②每日汇总邮件独立任务 (货代区块 + 店小秘8点批次区块)"""
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

tmp = tempfile.mkdtemp()
db_path = Path(tmp) / "test.db"
conn0 = sqlite3.connect(db_path)
conn0.row_factory = sqlite3.Row
conn0.executescript("""
CREATE TABLE dxm_order_deadlines (order_no TEXT PRIMARY KEY, shop_name TEXT, site TEXT,
  order_status TEXT, deadline_at TEXT, remaining_minutes INTEGER, alert_level INTEGER DEFAULT 0,
  first_seen_at TEXT, last_seen_at TEXT, updated_at TEXT, alerted_levels TEXT DEFAULT '');
CREATE TABLE dxm_order_sync_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger_type TEXT DEFAULT 'manual',
  status TEXT DEFAULT 'running', login_status TEXT DEFAULT '', orders_total INTEGER DEFAULT 0,
  alert_yellow INTEGER DEFAULT 0, alert_red INTEGER DEFAULT 0, alert_expired INTEGER DEFAULT 0,
  email_status TEXT DEFAULT '', message TEXT DEFAULT '', duration_ms INTEGER DEFAULT 0,
  started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMP);
CREATE TABLE forwarder_doc_sync_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, biz_date TEXT NOT NULL,
  trigger_type TEXT DEFAULT 'manual', status TEXT DEFAULT 'running', docs_total INTEGER DEFAULT 0,
  docs_ok INTEGER DEFAULT 0, docs_failed INTEGER DEFAULT 0, rows_total INTEGER DEFAULT 0,
  alert_rows INTEGER DEFAULT 0, email_status TEXT DEFAULT '', message TEXT DEFAULT '',
  duration_ms INTEGER DEFAULT 0, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMP);
CREATE TABLE forwarder_ship_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, forwarder_id INTEGER,
  forwarder_name TEXT, link_label TEXT, link_url TEXT, sheet_name TEXT, row_index INTEGER,
  purchase_date TEXT, days_elapsed INTEGER, row_json TEXT, biz_date TEXT);
CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
""")
conn0.commit()
conn0.close()

import server.database as db_mod
import server.services.dxm_order_service as dxm_mod
import server.services.daily_digest_service as dd_mod


def _tmp_conn():
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


# 全部走临时库 (get_setting/set_setting 内部同样调用 server.database.get_db_connection)
db_mod.get_db_connection = _tmp_conn
svc = dxm_mod.DxmOrderService
dd = dd_mod.DailyDigestService
dxm_mod.get_db_connection = _tmp_conn
dd_mod.get_db_connection = _tmp_conn
dd_mod.get_setting = db_mod.get_setting
dd_mod.set_setting = db_mod.set_setting

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + (f"  <- {detail}" if detail and not cond else ""))


import time as _time
now = _time.time()
TODAY = datetime.now().strftime("%Y-%m-%d")


def _od(no, remain_h, shipped=False):
    return {"orderId": no, "orderState": "shipped" if shipped else "pending",
            "orderStatePlatform": "pending", "orderTimeoutTime": int(now + remain_h * 3600),
            "shopPlatform": "Shop", "buyerCountry": "US"}


cfg = {"warn_hours": 24, "danger_hours": 6, "repeat_red_alert": False,
       "alert_email_enabled": True, "alert_mail_to": "a@t.com,b@t.com",
       "subject_prefix": "[预警]", "smtp_host": "", "smtp_user": ""}

sent = []
svc._send_alert_email = staticmethod(lambda c, rows: sent.append(rows) or "sent")

# ══ 场景1: 店小秘即时预警 (红/超时才发, 行为与解耦前一致) ══
print("== 场景1: 店小秘红色即时邮件 ==")
orders = [_od("T1", -2), _od("R1", 3), _od("Y1", 12), _od("S1", 72), _od("SH1", 1, shipped=True)]
stats = svc._store_and_alert(orders, cfg)
check("黄级/安全级不入即时邮件行", all(r["order_no"] != "Y1" and r["order_no"] != "S1" for r in stats["email_rows"]))
check("超时+红 入即时邮件行", {r["order_no"] for r in stats["email_rows"]} == {"T1", "R1"}, str(stats["email_rows"]))
check("黄色计数仍统计 (页面展示)", stats["alert_yellow"] == 1 and stats["alert_red"] == 1 and stats["alert_expired"] == 1)

sent.clear()
stats2 = svc._store_and_alert([_od("Y1", 3), _od("S1", 72)], cfg)   # Y1 黄→红
check("黄翻红后进即时邮件", any(r["order_no"] == "Y1" for r in stats2["email_rows"]))
sent.clear()
stats3 = svc._store_and_alert([_od("S1", 72), _od("Y2", 12), _od("Y3", 20)], cfg)
check("无红时轮询不即时邮件", len(sent) == 0 and stats3["email_status"] == "disabled")
sent.clear()
svc._store_and_alert([_od("R1", 3)], cfg)   # 红级重复, repeat_red_alert=False → 不再发
check("红级未开重复提醒不重发", len(sent) == 0)

# ══ 场景2: 汇总邮件·货代文档采集区块 ══
print("== 场景2: 汇总·货代区块 ==")
c = _tmp_conn()
c.execute("INSERT INTO forwarder_doc_sync_logs (biz_date, status, docs_total, docs_ok, docs_failed, message) "
          "VALUES (?, 'success', 3, 3, 0, '全部文档采集成功')", (TODAY,))
c.execute("INSERT INTO forwarder_ship_alerts (forwarder_id, forwarder_name, link_label, link_url, sheet_name, "
          "row_index, purchase_date, days_elapsed, row_json, biz_date) VALUES "
          "(1, '甲货代', '登记表', 'http://x', '发货数据', 1, '2026-09-01', 24, ?, ?)",
          ('{"产品名称及备注": "测试商品A", "订单号": "PO-1"}', TODAY))
c.commit(); c.close()

html, meta = dd.forwarder_section(TODAY)
check("货代成功批次 → 区块含采集统计", "今日采集文档 <b>3</b> 个" in html)
check("货代区块含告警明细 (货代名/商品/订单号)", "甲货代" in html and "测试商品A" in html and "PO-1" in html)
check("货代区块 meta 告警行数=1", meta["alerts"] == 1 and meta["ok"] is True)

c = _tmp_conn()
c.execute("DELETE FROM forwarder_doc_sync_logs WHERE biz_date = ?", (TODAY,))
c.commit(); c.close()
html2, meta2 = dd.forwarder_section(TODAY)
check("今日无批次 → 未采集到", "未采集到" in html2 and meta2["ok"] is False)
c = _tmp_conn()
c.execute("INSERT INTO forwarder_doc_sync_logs (biz_date, status, message) VALUES (?, 'failed', '登录超时')", (TODAY,))
c.commit(); c.close()
html3, _ = dd.forwarder_section(TODAY)
check("批次失败 → 未采集到含原因", "未采集到" in html3 and "failed" in html3 and "登录超时" in html3)

# ══ 场景3: 汇总邮件·店小秘 8 点批次区块 (橘色+红色都发) ══
print("== 场景3: 汇总·店小秘8点批次区块 ==")
html4, meta4 = dd.dxm_section(TODAY)
check("无 8 点批次 → 未采集到", "未采集到" in html4 and meta4["ok"] is False)

c = _tmp_conn()
c.execute("INSERT INTO dxm_order_sync_logs (trigger_type, status, orders_total, started_at) "
          "VALUES ('scheduled', 'success', 120, ?)", (f"{TODAY} 09:01:10",))   # 9点批次 → 不算8点那次
c.commit(); c.close()
html5, meta5 = dd.dxm_section(TODAY)
check("仅 9 点批次 → 仍判未采集到 (严格 8 点窗口)", "未采集到" in html5 and meta5["ok"] is False)

c = _tmp_conn()
c.execute("INSERT INTO dxm_order_sync_logs (trigger_type, status, orders_total, started_at) "
          "VALUES ('scheduled', 'success', 120, ?)", (f"{TODAY} 08:00:41",))   # 8点批次
c.commit(); c.close()
html6, meta6 = dd.dxm_section(TODAY)
check("8 点批次 → 橘色+红色均入邮件", "Y1" in html6 and "R1" in html6 and "T1" in html6
      and "Y2" in html6 and "Y3" in html6, str(meta6))
check("已发货/安全单不入汇总邮件", "S1" not in html6 and "SH1" not in html6)
check("区块标注橘色与红色计数", "橘色预警 <b style='color:#d97706;'>2</b>" in html6
      and "红色/超时 <b style='color:#dc2626;'>3</b>" in html6, str(meta6))
check("meta 统计正确", meta6["ok"] is True and meta6["yellow"] == 2 and meta6["red"] == 3 and meta6["alert_rows"] == 5)

# ══ 场景4: 汇总邮件组装与发送编排 ══
print("== 场景4: 汇总组装/调度编排 ==")
fwd_html, _ = dd.forwarder_section(TODAY)
dxm_html, _ = dd.dxm_section(TODAY)
digest = dd._build_digest_html(TODAY, fwd_html, dxm_html)
check("汇总邮件含两个区块标题", "🚢 货代文档采集" in digest and "📦 店小秘订单预警" in digest)

# 调度: 未开启开关 → 不触发
dd_mod.set_setting("fwd_doc_email_enabled", False)
check("汇总邮件开关关闭 → 不触发", dd.maybe_trigger_scheduled() is False)
# 调度: 发送时间未到 (23:59) → 不触发
dd_mod.set_setting("fwd_doc_email_enabled", True)
dd_mod.set_setting("fwd_doc_digest_time", "23:59")
check("未到发送时间 → 不触发", dd.maybe_trigger_scheduled() is False)
# 调度: 到期 (00:00) + 当天未发 → 触发, 且 send_digest 被同步执行并记录
dd_mod.set_setting("fwd_doc_digest_time", "00:00")
dd_mod.set_setting("fwd_doc_mail_to", ["a@t.com"])
fake_send = []
dd._send_email = staticmethod(lambda cfg: fake_send.append(1) or "sent")


class _FakeThread:
    def __init__(self, target=None, kwargs=None, daemon=None):
        self._t, self._k = target, kwargs or {}

    def start(self):
        self._t(**self._k)


from threading import Thread as _RealThread   # noqa: E402
dd_mod.threading.Thread = _FakeThread
check("到期且未发 → 触发", dd.maybe_trigger_scheduled() is True and fake_send == [1])
dd_mod.threading.Thread = _RealThread
last = dd_mod.get_setting("daily_digest_last", None)
check("发送后记录 daily_digest_last", isinstance(last, dict) and last.get("date") == TODAY and last.get("status") == "sent")
check("当天已发 → 不再触发", dd.maybe_trigger_scheduled() is False)

# send_digest: 未配置收件人 → failed 且记录
dd_mod.set_setting("daily_digest_last", None)
dd_mod.set_setting("fwd_doc_mail_to", "")
status = dd.send_digest(trigger="manual")
check("未配置收件人 → failed", status.startswith("failed"))
check("失败也记录 daily_digest_last", (dd_mod.get_setting("daily_digest_last") or {}).get("status", "").startswith("failed"))

print(f"\n结果: PASS {len(PASS)} / FAIL {len(FAIL)}")
sys.exit(1 if FAIL else 0)
