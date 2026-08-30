"""
智能运费比价与日元售价测算统一配置模块
收敛汇率、税率、售价系数及 10 大国际物流渠道参数规则
"""
from typing import Dict, Any

# ============================================================================
# 全局定价与汇率参数
# ============================================================================
GLOBAL_PRICING_CONFIG = {
    "tax_rate": 0.17,               # 日本消费税/平台税率 (默认 17%)
    "exchange_rate": 23.0,           # 日元兑人民币汇率 (1 人民币 ≈ 23 日元)
    "price_coefficient": 26.0,       # 日元售价转换系数 (默认 26.0)
    "default_profit_coeff": 1.0,     # 默认目标利润系数 (默认 1.0)
    "exchange_rate_usd_rmb": 7.19,   # 美元汇率 (用于商业件申报金额测算)
    "japan_tax_rate": 0.10,          # 日本商业件进口税率 (10%)
    "commercial_clearance_fee": 50.0 # 商业件报关操作费 (50 元)
}


def get_global_pricing_config() -> Dict[str, Any]:
    """获取当前生效的全局计价参数 (优先读取数据库自定义配置)"""
    try:
        from server.database import get_setting
        custom = get_setting("pricing_config", None)
        if custom and isinstance(custom, dict):
            merged = dict(GLOBAL_PRICING_CONFIG)
            merged.update(custom)
            return merged
    except Exception:
        pass
    return dict(GLOBAL_PRICING_CONFIG)

# ============================================================================
# 10 大物流渠道规则与费率配置
# ============================================================================
CHANNEL_RULES: Dict[str, Dict[str, Any]] = {
    "顺丰小包": {
        "max_single_side": 120.0,
        "max_sum_sides": 160.0,
        "max_weight": 30.0,
        "vol_ratio": 8000.0,
        "discount": 0.8,
        # 阶梯计费 (每 0.5kg 一档)
        "tiers": [
            {"max_cw": 2.0, "base": 38.0, "step": 8.0},
            {"max_cw": 5.0, "base": 40.0, "step": 9.0},
            {"max_cw": 10.0, "base": 41.0, "step": 11.0},
            {"max_cw": 999.0, "base": 42.0, "step": 12.0},
        ]
    },
    "顺丰国际大件": {
        "max_single_side": 200.0,
        "vol_ratio": 6000.0,
        "min_charge_weight": 20.0,
        "tiers": [
            {"max_cw": 100.0, "unit_price": 15.0},
            {"max_cw": 500.0, "unit_price": 14.0},
            {"max_cw": 1000.0, "unit_price": 13.0},
        ]
    },
    "日川普货": {
        "max_sum_sides": 960.0,
        "max_actual_weight": 20.0,
        "vol_ratio": 6000.0,
        "tiers": [
            {"max_cw": 2.0, "base": 32.0, "step": 6.5},
            {"max_cw": 5.0, "base": 33.0, "step": 7.0},
            {"max_cw": 10.0, "base": 34.0, "step": 7.5},
            {"max_cw": 999.0, "base": 35.0, "step": 8.0},
        ],
        "weight_surcharge": {"threshold": 9.9, "fee": 50.0},
        "size_surcharges": [
            {"min_sum": 239.0, "fee": 260.0},
            {"min_sum": 220.0, "fee": 200.0},
            {"min_sum": 200.0, "fee": 150.0},
            {"min_sum": 179.0, "fee": 100.0},
            {"min_sum": 159.0, "fee": 80.0},
        ]
    },
    "日川带电": {
        "max_sum_sides": 960.0,
        "max_actual_weight": 20.0,
        "vol_ratio": 6000.0,
        "tiers": [
            {"max_cw": 2.0, "base": 35.0, "step": 7.0},
            {"max_cw": 5.0, "base": 36.0, "step": 7.5},
            {"max_cw": 10.0, "base": 36.0, "step": 8.0},
            {"max_cw": 999.0, "base": 37.0, "step": 8.5},
        ],
        "weight_surcharge": {"threshold": 9.9, "fee": 50.0},
        "size_surcharges": [
            {"min_sum": 239.0, "fee": 260.0},
            {"min_sum": 220.0, "fee": 200.0},
            {"min_sum": 200.0, "fee": 150.0},
            {"min_sum": 179.0, "fee": 100.0},
            {"min_sum": 159.0, "fee": 80.0},
        ]
    },
    "川日大包": {
        "max_length": 305.0,
        "max_width": 175.0,
        "max_height": 155.0,
        "max_cw": 900.0,
        "vol_ratio": 6000.0,
        "tiers": [
            {"max_cw": 21.0, "base": 60.0, "step": 18.0},
            {"max_cw": 51.0, "rate": 19.0},
            {"max_cw": 101.0, "rate": 18.5},
            {"max_cw": 301.0, "rate": 17.5},
            {"max_cw": 501.0, "rate": 17.0},
            {"max_cw": 1000.0, "rate": 16.5},
        ],
        "length_surcharge": {"threshold": 159.0, "fee": 200.0}
    },
    "佐川大件": {
        "max_cw": 30.0,
        "max_sum_sides": 250.0,
        "max_single_side": 150.0,
        "base": 40.0,
        "step": 10.0
    },
    "义乌小包": {
        "max_actual_weight": 20.0,
        "max_single_side": 9100.0,
        "max_sum_sides": 9160.0,
        "tiers": [
            {"max_cw": 2.0, "base": 34.0, "step": 6.0},
            {"max_cw": 5.0, "base": 35.0, "step": 7.0},
            {"max_cw": 10.0, "base": 36.0, "step": 8.0},
            {"max_cw": 999.0, "base": 36.0, "step": 8.0},
        ]
    },
    "初岛160免泡": {
        "max_actual_weight": 20.0,
        "max_sum_sides": 260.0,
        "tiers": [
            {"max_cw": 2.0, "base": 34.0, "step": 6.0},
            {"max_cw": 5.0, "base": 35.0, "step": 7.0},
            {"max_cw": 10.0, "base": 36.0, "step": 8.0},
            {"max_cw": 999.0, "base": 36.0, "step": 8.0},
        ],
        "base_op_fee": 20.0
    },
    "初岛黑猫": {
        "max_actual_weight": 20.0,
        "max_single_side": 160.0,
        "max_sum_sides": 160.0,
        "tiers": [
            {"max_cw": 2.0, "base": 36.0, "step": 6.0},
            {"max_cw": 5.0, "base": 37.0, "step": 7.0},
            {"max_cw": 10.0, "base": 38.0, "step": 8.0},
            {"max_cw": 999.0, "base": 39.0, "step": 10.0},
        ]
    },
    "航空邮政大包": {
        "max_actual_weight": 30.0,
        "max_single_side": 150.0,
        "max_combined_girth": 330.0, # 长 + 2*(宽+高)
        "first_weight_fee": 124.2,
        "continue_weight_fee": 29.6,
        "extra_fee": 8.0
    }
}
