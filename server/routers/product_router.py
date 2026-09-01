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


@router.put("/{product_id}", summary="更新修改商品与变体信息")
async def update_product(product_id: int, data: ProductCreateSchema):
    """更新修改已有商品及变体完整信息"""
    product = ProductService.update_product(product_id, data)
    if not product:
        raise HTTPException(status_code=404, detail=f"ID 为 {product_id} 的商品不存在")
    return {"code": 0, "msg": "商品更新成功", "data": product}


@router.get("/by-parent-sku/{parent_sku}", summary="按 Parent SKU 获取商品完整数据（用于录入页面导入回填）")
async def get_product_by_parent_sku(parent_sku: str):
    """按 Parent SKU 查询商品父节点及全部变体，用于录入工作台导入已保存商品数据"""
    from server.database import get_db_connection
    import json as _json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT * FROM product_items WHERE parent_sku = ? AND is_parent = 1 LIMIT 1",
            (parent_sku,)
        )
        p_row = cursor.fetchone()
        if not p_row:
            raise HTTPException(status_code=404, detail=f"Parent SKU '{parent_sku}' 不存在")
        product = dict(p_row)
        # 反序列化 JSON 字段
        for json_field, alias in [
            ("extra_images_json", "extra_images"),
            ("color_options_json", "color_options"),
            ("size_options_json", "size_options"),
            ("variant_dimension_images_json", "variant_dimension_images"),
            ("bullet_points_json", "bullet_points"),
            ("chinese_translations_json", "chinese_translations"),
        ]:
            try:
                product[alias] = _json.loads(product.get(json_field) or ("[]" if alias != "variant_dimension_images" else "{}"))
            except Exception:
                product[alias] = [] if alias != "variant_dimension_images" else {}

        # 查询子变体
        cursor.execute(
            "SELECT * FROM product_items WHERE parent_sku = ? AND is_parent = 0 ORDER BY id ASC",
            (parent_sku,)
        )
        v_rows = cursor.fetchall()
        product["variations"] = [dict(v) for v in v_rows]
        product["variation_count"] = len(product["variations"])
        return {"code": 0, "msg": "获取成功", "data": product}
    finally:
        conn.close()


@router.get("/list-parent-skus", summary="获取所有父级商品 Parent SKU 列表（用于录入页面导入选择）")
async def list_parent_skus():
    """返回所有 is_parent=1 的商品简要信息列表，供录入工作台导入下拉框使用"""
    from server.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, parent_sku, sku, title, brand, store_account, status, created_by, main_image
            FROM product_items
            WHERE is_parent = 1
            ORDER BY id DESC
            LIMIT 200
        """)
        rows = cursor.fetchall()
        return {"code": 0, "msg": "获取成功", "data": [dict(r) for r in rows]}
    finally:
        conn.close()


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
