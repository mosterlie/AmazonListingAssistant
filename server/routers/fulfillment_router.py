"""
履约中心 API (独立模块, 不影响现有订单/附件接口)

页面: /fulfillment (工作台) + 采购单/包裹/发票/清关报税管理页
数据: fm_* 独立表; 订单与包裹从妙手订单缓存只读导入
"""
import json
import os
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.services.fulfillment_doc_service import (
    FM_DOC_CATEGORIES,
    FulfillmentDocService,
)
from server.services.fulfillment_service import FulfillmentService
from server.dependencies import get_current_user
from server.services.rbac_service import require_perm

router = APIRouter(prefix="/api/fulfillment", tags=["履约中心"])

READ_DEP = Depends(get_current_user)

EDIT_DEP = Depends(require_perm("fulfillment:edit"))
PARSE_DEP = Depends(require_perm("fulfillment:parse"))
DELETE_DEP = Depends(require_perm("fulfillment:delete"))


class SyncSchema(BaseModel):
    days: int = Field(7, ge=0, le=3650, description="最近 N 天; 0=不限")
    order_sn: str = Field("", max_length=80, description="只同步指定订单号")
    pull: bool = Field(False, description="是否先调用妙手在线同步刷新缓存")


class PurchaseOrderSchema(BaseModel):
    purchase_no: Optional[str] = ""
    supplier_name: Optional[str] = ""
    purchase_date: Optional[str] = ""
    currency: Optional[str] = "CNY"
    total_amount: Optional[float] = 0
    status: Optional[str] = "待付款"
    payment_status: Optional[str] = "未付款"
    note: Optional[str] = ""


class PurchaseOrderUpdateSchema(BaseModel):
    purchase_no: Optional[str] = None
    supplier_name: Optional[str] = None
    purchase_date: Optional[str] = None
    currency: Optional[str] = None
    total_amount: Optional[float] = None
    status: Optional[str] = None
    payment_status: Optional[str] = None
    note: Optional[str] = None


class LinkOrdersSchema(BaseModel):
    order_ids: List[int] = Field(default_factory=list)


class InvoiceUpdateSchema(BaseModel):
    invoice_kind: Optional[str] = None
    invoice_code: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    seller_name: Optional[str] = None
    seller_tax_id: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_tax_id: Optional[str] = None
    currency: Optional[str] = None
    amount_excl_tax: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: Optional[float] = None
    total_in_words: Optional[str] = None
    remark: Optional[str] = None
    verified: Optional[bool] = None


class InvoiceLinkSchema(BaseModel):
    owner_type: str = Field(..., description="order/package/purchase_order")
    owner_id: int = Field(..., ge=1)
    allocated_amount: float = 0


class TaxCertSchema(BaseModel):
    order_id: int = 0
    title: str = ""
    cert_no: str = ""
    cert_type: str = ""
    tax_period: str = ""
    country: str = ""
    amount: float = 0
    currency: str = "CNY"
    issued_date: str = ""
    note: str = ""
    status: str = "已归档"


# ═══════════════════════ 订单 / 同步 ═══════════════════════

@router.get("/meta", summary="履约中心资料分类元数据")
def get_meta(user: dict = READ_DEP):
    filters = FulfillmentService.list_order_filters()
    return {"code": 0, "msg": "success", "data": {
        "categories": FM_DOC_CATEGORIES,
        "owner_types": [
            {"key": "order", "label": "订单"},
            {"key": "package", "label": "包裹"},
            {"key": "purchase_order", "label": "采购单"},
            {"key": "tax_cert", "label": "清关报税"},
            {"key": "invoice", "label": "发票"},
        ],
        "order_statuses": filters["statuses"],
        "shops": filters["shops"],
    }}


