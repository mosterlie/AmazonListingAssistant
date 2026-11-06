"""
履约中心 · 统一附件服务

与现有 order_docs 完全隔离:
- 物理目录: data/uploads/fulfillment/{owner_type}/{owner_id}/
- 元数据表: fm_documents
- 支持: 采购单截图 / 转账凭证 / 发货单 / 签收单 / 清关报税 / 发票文件 / 其他
"""
import hashlib
import mimetypes
import os
import re
import shutil
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile

from server.config import UPLOADS_DIR
from server.database import get_db_connection
from server.services.order_doc_service import (
    ALLOWED_EXTS,
    IMAGE_EXTS,
    MAX_DOC_SIZE,
    OrderDocService,
    make_first_page_thumb,
)

# 附件分类注册表 (顺序即页面展示顺序)
FM_DOC_CATEGORIES: List[Dict[str, str]] = [
    {"key": "purchase_order_shot", "label": "采购单截图", "icon": "🧾", "owner": "purchase_order"},
    {"key": "transfer_voucher", "label": "转账凭证", "icon": "💳", "owner": "purchase_order"},
    {"key": "delivery_note", "label": "发货单", "icon": "📦", "owner": "package"},
    {"key": "receipt", "label": "签收单", "icon": "✍️", "owner": "package"},
    {"key": "tax_cert", "label": "清关报税", "icon": "🛃", "owner": "tax_cert"},
    {"key": "invoice", "label": "发票", "icon": "📄", "owner": "invoice"},
    {"key": "other", "label": "其他资料", "icon": "📎", "owner": "any"},
]
FM_DOC_CATEGORY_MAP = {c["key"]: c for c in FM_DOC_CATEGORIES}

FM_OWNER_TABLES = {
    "order": "fm_orders",
    "package": "fm_packages",
    "purchase_order": "fm_purchase_orders",
    "tax_cert": "fm_tax_certs",
    "invoice": "fm_invoices",
}


def _doc_root(owner_type: str, owner_id: int) -> str:
    return os.path.join(UPLOADS_DIR, "fulfillment", owner_type, str(int(owner_id)))


