"""
系统管理与全局配置 REST API 路由
包含店铺账号列表维护、Calcfee 物流税率/汇率/售价系数等核心参数配置
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from server.database import get_setting, set_setting
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


class StoreBrandItemSchema(BaseModel):
    store_name: str = Field(..., min_length=1, description="店铺账号名称")
    brand_name: str = Field(..., min_length=1, description="对应品牌名称 (1对1必填)")
    is_default: Optional[bool] = Field(False, description="是否为默认店铺 (只能设一个)")


class SystemSettingsSchema(BaseModel):
    store_accounts: List[Union[StoreBrandItemSchema, Dict[str, Any], str]] = Field(default_factory=list, description="店铺账号与品牌映射列表")
    pricing_config: PricingConfigSchema = Field(default_factory=PricingConfigSchema, description="物流与计价核心参数")
    storage_paths: StoragePathsSchema = Field(default_factory=StoragePathsSchema, description="本地归档存储目录")
    session_expire_hours: Optional[float] = Field(1.0, description="登录 Session 有效时长 (小时，默认 1.0h)")


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
                "storage_paths": {
                    "mac": storage_mac,
                    "win": storage_win,
                    "rel_main": rel_main,
                    "rel_sku": rel_sku
                },
                "session_expire_hours": session_exp
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

        # 同步刷新内存全局参数
        GLOBAL_PRICING_CONFIG.update(pricing_dict)

        return {
            "code": 0,
            "msg": "系统配置保存成功",
            "data": {
                "store_accounts": stores,
                "pricing_config": pricing_dict,
                "storage_paths": {
                    "mac": mac_path,
                    "win": win_path,
                    "rel_main": rel_main,
                    "rel_sku": rel_sku
                },
                "session_expire_hours": session_exp
            }
        }
    except Exception as e:
        return {"code": 500, "msg": f"保存配置异常: {str(e)}", "data": None}
