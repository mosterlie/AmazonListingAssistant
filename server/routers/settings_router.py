"""
系统管理与全局配置 REST API 路由
包含店铺账号列表维护、Calcfee 物流税率/汇率/售价系数等核心参数配置
"""
import sys
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from server.database import get_setting, set_setting, delete_setting, get_settings_by_prefix
from server.services.pricing_config import get_global_pricing_config, GLOBAL_PRICING_CONFIG
from server.dependencies import require_admin_user

router = APIRouter(prefix="/api/settings", tags=["System Settings"])


class PricingConfigSchema(BaseModel):
    tax_rate: float = Field(0.17, description="日本消费税/平台税率 (默认 0.17)")
    exchange_rate: float = Field(23.0, description="日元兑人民币汇率 (默认 23.0)")
    price_coefficient: float = Field(26.0, description="日元售价转换系数 (默认 26.0)")
    default_profit_coeff: float = Field(1.0, description="默认利润系数 (默认 1.0)")


class StoragePathsSchema(BaseModel):
    mac: str = Field("/Users/gx/Desktop/products", description="Mac 本地归档存储主绝对目录")
    win: str = Field("D:\\products", description="Windows 本地归档存储主绝对目录")
    rel_main: str = Field("main", description="主图/附图相对子文件夹路径 (默认 main)")
    rel_sku: str = Field("sku", description="SKU图片相对子文件夹路径 (默认 sku)")


class ChromeUserDataDirsSchema(BaseModel):
    mac: str = Field("~/ChromeDebugUser", description="Mac 端 Chrome 9222 自动化专属用户数据目录")
    win: str = Field("C:\\ChromeDebugUser", description="Windows 端 Chrome 9222 自动化专属用户数据目录")


class AiConfigSchema(BaseModel):
    generate_bullets_enabled: bool = Field(False, description="是否5点描述通过大模型生成: True=大模型生成 / False=不使用大模型生成 (默认否)")
    bullets_source: str = Field("public", description="五点描述生成来源: local=本地 Ollama / public=公共大模型 API")
    ollama_model: str = Field("qwen2.5:1.5b-instruct-q4_K_M", description="本地 Ollama 模型名称 (标题翻译/商品标识/五点描述均可用)")
    api_base_url: str = Field("https://api.deepseek.com", description="公共大模型 API Base URL (OpenAI 兼容)")
    model_name: str = Field("deepseek-v4-flash", description="公共大模型名称")
    api_key: str = Field("sk-44d5b47efaa64e3a967efc0c8fc05ce2", description="公共大模型 API Key")


class EmailNotifySchema(BaseModel):
    """SMTP 发信通道 + 默认收件人 (存 fwd_doc_* 扁平键)。
    提醒规则 (每日定时提醒/实时提醒的开关、时间、独立收件人、主题前缀) 已迁往「提醒任务」页 (/reminders)。"""
    smtp_host: str = Field("smtp.qq.com", description="SMTP 服务器")
    smtp_port: int = Field(465, description="SMTP 端口")
    smtp_ssl: bool = Field(True, description="是否 SSL")
    smtp_user: str = Field("", description="SMTP 账号")
    smtp_password: str = Field("", description="SMTP 授权码 (非登录密码)")
    mail_from: str = Field("", description="发件人 (留空用 smtp_user)")
    mail_to: str = Field("", description="默认收件人 (逗号分隔; 各提醒任务未配置独立收件人时使用)")


class StoreBrandItemSchema(BaseModel):
    store_name: str = Field(..., min_length=1, description="店铺账号名称")
    brand_name: str = Field(..., min_length=1, description="对应品牌名称 (1对1必填)")
    is_default: Optional[bool] = Field(False, description="是否为默认店铺 (只能设一个)")


