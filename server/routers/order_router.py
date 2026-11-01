"""
订单管理 API 路由 (妙手订单包裹同步/查询)

数据源: 妙手开放平台 订单包裹列表 (见 order_service.py)
权限: 查询登录即可; 同步需「订单同步」按钮权限点 (order:sync)
"""
import base64
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime
from io import BytesIO
from typing import List, Optional
from urllib.parse import quote, urlparse

import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import pixels_to_EMU
from PIL import Image as PILImage
from pydantic import BaseModel, Field

from server.config import UPLOADS_DIR
from server.dependencies import get_current_user
from server.services.miaoshou_service import MiaoshouApiError
from server.services.order_doc_service import OrderDocService
from server.services.order_service import OrderService, STATUS_OPTIONS, DEFAULT_STATUSES
from server.services.rbac_service import require_perm
from server.services.xlsx_ole import inject_ole_objects

router = APIRouter(prefix="/api/orders", tags=["订单管理·妙手"])


class OrderSyncSchema(BaseModel):
    """同步参数: statuses 缺省为全部状态; days>0 按妙手创建时间取最近 N 天"""
    statuses: Optional[List[str]] = None
    days: int = Field(0, ge=0, le=3650, description="最近 N 天, 0=不限")
    max_packages: int = Field(20000, ge=1, le=100000)


@router.get("", summary="订单列表 (分页 + 关键词/状态/店铺/平台/时间筛选)")
def list_orders(keyword: str = Query("", max_length=128),
                status: str = Query("", max_length=32),
                shop_id: str = Query("", max_length=32),
                platform: str = Query("", max_length=32),
                date_from: str = Query("", max_length=19),
                date_to: str = Query("", max_length=19),
                page: int = Query(1, ge=1),
                page_size: int = Query(20, ge=1, le=200),
                include_closed: bool = Query(False, description="是否包含已关闭订单"),
                user: dict = Depends(get_current_user)):
    data = OrderService.list_orders(keyword=keyword, status=status, shop_id=shop_id,
                                    platform=platform, date_from=date_from, date_to=date_to,
                                    page=page, page_size=page_size, include_closed=include_closed)
    return {"code": 0, "msg": "查询成功", "data": data}


@router.get("/filters", summary="筛选项与统计 (店铺/平台/状态/最近同步时间)")
def order_filters(include_closed: bool = Query(False, description="统计是否包含已关闭订单"),
                  user: dict = Depends(get_current_user)):
    data = OrderService.filter_options(include_closed=include_closed)
    return {"code": 0, "msg": "查询成功", "data": data}


