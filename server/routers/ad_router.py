"""
广告投放任务 API 路由层 (Ad Router)
"""
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Depends, Query, status
from server.routers.auth_router import get_current_user_from_request
from server.services.ad_service import AdTaskService
from server.models.ad_schemas import AdTaskCreateSchema, AdTaskUpdateSchema

router = APIRouter(prefix="/api/ads", tags=["赛狐广告投放任务模块"])


def require_auth(request: Request):
    """通用登录认证依赖"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录中台账号！"
        )
    return user


def require_admin(request: Request):
    """管理员权限专属依赖"""
    user = require_auth(request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作需要管理员权限！"
        )
    return user


@router.get("/options", summary="获取广告任务录入表单的下拉选项")
async def get_ad_options(user: dict = Depends(require_admin)):
    return {"code": 0, "msg": "获取成功", "data": AdTaskService.get_options()}


@router.get("/tasks", summary="查询广告投放任务列表")
async def list_ad_tasks(
    status: Optional[str] = Query(None, description="状态过滤 (all/pending/running/success/partial/failed)"),
    search: Optional[str] = Query(None, description="搜索关键词 (任务名/店铺/ASIN)"),
    shop_name: Optional[str] = Query(None, description="店铺筛选"),
    user: dict = Depends(require_admin)
):
    tasks = AdTaskService.list_tasks(status=status, search=search, shop_name=shop_name)
    return {"code": 0, "msg": "查询成功", "data": tasks, "total": len(tasks)}


@router.post("/tasks", summary="新增广告投放任务")
async def create_ad_task(data: AdTaskCreateSchema, user: dict = Depends(require_admin)):
    try:
        task = AdTaskService.create_task(data, current_user=user)
        return {"code": 0, "msg": "广告任务创建成功！", "data": task}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.get("/tasks/{task_id}", summary="获取广告任务详情")
async def get_ad_task(task_id: int, user: dict = Depends(require_admin)):
    task = AdTaskService.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="广告任务不存在！")
    return {"code": 0, "msg": "获取成功", "data": task}


@router.put("/tasks/{task_id}", summary="编辑广告投放任务")
async def update_ad_task(task_id: int, data: AdTaskUpdateSchema, user: dict = Depends(require_admin)):
    try:
        task = AdTaskService.update_task(task_id, data)
        return {"code": 0, "msg": "广告任务更新成功！", "data": task}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/tasks/{task_id}", summary="删除广告投放任务")
async def delete_ad_task(task_id: int, admin: dict = Depends(require_admin)):
    ok = AdTaskService.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="指定广告任务不存在或已删除！")
    return {"code": 0, "msg": "广告任务已成功删除！"}


@router.post("/tasks/{task_id}/run", summary="执行自动投放（调用赛狐自动化，暂不提交）")
async def run_ad_task(task_id: int, user: dict = Depends(require_admin)):
    try:
        res = AdTaskService.start_run(task_id, operator=user)
        return {"code": 0, "msg": "自动投放任务已启动，请轮询执行状态获取进度", "data": res}
    except ValueError as ve:
        # 参数/环境校验未通过
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as rerr:
        raise HTTPException(status_code=409, detail=str(rerr))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@router.post("/tasks/{task_id}/stop", summary="请求终止正在执行的自动投放任务")
async def stop_ad_task(task_id: int, user: dict = Depends(require_admin)):
    accepted = AdTaskService.request_stop(task_id)
    if not accepted:
        raise HTTPException(status_code=409, detail="该任务当前未在执行，无需终止")
    return {"code": 0, "msg": "终止请求已受理，任务将在当前 ASIN 录入环节结束后停止"}


@router.get("/tasks/{task_id}/run-status", summary="实时查询自动投放执行状态与增量日志")
async def get_ad_run_status(task_id: int, since: int = 0, user: dict = Depends(require_admin)):
    st = AdTaskService.get_run_status(task_id, since=since)
    return {"code": 0, "msg": "success", "data": st}


@router.get("/tasks/{task_id}/runs", summary="查询广告任务的历史执行记录")
async def list_ad_runs(task_id: int, limit: int = 20, user: dict = Depends(require_admin)):
    runs = AdTaskService.list_runs(task_id, limit=limit)
    return {"code": 0, "msg": "查询成功", "data": runs, "total": len(runs)}


@router.get("/runs/{run_id}", summary="获取单条执行记录详情（含完整日志与跳过明细）")
async def get_ad_run(run_id: int, user: dict = Depends(require_admin)):
    run = AdTaskService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在！")
    return {"code": 0, "msg": "获取成功", "data": run}


@router.get("/cdp-status", summary="检测 CDP 调试浏览器是否可用")
async def get_cdp_status(user: dict = Depends(require_admin)):
    ok = AdTaskService.check_cdp_available()
    return {"code": 0, "msg": "success", "data": {"available": ok}}


@router.post("/launch-browser", summary="启动 9222 调试浏览器并打开批量创建页")
async def launch_debug_browser(user: dict = Depends(require_admin)):
    try:
        ok, msg = AdTaskService.launch_debug_browser()
        if not ok:
            raise HTTPException(status_code=500, detail=msg)
        return {"code": 0, "msg": msg, "data": {"available": AdTaskService.check_cdp_available()}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动调试浏览器失败: {str(e)}")
