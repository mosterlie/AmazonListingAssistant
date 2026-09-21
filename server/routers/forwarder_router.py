"""
货代管理 API 路由层 (Forwarder Router)

权限: 列表全员可查看 (登录即可), 新增/更新/删除仅管理员。
"""
from fastapi import APIRouter, Depends, HTTPException

from server.dependencies import get_current_user, require_admin_user
from server.models.forwarder_schemas import ForwarderUpsertSchema
from server.services.forwarder_service import ForwarderService

router = APIRouter(prefix="/api/forwarders", tags=["货代管理模块"])


@router.get("", summary="货代列表 (全员可查看; 注册用户/密码仅管理员响应)")
def list_forwarders(user: dict = Depends(get_current_user)):
    include_secret = user.get("role") == "admin"
    return {"code": 0, "msg": "查询成功",
            "data": ForwarderService.list_forwarders(include_secret=include_secret)}


@router.post("", summary="新增货代 (仅管理员)")
def create_forwarder(payload: ForwarderUpsertSchema, user: dict = Depends(require_admin_user)):
    data = ForwarderService.create_forwarder(payload, operator=user.get("username", ""))
    return {"code": 0, "msg": "新增成功", "data": data}


@router.put("/{fid}", summary="更新货代 (仅管理员)")
def update_forwarder(fid: int, payload: ForwarderUpsertSchema, user: dict = Depends(require_admin_user)):
    try:
        data = ForwarderService.update_forwarder(fid, payload, operator=user.get("username", ""))
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    return {"code": 0, "msg": "更新成功", "data": data}


@router.delete("/{fid}", summary="删除货代 (仅管理员)")
def delete_forwarder(fid: int, user: dict = Depends(require_admin_user)):
    try:
        ForwarderService.delete_forwarder(fid)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    return {"code": 0, "msg": "删除成功", "data": None}
