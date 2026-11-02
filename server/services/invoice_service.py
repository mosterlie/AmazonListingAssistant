"""
发票信息自动化解析服务 (知识库 → 发票解析)

流程: 上传图片/PDF → PDF 逐页渲染或图片压缩 → WorkBuddy 多模态识别 → 结构化字段
约束:
  - 仅支持图片 (jpg/jpeg/png/webp/bmp) 与 PDF, 单文件 ≤ 20MB
  - 识别结果 is_invoice=false 时直接报错 (不是发票)
  - 每次调用写入 llm_call_logs (scene=invoice_parse), 便于追溯耗时/tokens
"""
import io
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from server.database import get_db_connection
from server.services.workbuddy_service import (
    WorkBuddyError, _cfg, _extract_json, chat_with_images,
)

MAX_INVOICE_SIZE = 20 * 1024 * 1024      # 单文件 20MB
MAX_PDF_PAGES = 2                        # 最多识别前 2 页 (控制 tokens 与耗时)
MAX_IMAGE_EDGE = 1600                    # 图片最长边缩放上限 (px)
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".pdf"}

INVOICE_SYSTEM_PROMPT = "你是严谨的发票信息抽取助手，只输出 JSON，不输出任何解释。"

INVOICE_PROMPT = """请判断图片是不是「发票」类单据，并把单据信息提取成 JSON。

判定为发票的类型：增值税专用发票、增值税普通发票、电子发票、形式发票(Proforma Invoice)、
商业发票(Commercial Invoice)、收据/付款凭证等贸易或税务票据。
如果图片是合同、装箱单、报价单、截图、照片、聊天记录等非发票内容，is_invoice 必须为 false。

严格返回如下 JSON（字段无法识别用空字符串 "" 或 0，禁止编造）：
{
  "is_invoice": true,
  "doc_type": "增值税专用发票|增值税普通发票|电子发票|形式发票|商业发票|其他发票|非发票",
  "reason": "非发票时说明这是什么文件，发票则留空",
  "invoice_code": "发票代码",
  "invoice_number": "发票号码",
  "invoice_date": "YYYY-MM-DD",
  "seller_name": "销售方/开票方名称",
  "seller_tax_id": "销售方税号",
  "buyer_name": "购买方名称",
  "buyer_tax_id": "购买方税号",
  "currency": "CNY|USD|JPY|EUR 等",
  "amount_excl_tax": 0,
  "tax_amount": 0,
  "total_amount": 0,
  "total_in_words": "价税合计大写（如有）",
  "remark": "备注",
  "items": [
    {"name": "货物或应税劳务名称", "spec": "规格型号", "unit": "单位",
     "quantity": 0, "unit_price": 0, "amount": 0, "tax_rate": "税率/征收率"}
  ]
}

规则：
1. 金额一律输出数字（不带千分位、不带货币符号）；数量/单价同理。
2. items 按发票明细逐行列全；没有明细时给空数组。
3. 日期统一转换为 YYYY-MM-DD。
4. 多页发票请合并信息，只输出一个 JSON 对象。
"""