@router.post("/orders/sync", summary="从妙手同步订单/包裹并自动匹配 (可按订单号)")
def sync_orders(payload: SyncSchema, user: dict = EDIT_DEP):
    data = FulfillmentService.sync_from_miaoshou(
        days=payload.days, order_sn=payload.order_sn.strip(),
        pull=payload.pull, username=user.get("username", ""))
    msg = f"已导入 {data['orders']} 个订单 / {data['packages']} 个包裹"
    if data.get("labeled"):
        msg += f"；商品标识识别 {data['labeled']} 单"
    if data.get("pull_error"):
        msg += f"；妙手在线同步失败: {data['pull_error']}"
    return {"code": 0, "msg": msg, "data": data}


@router.get("/materials-summary", summary="按订单批量汇总履约素材数量")
def materials_summary(order_ids: str = Query("", max_length=4000),
                      order_sns: str = Query("", max_length=8000),
                      user: dict = READ_DEP):
    ids = [int(x) for x in order_ids.split(",") if x.strip().isdigit()]
    sns = [x.strip() for x in order_sns.split(",") if x.strip()]
    return {"code": 0, "msg": "success",
            "data": FulfillmentService.materials_summary(ids, sns)}


@router.get("/orders", summary="履约订单列表 (逐步跟踪)")
def list_orders(keyword: str = Query("", max_length=120),
                status: str = Query("", max_length=60),
                shop: str = Query("", max_length=120),
                shop_id: str = Query("", max_length=120),
                date_from: str = Query("", max_length=40),
                date_to: str = Query("", max_length=40),
                include_closed: bool = Query(False, description="是否包含已关闭订单 (默认排除)"),
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                user: dict = READ_DEP):
    return {"code": 0, "msg": "success", "data": FulfillmentService.list_orders(
        keyword, page, page_size, status=status, shop=shop, shop_id=shop_id,
        date_from=date_from, date_to=date_to, include_closed=include_closed)}


@router.get("/orders/{order_id}/supplement", summary="履约订单补录信息")
def get_order_supplement(order_id: int, user: dict = READ_DEP):
    return {"code": 0, "msg": "success",
            "data": FulfillmentService.get_order_supplement(order_id)}


@router.post("/orders/{order_id}/supplement", summary="保存履约订单补录信息")
def save_order_supplement(order_id: int, payload: dict = Body(...),
                          user: dict = EDIT_DEP):
    data = FulfillmentService.save_order_supplement(
        order_id,
        purchase_date=str(payload.get("purchase_date") or ""),
        domestic_package_count=int(payload.get("domestic_package_count") or 0),
        domestic_tracking_no=str(payload.get("domestic_tracking_no") or ""),
    )
    return {"code": 0, "msg": "补录信息已保存", "data": data}


@router.get("/orders/{order_id}", summary="订单履约工作台聚合数据")
def get_order_workspace(order_id: int, user: dict = READ_DEP):
    return {"code": 0, "msg": "success", "data": FulfillmentService.get_order_workspace(order_id)}


@router.post("/orders/{order_id}/materials", summary="统一上传订单素材 (先暂存后一次性提交解析落库)")
def batch_upload_materials(order_id: int,
                           manifest: str = Form(..., description="素材清单 JSON 数组"),
                           files: List[UploadFile] = File(...),
                           user: dict = EDIT_DEP):
    try:
        items = json.loads(manifest)
    except ValueError:
        raise HTTPException(status_code=400, detail="素材清单格式错误")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="素材清单必须是数组")
    data = FulfillmentService.batch_upload_materials(
        order_id, items, files, username=user.get("username", ""))
    msg = f"已处理 {data['total']} 个素材：成功 {data['success']} 个"
    if data["failed"]:
        msg += f"，失败 {data['failed']} 个"
    return {"code": 0, "msg": msg, "data": data}


# ═══════════════════════ 包裹 ═══════════════════════