# ───────── 产品图片下载 (复制整行 / 导出 Excel 内嵌图片) ─────────
_IMG_CACHE: dict = {}          # url -> (bytes, content_type) 小容量进程内缓存
_IMG_CACHE_MAX = 300
_IMG_MAX_BYTES = 8 * 1024 * 1024
_IMG_LOCK = threading.Lock()
_IMG_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _download_image(url: str):
    """下载图片 -> (bytes, content_type); 非法链接/非图片/超限抛 ValueError"""
    raw = (url or "").strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("图片链接无效")
    with _IMG_LOCK:
        cached = _IMG_CACHE.get(raw)
    if cached:
        return cached
    try:
        with requests.get(raw, timeout=(5, 12), stream=True, headers={
            "User-Agent": _IMG_UA,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }) as resp:
            resp.raise_for_status()
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and not ctype.startswith("image/"):
                raise ValueError(f"链接不是图片 ({ctype})")
            chunks, size = [], 0
            for chunk in resp.iter_content(64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > _IMG_MAX_BYTES:
                    raise ValueError("图片过大 (>8MB)")
                chunks.append(chunk)
        blob = b"".join(chunks)
    except ValueError:
        raise
    except Exception as exc:  # 网络/证书/超时等
        raise ValueError(f"图片下载失败: {exc}")
    if not blob:
        raise ValueError("图片内容为空")
    item = (blob, ctype or "image/jpeg")
    with _IMG_LOCK:
        if len(_IMG_CACHE) >= _IMG_CACHE_MAX:
            _IMG_CACHE.pop(next(iter(_IMG_CACHE)), None)
        _IMG_CACHE[raw] = item
    return item


@router.get("/image-data", summary="产品图片下载为 data URL")
def order_image_data(url: str = Query(..., min_length=4, max_length=2048),
                     user: dict = Depends(get_current_user)):
    try:
        blob, ctype = _download_image(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    data_url = f"data:{ctype};base64,{base64.b64encode(blob).decode('ascii')}"
    return {"code": 0, "msg": "ok",
            "data": {"data_url": data_url, "content_type": ctype, "bytes": len(blob)}}


# ───────── 导出 Excel: 产品图片下载后锚定到对应单元格 ─────────
# 腾讯文档等在线表格不接受「复制内容里的图片」, 只能走导入 xlsx
XLSX_COLUMNS = [
    ("采购日期", 14), ("仓库发货日期", 14), ("产品图片", 12), ("产品名称及备注", 36),
    ("国内包裹数量", 13), ("国内单号", 20), ("国际单号", 20), ("订单号", 22),
    ("收件人名字", 14), ("亚马逊售卖单价", 14), ("换单号", 12), ("采购订单号", 14),
    ("店铺", 16), ("备注", 24), ("与客户沟通", 14), ("出库重量", 10),
]
XLSX_IMG_PX = 72          # 单元格内图片边长 (px)


# 店铺名替换: 对外展示/导出用店铺简称 (妙手店铺名带卖家 ID 后缀, 如 A3IM82P5RF6MRV-fe-JP)
SHOP_ALIAS = {"A3IM82P5RF6MRV": "金梧汇辰"}


def _shop_name(o: dict) -> str:
    name = str(o.get("shop_name") or "").strip()
    if not name:
        return ""
    if name in SHOP_ALIAS:
        return SHOP_ALIAS[name]
    for key, alias in SHOP_ALIAS.items():
        if key in name:
            return alias
    return name


def _ymd(value) -> str:
    """采购日期 -> YYYYMMDD"""
    s = str(value or "").strip()
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _order_image_url(o: dict) -> str:
    items = o.get("items") or []
    it = items[0] if items else {}
    return it.get("originalPicUrl") or it.get("picUrl") or ""


def _parse_ids(ids: str):
    """'1,2,3' -> [1,2,3]; 非法/为空抛 400, 单次上限 200 单"""
    id_list = []
    for part in str(ids or "").split(","):
        part = part.strip()
        if part.isdigit():
            id_list.append(int(part))
    id_list = id_list[:200]
    if not id_list:
        raise HTTPException(status_code=400, detail="请先选择要导出的订单")
    return id_list


def _embed_cell_image(ws, url: str, cell: str) -> None:
    """下载图片并锚定到指定单元格 (失败则留空, 不影响导出)"""
    if not url:
        return
    try:
        blob, _ctype = _download_image(url)
        if len(blob) > _IMG_MAX_BYTES:
            return
        buf = BytesIO(blob)
        try:
            img = XLImage(buf)
            img.width, img.height = XLSX_IMG_PX, XLSX_IMG_PX
        except Exception:
            # openpyxl 仅原生支持 png/jpeg: 其它格式先转 png
            buf.seek(0)
            conv = BytesIO()
            PILImage.open(buf).convert("RGB").save(conv, format="PNG")
            conv.seek(0)
            img = XLImage(conv)
            img.width, img.height = XLSX_IMG_PX, XLSX_IMG_PX
        ws.add_image(img, cell)
    except Exception:
        return


@router.get("/export-xlsx", summary="导出订单为 Excel (产品图片内嵌单元格)")
def export_orders_xlsx(ids: str = Query(..., max_length=4096, description="订单 id, 逗号分隔"),
                       user: dict = Depends(get_current_user)):
    id_list = _parse_ids(ids)

    wb = Workbook()
    ws = wb.active
    ws.title = "订单"
    head_font = Font(bold=True, color="475569")
    head_fill = PatternFill("solid", fgColor="F8FAFC")
    wrap = Alignment(wrap_text=True, vertical="top")

    for idx, (label, width) in enumerate(XLSX_COLUMNS, start=1):
        cell = ws.cell(row=1, column=idx, value=label)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"

    img_col = next(i for i, (label, _w) in enumerate(XLSX_COLUMNS, start=1) if label == "产品图片")
    row_idx = 2
    for oid in id_list:
        o = OrderService.get_order(oid)
        if not o:
            continue
        items = o.get("items") or []
        it = items[0] if items else {}
        sku = str(o.get("sku") or it.get("platformOuterSkuId") or it.get("platformItemId")
                  or it.get("platformSkuId") or "").strip()
        label = str(o.get("product_label") or it.get("title") or "").strip()
        consignee = ((o.get("raw") or {}).get("consigneeInfo") or {})
        order_info = ((o.get("raw") or {}).get("orderInfo") or {})
        price = it.get("originalPrice")

        values = [
            _ymd(o.get("purchase_date")), "", "", "\n".join([x for x in (sku, label) if x]),
            int(o.get("domestic_package_count") or 0) or "",
            o.get("domestic_tracking_no") or "", o.get("tracking_no") or "",
            o.get("order_sn") or "",
            consignee.get("name") or consignee.get("receiverName") or consignee.get("consigneeName") or "",
            "" if price is None else price,
            "", "", _shop_name(o),
            order_info.get("appNote") or order_info.get("sellerNote") or order_info.get("buyerMessage") or "",
            "", "",
        ]
        for idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=idx, value=value)
            cell.alignment = wrap
        # 长数字列按文本存, 避免变科学计数法
        for idx in (1, 6, 7, 8):
            ws.cell(row=row_idx, column=idx).number_format = "@"
        ws.row_dimensions[row_idx].height = 58
        _embed_cell_image(ws, _order_image_url(o), f"{get_column_letter(img_col)}{row_idx}")
        row_idx += 1

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    fname = f"订单导出_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    headers = {"Content-Disposition": f"attachment; filename=xlsx_export.xlsx; "
                                      f"filename*=UTF-8''{quote(fname)}"}
    return StreamingResponse(
        out, headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ───────── 亚马逊申诉模板导出 (直近配送済み自己発送注文のフルフィルメント記録) ─────────
# 列顺序/列宽与模板一致; 无对应字段一律留空
APPEAL_COLUMNS = [
    ("アマゾン注文番号", 32.6), ("発注書", 26), ("発注書インボイス", 26),
    ("ご配送業者名", 19.5), ("配送状況", 11.5), ("追跡番号", 24.0),
    ("出荷伝票", 46.5), ("ご配送状況のスクリーンショット", 56.3), ("受領証明書", 36.7),
    ("送料の適格請求書", 26), ("輸入（納税）申告書", 26), ("ご備考欄（）", 55.7),
    ("ご確認用ウェブサイト", 52.7),
]
# 单据列 ← 订单附件原文件: 图片用原图, PDF/Office 用上传时生成的首页快照
APPEAL_DOC_COLUMNS = {
    2: "purchase_order",      # 発注書 ← 采购单
    3: "purchase_invoice",    # 発注書インボイス ← 采购发票
    7: "delivery_note",       # 出荷伝票 ← 发货单
    8: "delivery_track",      # ご配送状況のスクリーンショット ← 配送轨迹
    9: "receipt",             # 受領証明書 ← 签收证明
    10: "logistics_invoice",  # 送料の適格請求書 ← 物流发票
    11: "customs_cert",       # 輸入（納税）申告書 ← 清关证明
}
APPEAL_DOC_MAX_W = 110      # 单据图片最大宽 (px)
APPEAL_DOC_MAX_H = 140      # 单据图片最大高 (px)
APPEAL_DOC_MIN_W = 58       # 并排时单张最小宽 (px), 低于则减少张数
APPEAL_DOC_PER_CELL = 3     # 同一单元格最多并排 3 份
APPEAL_DOC_GAP = 6          # 并排图片间距 (px)
APPEAL_DOC_PDF_PAGES = 6    # 单个 PDF 最多渲染页数 (需 PyMuPDF, 未装则只用首页快照)
APPEAL_DOC_OLE_SIZE = 30    # 文件类附件的 OLE 对象图标尺寸 (px)
APPEAL_EMBED_OLE = True     # 文件类附件是否以 OLE 附件对象嵌入 (False 则只留图片预览)


def _col_px(width_chars: float) -> int:
    """列宽(字符) → 像素 (Excel 默认字体经验换算)"""
    return int(width_chars * 7 + 5)


def _doc_image_path(order_id: int, doc: dict) -> str:
    """单据可嵌入的文件路径: 图片优先用原文件, 文档用首页快照 PNG (都没有返回空)"""
    root = os.path.join(UPLOADS_DIR, "orders", str(int(order_id)))
    if doc.get("is_image") and doc.get("stored_name"):
        path = os.path.join(root, doc["stored_name"])
        if os.path.isfile(path):
            return path
    thumb = doc.get("thumb_name") or ""
    if thumb:
        path = os.path.join(root, thumb)
        if os.path.isfile(path):
            return path
    return ""


def _render_pdf_pages(path: str, max_pages: int, tmp_dirs: list) -> list:
    """PDF 转逐页 PNG (需 PyMuPDF; 未安装/失败返回空列表, 由调用方回退首页快照)"""
    try:
        import pymupdf as fitz          # PyMuPDF 新版包名
    except Exception:
        try:
            import fitz                 # 旧版兼容
        except Exception:
            return []
    out = []
    try:
        tmpdir = tempfile.mkdtemp(prefix="appeal_pdf_")
        tmp_dirs.append(tmpdir)
        with fitz.open(path) as pdf:
            for i, page in enumerate(pdf):
                if i >= max_pages:
                    break
                png = os.path.join(tmpdir, f"p{i + 1}.png")
                page.get_pixmap(dpi=120).save(png)
                out.append(png)
    except Exception:
        return []
    return out


def _doc_image_paths(order_id: int, doc: dict, tmp_dirs: list) -> list:
    """一份单据 → 要嵌入的图片列表: 图片=原图; PDF=逐页渲染; 其它=首页快照"""
    root = os.path.join(UPLOADS_DIR, "orders", str(int(order_id)))
    stored = doc.get("stored_name") or ""
    if doc.get("is_image"):
        path = _doc_image_path(order_id, doc)
        return [path] if path else []
    if stored.lower().endswith(".pdf"):
        pages = _render_pdf_pages(os.path.join(root, stored), APPEAL_DOC_PDF_PAGES, tmp_dirs)
        if pages:
            return pages
    path = _doc_image_path(order_id, doc)
    return [path] if path else []


def _measure_doc_image(path: str, max_w: int):
    """按最大宽高等比缩放, 返回 (宽, 高) 像素"""
    with PILImage.open(path) as im:
        w, h = im.size
    scale = min(max_w / max(w, 1), APPEAL_DOC_MAX_H / max(h, 1), 2.0)
    return max(1, int(w * scale)), max(1, int(h * scale))


def _add_doc_image(ws, path: str, col_idx: int, row_idx: int,
                   dx_px: int, dy_px: int, out_w: int, out_h: int):
    """把单据图片放到 (col,row) 单元格内指定像素偏移处 (偏移用于单元格内居中)"""
    img = XLImage(path)
    img.width, img.height = out_w, out_h
    marker = AnchorMarker(col=col_idx, colOff=pixels_to_EMU(max(0, dx_px)),
                          row=row_idx, rowOff=pixels_to_EMU(max(0, dy_px)))
    img.anchor = OneCellAnchor(_from=marker, ext=XDRPositiveSize2D(
        pixels_to_EMU(out_w), pixels_to_EMU(out_h)))
    ws.add_image(img)


# 佐川急便官方查询页 (与页面 ↗ 跳转一致; 官网不支持带单号的直链, 单号见「追跡番号」列)
SAGAWA_TRACK_URL = "https://k2k.sagawa-exp.co.jp/p/sagawa/web/okurijoinput.jsp"
TRACK17_URL = "https://t.17track.net/zh-cn#nums="


def _is_sagawa(o: dict) -> bool:
    """与前端 isSagawaTracking 规则一致: 承运商命中, 或无承运商时 JP + 12 位纯数字"""
    no = str(o.get("tracking_no") or "").strip()
    company = str(o.get("tracking_company") or "").strip()
    if re.search(r"佐川|sagawa", company, re.I):
        return True
    if company:
        return False
    return bool(re.fullmatch(r"\d{12}", no)) and str(o.get("dest_country") or "").upper() == "JP"


def _carrier_name(o: dict) -> str:
    """ご配送業者名: 有承运商用原值(常见渠道规范成官方英文名); 无则按单号推断, 推断不出留空"""
    company = str(o.get("tracking_company") or "").strip()
    if company:
        if re.search(r"佐川|sagawa", company, re.I):
            return "SAGAWA EXPRESS"
        if re.search(r"ヤマト|大和|yamato", company, re.I):
            return "YAMATO TRANSPORT"
        return company
    return "SAGAWA EXPRESS" if _is_sagawa(o) else ""


def _delivery_status(o: dict) -> str:
    """配送状況: 运单状态为「派送妥投」→ 配達完了, 否则 配送中"""
    status = f"{o.get('track_status_name') or ''} {o.get('track_status') or ''}"
    return "配達完了" if ("派送妥投" in status or "配達完了" in status) else "配送中"


def _tracking_url(o: dict) -> str:
    """ご確認用ウェブサイト: 运单号跳转链接 (佐川官网 / 17TRACK, 与页面一致)"""
    no = str(o.get("tracking_no") or "").strip()
    if not no:
        return ""
    if _is_sagawa(o):
        return SAGAWA_TRACK_URL          # 官网查询页 (不支持带单号直链)
    return TRACK17_URL + no              # 17TRACK 可带单号直链


@router.get("/export-appeal-xlsx", summary="按亚马逊申诉模板导出选中订单")
def export_appeal_xlsx(ids: str = Query(..., max_length=4096, description="订单 id, 逗号分隔"),
                       user: dict = Depends(get_current_user)):
    id_list = _parse_ids(ids)

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_font = Font(bold=True, size=12)
    body_font = Font(size=12, name="宋体")
    head_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for idx, (label, width) in enumerate(APPEAL_COLUMNS, start=1):
        cell = ws.cell(row=1, column=idx, value=label)
        cell.font = head_font
        cell.alignment = head_align
        cell.border = border
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.row_dimensions[1].height = 65
    ws.freeze_panes = "A2"

    pdf_tmp_dirs = []      # PDF 逐页渲染的临时目录, 保存完再清理
    ole_items = []         # 文件类附件 → OLE 对象 (保存后注入)
    row_idx = 2
    for oid in id_list:
        o = OrderService.get_order(oid)
        if not o:
            continue
        info = ((o.get("raw") or {}).get("orderInfo") or {})
        values = [
            o.get("order_sn") or "",                       # アマゾン注文番号
            "",                                            # 発注書 (附件图片单元格)
            "",                                            # 発注書インボイス (附件图片单元格)
            _carrier_name(o),                              # ご配送業者名
            _delivery_status(o),                           # 配送状況
            str(o.get("tracking_no") or ""),               # 追跡番号
            "",                                            # 出荷伝票 (附件图片单元格)
            "",                                            # ご配送状況のスクリーンショット (附件图片单元格 ← 配送轨迹)
            "",                                            # 受領証明書 (附件图片单元格)
            "",                                            # 送料の適格請求書 (附件图片单元格)
            "",                                            # 輸入（納税）申告書 (附件图片单元格)
            info.get("appNote") or info.get("sellerNote") or info.get("buyerMessage") or "",
            _tracking_url(o),                              # ご確認用ウェブサイト
        ]
        for idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=idx, value=value)
            cell.font = body_font
            cell.border = border
            # 全部列水平/垂直居中 (含确认链接列与附件格)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if idx in (1, 6):
                cell.number_format = "@"      # 订单号 / 追跡番号 存文本, 避免科学计数法
        link = values[12]
        if link:
            link_cell = ws.cell(row=row_idx, column=13)
            link_cell.hyperlink = link
            link_cell.font = Font(size=12, name="宋体", color="0563C1", underline="single")

        # 单据原文件: 采购单/采购发票/发货单/配送轨迹/签收单/物流发票/清关证明 嵌入对应单元格
        try:
            docs = OrderDocService.list_docs(oid)
        except Exception:
            docs = []
        docs_by_type = {}
        for d in docs:
            docs_by_type.setdefault(d.get("doc_type"), []).append(d)

        # 第一遍: 量尺寸 → 决定每格张数/缩放, 供整行水平+垂直居中
        plans = []      # [(col_idx, [(path, w, h)], 总宽, 可用宽)]
        row_h = 0
        for col_idx, doc_type in APPEAL_DOC_COLUMNS.items():
            files = docs_by_type.get(doc_type) or []
            if not files:
                continue
            # 一份单据可能展成多张图 (PDF 逐页), 统一按"图片张数"排版
            entries = []                    # [(path, 来源文件名)]
            for doc in files:
                paths = _doc_image_paths(oid, doc, pdf_tmp_dirs)
                for p in paths:
                    entries.append((p, str(doc.get("file_name") or "")))
            if not entries:
                continue
            budget = _col_px(APPEAL_COLUMNS[col_idx - 1][1]) - 6
            count = min(len(entries), APPEAL_DOC_PER_CELL,
                        max(1, (budget + APPEAL_DOC_GAP) // (APPEAL_DOC_MIN_W + APPEAL_DOC_GAP)))
            each_w = min(APPEAL_DOC_MAX_W, (budget - APPEAL_DOC_GAP * (count - 1)) // count)
            items = []
            for path, _name in entries[:count]:
                try:
                    w, h = _measure_doc_image(path, each_w)
                except Exception:
                    continue
                items.append((path, w, h))
            if not items:
                continue

            # 文件类附件 (PDF/Office/压缩包) 额外以 OLE 附件对象嵌入单元格, 双击可打开原件
            ole_docs = []
            for doc in files if APPEAL_EMBED_OLE else []:
                if doc.get("is_image"):
                    continue
                path = os.path.join(UPLOADS_DIR, "orders", str(int(oid)), doc.get("stored_name") or "")
                icon = _doc_image_path(oid, doc)
                if not os.path.isfile(path) or not icon:
                    continue
                ole_docs.append((doc, path, icon))

            total_w = sum(w for _p, w, _h in items) + APPEAL_DOC_GAP * (len(items) - 1)
            if ole_docs:
                total_w += (APPEAL_DOC_OLE_SIZE + APPEAL_DOC_GAP) * len(ole_docs)
            plans.append((col_idx, items, ole_docs, total_w, budget))
            row_h = max(row_h, max(h for _p, _w, h in items), APPEAL_DOC_OLE_SIZE)
            # 批注标注原文件名 (文件类附件尤其需要, 表格内是渲染后的图片)
            has_file = any(not d.get("is_image") for d in files)
            if len(entries) > count or has_file:
                names = "、".join(dict.fromkeys(n for _p, n in entries if n))
                tip = f"原文件 {len(files)} 份：{names}"
                if len(entries) > count:
                    tip += f"（表格内展示前 {count} 张）"
                ws.cell(row=row_idx, column=col_idx).comment = Comment(tip, "ERP")

        # 第二遍: 按单元格可用空间居中摆放 (整体水平居中, 单张垂直居中)
        if plans:
            row_h = max(row_h, 40)
            for col_idx, items, ole_docs, total_w, budget in plans:
                dx = max(0, (budget - total_w) // 2)
                for path, w, h in items:
                    dy = max(0, (row_h - h) // 2)
                    try:
                        _add_doc_image(ws, path, col_idx - 1, row_idx - 1, dx, dy, w, h)
                    except Exception:
                        continue
                    dx += w + APPEAL_DOC_GAP
                # OLE 附件图标排在图片之后 (注入在保存后统一做)
                for doc, file_path, icon_path in ole_docs:
                    size = APPEAL_DOC_OLE_SIZE
                    dy = max(0, (row_h - size) // 2)
                    try:
                        with open(file_path, "rb") as fh:
                            blob = fh.read()
                        with open(icon_path, "rb") as fh:
                            icon_blob = fh.read()
                    except Exception:
                        dx += size + APPEAL_DOC_GAP
                        continue
                    ole_items.append({
                        "filename": str(doc.get("file_name") or ""),
                        "data": blob,
                        "icon_png": icon_blob,
                        "col": col_idx - 1,
                        "row": row_idx - 1,
                        "w_px": size,
                        "h_px": size,
                        "dx_px": dx,
                        "dy_px": dy,
                        "shape_id": 1000 + len(ole_items) + 1,
                    })
                    dx += size + APPEAL_DOC_GAP
            ws.row_dimensions[row_idx].height = max(58, row_h * 0.75 + 8)
        row_idx += 1

    out = BytesIO()
    wb.save(out)
    for tmp_dir in pdf_tmp_dirs:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    # 文件类附件: 以 OLE 附件对象嵌入单元格 (失败自动退回纯图片, 不影响表格打开)
    if ole_items:
        out = BytesIO(inject_ole_objects(out.getvalue(), ole_items))
    out.seek(0)
    fname = f"直近配送済み自己発送注文のフルフィルメント記録{datetime.now().strftime('%y%m%d')}.xlsx"
    headers = {"Content-Disposition": "attachment; filename=appeal_export.xlsx; "
                                      f"filename*=UTF-8''{quote(fname)}"}
    return StreamingResponse(
        out, headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/{order_id}", summary="订单详情 (含商品明细)")
def order_detail(order_id: int, user: dict = Depends(get_current_user)):
    data = OrderService.get_order(order_id)
    if not data:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {"code": 0, "msg": "查询成功", "data": data}


class TrackRefreshSchema(BaseModel):
    """批量刷新轨迹: 订单 id 列表 (空则仅刷新当前页时由前端传入)"""
    ids: List[int] = Field(default_factory=list)


@router.get("/{order_id}/track", summary="运单轨迹详情 (实时查询初道轨迹 + 时间线)")
def order_track(order_id: int, user: dict = Depends(get_current_user)):
    try:
        data = OrderService.get_track_detail(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "msg": "查询成功", "data": data}


class TrackingNoSchema(BaseModel):
    """修改运单号: 新单号 + 可选物流公司"""
    tracking_no: str = ""
    tracking_company: str = ""


class SupplementSchema(BaseModel):
    """补录信息: 采购日期 / 国内包裹数量 / 国内单号"""
    purchase_date: str = ""
    domestic_package_count: int = 0
    domestic_tracking_no: str = ""


@router.post("/{order_id}/supplement", summary="补录信息 (采购日期/国内包裹数量/国内单号)")
def update_order_supplement(order_id: int, payload: SupplementSchema,
                            user: dict = Depends(get_current_user)):
    try:
        data = OrderService.update_supplement(
            order_id, payload.purchase_date, payload.domestic_package_count,
            payload.domestic_tracking_no)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "msg": "补录信息已保存", "data": data}


@router.post("/{order_id}/tracking-no", summary="修改运单号 (保留上一次值用于对比)")
def update_order_tracking_no(order_id: int, payload: TrackingNoSchema,
                             user: dict = Depends(get_current_user)):
    try:
        data = OrderService.update_tracking_no(order_id, payload.tracking_no, payload.tracking_company)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    msg = "运单号已更新" + ("，轨迹已同步" if data.get("found") else "，暂未查询到轨迹")
    return {"code": 0, "msg": msg, "data": data}


@router.post("/{order_id}/track/refresh", summary="刷新单个订单的运单轨迹")
def refresh_order_track(order_id: int, user: dict = Depends(get_current_user)):
    try:
        data = OrderService.refresh_track(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    msg = "轨迹已更新" if data.get("found") else "未查询到轨迹, 请稍后再试"
    return {"code": 0, "msg": msg, "data": data}


@router.post("/tracks/refresh", summary="批量刷新运单轨迹 (按订单 id)")
def refresh_order_tracks(payload: TrackRefreshSchema, user: dict = Depends(get_current_user)):
    if not payload.ids:
        raise HTTPException(status_code=400, detail="请提供要刷新的订单 id")
    data = OrderService.refresh_tracks(payload.ids[:200])
    msg = f"已刷新 {len(data['refreshed'])} 单"
    if data["failed"]:
        msg += f", 失败 {len(data['failed'])} 单"
    return {"code": 0, "msg": msg, "data": data}


@router.get("/{order_id}/docs", summary="订单单据附件列表 (采购单/采购发票/发货单/配送轨迹/签收单/物流发票/清关证明)")
def list_order_docs(order_id: int, user: dict = Depends(get_current_user)):
    data = OrderDocService.list_docs(order_id)
    return {"code": 0, "msg": "查询成功", "data": data}


@router.post("/{order_id}/docs", summary="上传订单单据附件 (同类可多份, 支持图片与文档)")
def upload_order_docs(order_id: int,
                      doc_type: str = Form(..., description="单据类型 key"),
                      files: List[UploadFile] = File(...),
                      user: dict = Depends(get_current_user)):
    saved = OrderDocService.save_docs(order_id, doc_type, files, username=user.get("username", ""))
    return {"code": 0, "msg": f"已上传 {len(saved)} 个文件", "data": saved}


@router.get("/{order_id}/docs/zip", summary="批量下载某类单据附件 (打包 zip)")
def download_order_docs_zip(order_id: int, doc_type: str = Query(..., description="单据类型 key"),
                            user: dict = Depends(get_current_user)):
    from urllib.parse import quote
    from fastapi import Response
    content, filename = OrderDocService.build_zip(order_id, doc_type)
    return Response(
        content=content, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.delete("/docs/{doc_id}", summary="删除订单单据附件")
def delete_order_doc(doc_id: int, user: dict = Depends(get_current_user)):
    data = OrderDocService.delete_doc(doc_id)
    return {"code": 0, "msg": "已删除", "data": data}


class DocBatchDeleteSchema(BaseModel):
    """批量删除附件: 附件 id 列表"""
    ids: List[int] = Field(default_factory=list)


@router.post("/docs/batch-delete", summary="批量删除订单单据附件")
def batch_delete_order_docs(payload: DocBatchDeleteSchema,
                            user: dict = Depends(get_current_user)):
    try:
        data = OrderDocService.delete_docs(payload.ids)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    msg = f"已删除 {data['deleted']} 个附件"
    if data["missing"]:
        msg += f", {len(data['missing'])} 个已不存在"
    return {"code": 0, "msg": msg, "data": data}


@router.post("/docs/batch-upload", summary="批量上传单据附件到多个订单 (同一批文件同步写入每个订单)")
def batch_upload_order_docs(order_ids: str = Form(..., description="订单 id 列表, 逗号分隔"),
                            doc_type: str = Form(..., description="单据类型 key"),
                            files: List[UploadFile] = File(...),
                            user: dict = Depends(get_current_user)):
    ids = [s for s in re.split(r"[,\s]+", order_ids or "") if s.strip()]
    data = OrderDocService.save_docs_many(ids, doc_type, files, username=user.get("username", ""))
    msg = f"已上传 {len(data['saved'])} 个文件到 {data['ok_orders']} 个订单"
    if data["failed"]:
        msg += f", {len(data['failed'])} 个订单失败"
    return {"code": 0, "msg": msg, "data": data}


@router.get("/docs/{doc_id}/download", summary="下载订单单据附件 (保留原始文件名)")
def download_order_doc(doc_id: int, user: dict = Depends(get_current_user)):
    import os
    from server.config import UPLOADS_DIR
    doc = OrderDocService.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = os.path.join(UPLOADS_DIR, "orders", str(doc["order_id"]), doc["stored_name"] or "")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件已丢失")
    return FileResponse(path, filename=doc["file_name"], media_type=doc["mime_type"] or None)


@router.post("/sync", summary="从妙手同步订单包裹 (需「订单同步」权限)")
def sync_orders(payload: OrderSyncSchema,
                user: dict = Depends(require_perm("order:sync"))):
    statuses = payload.statuses or DEFAULT_STATUSES
    valid = {s["value"] for s in STATUS_OPTIONS}
    bad = [s for s in statuses if s not in valid]
    if bad:
        raise HTTPException(status_code=400, detail=f"未知状态: {bad}")
    try:
        data = OrderService.sync_orders(statuses=statuses, days=payload.days,
                                        max_packages=payload.max_packages)
    except MiaoshouApiError as exc:
        raise HTTPException(status_code=502, detail=f"妙手API调用失败: {exc}")
    msg = (f"同步完成: 拉取 {data['fetched']} 条, 新增 {data['inserted']}, "
           f"更新 {data['updated']} ({data['pages']} 页)")
    if data["failed"]:
        msg += f", 失败 {len(data['failed'])} 处"
    product = data.get("product") or {}
    if product.get("tagged"):
        msg += f", 商品识别 {product['tagged']} 单"
    if product.get("failed"):
        msg += f" (未识别 {product['failed']} 单, 下次同步重试)"
    if product.get("error"):
        msg += f", 商品识别异常: {product['error']}"
    return {"code": 0, "msg": msg, "data": data}
