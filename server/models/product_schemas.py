"""
Pydantic 数据契约与校验模型
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class VariationItemSchema(BaseModel):
    """单个变体行数据结构"""
    id: Optional[int] = None
    sku: str = Field(..., description="变体子 SKU 编码")
    ean: Optional[str] = Field("", description="变体 EAN / UPC 条码")
    color: Optional[str] = Field("", description="颜色属性值")
    size: Optional[str] = Field("", description="尺寸属性值")
    condition: Optional[str] = Field("新品", description="物品状况")
    description: Optional[str] = Field("", description="变体描述")
    price_jpy: Optional[float] = Field(0.0, description="售价(JPY)")
    quantity: Optional[int] = Field(0, description="库存数量")
    sale_price_jpy: Optional[float] = Field(0.0, description="促销价(JPY)")
    length_cm: Optional[float] = Field(0.0, description="长(cm)")
    width_cm: Optional[float] = Field(0.0, description="宽(cm)")
    height_cm: Optional[float] = Field(0.0, description="高(cm)")
    weight: Optional[float] = Field(0.0, description="重量(kg)")
    weight_kg: Optional[float] = Field(0.0, description="重量(kg)")
    purchase_price: Optional[float] = Field(50.0, description="采购价(RMB)")
    profit_coefficient: Optional[float] = Field(1.0, description="利润系数/价格系数")
    optimal_channel: Optional[str] = Field("", description="最优物流渠道")
    optimal_freight: Optional[float] = Field(0.0, description="最优运费(RMB)")
    shipping_channel: Optional[str] = Field("", description="变体表格快递选择")
    main_image: Optional[str] = Field("", description="主图文件路径")
    variant_image: Optional[str] = Field("", description="变体图片相对路径")
    swatch_image: Optional[str] = Field("", description="色块图文件路径")
    extra_images: Optional[List[str]] = Field(default_factory=list, description="附图文件路径列表")


class ProductCreateSchema(BaseModel):
    """商品创建 / 录入数据模型 (对标店小秘 Amazon 商品录入标准与本地数据库单表结构)"""
    model_config = {"protected_namespaces": ()}
    store_account: str = Field(..., description="店铺账号，如 金梧汇辰")
    site: str = Field("日本", description="目标站点，如 日本")
    parent_sku: Optional[str] = Field("", description="Parent SKU (父SKU)")
    manufacturer: Optional[str] = Field("", description="制造商 (Manufacturer)")
    product_id_type: str = Field("EAN", description="产品ID类型 (EAN/UPC)")
    product_id_value: Optional[str] = Field("", description="产品ID数值")
    title: str = Field(..., description="商品标题")
    brand: Optional[str] = Field("", description="品牌")
    category_name: Optional[str] = Field("", description="产品分类")
    category_type: Optional[str] = Field("", description="平台推荐产品类型代码 (如 LITTER_BOX)")
    model_number: Optional[str] = Field("", description="品番・型番(型号)")
    model_name: Optional[str] = Field("", description="モデル名(型号名称)")
    item_length: Optional[float] = Field(0.0, description="品目寸法 长")
    item_width: Optional[float] = Field(0.0, description="品目寸法 宽")
    item_height: Optional[float] = Field(0.0, description="品目寸法 高")
    item_dimension_unit: Optional[str] = Field("cm", description="品目寸法单位")
    package_length: Optional[float] = Field(0.0, description="パッケージ寸法 长")
    package_width: Optional[float] = Field(0.0, description="パッケージ寸法 宽")
    package_height: Optional[float] = Field(0.0, description="パッケージ寸法 高")
    package_dimension_unit: Optional[str] = Field("cm", description="パッケージ寸法单位")
    package_weight: Optional[float] = Field(0.0, description="包装時の重さ")
    package_weight_unit: Optional[str] = Field("kg", description="包装重量单位")
    main_image: Optional[str] = Field("", description="产品主图相对路径")
    extra_images: Optional[List[str]] = Field(default_factory=list, description="产品附图列表相对路径")
    sale_type: str = Field("variation", description="售卖形式: variation / single")
    variation_theme: str = Field("カラー/サイズ(颜色/尺寸)", description="变种主题")
    color_options: Optional[List[str]] = Field(default_factory=list, description="颜色选项清单 (父节点)")
    size_options: Optional[List[str]] = Field(default_factory=list, description="尺寸选项清单 (父节点)")
    variant_image_dimension: Optional[str] = Field("color", description="变体图片录入维度: color / size")
    variant_dimension_images: Optional[Dict[str, str]] = Field(default_factory=dict, description="各属性图片相对路径映射")
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="变种属性字典"
    )
    bullet_points: Optional[List[str]] = Field(default_factory=list, description="商品亮点列表 (五点描述)")
    chinese_translations: Optional[List[str]] = Field(default_factory=list, description="五点描述中文翻译参考")
    description: Optional[str] = Field("", description="商品描述")
    search_terms: Optional[str] = Field("", description="搜索关键词 (Search Terms)")
    fulfillment_channel: Optional[str] = Field("FBM", description="配送渠道 (默认 FBM)")
    created_by: Optional[str] = Field("admin", description="添加人/操作用户")
    variations: List[VariationItemSchema] = Field(default_factory=list, description="变体矩阵列表")


class ProductResponseSchema(ProductCreateSchema):
    """商品详情响应模型"""
    model_config = {"protected_namespaces": ()}
    id: int
    status: str
    created_at: str
    updated_at: str


class GenerateMatrixRequest(BaseModel):
    """生成变体矩阵请求"""
    colors: List[str] = Field(default_factory=list)
    sizes: List[str] = Field(default_factory=list)
    base_sku: Optional[str] = "DOG-TOILET"
    base_price: Optional[float] = 4000.0
    base_quantity: Optional[int] = 40
    base_purchase_price: Optional[float] = 50.0
    base_profit_coefficient: Optional[float] = 1.0


class CalculateSinglePricingRequest(BaseModel):
    """单 SKU 测算请求"""
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0
    weight_kg: float = 0.1
    purchase_price_rmb: float = 50.0
    profit_coefficient: float = 1.0


class CalculateBatchPricingRequest(BaseModel):
    """批量 SKU 测算请求"""
    items: List[CalculateSinglePricingRequest] = Field(default_factory=list)