@router.get("/packages", summary="包裹列表 (含关联订单与资料)")
def list_packages(keyword: str = Query("", max_length=120),
                  include_closed: bool = Query(False, description="是否包含已关闭包裹 (默认排除)"),
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  user: dict = READ_DEP):
    return {"code": 0, "msg": "success", "data": FulfillmentService.list_packages(
        keyword, page, page_size, include_closed=include_closed)}


@router.post("/packages/{package_id}/link-orders", summary="包裹补充关联多个订单 (合单)")
def link_package_orders(package_id: int, payload: LinkOrdersSchema, user: dict = EDIT_DEP):
    return {"code": 0, "msg": "包裹关联已更新",
            "data": FulfillmentService.link_package_orders(package_id, payload.order_ids)}


@router.delete("/packages/{package_id}/orders/{order_id}", summary="解除包裹与订单关联")
def unlink_package_order(package_id: int, order_id: int, user: dict = EDIT_DEP):
    return {"code": 0, "msg": "已解除包裹关联",
            "data": FulfillmentService.unlink_package_order(package_id, order_id)}


# ═══════════════════════ 国内采购单 ═══════════════════════

@router.get("/purchase-orders", summary="国内采购单列表")
def list_purchase_orders(keyword: str = Query("", max_length=120),
                         page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                         user: dict = READ_DEP):
    return {"code": 0, "msg": "success",
            "data": FulfillmentService.list_purchase_orders(keyword, page, page_size)}


@router.get("/purchase-orders/{po_id}", summary="采购单详情")
def get_purchase_order(po_id: int, user: dict = READ_DEP):
    return {"code": 0, "msg": "success", "data": FulfillmentService.get_purchase_order(po_id)}


@router.post("/purchase-orders", summary="新建采购单")
def create_purchase_order(payload: PurchaseOrderSchema, user: dict = EDIT_DEP):
    data = FulfillmentService.create_purchase_order(payload.dict(), username=user.get("username", ""))
    return {"code": 0, "msg": "采购单已创建", "data": data}


@router.put("/purchase-orders/{po_id}", summary="编辑采购单")
def update_purchase_order(po_id: int, payload: PurchaseOrderUpdateSchema, user: dict = EDIT_DEP):
    data = FulfillmentService.update_purchase_order(
        po_id, {k: v for k, v in payload.dict().items() if v is not None})
    return {"code": 0, "msg": "采购单已更新", "data": data}


@router.delete("/purchase-orders/{po_id}", summary="删除采购单 (需删除权限)")
def delete_purchase_order(po_id: int, user: dict = DELETE_DEP):
    return {"code": 0, "msg": "采购单已删除", "data": FulfillmentService.delete_purchase_order(po_id)}


@router.post("/purchase-orders/{po_id}/link-orders", summary="采购单关联多个亚马逊订单")
def link_purchase_orders(po_id: int, payload: LinkOrdersSchema, user: dict = EDIT_DEP):
    return {"code": 0, "msg": "关联已更新",
            "data": FulfillmentService.link_purchase_orders(po_id, payload.order_ids)}


@router.delete("/purchase-orders/{po_id}/orders/{order_id}", summary="解除采购单与订单关联")
def unlink_purchase_order(po_id: int, order_id: int, user: dict = EDIT_DEP):
    return {"code": 0, "msg": "已解除关联",
            "data": FulfillmentService.unlink_purchase_order(po_id, order_id)}


@router.post("/purchase-orders/import", summary="上传采购单截图并自动结构化建档")
def import_purchase_order(file: UploadFile = File(...),
                          order_id: int = Form(0),
                          user: dict = EDIT_DEP):
    data = FulfillmentService.import_purchase_order(
        file, order_id=order_id, username=user.get("username", ""))
    msg = "采购单已自动建档"
    if data.get("warnings"):
        msg += "；" + "；".join(data["warnings"])
    return {"code": 0, "msg": msg, "data": data}