class SystemSettingsSchema(BaseModel):
    store_accounts: List[Union[StoreBrandItemSchema, Dict[str, Any], str]] = Field(default_factory=list, description="店铺账号与品牌映射列表")
    pricing_config: PricingConfigSchema = Field(default_factory=PricingConfigSchema, description="物流与计价核心参数")
    storage_paths: StoragePathsSchema = Field(default_factory=StoragePathsSchema, description="本地归档存储目录")
    session_expire_hours: Optional[float] = Field(1.0, description="登录 Session 有效时长 (小时，默认 1.0h)")
    chrome_user_data_dirs: ChromeUserDataDirsSchema = Field(default_factory=ChromeUserDataDirsSchema, description="Chrome 9222 自动化专属用户数据目录 (mac/win 分平台配置)")
    submit_ad_enabled: bool = Field(False, description="自动投放是否提交广告 (True=每批录入后自动点击提交并确认; False=停在提交前待人工确认)")
    ai_config: AiConfigSchema = Field(default_factory=AiConfigSchema, description="AI 大模型配置 (自动生成五点描述)")
    db_agent_token: Optional[str] = Field("", description="桌面上件助手远程通道令牌 (内嵌图片服务 X-DB-Token 校验, 留空使用默认 erp2024)")
    email_notify: EmailNotifySchema = Field(default_factory=EmailNotifySchema, description="邮件通知配置 (汇总邮件+各预警邮件共用 SMTP 发信通道)")


def normalize_store_accounts(raw_stores: Any) -> List[Dict[str, Any]]:
    """将历史字符串数组或对象数组规范化为标准的 [{store_name, brand_name, is_default}] 列表，确保全局唯一默认店铺，并将默认项排在首位"""
    default_stores = [
        {"store_name": "金梧汇辰", "brand_name": "JINWU", "is_default": True},
        {"store_name": "店小秘通用测试", "brand_name": "DXM", "is_default": False}
    ]
    if not raw_stores or not isinstance(raw_stores, list):
        return default_stores

    known_default_brands = {
        "金梧汇辰": "JINWU",
        "店小秘通用测试": "DXM",
        "飞行的高压锅": "FLYCOOKER"
    }

    normalized = []
    seen = set()
    has_default = False

    for item in raw_stores:
        is_def = False
        if isinstance(item, str):
            s_name = item.strip()
            b_name = known_default_brands.get(s_name, s_name)
        elif isinstance(item, dict):
            s_name = (item.get("store_name") or item.get("store") or "").strip()
            b_name = (item.get("brand_name") or item.get("brand") or "").strip()
            is_def = bool(item.get("is_default", False))
            if not b_name:
                b_name = known_default_brands.get(s_name, s_name)
        elif hasattr(item, "store_name"):
            s_name = item.store_name.strip()
            b_name = item.brand_name.strip()
            is_def = bool(getattr(item, "is_default", False))
            if not b_name:
                b_name = known_default_brands.get(s_name, s_name)
        else:
            continue

        if s_name and s_name not in seen:
            seen.add(s_name)
            if is_def and not has_default:
                has_default = True
            else:
                is_def = False
            normalized.append({"store_name": s_name, "brand_name": b_name, "is_default": is_def})

    # 若没有任何项标记为默认，且列表非空，则默认将第1个标记为默认
    if normalized and not any(x.get("is_default") for x in normalized):
        normalized[0]["is_default"] = True

    # 将默认项排序在最前面展示
    default_item = next((x for x in normalized if x.get("is_default")), None)
    if default_item:
        other_items = [x for x in normalized if not x.get("is_default")]
        normalized = [default_item] + other_items

    return normalized if normalized else default_stores


