"""
商品维护 API 路由
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from server.models.product_schemas import ProductCreateSchema, GenerateMatrixRequest
from server.services.product_service import ProductService
from server.dependencies import get_current_user_from_request

router = APIRouter(prefix="/api/products", tags=["商品维护"])


@router.post("/generate-matrix", summary="自动生成多变体笛卡尔积矩阵")
async def generate_matrix(req: GenerateMatrixRequest):
    """根据提交的颜色与尺寸选项，实时计算笛卡尔积变体组合矩阵"""
    matrix = ProductService.generate_variation_matrix(req)
    return {"code": 0, "msg": "生成成功", "data": matrix}


@router.get("/seq-numbers", summary="获取当前用户与品牌的自动编号 (Parent SKU / 型号 / 型号名称)")
async def get_seq_numbers(request: Request, brand: Optional[str] = Query(None)):
    """
    自动生成编号规则：
    1. Parent SKU = 登录用户名 + 用户创建的第几个品 (数字)
    2. 品番・型番 = 品牌
    3. モデル名 = 品牌 + 该品牌下的第几个品 (数字)
    """
    user = get_current_user_from_request(request)
    username = user.get("username", "admin") if user else "admin"
    seq_data = ProductService.get_next_sequence_numbers(username, brand or "")
    return {"code": 0, "msg": "获取成功", "data": seq_data}


@router.get("/filter-options", summary="获取商品列表筛选下拉可选项")
async def get_product_filter_options():
    """返回所有已录入商品的店铺、品牌与维护人列表，用于前端筛选器下拉菜单"""
    opts = ProductService.get_filter_options()
    return {"code": 0, "msg": "获取成功", "data": opts}


@router.post("", summary="保存/创建商品与变体信息")
async def create_product(data: ProductCreateSchema):
    """保存商品完整信息至本地数据库"""
    product = ProductService.create_product(data)
    return {"code": 0, "msg": "商品录入成功", "data": product}


@router.get("/{product_id}", summary="获取商品详情")
async def get_product_detail(product_id: int):
    """获取指定商品的完整结构化数据"""
    product = ProductService.get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return {"code": 0, "msg": "获取成功", "data": product}


@router.get("", summary="获取商品列表 (支持多条件组合检索与模糊查询)")
async def list_products(
    keyword: Optional[str] = Query(None, description="搜索标题/Parent SKU/型号/关键词"),
    store_account: Optional[str] = Query(None, description="店铺账号筛选"),
    brand: Optional[str] = Query(None, description="品牌筛选"),
    created_by: Optional[str] = Query(None, description="维护人筛选"),
    sale_type: Optional[str] = Query(None, description="售卖形式筛选 (variation / single)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """获取录入的商品列表与变体总数看板"""
    products = ProductService.list_products(
        limit=limit,
        offset=offset,
        keyword=keyword,
        store_account=store_account,
        brand=brand,
        created_by=created_by,
        sale_type=sale_type
    )
    return {"code": 0, "msg": "获取成功", "data": products}