@router.post("/purchase-orders/{po_id}/documents", summary="上传采购单截图/转账凭证并自动解析")
def upload_purchase_document(po_id: int,
                             category: str = Form(...),
                             file: UploadFile = File(...),
                             auto_parse: bool = Form(True),
                             user: dict = EDIT_DEP):
    data = FulfillmentService.add_purchase_document(
        po_id, category, file, username=user.get("username", ""), auto_parse=auto_parse)
    msg = "资料已上传"
    if data.get("warnings"):
        msg += "；" + "；".join(data["warnings"])
    return {"code": 0, "msg": msg, "data": data}


# ═══════════════════════ 清关报税 ═══════════════════════

@router.get("/tax-certs", summary="清关报税列表")
def list_tax_certs(keyword: str = Query("", max_length=120),
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   user: dict = READ_DEP):
    return {"code": 0, "msg": "success", "data": FulfillmentService.list_tax_certs(keyword, page, page_size)}


@router.get("/tax-certs/{cert_id}", summary="清关报税详情")
def get_tax_cert(cert_id: int, user: dict = READ_DEP):
    return {"code": 0, "msg": "success", "data": FulfillmentService.get_tax_cert(cert_id)}


@router.post("/tax-certs", summary="新建清关报税 (可选关联订单)")
def create_tax_cert(payload: TaxCertSchema, user: dict = EDIT_DEP):
    data = FulfillmentService.create_tax_cert(payload.dict(), username=user.get("username", ""))
    return {"code": 0, "msg": "清关报税已创建", "data": data}


@router.put("/tax-certs/{cert_id}", summary="编辑清关报税")
def update_tax_cert(cert_id: int, payload: TaxCertSchema, user: dict = EDIT_DEP):
    data = FulfillmentService.update_tax_cert(cert_id, payload.dict())
    return {"code": 0, "msg": "清关报税已更新", "data": data}


@router.delete("/tax-certs/{cert_id}", summary="删除清关报税 (需删除权限)")
def delete_tax_cert(cert_id: int, user: dict = DELETE_DEP):
    return {"code": 0, "msg": "清关报税已删除", "data": FulfillmentService.delete_tax_cert(cert_id)}


@router.post("/tax-certs/{cert_id}/documents", summary="上传清关报税文件")
def upload_tax_cert_document(cert_id: int, file: UploadFile = File(...),
                             note: str = Form(""), user: dict = EDIT_DEP):
    doc = FulfillmentDocService.save_upload(
        "tax_cert", cert_id, "tax_cert", file,
        username=user.get("username", ""), note=note)
    return {"code": 0, "msg": "文件已上传", "data": doc}


# ═══════════════════════ 发票 ═══════════════════════

@router.get("/invoices", summary="发票列表 (含明细与关联对象)")
def list_invoices(keyword: str = Query("", max_length=120),
                  parse_status: str = Query("", max_length=20),
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  user: dict = READ_DEP):
    return {"code": 0, "msg": "success",
            "data": FulfillmentService.list_invoices(keyword, parse_status, page, page_size)}


@router.get("/invoices/{invoice_id}", summary="发票详情")
def get_invoice(invoice_id: int, user: dict = READ_DEP):
    return {"code": 0, "msg": "success", "data": FulfillmentService.get_invoice(invoice_id)}


@router.post("/invoices", summary="上传发票并自动解析/关联")
def upload_invoice(file: UploadFile = File(...),
                   owner_type: str = Form(""),
                   owner_id: int = Form(0),
                   invoice_kind: str = Form(""),
                   auto_parse: bool = Form(True),
                   user: dict = EDIT_DEP):
    data = FulfillmentService.create_invoice(
        file, owner_type=owner_type.strip(), owner_id=owner_id,
        invoice_kind=invoice_kind, username=user.get("username", ""), auto_parse=auto_parse)
    msg = "发票已保存"
    if data.get("duplicate"):
        msg = "发票文件已存在，已复用"
    if data.get("warnings"):
        msg += "；" + "；".join(data["warnings"])
    return {"code": 0, "msg": msg, "data": data}


