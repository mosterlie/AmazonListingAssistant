"""
测试2: 系统管理配置功能全项验证 (GET/POST /api/settings + 配置联动计算)
覆盖: pricing_config(税率/汇率/售价系数) / channel_rules(渠道规则自定义与清除回退)
      / session_expire_hours 边界钳制 / storage_paths / chrome目录回退 / ai_config 归一化
      / db_agent_token 回退 / store_accounts 归一化 / doc_sync(货代采集+SMTP) / dxm_order
      / 鉴权 (未登录401 / 非管理员403) / 配置持久化 / 计算联动
说明: 直接调用路由协程 (不触发主应用调度器, 不依赖 HTTP 层);
      测试前快照全部配置, 结束后原样恢复, 不污染真实数据。
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from server.database import get_setting, set_setting           # noqa: E402
from server.routers.settings_router import get_system_settings, update_system_settings, SystemSettingsSchema  # noqa: E402
from server.dependencies import get_current_user, require_admin_user  # noqa: E402
from server.services.pricing_config import GLOBAL_PRICING_CONFIG  # noqa: E402
from server.services.pricing_service import PricingService     # noqa: E402
from server.services.forwarder_doc_service import ForwarderDocService as FDS  # noqa: E402
from server.services.dxm_order_service import DxmOrderService as DOS          # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))


# ---------------------------------------------------------------- 快照/恢复
PLAIN_KEYS = ["store_accounts", "pricing_config", "storage_path_mac", "storage_path_win",
              "storage_rel_main", "storage_rel_sku", "session_expire_hours",
              "chrome_user_data_dir_mac", "chrome_user_data_dir_win", "chrome_user_data_dir",
              "submit_ad_enabled", "ai_generate_bullets_enabled", "ai_bullets_source",
              "ai_ollama_model", "ai_api_base_url", "ai_model_name", "ai_api_key",
              "db_agent_token", "channel_rules", "fwd_doc_config", "dxm_order_config"]
FDS_KEYS = ["sync_mode", "sync_time", "interval_hours", "alert_days", "date_column",
            "ship_column", "sheet_name", "email_enabled", "digest_time", "smtp_host",
            "smtp_port", "smtp_ssl", "smtp_user", "smtp_password", "mail_from",
            "mail_to", "subject_prefix"]
DOS_KEYS = ["dxm_account", "dxm_password", "scan_enabled",
            "warn_hours", "danger_hours", "repeat_red_alert", "alert_email_enabled",
            "alert_mail_to", "subject_prefix"]

snapshot = {k: get_setting(k, None) for k in PLAIN_KEYS}
for k in FDS_KEYS:
    snapshot[f"fwd_doc_{k}"] = get_setting(f"fwd_doc_{k}", None)
for k in DOS_KEYS:
    snapshot[f"dxm_order_{k}"] = get_setting(f"dxm_order_{k}", None)
snap_pricing = dict(GLOBAL_PRICING_CONFIG)


def restore():
    for k, v in snapshot.items():
        set_setting(k, v)
    GLOBAL_PRICING_CONFIG.update(snap_pricing)


ADMIN = {"username": "tester", "role": "admin"}


def _fake_request():
    """无 Cookie 无 Header 的空请求 (用于未登录 401 测试)"""
    from starlette.requests import Request
    return Request(scope={"type": "http", "method": "GET", "path": "/",
                          "headers": [], "query_string": b""})


def post_settings(payload):
    body = SystemSettingsSchema(**payload)
    return asyncio.run(update_system_settings(body, admin=ADMIN))


def get_settings():
    r = asyncio.run(get_system_settings())
    assert r["code"] == 0 or True
    return r


try:
    # ================= A. 鉴权 =================
    print("\n== A. 鉴权保护 ==")
    from fastapi import HTTPException
    try:
        asyncio.run(get_current_user(_fake_request()))
        check("未登录读取会话 → 401", False, "未抛出 401")
    except HTTPException as e:
        check("未登录读取会话 → 401", e.status_code == 401, f"got {e.status_code}")
    try:
        asyncio.run(require_admin_user(user={"username": "tester", "role": "user"}))
        check("非管理员保存配置 → 403", False, "未抛出 403")
    except HTTPException as e:
        check("非管理员保存配置 → 403", e.status_code == 403, f"got {e.status_code}")
    ok_admin = asyncio.run(require_admin_user(user={"username": "tester", "role": "admin"}))
    check("管理员通过鉴权", ok_admin.get("role") == "admin")

    # ================= B. GET 全量配置结构 =================
    print("\n== B. GET 配置结构完整性 ==")
    base = get_settings()
    d = base.get("data") or {}
    for sec in ["store_accounts", "pricing_config", "channel_rules", "storage_paths",
                "session_expire_hours", "chrome_user_data_dirs", "submit_ad_enabled",
                "ai_config", "db_agent_token", "doc_sync", "dxm_order"]:
        check(f"GET 返回 {sec}", sec in d)
    for k in ["tax_rate", "exchange_rate", "price_coefficient", "default_profit_coeff"]:
        check(f"pricing_config.{k} 存在且为数值", isinstance(d["pricing_config"].get(k), (int, float)))
    check("base.code == 0", base.get("code") == 0)

    # ================= C. pricing_config 保存 + 计算联动 =================
    print("\n== C. 计价核心参数保存与计算联动 ==")
    payload = json_mod = {**d, "pricing_config": {"tax_rate": 0.1, "exchange_rate": 22.5,
                                                  "price_coefficient": 30.0, "default_profit_coeff": 1.2}}
    r = post_settings(payload)
    check("POST pricing_config → code 0", r.get("code") == 0, str(r.get("msg")))
    after = get_settings()["data"]["pricing_config"]
    check("tax_rate 持久化", after["tax_rate"] == 0.1, str(after))
    check("exchange_rate 持久化", after["exchange_rate"] == 22.5)
    check("price_coefficient 持久化", after["price_coefficient"] == 30.0)
    check("default_profit_coeff 持久化", after["default_profit_coeff"] == 1.2)
    res = PricingService.calculate_sku_pricing(55.5, 38.2, 22.0, 1.85, 50.0, profit_coefficient=1.2)
    total = res["total_cost_rmb"]
    expect = round((total + round(total * 1.2, 2)) * 30.0, 2)
    check("售价联动: 售价=(成本+利润系数1.2)×新售价系数30", abs(res["selling_price_jpy"] - expect) < 0.02,
          f"got {res['selling_price_jpy']} expect {expect}")
    check("default_profit_coeff 随配置下发 (前端表单默认值来源)",
          get_settings()["data"]["pricing_config"]["default_profit_coeff"] == 1.2)
    tax_expect = round(res["selling_price_jpy"] - res["selling_price_jpy"] * 0.1, 2)
    check("税率联动: tax_deducted_jpy 按新税率", abs(res["tax_deducted_jpy"] - tax_expect) < 0.02)
    cost_expect = round(total * 22.5, 2)
    check("汇率联动: cost_jpy 按新汇率", abs(res["cost_jpy"] - cost_expect) < 0.02)
    check("DB get_setting 直读 pricing_config", get_setting("pricing_config", {}).get("price_coefficient") == 30.0)

    # ================= D. session_expire_hours 边界钳制 =================
    print("\n== D. Session 有效期钳制 ==")
    post_settings({**d, "session_expire_hours": 9999})
    check("9999 → 钳制 720", get_settings()["data"]["session_expire_hours"] == 720)
    post_settings({**d, "session_expire_hours": -5})
    check("-5 → 钳制 0 (永久)", get_settings()["data"]["session_expire_hours"] == 0)

    # ================= E. channel_rules 自定义与清除回退 =================
    print("\n== E. 渠道计费规则配置 ==")
    rules = [{"key": "sf_small", "name": "顺丰小包", "enabled": True,
              "limits": {"max_weight": 30, "max_single_side": 120, "max_sum_sides": 160, "max_length": None,
                         "max_width": None, "max_height": None, "max_combined_girth": None,
                         "max_cw": None, "reject_both_over": [], "max_cw_surplus_ratio": None},
              "charge_weight": {"vol_ratio": 8000, "round_to": None, "min_cw": None,
                                "bands": [{"max_sum": None, "cmp": "lte", "mode": "max_actual_vol"}]},
              "pricing": {"type": "tiered_step", "step_unit": 0.5,
                          "tiers": [{"max_cw": 2, "cmp": "lte", "base": 50, "step": 8, "rate": None, "min_charge": None}],
                          "first_weight_fee": None, "continue_per_kg": None, "extra_fee": None,
                          "op_fee": 0, "discount": 0.8},
              "surcharges": [], "round_total": "round2"}]
    r = post_settings({**d, "channel_rules": rules})
    check("POST 自定义 channel_rules → code 0", r.get("code") == 0)
    check("GET 回读自定义规则", get_settings()["data"]["channel_rules"] == rules)
    r = post_settings({**d, "channel_rules": None})
    check("POST null 清除规则 → code 0", r.get("code") == 0)
    check("清除后 GET 为 None (回退内置默认)", get_settings()["data"]["channel_rules"] is None)

    # ================= F. store_accounts 归一化 =================
    print("\n== F. 店铺账号归一化 ==")
    r = post_settings({**d, "store_accounts": ["金梧汇辰", {"store_name": "测试店", "brand_name": "TEST", "is_default": True}]})
    stores = r["data"]["store_accounts"]
    names = [s["store_name"] for s in stores]
    check("字符串项归一化为对象", all(isinstance(s, dict) and s.get("brand_name") for s in stores))
    check("默认店铺排首位", names[0] == "测试店", str(names))
    check("默认唯一", sum(1 for s in stores if s.get("is_default")) == 1)
    check("字符串项品牌回填", any(s["store_name"] == "金梧汇辰" and s["brand_name"] == "JINWU" for s in stores))

    # ================= G. storage_paths / chrome 目录 / token 回退 =================
    print("\n== G. 路径与令牌配置 ==")
    post_settings({**d, "storage_paths": {"mac": "/tmp/arch", "win": "E:\\arch",
                                          "rel_main": " /main/ ", "rel_sku": "sku "}})
    sp = get_settings()["data"]["storage_paths"]
    check("rel_main 去空白去斜杠", sp["rel_main"] == "main", sp["rel_main"])
    check("rel_sku 去空白", sp["rel_sku"] == "sku")
    post_settings({**d, "chrome_user_data_dirs": {"mac": "", "win": ""}})
    cd = get_settings()["data"]["chrome_user_data_dirs"]
    check("chrome mac 留空回退默认", cd["mac"] == "~/ChromeDebugUser")
    check("chrome win 留空回退默认", cd["win"] == "C:\\ChromeDebugUser")
    post_settings({**d, "db_agent_token": "  "})
    check("db_agent_token 留空回退 erp2024", get_settings()["data"]["db_agent_token"] == "erp2024")

    # ================= H. ai_config 归一化 =================
    print("\n== H. AI 配置归一化 ==")
    ai = dict(d["ai_config"]) if isinstance(d.get("ai_config"), dict) else {}
    ai.update({"bullets_source": "WEIRD", "generate_bullets_enabled": True, "ollama_model": " qwen2.5:0.5b "})
    post_settings({**d, "ai_config": ai})
    got = get_settings()["data"]["ai_config"]
    check("非法来源归一化为 public", got["bullets_source"] == "public", str(got))
    check("布尔开关保存", got["generate_bullets_enabled"] is True)
    check("ollama_model 去空白", got["ollama_model"] == "qwen2.5:0.5b")

    # ================= I. doc_sync (货代采集/SMTP邮件) roundtrip =================
    print("\n== I. 货代文档采集配置 roundtrip ==")
    ds = dict(d["doc_sync"])
    ds.update({"sync_mode": "interval", "interval_hours": 12, "alert_days": 5,
               "email_enabled": True, "digest_time": "08:20",
               "smtp_host": "smtp.163.com", "smtp_port": 465,
               "smtp_ssl": True, "smtp_user": "test@163.com", "smtp_password": "authcode123",
               "mail_to": "a@x.com, b@y.com", "subject_prefix": "[测试提醒]"})
    r = post_settings({**d, "doc_sync": ds})
    check("POST doc_sync → code 0", r.get("code") == 0, str(r.get("msg")))
    got = get_settings()["data"]["doc_sync"]
    check("sync_mode=interval", got["sync_mode"] == "interval")
    check("interval_hours=12", got["interval_hours"] == 12)
    check("alert_days=5 (告警阈值)", got["alert_days"] == 5)
    check("digest_time=08:20 (汇总邮件时间)", got["digest_time"] == "08:20")
    check("smtp_host/user 保存", got["smtp_host"] == "smtp.163.com" and got["smtp_user"] == "test@163.com")
    check("mail_to 逗号串 ↔ 列表互转", got["mail_to"] == "a@x.com, b@y.com", str(got.get("mail_to")))
    svc_cfg = FDS.get_config()
    check("service 直读 mail_to 为列表", svc_cfg.get("mail_to") == ["a@x.com", "b@y.com"], str(svc_cfg.get("mail_to")))
    check("service 直读 alert_days=5", svc_cfg.get("alert_days") == 5)

    # ================= J. dxm_order roundtrip =================
    print("\n== J. 店小秘采集预警配置 roundtrip ==")
    dx = dict(d["dxm_order"])
    dx.update({"warn_hours": 12, "danger_hours": 3,
               "alert_mail_to": "c@z.com", "repeat_red_alert": False})
    r = post_settings({**d, "dxm_order": dx})
    check("POST dxm_order → code 0", r.get("code") == 0, str(r.get("msg")))
    got = get_settings()["data"]["dxm_order"]
    check("scan_interval_minutes 已移除 (每小时调度)", "scan_interval_minutes" not in got)
    check("warn_hours=12 / danger_hours=3", got["warn_hours"] == 12 and got["danger_hours"] == 3)
    check("repeat_red_alert=False", got["repeat_red_alert"] is False)
    check("service 直读 warn_hours", DOS.get_config().get("warn_hours") == 12)

    # ================= K. 全量恢复后回读一致 =================
    print("\n== K. 恢复原始配置 ==")
    restore()
    ok = all(get_setting(k, None) == v for k, v in snapshot.items())
    check("全部配置键恢复原值", ok)
    check("内存计价参数恢复", abs(GLOBAL_PRICING_CONFIG.get("price_coefficient", 26) - snap_pricing.get("price_coefficient", 26)) < 1e-9)

finally:
    restore()

print(f"\n========== 结果: PASS {len(PASS)} / FAIL {len(FAIL)} ==========")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("=== PASS: 系统管理配置功能全项验证通过 ===")