@router.get("")
async def get_system_settings():
    """获取所有系统配置（店铺账号与品牌、物流计价参数、本地归档存储绝对/相对目录、Session 有效期等）"""
    try:
        raw_stores = get_setting("store_accounts", [
            {"store_name": "金梧汇辰", "brand_name": "JINWU"},
            {"store_name": "店小秘通用测试", "brand_name": "DXM"}
        ])
        stores = normalize_store_accounts(raw_stores)
        pricing = get_global_pricing_config()
        storage_mac = get_setting("storage_path_mac", "/Users/gx/Desktop/products")
        storage_win = get_setting("storage_path_win", "D:\\products")
        rel_main = get_setting("storage_rel_main", "main")
        rel_sku = get_setting("storage_rel_sku", "sku")
        session_exp = float(get_setting("session_expire_hours", 1.0))
        # Chrome 9222 用户数据目录 (mac/win 分平台配置; 留空回退平台默认)
        chrome_dir = {
            "mac": (get_setting("chrome_user_data_dir_mac", "") or "").strip() or "~/ChromeDebugUser",
            "win": (get_setting("chrome_user_data_dir_win", "") or "").strip() or "C:\\ChromeDebugUser"
        }
        # 自动投放是否提交广告 (默认否: 停在提交前待人工确认)
        submit_ad_enabled = bool(get_setting("submit_ad_enabled", False))
        # AI 大模型配置 (是否生成五点描述 + 五点描述生成来源 + 本地 Ollama 模型 + 公共 API)
        generate_bullets_enabled = bool(get_setting("ai_generate_bullets_enabled", False))
        bullets_source = (get_setting("ai_bullets_source", "") or "").strip().lower()
        if bullets_source not in ("local", "public"):
            bullets_source = "public"
        ai_config = {
            "generate_bullets_enabled": generate_bullets_enabled,
            "bullets_source": bullets_source,
            "ollama_model": (get_setting("ai_ollama_model", "") or "").strip() or "qwen2.5:1.5b-instruct-q4_K_M",
            "api_base_url": (get_setting("ai_api_base_url", "") or "").strip() or "https://api.deepseek.com",
            "model_name": (get_setting("ai_model_name", "") or "").strip() or "deepseek-v4-flash",
            "api_key": (get_setting("ai_api_key", "") or "").strip() or "sk-44d5b47efaa64e3a967efc0c8fc05ce2"
        }
        # 桌面上件助手远程通道令牌 (原 db_agent 8765, 现已内嵌于本服务同一端口)
        db_agent_token = (get_setting("db_agent_token", "") or "").strip() or "erp2024"
        # 邮件通知配置 (SMTP 通道 + 默认收件人; 提醒规则在「提醒任务」页, mail_to 存列表, 展示为逗号串)
        from server.services.forwarder_doc_service import ForwarderDocService as _FDS
        _en = _FDS.get_config()
        email_notify = {k: _en.get(k) for k in
                        ("smtp_host", "smtp_port", "smtp_ssl", "smtp_user", "smtp_password", "mail_from")}
        email_notify["mail_to"] = ", ".join(_en.get("mail_to") or [])

        return {
            "code": 0,
            "msg": "success",
            "data": {
                "store_accounts": stores,
                "pricing_config": {
                    "tax_rate": pricing.get("tax_rate", 0.17),
                    "exchange_rate": pricing.get("exchange_rate", 23.0),
                    "price_coefficient": pricing.get("price_coefficient", 26.0),
                    "default_profit_coeff": pricing.get("default_profit_coeff", 1.0)
                },
                "channel_rules": _aggregate_channel_rules(),
                "storage_paths": {
                    "mac": storage_mac,
                    "win": storage_win,
                    "rel_main": rel_main,
                    "rel_sku": rel_sku
                },
                "session_expire_hours": session_exp,
                "chrome_user_data_dirs": chrome_dir,
                "submit_ad_enabled": submit_ad_enabled,
                "ai_config": ai_config,
                "db_agent_token": db_agent_token,
                "email_notify": email_notify
            }
        }
    except Exception as e:
        return {"code": 500, "msg": f"获取配置异常: {str(e)}", "data": None}


