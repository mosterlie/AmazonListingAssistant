"""
任务管理 Pydantic 数据验证与响应模型
"""
from typing import Optional
from pydantic import BaseModel, Field


class TaskCreateSchema(BaseModel):
    """管理员派发任务入参模型"""
    title: Optional[str] = Field("", description="任务标题或简述")
    reference_url: str = Field(..., description="1. 参考链接 (必填)")
    instructions: Optional[str] = Field("", description="2. 任务说明与要求")
    assigned_to: str = Field(..., description="执行人用户名 (必填)")


class TaskUpdateSchema(BaseModel):
    """管理员更新任务基本信息入参模型"""
    title: Optional[str] = Field(None, description="任务标题")
    reference_url: Optional[str] = Field(None, description="参考链接")
    instructions: Optional[str] = Field(None, description="任务说明")
    assigned_to: Optional[str] = Field(None, description="执行人用户名")


class TaskSubmitSchema(BaseModel):
    """执行人/管理员登记成果与关联商品入参模型 (成品链接与关联商品均为必填项)"""
    result_url: str = Field(..., min_length=1, description="1. 成品链接 (必填)")
    product_id: int = Field(..., gt=0, description="2. 关联的已录入商品 ID (必填且大于0)")


class TaskResponseSchema(BaseModel):
    """任务响应数据模型"""
    id: int
    title: str = ""
    reference_url: str = ""
    instructions: str = ""
    assigned_by: str = ""
    assigned_to: str = ""
    assigned_to_name: str = ""
    assigned_at: str = ""
    result_url: str = ""
    submitted_at: Optional[str] = None
    product_id: int = 0
    product_title: str = ""
    product_parent_sku: str = ""
    product_main_image: str = ""
    status: str = "pending"  # pending: 待处理, completed: 已完成
    created_at: str = ""
    updated_at: str = ""

    model_config = {
        "protected_namespaces": ()
    }
