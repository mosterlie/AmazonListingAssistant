"""
任务管理 API 路由层 (Task Router)
"""
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Depends, Query, status
from server.routers.auth_router import get_current_user_from_request
from server.services.task_service import TaskService
from server.models.task_schemas import TaskCreateSchema, TaskUpdateSchema, TaskSubmitSchema

router = APIRouter(prefix="/api/tasks", tags=["任务管理模块"])


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


@router.get("", summary="查询任务列表（按角色权限隔离）")
async def list_tasks(
    request: Request,
    status: Optional[str] = Query(None, description="状态过滤 (all/pending/completed)"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    assigned_to: Optional[str] = Query(None, description="执行人筛选 (仅管理员可用)"),
    user: dict = Depends(require_auth)
):
    tasks = TaskService.list_tasks(
        current_user=user,
        status_filter=status,
        search=search,
        assigned_to_filter=assigned_to
    )
    return {"code": 0, "msg": "查询成功", "data": tasks, "total": len(tasks)}


@router.get("/products/options", summary="获取可关联的商品下拉选项列表")
async def get_product_options(user: dict = Depends(require_auth)):
    products = TaskService.get_product_options()
    return {"code": 0, "msg": "获取成功", "data": products}


@router.post("", summary="管理员派发新任务")
async def create_task(
    data: TaskCreateSchema,
    admin: dict = Depends(require_admin)
):
    try:
        task = TaskService.create_task(data, current_user=admin)
        return {"code": 0, "msg": "任务派发成功！", "data": task}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{task_id}", summary="获取任务详情")
async def get_task_detail(
    task_id: int,
    user: dict = Depends(require_auth)
):
    task = TaskService.get_task_by_id(task_id, current_user=user)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权查看！")
    return {"code": 0, "msg": "获取成功", "data": task}


@router.post("/{task_id}/submit", summary="登记成果信息与关联商品")
async def submit_task_deliverable(
    task_id: int,
    data: TaskSubmitSchema,
    user: dict = Depends(require_auth)
):
    try:
        updated_task = TaskService.submit_task_deliverable(task_id, data, current_user=user)
        return {"code": 0, "msg": "成果信息登记成功！", "data": updated_task}
    except ValueError as ve:
        raise HTTPException(status_code=403, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"登记失败: {str(e)}")


@router.put("/{task_id}", summary="管理员更新任务派发信息")
async def update_task(
    task_id: int,
    data: TaskUpdateSchema,
    admin: dict = Depends(require_admin)
):
    try:
        updated = TaskService.update_task(task_id, data)
        return {"code": 0, "msg": "任务更新成功！", "data": updated}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{task_id}", summary="管理员删除任务")
async def delete_task(
    task_id: int,
    admin: dict = Depends(require_admin)
):
    success = TaskService.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="指定任务不存在或已删除！")
    return {"code": 0, "msg": "任务已成功删除！"}
