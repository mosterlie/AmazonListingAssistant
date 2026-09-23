"""
店小秘订单剩余发货时间预警 REST API 路由

- GET  /api/dxm-orders/status        采集状态 + 预警统计 (全员)
- GET  /api/dxm-orders/list          订单预警列表 (全员, 剩余时间升序)
- POST /api/dxm-orders/run           手动立即采集 (仅管理员; 非阻塞后台线程)
- POST /api/dxm-orders/test-login    测试登录态/模拟登录 (仅管理员, 同步阻塞约30s)
- POST /api/dxm-orders/test-email    发送测试预警邮件 (仅管理员)
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Any, Dict, Optional

from server.dependencies import require_admin_user
from server.services import dxm_order_service

router = APIRouter(prefix="/api/dxm-orders", tags=["DXM Order Deadline Alert"])


@router.get("/status")
async def get_status():
    """采集状态: 最近批次 + 运行标志 + 预警统计 + 配置摘要 (密码脱敏)"""
    return {"code": 0, "msg": "success", "data": dxm_order_service.DxmOrderService.get_status()}


@router.get("/list")
async def list_orders(alert_level: Optional[int] = None, pending_only: bool = True,
                      keyword: str = "", page: int = 1, page_size: int = 50):
    """订单预警列表 (按剩余时间升序; alert_level: 0无/1黄/2红)"""
    data = dxm_order_service.DxmOrderService.list_orders(
        alert_level=alert_level, pending_only=pending_only, keyword=keyword,
        page=max(1, page), page_size=min(200, max(1, page_size)))
    return {"code": 0, "msg": "success", "data": data}


@router.post("/run")
async def run_now(admin: Dict[str, Any] = Depends(require_admin_user)):
    """手动触发采集批次 (非阻塞: 后台线程执行, 用 /status 轮询)"""
    if dxm_order_service.DxmOrderService.is_running():
        return {"code": 1, "msg": "采集批次运行中, 请稍后", "data": None}
    import threading
    threading.Thread(
        target=dxm_order_service.DxmOrderService.run_batch,
        kwargs={"trigger": "manual"}, daemon=True).start()
    return {"code": 0, "msg": "采集批次已启动", "data": None}


@router.post("/test-login")
async def test_login(payload: Optional[Dict[str, Any]] = Body(default=None),
                     admin: Dict[str, Any] = Depends(require_admin_user)):
    """测试登录态 (未登录则用配置账密模拟登录, 含验证码 OCR; 同步阻塞约30s)"""
    override = None
    if isinstance(payload, dict) and isinstance(payload.get("dxm_order"), dict):
        override = payload["dxm_order"]
    try:
        res = dxm_order_service.DxmOrderService.test_login(override)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试登录异常: {e}")
    return {"code": 0 if res.get("ok") else 1, "msg": res.get("msg", ""), "data": res}


@router.post("/test-email")
async def test_email(payload: Optional[Dict[str, Any]] = Body(default=None),
                     admin: Dict[str, Any] = Depends(require_admin_user)):
    """发送测试预警邮件; 请求体可带 {dxm_order:{...}} 表单当前值 (优先使用, 不落库)"""
    override = None
    if isinstance(payload, dict) and isinstance(payload.get("dxm_order"), dict):
        override = payload["dxm_order"]
    status = dxm_order_service.DxmOrderService.send_test_email(override)
    if status == "sent":
        return {"code": 0, "msg": "测试邮件已发送", "data": {"status": status}}
    raise HTTPException(status_code=400, detail=f"发送失败: {status}")
