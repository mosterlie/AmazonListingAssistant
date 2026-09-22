"""
货代在线登记文档采集 REST API 路由

- GET  /api/forwarder-docs/status        采集状态 (全员)
- GET  /api/forwarder-docs/alerts        未发货告警查询 (全员)
- GET  /api/forwarder-docs/records       每日快照查询 (全员)
- GET  /api/forwarder-docs/dates         有快照的日期列表 (全员)
- POST /api/forwarder-docs/run           手动立即采集 (仅管理员; 重跑=先删当天)
- POST /api/forwarder-docs/test-email    发送测试邮件 (仅管理员)
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Any, Dict, Optional

from server.dependencies import require_admin_user
from server.services import forwarder_doc_service

router = APIRouter(prefix="/api/forwarder-docs", tags=["Forwarder Doc Sync"])


@router.get("/status")
async def get_status():
    """采集状态: 最近批次 + 运行标志 + 当日告警数 + 配置摘要 (密码脱敏)"""
    return {"code": 0, "msg": "success", "data": forwarder_doc_service.ForwarderDocService.get_status()}


@router.get("/alerts")
async def list_alerts(biz_date: Optional[str] = None):
    """7天未发货告警列表 (默认全部日期最近500条)"""
    data = forwarder_doc_service.ForwarderDocService.list_alerts(biz_date)
    return {"code": 0, "msg": "success", "data": data}


@router.get("/records")
async def list_records(biz_date: Optional[str] = None, link_url: Optional[str] = None,
                       sheet_name: Optional[str] = None, page: int = 1, page_size: int = 50):
    """每日快照查询 (biz_date/link_url/sheet_name 过滤, 分页)"""
    data = forwarder_doc_service.ForwarderDocService.list_records(
        biz_date, link_url, sheet_name, max(1, page), min(200, max(1, page_size)))
    return {"code": 0, "msg": "success", "data": data}


@router.get("/dates")
async def list_dates():
    """有快照数据的采集日期列表 (倒序)"""
    return {"code": 0, "msg": "success",
            "data": forwarder_doc_service.ForwarderDocService.list_biz_dates()}


@router.post("/run")
async def run_now(admin: Dict[str, Any] = Depends(require_admin_user)):
    """手动触发采集批次 (非阻塞: 后台线程执行, 用 /status 轮询); 重跑=先删当天再入库"""
    if forwarder_doc_service.ForwarderDocService.is_running():
        return {"code": 1, "msg": "采集批次运行中, 请稍后", "data": None}
    import threading
    threading.Thread(
        target=forwarder_doc_service.ForwarderDocService.run_batch,
        kwargs={"trigger": "manual"}, daemon=True).start()
    return {"code": 0, "msg": "采集批次已启动", "data": None}


@router.post("/test-email")
async def test_email(payload: Optional[Dict[str, Any]] = Body(default=None),
                     admin: Dict[str, Any] = Depends(require_admin_user)):
    """发送测试邮件; 请求体可带 {doc_sync:{...}} 表单当前值 (优先使用, 不落库)"""
    override = None
    if isinstance(payload, dict) and isinstance(payload.get("doc_sync"), dict):
        override = payload["doc_sync"]
    status = forwarder_doc_service.ForwarderDocService.send_test_email(override)
    if status == "sent":
        return {"code": 0, "msg": "测试邮件已发送", "data": {"status": status}}
    raise HTTPException(status_code=400, detail=f"发送失败: {status}")