@router.post("")
async def update_system_settings(payload: SystemSettingsSchema, admin: Dict[str, Any] = Depends(require_admin_user)):
    """保存并更新系统配置 (仅管理员)"""
    try:
        # 1. 规范化并保存店铺与品牌映射列表 (1对1必填校验)
        stores = normalize_store_accounts(payload.store_accounts)
        for s in stores:
            if not s.get("store_name") or not s.get("brand_name"):
                raise HTTPException(status_code=400, detail="店铺名称和对应品牌均为必填项！")

        set_setting("store_accounts", stores)

        # 2. 保存物流与计价核心参数
        pricing_dict = {
            "tax_rate": float(payload.pricing_config.tax_rate),
            "exchange_rate": float(payload.pricing_config.exchange_rate),
            "price_coefficient": float(payload.pricing_config.price_coefficient),
            "default_profit_coeff": float(payload.pricing_config.default_profit_coeff)
        }
        set_setting("pricing_config", pricing_dict)

        # 3. 保存本地归档存储目录 (绝对路径与相对子文件夹路径)
        mac_path = (payload.storage_paths.mac or "/Users/gx/Desktop/products").strip()
        win_path = (payload.storage_paths.win or "D:\\products").strip()
        rel_main = (payload.storage_paths.rel_main or "main").strip().strip("/\\") or "main"
        rel_sku = (payload.storage_paths.rel_sku or "sku").strip().strip("/\\") or "sku"
        set_setting("storage_path_mac", mac_path)
        set_setting("storage_path_win", win_path)
        set_setting("storage_rel_main", rel_main)
        set_setting("storage_rel_sku", rel_sku)

        # 4. 保存 Session 过期时长 (0 表示永久有效)
        session_exp = float(payload.session_expire_hours) if payload.session_expire_hours is not None else 1.0
        session_exp = max(0.0, min(720.0, session_exp))
        set_setting("session_expire_hours", session_exp)

        # 5. 保存 Chrome 9222 自动化用户数据目录 (mac/win 分平台; 留空回退平台默认)
        default_mac, default_win = "~/ChromeDebugUser", "C:\\ChromeDebugUser"
        chrome_mac = (payload.chrome_user_data_dirs.mac or "").strip() or default_mac
        chrome_win = (payload.chrome_user_data_dirs.win or "").strip() or default_win
        set_setting("chrome_user_data_dir_mac", chrome_mac)
        set_setting("chrome_user_data_dir_win", chrome_win)
        # 同步旧单字段 (兼容历史读取方: 当前平台对应的值)
        set_setting("chrome_user_data_dir", chrome_mac if sys.platform == "darwin" else chrome_win)
        chrome_dir = {"mac": chrome_mac, "win": chrome_win}

        # 6. 保存自动投放是否提交广告 (默认否)
        submit_ad_enabled = bool(payload.submit_ad_enabled)
        set_setting("submit_ad_enabled", submit_ad_enabled)

        # 7. 保存 AI 大模型配置 (是否生成五点描述 + 来源: local=本地 Ollama / public=公共 API)
        ai = payload.ai_config
        generate_bullets_enabled = bool(ai.generate_bullets_enabled)
        set_setting("ai_generate_bullets_enabled", generate_bullets_enabled)
        source = (ai.bullets_source or "").strip().lower()
        if source not in ("local", "public"):
            source = "public"
        set_setting("ai_bullets_source", source)
        set_setting("ai_ollama_model", (ai.ollama_model or "").strip() or "qwen2.5:1.5b-instruct-q4_K_M")
        set_setting("ai_api_base_url", (ai.api_base_url or "").strip() or "https://api.deepseek.com")
        set_setting("ai_model_name", (ai.model_name or "").strip() or "deepseek-v4-flash")
        set_setting("ai_api_key", (ai.api_key or "").strip())
        ai_config = {
            "generate_bullets_enabled": generate_bullets_enabled,
            "bullets_source": source,
            "ollama_model": (ai.ollama_model or "").strip() or "qwen2.5:1.5b-instruct-q4_K_M",
            "api_base_url": (ai.api_base_url or "").strip() or "https://api.deepseek.com",
            "model_name": (ai.model_name or "").strip() or "deepseek-v4-flash",
            "api_key": (ai.api_key or "").strip()
        }

        # 8. 保存桌面上件助手远程通道令牌 (内嵌图片服务 X-DB-Token 校验; 留空回退默认值)
        db_agent_token = (payload.db_agent_token or "").strip() or "erp2024"
        set_setting("db_agent_token", db_agent_token)

        # 9. 保存邮件通知配置 (汇总邮件+各预警邮件共用 SMTP 发信通道, 落 fwd_doc_* 扁平键)
        from server.services.forwarder_doc_service import ForwarderDocService as _FDS
        _en_payload = payload.email_notify.model_dump()
        email_notify = _FDS.save_config(_en_payload)
        email_notify["mail_to"] = ", ".join(email_notify.get("mail_to") or [])

        # 10. 物流渠道计费规则已改为每渠道独立存储键 (channel_rule:{key}), 由渠道级接口单独读写;
        #     此处不再接收整表覆盖, 防止整批写回波及其他渠道

        # 同步刷新内存全局参数
        GLOBAL_PRICING_CONFIG.update(pricing_dict)

        return {
            "code": 0,
            "msg": "系统配置保存成功",
            "data": {
                "store_accounts": stores,
                "pricing_config": pricing_dict,
                "channel_rules": _aggregate_channel_rules(),
                "storage_paths": {
                    "mac": mac_path,
                    "win": win_path,
                    "rel_main": rel_main,
                    "rel_sku": rel_sku
                },
                "session_expire_hours": session_exp,
                "chrome_user_data_dirs": chrome_dir,
                "submit_ad_enabled": submit_ad_enabled,
                "ai_config": ai_config,
                "db_agent_token": db_agent_token,
                "email_notify": email_notify
            }
        }
    except Exception as e:
        return {"code": 500, "msg": f"保存配置异常: {str(e)}", "data": None}


