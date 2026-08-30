"""
图片上传 API 路由
"""
import os
import mimetypes
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from server.services.file_service import FileService

router = APIRouter(prefix="/api/upload", tags=["图片上传与资产管理"])


@router.post("/single", summary="上传单张图片")
async def upload_single_image(file: UploadFile = File(...)):
    """上传单张图片，返回文件的相对 URL 与本地物理绝对路径"""
    result = FileService.save_upload_file(file)
    return {"code": 0, "msg": "上传成功", "data": result}


@router.post("/multiple", summary="批量上传多张图片")
async def upload_multiple_images(files: List[UploadFile] = File(...)):
    """批量上传多张图片，常用于附图批量上传"""
    results = FileService.save_multiple_upload_files(files)
    return {"code": 0, "msg": f"成功上传 {len(results)} 张图片", "data": results}


@router.get("/preview", summary="预览本地相对路径或上传图片")
async def preview_image(path: str = Query(..., description="图片相对路径或文件名")):
    """
    根据相对路径或文件名解析本地物理文件并返回流式图片内容，供前端 <img> 标签正常加载
    """
    abs_path = FileService.resolve_image_path(path)
    if abs_path and os.path.exists(abs_path) and os.path.isfile(abs_path):
        mime_type, _ = mimetypes.guess_type(abs_path)
        return FileResponse(abs_path, media_type=mime_type or "image/jpeg")
    
    # 若图片在本地未找到，返回 404
    raise HTTPException(status_code=404, detail=f"Image not found: {path}")