@router.put("/invoices/{invoice_id}", summary="人工修正发票信息")
def update_invoice(invoice_id: int, payload: InvoiceUpdateSchema, user: dict = EDIT_DEP):
    data = FulfillmentService.update_invoice(
        invoice_id, {k: v for k, v in payload.dict().items() if v is not None})
    return {"code": 0, "msg": "发票已更新", "data": data}


@router.post("/invoices/{invoice_id}/reparse", summary="重新解析发票 (需解析权限)")
def reparse_invoice(invoice_id: int, user: dict = PARSE_DEP):
    data = FulfillmentService.reparse_invoice(invoice_id, username=user.get("username", ""))
    return {"code": 0, "msg": "发票已重新解析", "data": data}


@router.delete("/invoices/{invoice_id}", summary="删除发票 (需删除权限)")
def delete_invoice(invoice_id: int, user: dict = DELETE_DEP):
    return {"code": 0, "msg": "发票已删除", "data": FulfillmentService.delete_invoice(invoice_id)}


@router.post("/invoices/{invoice_id}/links", summary="发票追加关联订单/包裹/采购单")
def add_invoice_link(invoice_id: int, payload: InvoiceLinkSchema, user: dict = EDIT_DEP):
    data = FulfillmentService.add_invoice_link(
        invoice_id, payload.owner_type, payload.owner_id, payload.allocated_amount)
    return {"code": 0, "msg": "关联已添加", "data": data}


@router.delete("/invoices/{invoice_id}/links", summary="解除发票关联")
def remove_invoice_link(invoice_id: int, owner_type: str = Query(...),
                        owner_id: int = Query(...), user: dict = EDIT_DEP):
    data = FulfillmentService.remove_invoice_link(invoice_id, owner_type, owner_id)
    return {"code": 0, "msg": "关联已解除", "data": data}


# ═══════════════════════ 通用附件 ═══════════════════════

@router.get("/documents", summary="履约资料列表")
def list_documents(owner_type: str = Query(...), owner_id: int = Query(...),
                   category: str = Query(""), user: dict = READ_DEP):
    data = FulfillmentDocService.list_docs(owner_type, owner_id, category)
    return {"code": 0, "msg": "success", "data": data}


@router.post("/documents", summary="上传履约资料 (发货单/签收单/其他, 支持多文件)")
def upload_documents(owner_type: str = Form(...), owner_id: int = Form(...),
                     category: str = Form(...), note: str = Form(""),
                     files: List[UploadFile] = File(...), user: dict = EDIT_DEP):
    saved = [
        FulfillmentDocService.save_upload(owner_type, owner_id, category, f,
                                          username=user.get("username", ""), note=note)
        for f in files
    ]
    return {"code": 0, "msg": f"已上传 {len(saved)} 个文件", "data": saved}


@router.delete("/documents/{doc_id}", summary="删除履约资料 (需删除权限)")
def delete_document(doc_id: int, user: dict = DELETE_DEP):
    doc = FulfillmentDocService.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="资料不存在")
    data = FulfillmentDocService.delete_doc(doc_id)
    # 采购单最后一素材被删掉后, 空壳采购单同步清理
    removed = False
    if doc.get("owner_type") == "purchase_order":
        removed = FulfillmentService.cleanup_purchase_order_if_empty(int(doc["owner_id"]))
    return {"code": 0, "msg": "资料已删除" + ("，对应采购单已一并删除" if removed else ""),
            "data": data}


@router.get("/documents/{doc_id}/download", summary="下载履约资料")
def download_document(doc_id: int, user: dict = READ_DEP):
    doc = FulfillmentDocService.get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = FulfillmentDocService.get_doc_path(doc)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件已丢失")
    return FileResponse(path, filename=doc.get("file_name") or "file",
                        media_type=doc.get("mime_type") or None)
