"""
初道物流 API 路由层 (运单管理模块: 运单查询 / 轨迹跟踪)

权限: 查询/入库/单票刷新/查轨迹 登录即可; 全量刷新/妙手同步/删除运单为按钮权限点控制 (RBAC)。
初道 API 无订单列表接口 → 数据源为本地运单库 (waybill_service.py)。
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from server.dependencies import get_current_user
from server.services.chudao_service import ChudaoService, ChudaoApiError
from server.services.miaoshou_service import MiaoshouService, MiaoshouApiError
from server.services.waybill_service import WaybillService
from server.services.rbac_service import RbacService, require_perm

router = APIRouter(prefix="/api/chudao", tags=["运单管理·初道物流"])


class WaybillAddSchema(BaseModel):
    """批量入库: numbers 支持参考号/运单号混贴, 后端自动清洗去重"""
    numbers: List[str] = Field(default_factory=list, description="单号列表")


class WaybillRefreshSchema(BaseModel):
    """批量刷新状态: ids 为空则刷新全部"""
    ids: Optional[List[int]] = None


@router.get("/waybills", summary="运单列表 (keyword 模糊搜索单号)")
def list_waybills(keyword: str = Query("", max_length=128),
                  user: dict = Depends(get_current_user)):
    data = WaybillService.list_waybills(keyword=keyword)
    return {"code": 0, "msg": "查询成功", "data": data}


@router.post("/waybills", summary="批量入库单号 (自动识别+查状态)")
def add_waybills(payload: WaybillAddSchema, user: dict = Depends(get_current_user)):
    try:
        result = WaybillService.add_numbers(payload.numbers, created_by=user.get("username", ""))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    return {"code": 0, "msg": "入库完成", "data": result}


@router.post("/waybills/refresh", summary="批量刷新运输状态 (ids为空刷全部, 需「全部刷新」按钮权限)")
def refresh_waybills(payload: WaybillRefreshSchema, user: dict = Depends(get_current_user)):
    # 全量刷新 (ids 为空) 需要独立按钮权限; 单票刷新登录即可
    if not payload.ids and not RbacService.user_has_perm(user, "waybill:refresh_all"):
        raise HTTPException(status_code=403, detail="无操作权限: 全部刷新")
    data = WaybillService.refresh_waybills(payload.ids)
    return {"code": 0, "msg": "刷新完成", "data": data}


@router.post("/waybills/sync-miaoshou", summary="从妙手ERP同步已发货包裹运单号入库 (需「妙手同步」按钮权限)")
def sync_miaoshou(user: dict = Depends(require_perm("waybill:sync"))):
    try:
        packages = MiaoshouService.fetch_shipped_packages()
    except MiaoshouApiError as exc:
        raise HTTPException(status_code=502, detail=f"妙手API调用失败: {exc}")
    result = WaybillService.sync_from_miaoshou(packages, created_by=user.get("username", ""))
    msg = f"同步完成: 妙手取回 {result['fetched']} 个包裹, 新入库 {len(result['added'])}, 已存在 {len(result['existing'])}"
    if result["failed"]:
        msg += f", 失败 {len(result['failed'])}"
    return {"code": 0, "msg": msg, "data": result}


@router.delete("/waybills/{waybill_id}", summary="删除运单 (需「运单删除」按钮权限)")
def delete_waybill(waybill_id: int, user: dict = Depends(require_perm("waybill:delete"))):
    try:
        WaybillService.delete_waybill(waybill_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    return {"code": 0, "msg": "删除成功", "data": None}


@router.get("/track", summary="实时查询运单轨迹 (不落库)")
def query_track(number: str = Query(..., min_length=1, max_length=64, description="运单号或参考号"),
                user: dict = Depends(get_current_user)):
    try:
        track = ChudaoService.get_track(number.strip())
    except ChudaoApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not track:
        return {"code": 1, "msg": "初道系统中未查到该单号的轨迹", "data": None}
    return {"code": 0, "msg": "查询成功", "data": track}
