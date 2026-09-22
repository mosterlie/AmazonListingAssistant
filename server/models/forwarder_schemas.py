"""
货代管理 Pydantic 数据验证模型
（货代基本信息 + 在线链接, 链接点击后新页签打开）
"""
from typing import List
from pydantic import BaseModel, Field, field_validator

# 单个货代最多维护的在线链接数
MAX_LINKS = 20


class ForwarderLinkSchema(BaseModel):
    """货代在线链接项"""
    label: str = Field("", max_length=64, description="链接名称 (空则前端展示域名)")
    url: str = Field(..., min_length=1, max_length=1024, description="链接地址")

    @field_validator("label", "url")
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()


class ForwarderUpsertSchema(BaseModel):
    """新增/更新货代入参模型"""
    name: str = Field(..., min_length=1, max_length=128, description="货代名称")
    contact: str = Field("", max_length=64, description="联系人")
    phone: str = Field("", max_length=64, description="联系电话")
    website: str = Field("", max_length=512, description="货代网址")
    reg_user: str = Field("", max_length=128, description="货代系统注册用户 (仅管理员可见)")
    reg_password: str = Field("", max_length=128, description="货代系统密码 (仅管理员可见)")
    shipping_address: str = Field("", max_length=512, description="收货地址")
    settlement_method: str = Field("", max_length=128, description="结算方式")
    remark: str = Field("", max_length=512, description="备注")
    sort_order: int = Field(0, ge=0, le=9999, description="排序 (越小越靠前)")
    links: List[ForwarderLinkSchema] = Field(default_factory=list, description="在线链接列表")

    @field_validator("links")
    @classmethod
    def _clean_links(cls, links: List[ForwarderLinkSchema]) -> List[dict]:
        """剔除无 url 的空行, 并限制数量"""
        out = []
        for lk in links or []:
            if lk.url:
                out.append({"label": lk.label, "url": lk.url})
            if len(out) >= MAX_LINKS:
                break
        return out

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("货代名称不能为空")
        return v
