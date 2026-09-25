"""
智能运费比价与日元售价测算核心引擎
基于 /Users/gx/Desktop/mypro/calcfee 完整物流规则重构
"""
import math
from typing import Dict, Any, List, Optional, Tuple
from server.services.pricing_config import GLOBAL_PRICING_CONFIG, CHANNEL_RULES, get_global_pricing_config


class PricingService:
    """提供 10 大物流渠道计费重、运费测算、选优与日元售价推导服务"""

    @staticmethod
    def calculate_sku_pricing(
        length_cm: float,
        width_cm: float,
        height_cm: float,
        weight_kg: float,
        purchase_price_rmb: float,
        profit_coefficient: float = 1.0,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        计算单个 SKU 的所有物流渠道运费、选择最优渠道，并推导日元售价与利润指标
        """
        cfg = get_global_pricing_config()
        if config:
            cfg.update(config)

        # 基础输入与保护
        length = float(length_cm or 0.0)
        width = float(width_cm or 0.0)
        height = float(height_cm or 0.0)
        act_wt = float(weight_kg or 0.1)
        if act_wt <= 0:
            act_wt = 0.1
        purchase_price = float(purchase_price_rmb or 0.0)
        profit_coeff = float(profit_coefficient if profit_coefficient and profit_coefficient > 0 else 1.0)

        # 基础物理量计算
        sum_sides = length + width + height
        max_side = max(length, width, height) if sum_sides > 0 else 0.0
        min_side = min(length, width, height) if sum_sides > 0 else 0.0
        mid_side = sum_sides - max_side - min_side

        vol_6000 = math.ceil(round((length * width * height / 6000.0) * 1000, 6)) / 1000.0 if sum_sides > 0 else 0.0
        vol_8000 = math.ceil(round((length * width * height / 8000.0) * 1000, 6)) / 1000.0 if sum_sides > 0 else 0.0

        def _ceil2(x: float) -> float:
            """Excel ROUNDUP(x, 2): 正数向上保留2位"""
            return math.ceil(round(x * 100, 6)) / 100.0

        # =====================================================================
        # 1. 各渠道计费重预判定
        # =====================================================================
        # 川日系计费重 (日川普货/带电/川日大包/佐川)
        cw_richuan: Optional[float] = None
        if sum_sides <= 960.0:
            if sum_sides < 100.0:
                raw_cw = act_wt
            elif act_wt > vol_6000:
                raw_cw = act_wt
            else:
                raw_cw = (act_wt + vol_6000) / 2.0
            cw_richuan = math.ceil(round(raw_cw / 0.5, 6)) * 0.5

        # 初岛系计费重 (义乌小包)
        cw_chudao: Optional[float] = None
        if sum_sides <= 140.0:
            cw_chudao = act_wt
        elif sum_sides <= 160.0:
            cw_chudao = (act_wt + vol_6000) / 2.0
        else:
            cw_chudao = max(act_wt, vol_6000)

        # 初岛 160 免泡计费重
        cw_chudao160: Optional[float] = None
        if sum_sides <= 160.0:
            cw_chudao160 = act_wt
        else:
            cw_chudao160 = (act_wt + vol_6000) / 2.0

        # 顺丰大件计费重
        cw_sf_large: Optional[float] = None
        if not (max_side > 200.0 or (mid_side > 80.0 and min_side > 80.0) or (mid_side > 70.0 and min_side > 70.0)):
            cw_sf_large = math.ceil(round(max(act_wt, vol_6000) * 1000, 6)) / 1000.0

        # 初岛黑猫计费重 (Excel L列: 三边和≤120按实重, 120<三边和≤159取(实重+泡重)/2)
        cw_heimao: Optional[float] = None
        if sum_sides <= 159.0:
            cw_heimao = act_wt if sum_sides <= 120.0 else (act_wt + vol_6000) / 2.0

        # =====================================================================
        # 2. 计算 10 大渠道运费
        # =====================================================================
        freights: List[Dict[str, Any]] = []

        # 1. 顺丰小包
        if act_wt > 30.0 or max_side > 120.0 or sum_sides > 160.0:
            freights.append({"channel": "顺丰小包", "status": "拒收", "cost": None, "reason": "单边>120或三边和>160或实重>30"})
        else:
            cw_sf = max(act_wt, vol_8000)
            steps = math.ceil(round(cw_sf / 0.5, 6))
            if cw_sf <= 2.0:
                base = 38.0 + (steps - 1) * 8.0
            elif cw_sf <= 5.0:
                base = 40.0 + (steps - 1) * 9.0
            elif cw_sf <= 10.0:
                base = 41.0 + (steps - 1) * 11.0
            else:
                base = 42.0 + (steps - 1) * 12.0
            cost = round(base * 0.8, 2)
            freights.append({"channel": "顺丰小包", "status": "可用", "cost": cost, "charge_weight": cw_sf})

        # 2. 顺丰国际大件
        if cw_sf_large is None:
            freights.append({"channel": "顺丰国际大件", "status": "拒收", "cost": None, "reason": "尺寸超限"})
        else:
            if cw_sf_large < 100.0:
                cost = _ceil2(max(cw_sf_large, 20.0) * 15.0)
            elif cw_sf_large < 500.0:
                cost = _ceil2(cw_sf_large * 14.0)
            elif cw_sf_large < 1000.0:
                cost = _ceil2(cw_sf_large * 13.0)
            else:
                cost = None
            if cost is not None:
                freights.append({"channel": "顺丰国际大件", "status": "可用", "cost": cost, "charge_weight": cw_sf_large})
            else:
                freights.append({"channel": "顺丰国际大件", "status": "询价", "cost": None, "charge_weight": cw_sf_large})

        # 3. 日川普货
        if cw_richuan is None:
            freights.append({"channel": "日川普货", "status": "拒收", "cost": None, "reason": "三边和>960"})
        else:
            steps = math.ceil(round(cw_richuan / 0.5, 6))
            if cw_richuan <= 2.0:
                base = 32.0 + (steps - 1) * 6.5
            elif cw_richuan <= 5.0:
                base = 33.0 + (steps - 1) * 7.0
            elif cw_richuan <= 10.0:
                base = 34.0 + (steps - 1) * 7.5
            else:
                base = 35.0 + (steps - 1) * 8.0
            extra_size = 260.0 if sum_sides > 239.0 else (200.0 if sum_sides > 220.0 else (150.0 if sum_sides > 200.0 else (100.0 if sum_sides > 179.0 else (80.0 if sum_sides > 159.0 else 0.0))))
            extra_wt = 50.0 if act_wt > 9.9 else 0.0
            cost = float(math.ceil(base + extra_size + extra_wt))
            freights.append({"channel": "日川普货", "status": "可用", "cost": cost, "charge_weight": cw_richuan})

        # 4. 日川带电 (Excel: 38/39/40/41 + 9/9.5/10/11)
        if cw_richuan is None:
            freights.append({"channel": "日川带电", "status": "拒收", "cost": None, "reason": "三边和>960"})
        else:
            steps = math.ceil(round(cw_richuan / 0.5, 6))
            if cw_richuan <= 2.0:
                base = 38.0 + (steps - 1) * 9.0
            elif cw_richuan <= 5.0:
                base = 39.0 + (steps - 1) * 9.5
            elif cw_richuan <= 10.0:
                base = 40.0 + (steps - 1) * 10.0
            else:
                base = 41.0 + (steps - 1) * 11.0
            extra_size = 260.0 if sum_sides > 239.0 else (200.0 if sum_sides > 220.0 else (150.0 if sum_sides > 200.0 else (100.0 if sum_sides > 179.0 else (80.0 if sum_sides > 159.0 else 0.0))))
            extra_wt = 50.0 if act_wt > 9.9 else 0.0
            cost = float(math.ceil(base + extra_size + extra_wt))
            freights.append({"channel": "日川带电", "status": "可用", "cost": cost, "charge_weight": cw_richuan})

        # 5. 川日大包 (Excel: 超尺/超3倍泡→询价, 无计费重上限, ≥1000kg费率16)
        if length > 305.0 or width > 175.0 or height > 155.0:
            freights.append({"channel": "川日大包", "status": "询价", "cost": None, "reason": "超尺单询"})
        elif cw_richuan is None or cw_richuan > act_wt * 3.0:
            freights.append({"channel": "川日大包", "status": "询价", "cost": None, "reason": "超3倍泡单询"})
        else:
            if cw_richuan < 21.0:
                base = 60.0 + (math.ceil(round(cw_richuan / 0.5, 6)) - 1) * 18.0
            elif cw_richuan < 51.0:
                base = cw_richuan * 19.0
            elif cw_richuan < 101.0:
                base = cw_richuan * 18.5
            elif cw_richuan < 301.0:
                base = cw_richuan * 17.5
            elif cw_richuan < 501.0:
                base = cw_richuan * 17.0
            elif cw_richuan < 1000.0:
                base = cw_richuan * 16.5
            else:
                base = cw_richuan * 16.0
            extra = 200.0 if (max_side > 159.0 and cw_richuan < 300.0) else 0.0
            cost = round(base + extra, 2)
            freights.append({"channel": "川日大包", "status": "可用", "cost": cost, "charge_weight": cw_richuan})

        # 6. 佐川大件
        if cw_richuan is None or cw_richuan > 30.0 or sum_sides > 250.0 or max_side > 150.0:
            freights.append({"channel": "佐川大件", "status": "拒收", "cost": None, "reason": "计费重>30或三边和>250或单边>150"})
        else:
            steps = math.ceil(round(cw_richuan / 0.5, 6))
            cost = round(40.0 + (steps - 1) * 10.0, 2)
            freights.append({"channel": "佐川大件", "status": "可用", "cost": cost, "charge_weight": cw_richuan})

        # 7. 义乌小包 (Excel 无实重限制)
        if cw_chudao is None or max_side > 9100.0 or sum_sides > 9160.0:
            freights.append({"channel": "义乌小包", "status": "拒收", "cost": None, "reason": "尺寸超限"})
        else:
            steps = math.ceil(round(cw_chudao / 0.5, 6))
            if cw_chudao <= 2.0:
                base = 34.0 + (steps - 1) * 6.0
            elif cw_chudao <= 5.0:
                base = 35.0 + (steps - 1) * 7.0
            else:
                base = 36.0 + (steps - 1) * 8.0
            extra1 = 35.0 if max_side > 99.0 else 0.0
            extra2 = 120.0 if sum_sides > 200.0 else (80.0 if sum_sides > 160.0 else 0.0)
            cost = round(float(math.ceil(base + max(extra1, extra2))), 2)
            freights.append({"channel": "义乌小包", "status": "可用", "cost": cost, "charge_weight": cw_chudao})

        # 8. 初岛 160 免泡 (Excel 无实重限制)
        if cw_chudao160 is None or max_side > 9100.0 or sum_sides > 260.0:
            freights.append({"channel": "初岛160免泡", "status": "拒收", "cost": None, "reason": "三边和>260"})
        else:
            steps = math.ceil(round(cw_chudao160 / 0.5, 6))
            if cw_chudao160 <= 2.0:
                base = 34.0 + (steps - 1) * 6.0
            elif cw_chudao160 <= 5.0:
                base = 35.0 + (steps - 1) * 7.0
            else:
                base = 36.0 + (steps - 1) * 8.0
            extra_max = 100.0 if sum_sides > 200.0 else (50.0 if sum_sides > 160.0 else 0.0)
            extra_sum = 20.0 if sum_sides > 200.0 else (30.0 if sum_sides > 160.0 else 0.0)
            cost = round(float(math.ceil(base + extra_max + extra_sum + 20.0)), 2)
            freights.append({"channel": "初岛160免泡", "status": "可用", "cost": cost, "charge_weight": cw_chudao160})

        # 9. 初岛黑猫 (Excel 无实重限制)
        if cw_heimao is None or max_side > 160.0 or sum_sides > 160.0:
            freights.append({"channel": "初岛黑猫", "status": "拒收", "cost": None, "reason": "单边>160或三边和>160"})
        else:
            steps = math.ceil(round(cw_heimao / 0.5, 6))
            if cw_heimao <= 2.0:
                raw_cost = 36.0 + (steps - 1) * 6.0
            elif cw_heimao <= 5.0:
                raw_cost = 37.0 + (steps - 1) * 7.0
            elif cw_heimao <= 10.0:
                raw_cost = 38.0 + (steps - 1) * 8.0
            else:
                raw_cost = 39.0 + (steps - 1) * 10.0
            cost = round(float(math.ceil(raw_cost)), 2)
            freights.append({"channel": "初岛黑猫", "status": "可用", "cost": cost, "charge_weight": cw_heimao})

        # 10. 航空邮政大包 (Excel: 围长≤330打9折, >330不打折也不拒收)
        if act_wt > 30.0 or max_side > 150.0:
            freights.append({"channel": "航空邮政大包", "status": "拒收", "cost": None, "reason": "重量>30或单边>150"})
        else:
            wt_ceil = math.ceil(round(act_wt, 6))
            girth = (sum_sides - max_side) * 2.0 + max_side
            raw = (124.2 + (wt_ceil - 1) * 29.6) * (1.0 if girth > 330.0 else 0.9) + 8.0
            cost = _ceil2(raw)
            freights.append({"channel": "航空邮政大包", "status": "可用", "cost": cost, "charge_weight": wt_ceil})

        # =====================================================================
        # 3. 筛选最优渠道
        # =====================================================================
        available = [f for f in freights if f.get("cost") is not None and isinstance(f["cost"], (int, float))]
        if available:
            optimal = min(available, key=lambda x: x["cost"])
            optimal_channel = optimal["channel"]
            optimal_freight = float(optimal["cost"])
        else:
            optimal_channel = "暂无可用渠道"
            optimal_freight = 0.0

        # =====================================================================
        # 4. 联动推导售价与利润
        # =====================================================================
        z = optimal_freight
        total_cost_rmb = round(purchase_price + z, 2)
        planned_profit_rmb = round(total_cost_rmb * profit_coeff, 2)
        price_coeff = float(cfg.get("price_coefficient", 26.0))
        selling_price_jpy = round((total_cost_rmb + planned_profit_rmb) * price_coeff, 2)
        final_price_jpy = int(round(selling_price_jpy)) if selling_price_jpy > 0 else 0

        tax_rate = float(cfg.get("tax_rate", 0.17))
        tax_deducted_jpy = round(selling_price_jpy - (selling_price_jpy * tax_rate), 2)
        exchange_rate = float(cfg.get("exchange_rate", 23.0))
        cost_jpy = round(total_cost_rmb * exchange_rate, 2)

        profit_margin = 0.0
        if tax_deducted_jpy > 0:
            profit_margin = round(1.0 - (cost_jpy / tax_deducted_jpy), 4)

        return {
            "sum_sides": sum_sides,
            "vol_6000": vol_6000,
            "vol_8000": vol_8000,
            "freights": freights,
            "optimal_channel": optimal_channel,
            "optimal_freight": optimal_freight,
            "total_cost_rmb": total_cost_rmb,
            "planned_profit_rmb": planned_profit_rmb,
            "selling_price_jpy": selling_price_jpy,
            "final_price_jpy": final_price_jpy,
            "tax_deducted_jpy": tax_deducted_jpy,
            "cost_jpy": cost_jpy,
            "profit_margin": profit_margin,
            "profit_margin_pct": f"{round(profit_margin * 100, 2)}%"
        }


if __name__ == "__main__":
    res = PricingService.calculate_sku_pricing(
        length_cm=55.5, width_cm=38.2, height_cm=22.0, weight_kg=1.85,
        purchase_price_rmb=50.0, profit_coefficient=1.0
    )
    print("最优物流:", res["optimal_channel"], f"¥{res['optimal_freight']}")
    print("日元售价:", res["final_price_jpy"], f"利润率: {res['profit_margin_pct']}")
    print("所有渠道测算:")
    for f in res["freights"]:
        print(" ", f)
