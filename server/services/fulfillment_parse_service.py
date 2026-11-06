"""
履约中心 · 票据智能解析服务

复用现有知识库发票解析的底层能力 (图片规整 / PDF 逐页渲染 / WorkBuddy 多模态 / 调用日志),
新增两类单据的结构化抽取:
- 采购单截图 → 采购单号/供应商/日期/金额/明细
- 转账凭证   → 交易号/付款时间/金额/收付款方/方式

发票解析直接复用 invoice_service.parse_invoice (同一套规则与校验), 避免两套标准。
"""
import io
import mimetypes
import os
import time
from types import SimpleNamespace
from typing import Any, Dict, List

from fastapi import HTTPException, UploadFile

from server.services.invoice_service import (
    ALLOWED_EXTS,
    _clean,
    _cfg,
    _extract_json,
    _log_call,
    _normalize_date,
    _prepare_images,
    _to_float,
    parse_invoice,
)
from server.services.workbuddy_service import WorkBuddyError, chat_with_images

PURCHASE_SYSTEM_PROMPT = "你是严谨的采购单据信息抽取助手，只输出 JSON，不输出任何解释。"

PURCHASE_PROMPT = """请判断图片是不是「采购单 / 采购订单 / 采购清单」类单据，并提取信息。

如果不是采购单（例如发票、转账截图、聊天记录、商品图、快递单），is_purchase_order 必须为 false。
严格返回如下 JSON（识别不到用 "" 或 0，禁止编造）：
{
  "is_purchase_order": true,
  "reason": "非采购单时说明这是什么",
  "purchase_no": "采购单号/订单编号",
  "supplier_name": "供应商/供货方",
  "buyer_name": "采购方",
  "purchase_date": "YYYY-MM-DD",
  "currency": "CNY|USD|JPY 等",
  "total_amount": 0,
  "remark": "备注",
  "items": [
    {"name": "商品名称", "spec": "规格型号", "unit": "单位",
     "quantity": 0, "unit_price": 0, "amount": 0}
  ]
}
规则:
1. 金额/数量/单价输出纯数字, 不带货币符号与千分位。
2. items 逐行提取, 没有明细时给空数组。
3. 日期统一 YYYY-MM-DD。
"""

TRANSFER_SYSTEM_PROMPT = "你是严谨的银行转账凭证信息抽取助手，只输出 JSON，不输出任何解释。"

TRANSFER_PROMPT = """请判断图片是不是「银行转账凭证 / 汇款回单 / 付款成功截图」类单据，并提取信息。

如果不是转账凭证（例如采购单、发票、商品图），is_transfer_voucher 必须为 false。
严格返回如下 JSON（识别不到用 "" 或 0，禁止编造）：
{
  "is_transfer_voucher": true,
  "reason": "非转账凭证时说明这是什么",
  "transaction_no": "交易流水号/回单编号",
  "paid_at": "YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD",
  "amount": 0,
  "currency": "CNY|USD|JPY 等",
  "payer": "付款方",
  "payee": "收款方",
  "method": "银行转账/支付宝/微信/PayPal 等",
  "remark": "备注/用途"
}
规则: 金额输出纯数字; 日期尽量统一 YYYY-MM-DD; 无法识别留空, 禁止编造。
"""


def _read_upload(file: UploadFile) -> tuple:
    """读取上传文件并校验格式/大小, 返回 (文件名, 扩展名, 内容, mime)"""
    filename = os.path.basename(file.filename or "file")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400,
                           detail=f"「{filename}」格式不支持，请上传图片(jpg/png/webp)或 PDF")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size <= 0:
        raise HTTPException(status_code=400, detail=f"「{filename}」内容为空")
    if size > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"「{filename}」超过 20MB 上限")
    raw = file.file.read()
    mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return filename, ext, raw, mime


