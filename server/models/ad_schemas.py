"""
广告投放任务 Pydantic 数据验证与响应模型
（对应赛狐 ERP → SP 批量创建广告录入页字段）
"""
import re
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator

# ASIN 标准格式: 10 位大写字母/数字 (亚马逊 ASIN)
ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")

# 业务允许的枚举值 (与赛狐录入页下拉/单选保持一致)
CREATE_MODES = ["所有产品合并创建广告", "每个产品单独创建广告"]
BID_STRATEGIES = ["动态竞价-只降低", "动态竞价-提高和降低", "固定竞价"]

# 数值边界
BUDGET_MIN, BUDGET_MAX = 1, 1_000_000
BID_MIN, BID_MAX = 0.01, 1_000_000
ASIN_MAX_COUNT = 500


def parse_asins(raw: str, dedup: bool = True) -> List[str]:
    """
    解析批量输入的 ASIN 文本。
    支持分隔符: 逗号(中英文)、分号、换行、空格、制表符
    自动转大写并剔除空项; 是否去重由 dedup 控制 (默认去重)。

    注意: 转大写属于 ASIN 格式规范化, 与去重无关, 关闭去重时依然生效。
    """
    if not raw:
        return []
    parts = re.split(r"[,，;；\s\r\n\t]+", raw.strip())
    if dedup:
        out, seen = [], set()
        for p in parts:
            a = p.strip().upper()
            if a and a not in seen:
                seen.add(a)
                out.append(a)
        return out
    return [p.strip().upper() for p in parts if p.strip()]


class AdTaskCreateSchema(BaseModel):
    """新增广告投放任务入参模型"""
    task_name: str = Field(..., min_length=1, description="任务名称")
    shop_name: str = Field(..., min_length=1, description="1. 店铺名称")
    create_mode: str = Field("所有产品合并创建广告", description="2. 创建方式")
    start_date: str = Field(..., description="3. 开始时间 YYYY-MM-DD (默认当天)")
    end_date: Optional[str] = Field("", description="3. 结束时间 YYYY-MM-DD (可空)")
    daily_budget: float = Field(300, description="4. 每日预算 (默认 300)")
    bid_strategy: str = Field("动态竞价-只降低", description="5. 竞价策略 (默认动态竞价-只降低)")
    default_bid: float = Field(15, description="6. 默认竞价 (默认 15)")
    asins_text: str = Field(..., min_length=1, description="7. ASIN 列表 (逗号分隔)")
    auto_dedup: bool = Field(False, description="是否自动去除重复 ASIN (默认否)")
    batch_size: int = Field(20, description="8. 批次数量 (每批最多处理的 ASIN 数, 默认 20)")

    @field_validator("task_name", "shop_name")
    @classmethod
    def _strip_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("该项为必填，不能为空")
        return v

    @field_validator("create_mode")
    @classmethod
    def _check_create_mode(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in CREATE_MODES:
            raise ValueError(f"创建方式仅支持: {' / '.join(CREATE_MODES)}")
        return v

    @field_validator("bid_strategy")
    @classmethod
    def _check_bid_strategy(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in BID_STRATEGIES:
            raise ValueError(f"竞价策略仅支持: {' / '.join(BID_STRATEGIES)}")
        return v

    @field_validator("start_date")
    @classmethod
    def _check_start_date(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("开始时间不能为空")
        _assert_date(v, "开始时间")
        return v

    @field_validator("end_date")
    @classmethod
    def _check_end_date(cls, v: Optional[str]) -> str:
        return (v or "").strip()

    @field_validator("daily_budget")
    @classmethod
    def _check_budget(cls, v: float) -> float:
        if v is None or v < BUDGET_MIN or v > BUDGET_MAX:
            raise ValueError(f"每日预算需在 {BUDGET_MIN} ~ {BUDGET_MAX} 之间")
        return round(float(v), 2)

    @field_validator("default_bid")
    @classmethod
    def _check_bid(cls, v: float) -> float:
        if v is None or v < BID_MIN or v > BID_MAX:
            raise ValueError(f"默认竞价需在 {BID_MIN} ~ {BID_MAX} 之间")
        return round(float(v), 2)

    @field_validator("batch_size")
    @classmethod
    def _check_batch(cls, v: int) -> int:
        v = int(v or 0)
        if v < 0:
            raise ValueError("批次数量不能为负数")
        return v


def _assert_date(text: str, label: str):
    """校验 YYYY-MM-DD 合法日期"""
    from datetime import datetime
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except Exception:
        raise ValueError(f"{label}格式非法，需为 YYYY-MM-DD（如 2026-09-06）")


class AdTaskUpdateSchema(BaseModel):
    """编辑广告投放任务入参模型 (字段均可选)"""
    task_name: Optional[str] = Field(None, description="任务名称")
    shop_name: Optional[str] = Field(None, description="店铺名称")
    create_mode: Optional[str] = Field(None, description="创建方式")
    start_date: Optional[str] = Field(None, description="开始时间")
    end_date: Optional[str] = Field(None, description="结束时间")
    daily_budget: Optional[float] = Field(None, description="每日预算")
    bid_strategy: Optional[str] = Field(None, description="竞价策略")
    default_bid: Optional[float] = Field(None, description="默认竞价")
    asins_text: Optional[str] = Field(None, description="ASIN 列表")
    auto_dedup: Optional[bool] = Field(None, description="是否自动去除重复 ASIN")
    batch_size: Optional[int] = Field(None, description="批次数量")


class AdTaskRunSchema(BaseModel):
    """触发自动投放入参模型"""
    submit: bool = Field(False, description="是否自动提交 (当前阶段固定为不提交)")
