"""
告警任务/提醒任务/告警中心 REST API 路由

- GET  /api/alert-tasks                       告警任务列表=轮询采集配置 (登录用户可看)
- POST /api/alert-tasks/{key}/config          保存任务配置 (仅管理员)
- POST /api/alert-tasks/{key}/run             立即执行采集批次 (仅管理员)
- POST /api/alert-tasks/dxm_order/test-login  测试店小秘登录态 (仅管理员)
- GET  /api/reminders                         提醒任务列表=邮件提醒配置 (登录用户可看)
- POST /api/reminders/{key}/config            保存提醒配置 (仅管理员)
- POST /api/reminders/{key}/test-email        发送提醒测试邮件 (仅管理员)
- GET  /api/alerts/summary                    告警中心统计 (登录用户)
- GET  /api/alerts/list                       统一告警列表 (登录用户)
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Any, Dict, Optional

from server.dependencies import get_current_user, require_admin_user
from server.services import alert_service

router = APIRouter(prefix="/api", tags=["Alert Tasks & Center"])


@router.get("/alert-tasks")
async def get_tasks(user: Dict[str, Any] = Depends(get_current_user)):
    """告警任务列表 (配置密码脱敏, 仅管理员可改)"""
    return {"code": 0, "msg": "success", "data": alert_service.AlertService.get_tasks()}


@router.post("/alert-tasks/{key}/config")
async def save_task_config(key: str, payload: Dict[str, Any] = Body(default={}),
                           admin: Dict[str, Any] = Depends(require_admin_user)):
    """保存指定任务配置 (白名单过滤; 密码留空=保持原值)"""
    patch = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    try:
        task = alert_service.AlertService.save_task_config(key, patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置异常: {e}")
    return {"code": 0, "msg": "配置已保存", "data": task}


@router.post("/alert-tasks/{key}/run")
async def run_task(key: str, admin: Dict[str, Any] = Depends(require_admin_user)):
    """立即执行采集批次 (非阻塞后台线程, 用 GET /alert-tasks 轮询状态)"""
    try:
        res = alert_service.AlertService.run_task(key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0 if res.get("started") else 1, "msg": res.get("msg", ""), "data": res}


@router.post("/alert-tasks/dxm_order/test-login")
async def test_dxm_login(payload: Optional[Dict[str, Any]] = Body(default=None),
                         admin: Dict[str, Any] = Depends(require_admin_user)):
    """测试店小秘登录态 (未登录则用配置账密模拟登录, 含验证码 OCR; 同步阻塞约30s)"""
    override = payload.get("config") if isinstance(payload, dict) and isinstance(payload.get("config"), dict) else None
    try:
        res = alert_service.AlertService.test_dxm_login(override)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试登录异常: {e}")
    return {"code": 0 if res.get("ok") else 1, "msg": res.get("msg", ""), "data": res}


@router.get("/reminders")
async def get_reminders(user: Dict[str, Any] = Depends(get_current_user)):
    """提醒任务列表 (邮件提醒配置, 与轮询采集解耦; 仅管理员可改)"""
    return {"code": 0, "msg": "success", "data": alert_service.AlertService.get_reminders()}


@router.post("/reminders/{key}/config")
async def save_reminder_config(key: str, payload: Dict[str, Any] = Body(default={}),
                               admin: Dict[str, Any] = Depends(require_admin_user)):
    """保存指定提醒任务配置 (白名单过滤)"""
    patch = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    try:
        reminder = alert_service.AlertService.save_reminder_config(key, patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置异常: {e}")
    return {"code": 0, "msg": "配置已保存", "data": reminder}


@router.post("/reminders/{key}/test-email")
async def test_reminder_email(key: str, payload: Optional[Dict[str, Any]] = Body(default=None),
                              admin: Dict[str, Any] = Depends(require_admin_user)):
    """发送提醒测试邮件 (请求体可带 {config:{...}} 表单当前值, 优先使用不落库)"""
    override = payload.get("config") if isinstance(payload, dict) and isinstance(payload.get("config"), dict) else None
    try:
        status = alert_service.AlertService.test_reminder_email(key, override)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if status == "sent":
        return {"code": 0, "msg": "测试邮件已发送", "data": {"status": status}}
    raise HTTPException(status_code=400, detail=f"发送失败: {status}")


@router.get("/alerts/summary")
async def alerts_summary(user: Dict[str, Any] = Depends(get_current_user)):
    """告警中心顶部统计 (货代今日告警 / 店小秘黄红超时 / 汇总邮件最近发送)"""
    return {"code": 0, "msg": "success", "data": alert_service.AlertService.get_alert_summary()}


@router.get("/alerts/list")
async def alerts_list(source: Optional[str] = None, biz_date: Optional[str] = None,
                      alert_level: Optional[int] = None, keyword: str = "",
                      page: int = 1, page_size: int = 50,
                      user: Dict[str, Any] = Depends(get_current_user)):
    """统一告警列表 (source: forwarder/dxm/全部; level: 1黄/2红)"""
    if source not in (None, "", "forwarder", "dxm"):
        raise HTTPException(status_code=400, detail="source 仅支持 forwarder/dxm")
    data = alert_service.AlertService.list_alerts(
        source=source or None, biz_date=biz_date or None,
        alert_level=alert_level, keyword=keyword or "",
        page=page, page_size=page_size)
    return {"code": 0, "msg": "success", "data": data}