class FulfillmentDocService:
    """履约资料上传 / 查询 / 删除"""

    @staticmethod
    def check_category(category: str, owner_type: str) -> Dict[str, str]:
        meta = FM_DOC_CATEGORY_MAP.get(category)
        if not meta:
            raise HTTPException(status_code=400, detail=f"未知资料分类: {category}")
        if meta["owner"] != "any" and meta["owner"] != owner_type:
            raise HTTPException(status_code=400,
                                detail=f"「{meta['label']}」只能挂在 {meta['owner']} 上")
        return meta

    @staticmethod
    def owner_exists(owner_type: str, owner_id: int) -> bool:
        table = FM_OWNER_TABLES.get(owner_type)
        if not table:
            raise HTTPException(status_code=400, detail=f"未知归属类型: {owner_type}")
        conn = get_db_connection()
        try:
            return bool(conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (int(owner_id),)).fetchone())
        finally:
            conn.close()

    @staticmethod
    def read_upload(file: UploadFile) -> Dict[str, Any]:
        """读取并校验上传文件 (20MB, 白名单), 返回文件名/内容/mime/扩展名"""
        raw_name = os.path.basename(file.filename or "file")
        clean_name = re.sub(r'[\\/*?:"<>|]', "_", raw_name).strip() or "file"
        ext = os.path.splitext(clean_name)[1].lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400,
                                detail=f"「{raw_name}」类型不支持，请上传图片或 PDF/Office/压缩包文件")
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size <= 0:
            raise HTTPException(status_code=400, detail=f"「{raw_name}」内容为空")
        if size > MAX_DOC_SIZE:
            raise HTTPException(status_code=400, detail=f"「{raw_name}」超过 20MB 上限")
        content = file.file.read()
        mime = file.content_type or mimetypes.guess_type(clean_name)[0] or "application/octet-stream"
        return {"file_name": clean_name, "ext": ext, "size": size,
                "content": content, "mime": mime, "sha256": hashlib.sha256(content).hexdigest()}

    @staticmethod
    def save_bytes(owner_type: str, owner_id: int, category: str, payload: Dict[str, Any],
                   username: str = "", note: str = "") -> Dict[str, Any]:
        """把已读入内存的文件落盘并写元数据"""
        meta = FulfillmentDocService.check_category(category, owner_type)
        if not FulfillmentDocService.owner_exists(owner_type, owner_id):
            raise HTTPException(status_code=404, detail="资料归属对象不存在")

        target_dir = _doc_root(owner_type, owner_id)
        os.makedirs(target_dir, exist_ok=True)
        ext = payload["ext"]
        stored_name = f"{uuid.uuid4().hex[:12]}_{payload['file_name']}"
        path = os.path.join(target_dir, stored_name)
        with open(path, "wb") as buf:
            buf.write(payload["content"])

        thumb_name = ""
        if ext not in IMAGE_EXTS:
            try:
                thumb_name = make_first_page_thumb(path)
            except Exception:
                thumb_name = ""

        rel_url = f"/uploads/fulfillment/{owner_type}/{int(owner_id)}/{stored_name}"
        conn = get_db_connection()
        try:
            cur = conn.execute("""
                INSERT INTO fm_documents (owner_type, owner_id, category, file_name, stored_name,
                                          relative_url, thumb_name, mime_type, size_bytes, sha256,
                                          note, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (owner_type, int(owner_id), category, payload["file_name"], stored_name,
                  rel_url, thumb_name, payload["mime"], payload["size"], payload["sha256"],
                  note or "", username or ""))
            conn.commit()
            doc_id = cur.lastrowid
        finally:
            conn.close()

        return FulfillmentDocService._to_dict({
            "id": doc_id, "owner_type": owner_type, "owner_id": int(owner_id),
            "category": category, "file_name": payload["file_name"], "stored_name": stored_name,
            "relative_url": rel_url, "thumb_name": thumb_name, "mime_type": payload["mime"],
            "size_bytes": payload["size"], "sha256": payload["sha256"],
            "note": note or "", "uploaded_by": username or "",
            "created_at": "",
        }, category_label=meta["label"], category_icon=meta["icon"])

    @staticmethod
    def save_upload(owner_type: str, owner_id: int, category: str, file: UploadFile,
                    username: str = "", note: str = "") -> Dict[str, Any]:
        payload = FulfillmentDocService.read_upload(file)
        return FulfillmentDocService.save_bytes(owner_type, owner_id, category, payload,
                                                username=username, note=note)

    @staticmethod
    def _to_dict(row, category_label: str = "", category_icon: str = "") -> Dict[str, Any]:
        d = dict(row)
        meta = FM_DOC_CATEGORY_MAP.get(d.get("category") or "", {})
        ext = os.path.splitext(d.get("stored_name") or "")[1].lower()
        is_image = ext in IMAGE_EXTS
        thumb = d.get("thumb_name") or ""
        thumb_url = (f"/uploads/fulfillment/{d['owner_type']}/{d['owner_id']}/{thumb}"
                     if thumb else "")
        d["is_image"] = is_image
        d["size_text"] = OrderDocService.size_text(d.get("size_bytes") or 0)
        d["thumb_url"] = thumb_url
        d["preview_url"] = (d.get("relative_url") or "") if is_image else thumb_url
        d["download_url"] = f"/api/fulfillment/documents/{d['id']}/download"
        d["category_label"] = category_label or meta.get("label", d.get("category") or "")
        d["category_icon"] = category_icon or meta.get("icon", "📎")
        return d

    @staticmethod
    def list_docs(owner_type: str, owner_id: int, category: str = "") -> List[Dict[str, Any]]:
        sql = "SELECT * FROM fm_documents WHERE owner_type = ? AND owner_id = ?"
        params: List[Any] = [owner_type, int(owner_id)]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY id DESC"
        conn = get_db_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [FulfillmentDocService._to_dict(r) for r in rows]

    @staticmethod
    def count_docs(owner_type: str, owner_ids: List[int]) -> Dict[int, Dict[str, int]]:
        """批量统计: {owner_id: {category: count}}"""
        if not owner_ids:
            return {}
        marks = ",".join("?" * len(owner_ids))
        conn = get_db_connection()
        try:
            rows = conn.execute(
                f"SELECT owner_id, category, COUNT(1) c FROM fm_documents "
                f"WHERE owner_type = ? AND owner_id IN ({marks}) GROUP BY owner_id, category",
                [owner_type] + [int(i) for i in owner_ids]).fetchall()
        finally:
            conn.close()
        out: Dict[int, Dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["owner_id"], {})[r["category"]] = r["c"]
        return out

    @staticmethod
    def get_doc(doc_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM fm_documents WHERE id = ?", (int(doc_id),)).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_doc_path(doc: Dict[str, Any]) -> str:
        return os.path.join(UPLOADS_DIR, "fulfillment", doc["owner_type"],
                            str(doc["owner_id"]), doc.get("stored_name") or "")

    @staticmethod
    def delete_doc(doc_id: int) -> Dict[str, Any]:
        doc = FulfillmentDocService.get_doc(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="附件不存在")
        if doc.get("category") == "invoice":
            raise HTTPException(status_code=400, detail="发票请到发票管理中删除，避免遗留空发票记录")
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM fm_documents WHERE id = ?", (int(doc_id),))
            conn.commit()
        finally:
            conn.close()
        folder = os.path.dirname(FulfillmentDocService.get_doc_path(doc))
        for name in (doc.get("stored_name"), doc.get("thumb_name")):
            if not name:
                continue
            try:
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        return {"id": int(doc_id)}
