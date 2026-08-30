"""
用户管理 RESTful API 路由 (仅限管理员访问)
"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from server.models.user_schemas import UserCreateSchema, UserUpdateSchema
from server.services.auth_service import AuthService
from server.dependencies import require_admin_user

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.get("", summary="获取用户列表")
async def list_users(admin: Dict[str, Any] = Depends(require_admin_user)):
    """查询系统所有用户 (仅管理员)"""
    users = AuthService.list_users()
    return {"code": 0, "msg": "success", "data": users}


@router.post("", summary="创建新用户")
async def create_user(data: UserCreateSchema, admin: Dict[str, Any] = Depends(require_admin_user)):
    """管理员创建新用户"""
    try:
        user = AuthService.create_user(data)
        return {"code": 0, "msg": "用户创建成功！", "data": user}
    except ValueError as ve:
        return {"code": 400, "msg": str(ve), "data": None}
    except Exception as e:
        return {"code": 500, "msg": f"创建用户失败: {str(e)}", "data": None}


@router.get("/{user_id}", summary="获取单个用户详情")
async def get_user(user_id: int, admin: Dict[str, Any] = Depends(require_admin_user)):
    """获取单个用户信息"""
    user = AuthService.get_user_by_id(user_id)
    if not user:
        return {"code": 404, "msg": "用户不存在", "data": None}
    return {"code": 0, "msg": "success", "data": user}


@router.put("/{user_id}", summary="修改用户信息或重置密码")
async def update_user(user_id: int, data: UserUpdateSchema, admin: Dict[str, Any] = Depends(require_admin_user)):
    """修改用户信息"""
    try:
        user = AuthService.update_user(user_id, data)
        return {"code": 0, "msg": "用户信息更新成功！", "data": user}
    except ValueError as ve:
        return {"code": 400, "msg": str(ve), "data": None}
    except Exception as e:
        return {"code": 500, "msg": f"更新用户失败: {str(e)}", "data": None}


@router.delete("/{user_id}", summary="删除用户")
async def delete_user(user_id: int, admin: Dict[str, Any] = Depends(require_admin_user)):
    """删除用户"""
    try:
        AuthService.delete_user(user_id, current_user_id=admin["id"])
        return {"code": 0, "msg": "用户已成功删除！", "data": None}
    except ValueError as ve:
        return {"code": 400, "msg": str(ve), "data": None}
    except Exception as e:
        return {"code": 500, "msg": f"删除用户失败: {str(e)}", "data": None}