# ============================================================================
# 物流渠道计费规则 — 渠道级粒度存储与操作 (每渠道独立存储键, 互不影响)
# 存储: 每个渠道一条独立配置键 channel_rule:{key}; channel_rules_order 维护展示顺序;
#       历史 channel_rules 大键在首次访问时自动拆分迁移, 之后删除
# 效果: 启停/保存/删除某渠道只写它自己的那一行, 其他渠道物理上不可能被波及
# ============================================================================

CR_PREFIX = "channel_rule:"
CR_ORDER_KEY = "channel_rules_order"


def _migrate_legacy_channel_rules() -> None:
    """历史整表大键 → 每渠道独立键 (幂等, 只在旧键存在时执行一次)"""
    legacy = get_setting("channel_rules", None)
    if not (isinstance(legacy, list) and legacy):
        return
    order = []
    for r in legacy:
        if isinstance(r, dict) and r.get("key"):
            set_setting(CR_PREFIX + str(r["key"]), r)
            order.append(str(r["key"]))
    if order:
        set_setting(CR_ORDER_KEY, order)
    delete_setting("channel_rules")


def _aggregate_channel_rules() -> List[Dict[str, Any]]:
    """聚合全部渠道独立键为列表 (按 channel_rules_order 排序, 未登记的新键排在尾部)"""
    _migrate_legacy_channel_rules()
    rows = get_settings_by_prefix(CR_PREFIX)
    order = get_setting(CR_ORDER_KEY, [])
    if not isinstance(order, list):
        order = []
    ordered = [k for k in order if k in rows] + [k for k in rows if k not in order]
    return [rows[k] for k in ordered if isinstance(rows[k], dict)]


class ChannelRuleSaveSchema(BaseModel):
    rule: Dict[str, Any] = Field(..., description="单条渠道规则完整对象 (key 必填)")
    defaults: Optional[List[Dict[str, Any]]] = Field(None, description="该渠道尚无独立存储且库内无来源时用于物化的内置默认规则")


