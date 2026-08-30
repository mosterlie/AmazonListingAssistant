"""
用户认证与管理相关 Pydantic 数据模型
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class UserLoginSchema(BaseModel):
    """用户登录请求模型"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserCreateSchema(BaseModel):
    """创建新用户模型"""
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=4, max_length=100, description="密码")
    display_name: Optional[str] = Field("", description="昵称/姓名备注")
    role: str = Field("user", description="用户角色: admin | user")
    status: str = Field("active", description="用户状态: active | disabled")


class UserUpdateSchema(BaseModel):
    """更新用户信息模型"""
    display_name: Optional[str] = Field(None, description="昵称/姓名备注")
    password: Optional[str] = Field(None, description="新密码(不填则保持不变)")
    role: Optional[str] = Field(None, description="用户角色: admin | user")
    status: Optional[str] = Field(None, description="用户状态: active | disabled")


class UserResponseSchema(BaseModel):
    """用户响应数据模型"""
    id: int
    username: str
    display_name: str = ""
    role: str = "user"
    status: str = "active"
    created_at: Optional[str] = None

    class Config:
        from_attributes = True
