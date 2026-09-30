"""
RBAC 权限管理 API (仅管理员): 角色CRUD / 角色菜单与按钮权限配置 / 用户角色分配
"""
from typing import List

from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel

from server.dependencies import get_current_user_from_request
from server.services.rbac_service import RbacService, MENU_REGISTRY, PERMISSION_REGISTRY

router = APIRouter(prefix="/api/rbac", tags=["RBAC权限管理"])


def _require_admin(request: Request):
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或会话已过期")
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可操作权限配置")
    return user


class RoleCreateSchema(BaseModel):
    code: str
    name: str
    description: str = ""


class RoleConfigSchema(BaseModel):
    menus: List[str] = []
    permissions: List[str] = []


class UserRoleSchema(BaseModel):
    role_ids: List[int] = []


@router.get("/roles", summary="角色列表(含菜单/权限点/用户数)")
def list_roles(request: Request):
    _require_admin(request)
    return {"roles": RbacService.list_roles(),
            "menu_registry": MENU_REGISTRY,
            "permission_registry": [{"key": k, **v} for k, v in PERMISSION_REGISTRY.items()]}


@router.post("/roles", summary="新建角色")
def create_role(request: Request, data: RoleCreateSchema):
    _require_admin(request)
    try:
        return {"role": RbacService.create_role(data.code, data.name, data.description)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/roles/{role_id}/delete", summary="删除角色(内置不可删)")
def delete_role(request: Request, role_id: int):
    _require_admin(request)
    try:
        RbacService.delete_role(role_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/roles/{role_id}/config", summary="配置角色菜单与按钮权限")
def config_role(request: Request, role_id: int, data: RoleConfigSchema):
    _require_admin(request)
    try:
        RbacService.update_role_config(role_id, data.menus, data.permissions)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/user-roles-map", summary="全部用户的角色绑定映射 (用户列表徽章用)")
def user_roles_map(request: Request):
    _require_admin(request)
    from server.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ur.user_id, r.id AS role_id, r.name AS role_name
        FROM user_roles ur JOIN roles r ON r.id = ur.role_id;
    """)
    mapping = {}
    for row in cursor.fetchall():
        mapping.setdefault(str(row["user_id"]), []).append(
            {"role_id": row["role_id"], "role_name": row["role_name"]})
    conn.close()
    return {"map": mapping}


@router.get("/users/{user_id}/roles", summary="查询用户绑定的角色")
def get_user_roles(request: Request, user_id: int):
    _require_admin(request)
    return {"role_ids": RbacService.get_user_roles(user_id)}


@router.post("/users/{user_id}/roles", summary="配置用户角色(多对多)")
def set_user_roles(request: Request, user_id: int, data: UserRoleSchema):
    _require_admin(request)
    try:
        RbacService.set_user_roles(user_id, data.role_ids)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