class ChannelRuleToggleSchema(BaseModel):
    enabled: bool = Field(..., description="目标渠道启用状态")
    defaults: Optional[List[Dict[str, Any]]] = Field(None, description="该渠道尚无独立存储时用于物化的内置默认规则")


@router.post("/channel_rules/{key}")
async def save_one_channel_rule(key: str, payload: ChannelRuleSaveSchema, admin: Dict[str, Any] = Depends(require_admin_user)):
    """单渠道保存: 只写 channel_rule:{key} 这一行 (新渠道追加到展示顺序尾部), 其他渠道零接触"""
    rule = dict(payload.rule or {})
    if not rule:
        raise HTTPException(400, detail="rule 不能为空")
    _migrate_legacy_channel_rules()
    rule["key"] = key
    set_setting(CR_PREFIX + key, rule)
    order = get_setting(CR_ORDER_KEY, [])
    if not isinstance(order, list):
        order = []
    if key not in order:
        order.append(key)
        set_setting(CR_ORDER_KEY, order)
    return {"code": 0, "msg": f"渠道「{rule.get('name') or key}」已单独保存 (其他渠道不受影响)", "data": {"channel_rules": _aggregate_channel_rules()}}


@router.post("/channel_rules/{key}/toggle")
async def toggle_one_channel_rule(key: str, payload: ChannelRuleToggleSchema, admin: Dict[str, Any] = Depends(require_admin_user)):
    """单渠道启停: 只读写 channel_rule:{key} 这一行, 仅翻转 enabled 字段"""
    _migrate_legacy_channel_rules()
    row = get_setting(CR_PREFIX + key, None)
    if not isinstance(row, dict):
        # 该渠道尚无独立存储 → 从前端物化的默认列表中取该渠道落库 (仅此一条)
        seed = next((r for r in (payload.defaults or []) if isinstance(r, dict) and r.get("key") == key), None)
        if not isinstance(seed, dict):
            raise HTTPException(404, detail=f"渠道 {key} 不存在")
        row = dict(seed)
        order = get_setting(CR_ORDER_KEY, [])
        if isinstance(order, list) and key not in order:
            order.append(key)
            set_setting(CR_ORDER_KEY, order)
    row["enabled"] = bool(payload.enabled)
    set_setting(CR_PREFIX + key, row)
    return {"code": 0, "msg": f"渠道「{row.get('name') or key}」已{'启用' if payload.enabled else '停用'} (仅此渠道)", "data": {"channel_rules": _aggregate_channel_rules()}}


@router.post("/channel_rules/{key}/delete")
async def delete_one_channel_rule(key: str, admin: Dict[str, Any] = Depends(require_admin_user)):
    """单渠道删除: 只删除 channel_rule:{key} 这一行"""
    _migrate_legacy_channel_rules()
    if get_setting(CR_PREFIX + key, None) is None:
        raise HTTPException(404, detail=f"渠道 {key} 不存在")
    delete_setting(CR_PREFIX + key)
    order = get_setting(CR_ORDER_KEY, [])
    if isinstance(order, list) and key in order:
        order = [k for k in order if k != key]
        set_setting(CR_ORDER_KEY, order)
    return {"code": 0, "msg": "渠道已删除", "data": {"channel_rules": _aggregate_channel_rules()}}


@router.post("/channel_rules/reset")
async def reset_channel_rules_config(admin: Dict[str, Any] = Depends(require_admin_user)):
    """清空全部渠道独立键与顺序 → 全部渠道回退前端内置默认"""
    _migrate_legacy_channel_rules()
    for k in get_settings_by_prefix(CR_PREFIX).keys():
        delete_setting(CR_PREFIX + k)
    delete_setting(CR_ORDER_KEY)
    return {"code": 0, "msg": "已恢复默认渠道计费标准", "data": {"channel_rules": None}}
