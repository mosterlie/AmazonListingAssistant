"""
日本节假日日历 REST API 路由

- GET  /api/jp-holidays/calendar?year&month  月历数据 (含节假日/周末标记)
- GET  /api/jp-holidays/upcoming             未来节日+连休列表 (默认 advance_days, 可传 days)
- GET  /api/jp-holidays/status               同步/提醒状态+配置
- POST /api/jp-holidays/sync                  手动立即同步 (当年+次年)
- POST /api/jp-holidays/config                保存提醒配置 (仅管理员)
- POST /api/jp-holidays/test-email            发送测试提醒邮件 (仅管理员)
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Any, Dict, Optional

from server.dependencies import get_current_user, require_admin_user
from server.services import jp_holiday_service

router = APIRouter(prefix="/api/jp-holidays", tags=["Japan Holidays"])


@router.get("/calendar")
async def get_calendar(year: int, month: int,
                       user: Dict[str, Any] = Depends(get_current_user)):
    """月历数据 (每天附 is_holiday/is_weekend/休息日标记)"""
    try:
        data = jp_holiday_service.JpHolidayService.month_calendar(year, month)
    except ValueError:
        raise HTTPException(status_code=400, detail="year/month 参数无效")
    return {"code": 0, "msg": "success", "data": data}


@router.get("/upcoming")
async def get_upcoming(days: Optional[int] = None,
                       user: Dict[str, Any] = Depends(get_current_user)):
    """未来 N 天节假日+连休列表 (同连休只列首日, 含大节日标记)"""
    items = jp_holiday_service.JpHolidayService.upcoming(days=days)
    return {"code": 0, "msg": "success", "data": items}


@router.get("/status")
async def get_status(user: Dict[str, Any] = Depends(get_current_user)):
    """同步/提醒状态 + 当前配置 + 库内统计 + 未来90天节日"""
    return {"code": 0, "msg": "success",
            "data": jp_holiday_service.JpHolidayService.get_status()}


@router.post("/sync")
async def sync_now(admin: Dict[str, Any] = Depends(require_admin_user)):
    """手动立即同步当年+次年日历 (阻塞, 通常几秒)"""
    result = jp_holiday_service.JpHolidayService.sync_due(force=True)
    failed = [v for v in (result.get("years") or {}).values()
              if isinstance(v, str) and v.startswith("failed")]
    if failed:
        raise HTTPException(status_code=502, detail=f"同步失败: {'; '.join(failed)}")
    return {"code": 0, "msg": "日历已同步", "data": result}


@router.post("/config")
async def save_config(payload: Dict[str, Any] = Body(default={}),
                      admin: Dict[str, Any] = Depends(require_admin_user)):
    """保存提醒配置 (email_enabled/advance_days/mail_to; SMTP 通道在系统管理维护)"""
    patch = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    cfg = jp_holiday_service.JpHolidayService.save_config(patch)
    return {"code": 0, "msg": "配置已保存", "data": cfg}


@router.post("/test-email")
async def test_email(payload: Optional[Dict[str, Any]] = Body(default=None),
                     admin: Dict[str, Any] = Depends(require_admin_user)):
    """发送测试提醒邮件 (请求体可带 {config:{...}} 表单当前值, 优先使用不落库; 无临近节日时查未来90天)"""
    override = payload.get("config") if isinstance(payload, dict) and isinstance(payload.get("config"), dict) else None
    try:
        status = jp_holiday_service.JpHolidayService.send_test_email(override)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试邮件异常: {e}")
    if status == "sent":
        return {"code": 0, "msg": "测试邮件已发送", "data": {"status": status}}
    raise HTTPException(status_code=400, detail=f"发送失败: {status}")
