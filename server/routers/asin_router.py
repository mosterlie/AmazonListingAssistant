"""
ASIN 生成池 API 路由层 (Asin Pool Router)

提供赛狐在线产品 Excel 父子 ASIN 导入、排除式随机生成 ASIN、
生成记录查询、入库 ASIN 总览与模板下载。
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from starlette.responses import Response
from urllib.parse import quote

from server.routers.ad_router import require_admin
from server.services.asin_pool_service import AsinPoolService

router = APIRouter(prefix="/api/asin-pool", tags=["ASIN生成池模块"])


@router.get("/template", summary="下载 Excel 导入模板")
def download_template(user: dict = Depends(require_admin)):
    content = AsinPoolService.build_template()
    filename = quote("ASIN父子关系导入模板.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/import", summary="导入赛狐在线产品 Excel (父子ASIN, 追加批次)")
async def import_excel(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    if not (file.filename or "").lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")
    content = await file.read()
    try:
        data = AsinPoolService.import_excel(file.filename, content, operator=user.get("username", ""))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    return {"code": 0, "msg": "导入成功", "data": data}


@router.get("/batches", summary="导入批次列表 (首条为当前生效批次)")
def list_batches(user: dict = Depends(require_admin)):
    return {"code": 0, "msg": "查询成功", "data": AsinPoolService.list_batches()}


@router.delete("/all", summary="清空 ASIN 生成池 (全部导入批次/父子关系/生成记录)")
def purge_all(user: dict = Depends(require_admin)):
    counts = AsinPoolService.purge_all()
    return {"code": 0,
            "msg": f"已清空: {counts['batches']} 个批次, {counts['pairs']} 对父子关系, {counts['logs']} 条生成记录",
            "data": counts}


@router.post("/generate", summary="输入已投放ASIN, 从未覆盖父体随机生成ASIN")
async def generate_asins(request: Request, user: dict = Depends(require_admin)):
    body = await request.json()
    asins_text = (body or {}).get("asins_text", "")
    try:
        data = AsinPoolService.generate(asins_text, operator=user.get("username", ""))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    return {"code": 0, "msg": "生成成功", "data": data}


@router.get("/query-logs", summary="ASIN 获取记录")
def list_query_logs(limit: int = Query(50, ge=1, le=500), user: dict = Depends(require_admin)):
    return {"code": 0, "msg": "查询成功", "data": AsinPoolService.list_query_logs(limit)}


@router.get("/overview", summary="入库 ASIN 总览 (当前批次统计+父体分页)")
def overview(
    search: Optional[str] = Query(None, description="父ASIN关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user: dict = Depends(require_admin),
):
    return {"code": 0, "msg": "查询成功",
            "data": AsinPoolService.overview(search=search or "", page=page, page_size=page_size)}


@router.get("/parents/{parent}/children", summary="查看某父ASIN下的全部子ASIN")
def list_children(parent: str, batch_id: Optional[int] = None, user: dict = Depends(require_admin)):
    try:
        data = AsinPoolService.list_children(parent, batch_id=batch_id)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    return {"code": 0, "msg": "查询成功", "data": data}
