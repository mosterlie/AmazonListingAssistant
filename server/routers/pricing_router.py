"""
智能运费比价与日元售价测算 REST API 路由
"""
from fastapi import APIRouter
from server.models.product_schemas import CalculateSinglePricingRequest, CalculateBatchPricingRequest
from server.services.pricing_service import PricingService
from server.services.pricing_config import GLOBAL_PRICING_CONFIG, CHANNEL_RULES

router = APIRouter(prefix="/api/pricing", tags=["Pricing & Logistics"])


@router.get("/config")
def get_pricing_config():
    """获取当前系统的全局定价参数与各物流渠道规则"""
    return {
        "code": 0,
        "msg": "获取定价配置成功",
        "data": {
            "global_config": GLOBAL_PRICING_CONFIG,
            "channels": list(CHANNEL_RULES.keys())
        }
    }


@router.post("/calculate-single")
def calculate_single_sku(req: CalculateSinglePricingRequest):
    """测算单个 SKU 的物流渠道运费比价与日元售价"""
    res = PricingService.calculate_sku_pricing(
        length_cm=req.length_cm,
        width_cm=req.width_cm,
        height_cm=req.height_cm,
        weight_kg=req.weight_kg,
        purchase_price_rmb=req.purchase_price_rmb,
        profit_coefficient=req.profit_coefficient
    )
    return {"code": 0, "msg": "测算成功", "data": res}


@router.post("/calculate-batch")
def calculate_batch_sku(req: CalculateBatchPricingRequest):
    """批量测算多个 SKU 的物流渠道运费比价与日元售价"""
    results = []
    for item in req.items:
        res = PricingService.calculate_sku_pricing(
            length_cm=item.length_cm,
            width_cm=item.width_cm,
            height_cm=item.height_cm,
            weight_kg=item.weight_kg,
            purchase_price_rmb=item.purchase_price_rmb,
            profit_coefficient=item.profit_coefficient
        )
        results.append(res)
    return {"code": 0, "msg": "批量测算成功", "data": results}