def _to_float(value: Any) -> float:
    """金额/数量规整: 去千分位、货币符号、中文单位后缀, 失败返回 0.0"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    text = re.sub(r"[,\s¥￥$€£]|元|CNY|USD|JPY|RMB", "", text, flags=re.I)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    try:
        return float(match.group(0)) if match else 0.0
    except ValueError:
        return 0.0


def _clean(value: Any, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _normalize_date(value: Any) -> str:
    """发票日期规整为 YYYY-MM-DD (支持 2026年1月2日 / 2026/1/2 / 20260102)"""
    text = _clean(value, 40)
    if not text:
        return ""
    match = re.search(r"(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m}-{d}"
    return text


def _load_pdf_pages(data: bytes) -> Tuple[List[bytes], int]:
    """PDF → 每页 PNG 字节 (最多 MAX_PDF_PAGES 页)"""
    try:
        try:
            import pymupdf as fitz          # PyMuPDF ≥ 1.24 新包名
        except ImportError:                 # 兼容旧版
            import fitz                     # type: ignore
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="缺少 PDF 解析依赖, 请先安装 pymupdf (pip install pymupdf)") from exc
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF 无法打开: {exc}") from exc
    pages: List[bytes] = []
    total = doc.page_count
    try:
        for index in range(min(total, MAX_PDF_PAGES)):
            page = doc.load_page(index)
            pix = page.get_pixmap(dpi=170)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    if not pages:
        raise HTTPException(status_code=400, detail="PDF 没有可识别的页面")
    return pages, total


def _load_image(data: bytes) -> bytes:
    """图片规整: 转 RGB、最长边缩到 MAX_IMAGE_EDGE、输出 JPEG"""
    try:
        from PIL import Image
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="缺少图片处理依赖 Pillow") from exc
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"图片无法解析: {exc}") from exc
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    width, height = img.size
    longest = max(width, height)
    if longest > MAX_IMAGE_EDGE:
        ratio = MAX_IMAGE_EDGE / float(longest)
        img = img.resize((max(1, int(width * ratio)), max(1, int(height * ratio))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _prepare_images(raw: bytes, ext: str) -> Tuple[List[bytes], str, int]:
    """原始文件 → (图片字节列表, mime, 总页数)"""
    if ext == ".pdf":
        pages, total = _load_pdf_pages(raw)
        return pages, "image/png", total
    return [_load_image(raw)], "image/jpeg", 1


def _log_call(title: str, model: str, prompt: str, response: str, status: str,
              error: str, usage: Dict[str, int], duration_ms: int, username: str) -> None:
    """调用日志 (llm_call_logs); 日志异常不影响主流程"""
    try:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO llm_call_logs (scene, source, model, title, prompt, response, status,
                                           error_detail, prompt_tokens, completion_tokens,
                                           total_tokens, duration_ms, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "invoice_parse", "workbuddy", model, title,
                prompt[:5000], (response or "")[:20000], status, (error or "")[:2000],
                usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0), duration_ms, username or "system",
            ))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
    """模型 JSON → 前端展示结构 (金额转数字、日期归一、明细过滤)"""
    invoice = {
        "doc_type": _clean(payload.get("doc_type"), 40),
        "invoice_code": _clean(payload.get("invoice_code"), 60),
        "invoice_number": _clean(payload.get("invoice_number"), 60),
        "invoice_date": _normalize_date(payload.get("invoice_date")),
        "seller_name": _clean(payload.get("seller_name"), 120),
        "seller_tax_id": _clean(payload.get("seller_tax_id"), 60),
        "buyer_name": _clean(payload.get("buyer_name"), 120),
        "buyer_tax_id": _clean(payload.get("buyer_tax_id"), 60),
        "currency": _clean(payload.get("currency"), 12).upper(),
        "amount_excl_tax": _to_float(payload.get("amount_excl_tax")),
        "tax_amount": _to_float(payload.get("tax_amount")),
        "total_amount": _to_float(payload.get("total_amount")),
        "total_in_words": _clean(payload.get("total_in_words"), 120),
        "remark": _clean(payload.get("remark"), 200),
    }
    items: List[Dict[str, Any]] = []
    for row in payload.get("items") or []:
        if not isinstance(row, dict):
            continue
        name = _clean(row.get("name"), 120)
        if not name and not _to_float(row.get("amount")):
            continue
        items.append({
            "name": name,
            "spec": _clean(row.get("spec"), 80),
            "unit": _clean(row.get("unit"), 20),
            "quantity": _to_float(row.get("quantity")),
            "unit_price": _to_float(row.get("unit_price")),
            "amount": _to_float(row.get("amount")),
            "tax_rate": _clean(row.get("tax_rate"), 20),
        })
    return {"invoice": invoice, "items": items[:100]}


def parse_invoice(file: UploadFile, username: str = "") -> Dict[str, Any]:
    """解析单张发票文件, 返回结构化结果; 非发票/无法解析时抛 HTTPException"""
    filename = os.path.basename(file.filename or "invoice")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400,
                            detail=f"「{filename}」格式不支持，请上传图片(jpg/png/webp)或 PDF")

    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size <= 0:
        raise HTTPException(status_code=400, detail=f"「{filename}」内容为空")
    if size > MAX_INVOICE_SIZE:
        raise HTTPException(status_code=400, detail=f"「{filename}」超过 20MB 上限")
    raw = file.file.read()

    images, mime, pages = _prepare_images(raw, ext)
    base_url, api_key, model = _cfg()
    if not api_key:
        raise HTTPException(status_code=500, detail="未配置 WorkBuddy API Key，请到系统管理填写")

    started = time.monotonic()
    status, error, text, usage = "success", "", "", {}
    try:
        text, usage = chat_with_images(INVOICE_PROMPT, images, mime=mime,
                                       system=INVOICE_SYSTEM_PROMPT, temperature=0.0)
    except WorkBuddyError as exc:
        status, error = "error", str(exc)
        raise HTTPException(status_code=502, detail=f"模型调用失败: {exc}") from exc
    finally:
        _log_call(filename, model, INVOICE_PROMPT, text, status, error, usage,
                  int((time.monotonic() - started) * 1000), username)

    payload = _extract_json(text)
    if not payload:
        raise HTTPException(status_code=502, detail="模型返回内容无法解析为 JSON，请重试")

    if not payload.get("is_invoice"):
        reason = _clean(payload.get("reason") or payload.get("doc_type"), 120)
        raise HTTPException(
            status_code=400,
            detail=f"该文件不是发票" + (f"（识别为：{reason}）" if reason else "，请上传发票图片或 PDF"))

    normalized = _normalize(payload)
    return {
        "file_name": filename,
        "pages": pages,
        "model": model,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "usage": usage,
        **normalized,
        "raw_text": text,
    }
