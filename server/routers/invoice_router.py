"""
发票解析 API 路由层 (知识库 → 发票解析)

- POST /api/invoices/parse: 上传发票图片或 PDF, 用 WorkBuddy 多模态模型提取结构化信息
- 非发票 / 格式不支持 / 超过 20MB → 400; 模型异常 → 502
"""
from fastapi import APIRouter, Depends, File, UploadFile

from server.dependencies import get_current_user
from server.services.invoice_service import parse_invoice

router = APIRouter(prefix="/api/invoices", tags=["发票解析"])


@router.post("/parse", summary="解析发票图片/PDF, 自动提取发票信息 (WorkBuddy 多模态)")
def parse_invoice_file(file: UploadFile = File(..., description="发票图片(jpg/png/webp) 或 PDF"),
                       user: dict = Depends(get_current_user)):
    data = parse_invoice(file, username=user.get("username", ""))
    return {"code": 0, "msg": "解析成功", "data": data}