def _normalize_items(rows: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = _clean(row.get("name"), 120)
        amount = _to_float(row.get("amount"))
        if not name and not amount:
            continue
        items.append({
            "name": name,
            "spec": _clean(row.get("spec"), 80),
            "unit": _clean(row.get("unit"), 20),
            "quantity": _to_float(row.get("quantity")),
            "unit_price": _to_float(row.get("unit_price")),
            "amount": amount,
        })
    return items[:200]


def _call_multimodal(prompt: str, system: str, raw: bytes, ext: str,
                     title: str, username: str) -> Dict[str, Any]:
    """调用多模态模型并返回 (JSON, 原始文本, 模型名, 耗时)"""
    images, mime, _pages = _prepare_images(raw, ext)
    _base, api_key, model = _cfg()
    if not api_key:
        raise HTTPException(status_code=500, detail="未配置 WorkBuddy API Key，请到系统管理填写")

    started = time.monotonic()
    status, error, text, usage = "success", "", "", {}
    try:
        text, usage = chat_with_images(prompt, images, mime=mime,
                                       system=system, temperature=0.0)
    except WorkBuddyError as exc:
        status, error = "error", str(exc)
        raise HTTPException(status_code=502, detail=f"模型调用失败: {exc}") from exc
    finally:
        _log_call(title, model, prompt, text, status, error, usage,
                  int((time.monotonic() - started) * 1000), username)

    payload = _extract_json(text)
    if not payload:
        raise HTTPException(status_code=502, detail="模型返回内容无法解析为 JSON，请重试")
    return {
        "payload": payload,
        "raw_text": text,
        "model": model,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def parse_purchase_order(file: UploadFile, username: str = "") -> Dict[str, Any]:
    """解析采购单截图/PDF, 返回结构化采购单信息"""
    filename, ext, raw, _mime = _read_upload(file)
    result = _call_multimodal(PURCHASE_PROMPT, PURCHASE_SYSTEM_PROMPT, raw, ext,
                              f"purchase:{filename}", username)
    payload = result["payload"]
    if not payload.get("is_purchase_order"):
        reason = _clean(payload.get("reason") or "", 120)
        raise HTTPException(status_code=400,
                            detail="该文件不是采购单" + (f"（识别为：{reason}）" if reason else ""))
    data = {
        "purchase_no": _clean(payload.get("purchase_no"), 80),
        "supplier_name": _clean(payload.get("supplier_name"), 120),
        "buyer_name": _clean(payload.get("buyer_name"), 120),
        "purchase_date": _normalize_date(payload.get("purchase_date")),
        "currency": _clean(payload.get("currency"), 12).upper(),
        "total_amount": _to_float(payload.get("total_amount")),
        "remark": _clean(payload.get("remark"), 200),
        "items": _normalize_items(payload.get("items")),
    }
    return {"file_name": filename, "model": result["model"],
            "duration_ms": result["duration_ms"], "data": data,
            "raw_text": result["raw_text"]}


def parse_transfer_voucher(file: UploadFile, username: str = "") -> Dict[str, Any]:
    """解析转账凭证截图/PDF, 返回结构化付款信息"""
    filename, ext, raw, _mime = _read_upload(file)
    result = _call_multimodal(TRANSFER_PROMPT, TRANSFER_SYSTEM_PROMPT, raw, ext,
                              f"transfer:{filename}", username)
    payload = result["payload"]
    if not payload.get("is_transfer_voucher"):
        reason = _clean(payload.get("reason") or "", 120)
        raise HTTPException(status_code=400,
                            detail="该文件不是转账凭证" + (f"（识别为：{reason}）" if reason else ""))
    data = {
        "transaction_no": _clean(payload.get("transaction_no"), 80),
        "paid_at": _clean(payload.get("paid_at"), 40),
        "amount": _to_float(payload.get("amount")),
        "currency": _clean(payload.get("currency"), 12).upper(),
        "payer": _clean(payload.get("payer"), 120),
        "payee": _clean(payload.get("payee"), 120),
        "method": _clean(payload.get("method"), 40),
        "remark": _clean(payload.get("remark"), 200),
    }
    return {"file_name": filename, "model": result["model"],
            "duration_ms": result["duration_ms"], "data": data,
            "raw_text": result["raw_text"]}


def parse_invoice_bytes(content: bytes, filename: str, username: str = "") -> Dict[str, Any]:
    """解析已保存到磁盘的发票字节内容 (复用知识库发票解析标准)"""
    shim = SimpleNamespace(
        file=io.BytesIO(content),
        filename=filename,
        content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )
    return parse_invoice(shim, username=username)
