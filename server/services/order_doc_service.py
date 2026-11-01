"""
订单单据附件服务 (采购单 / 采购发票 / 发货单 / 配送轨迹 / 签收单 / 物流发票 / 清关证明)

- 每单每类单据可上传多份 (图片或任意文档)
- 物理文件: data/uploads/orders/{order_id}/{uuid}_{原文件名}, 通过 /uploads/** 直接访问
- 文档类文件上传时生成「首页快照」PNG (thumb_name), 供列表/弹窗预览
  快照生成链: macOS QuickLook(qlmanage) → sips(PDF) → LibreOffice 转 PDF 后再走前两者
- 元数据: order_docs 表
"""
import io
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from server.config import UPLOADS_DIR
from server.database import get_db_connection

# 单据类型注册表 (顺序即列表列顺序)
# name_by: 附件重命名前缀依据 —— order_sn=amazon 订单号 / tracking_no=运单号
DOC_TYPES: List[Dict[str, str]] = [
    {"key": "purchase_order", "label": "采购单", "icon": "🧾", "name_by": "order_sn"},
    {"key": "purchase_invoice", "label": "采购发票", "icon": "🧮", "name_by": "order_sn"},
    {"key": "delivery_note", "label": "发货单", "icon": "📦", "name_by": "tracking_no"},
    {"key": "delivery_track", "label": "配送轨迹", "icon": "🛣️", "name_by": "tracking_no"},
    {"key": "receipt", "label": "签收单", "icon": "✍️", "name_by": "tracking_no"},
    {"key": "logistics_invoice", "label": "物流发票", "icon": "🚚", "name_by": "tracking_no"},
    {"key": "customs_cert", "label": "清关证明", "icon": "🛃", "name_by": "tracking_no"},
]
DOC_TYPE_KEYS = [d["key"] for d in DOC_TYPES]

MAX_DOC_SIZE = 20 * 1024 * 1024   # 单文件 20MB
MAX_BATCH_ORDERS = 200            # 批量上传单次最多覆盖的订单数

# 允许的附件类型 (扩展名白名单; 图片 + 常见办公文档 + 压缩包)
ALLOWED_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
    ".zip", ".rar", ".7z",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic"}

THUMB_MAX = 640          # 首页快照最长边 (px)
THUMB_TIMEOUT = 25       # 单次快照命令超时 (秒)
SOFFICE_TIMEOUT = 90     # 文档转 PDF 超时 (秒)


def _doc_root(order_id: int) -> str:
    return os.path.join(UPLOADS_DIR, "orders", str(int(order_id)))


def _normalize_image(src: str, dst: str) -> bool:
    """把快照统一压成 RGB 最长边 640 的 PNG (PIL 不可用时直接复制)"""
    try:
        from PIL import Image
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB_MAX, THUMB_MAX))
            im.save(dst, format="PNG", optimize=True)
        return os.path.isfile(dst)
    except Exception:
        try:
            shutil.copyfile(src, dst)
            return True
        except Exception:
            return False


def _first_png(folder: str) -> Optional[str]:
    try:
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".png"):
                return os.path.join(folder, name)
    except OSError:
        pass
    return None


def make_first_page_thumb(file_path: str) -> str:
    """为文档生成首页快照, 返回快照文件名 (失败返回空串)

    依次尝试: QuickLook(qlmanage) → sips(PDF) → LibreOffice 转 PDF 后再渲染
    """
    base = os.path.basename(file_path)
    thumb_name = f"{base}.thumb.png"
    out_path = os.path.join(os.path.dirname(file_path), thumb_name)
    tmpdir = tempfile.mkdtemp(prefix="orderdoc_thumb_")
    try:
        # 1) macOS QuickLook: 原生支持 pdf/docx/xlsx/pptx/zip 等
        ql = shutil.which("qlmanage")
        if ql:
            try:
                subprocess.run([ql, "-t", "-s", str(THUMB_MAX), "-o", tmpdir, file_path],
                               capture_output=True, timeout=THUMB_TIMEOUT)
            except (subprocess.SubprocessError, OSError):
                pass
            cand = _first_png(tmpdir)
            if cand and _normalize_image(cand, out_path):
                return thumb_name

        # 2) macOS sips: PDF 首页
        if file_path.lower().endswith(".pdf"):
            sips = shutil.which("sips")
            if sips:
                try:
                    r = subprocess.run([sips, "-s", "format", "png", "-Z", str(THUMB_MAX),
                                        file_path, "--out", out_path],
                                       capture_output=True, timeout=THUMB_TIMEOUT)
                    if r.returncode == 0 and os.path.isfile(out_path):
                        return thumb_name
                except (subprocess.SubprocessError, OSError):
                    pass

        # 3) LibreOffice 转 PDF 后再渲染 (跨平台兜底, 较慢)
        office = shutil.which("soffice") or shutil.which("libreoffice")
        if office:
            convert_dir = os.path.join(tmpdir, "pdf")
            os.makedirs(convert_dir, exist_ok=True)
            try:
                subprocess.run([office, "--headless", "--convert-to", "pdf", "--outdir",
                                convert_dir, file_path],
                               capture_output=True, timeout=SOFFICE_TIMEOUT)
            except (subprocess.SubprocessError, OSError):
                pass
            pdfs = [f for f in (os.listdir(convert_dir) if os.path.isdir(convert_dir) else [])
                    if f.lower().endswith(".pdf")]
            if pdfs and shutil.which("qlmanage"):
                render_dir = os.path.join(tmpdir, "render")
                os.makedirs(render_dir, exist_ok=True)
                try:
                    subprocess.run([shutil.which("qlmanage"), "-t", "-s", str(THUMB_MAX), "-o",
                                    render_dir, os.path.join(convert_dir, pdfs[0])],
                                   capture_output=True, timeout=THUMB_TIMEOUT)
                except (subprocess.SubprocessError, OSError):
                    pass
                cand = _first_png(render_dir)
                if cand and _normalize_image(cand, out_path):
                    return thumb_name
        return ""
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class OrderDocService:
    """订单单据附件的上传 / 查询 / 删除"""

    @staticmethod
    def _check_type(doc_type: str) -> Dict[str, str]:
        for d in DOC_TYPES:
            if d["key"] == doc_type:
                return d
        raise HTTPException(status_code=400, detail=f"未知单据类型: {doc_type}")

    @staticmethod
    def _order_exists(order_id: int) -> bool:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT 1 FROM miaoshou_orders WHERE id = ?", (order_id,)).fetchone()
            return bool(row)
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        d = dict(row)
        ext = os.path.splitext(d.get("stored_name") or "")[1].lower()
        d["is_image"] = ext in IMAGE_EXTS
        d["size_text"] = OrderDocService.size_text(d.get("size_bytes") or 0)
        # preview_url: 图片用原图, 文档用首页快照 (都没有则为空, 前端退回文件图标)
        thumb = d.get("thumb_name") or ""
        thumb_url = f"/uploads/orders/{d['order_id']}/{thumb}" if thumb else ""
        d["thumb_url"] = thumb_url
        d["preview_url"] = (d.get("relative_url") or "") if d["is_image"] else thumb_url
        return d

    @staticmethod
    def _ensure_thumb(d: Dict[str, Any]) -> Dict[str, Any]:
        """历史文件懒补快照: 文档缺 thumb_name 时现场生成并写库 (失败静默)"""
        if d.get("is_image") or d.get("thumb_name"):
            return d
        path = os.path.join(_doc_root(d["order_id"]), d.get("stored_name") or "")
        if not d.get("stored_name") or not os.path.isfile(path):
            return d
        try:
            thumb = make_first_page_thumb(path)
        except Exception:
            thumb = ""
        if not thumb:
            return d
        conn = get_db_connection()
        try:
            conn.execute("UPDATE order_docs SET thumb_name = ? WHERE id = ?", (thumb, d["id"]))
            conn.commit()
        finally:
            conn.close()
        d["thumb_name"] = thumb
        d["thumb_url"] = f"/uploads/orders/{d['order_id']}/{thumb}"
        d["preview_url"] = d["thumb_url"]
        return d

    @staticmethod
    def size_text(size: int) -> str:
        n = float(size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"

    @staticmethod
    def _doc_prefix(order_id: int, doc_type: str) -> str:
        """附件命名前缀: 采购单/采购发票用 amazon 订单号, 其余单据用运单号

        对应字段缺失时依次回退 (运单号 → 订单号 → order{id})
        """
        meta = OrderDocService._check_type(doc_type)
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT order_sn, tracking_no FROM miaoshou_orders WHERE id = ?",
                               (int(order_id),)).fetchone()
        finally:
            conn.close()

        def _clean(v) -> str:
            return re.sub(r'[\\/*?:"<>|\s]+', "_", str(v or "")).strip("_")

        sn = _clean(row["order_sn"] if row else "")
        tail = _clean(row["tracking_no"] if row else "")
        if meta.get("name_by") == "tracking_no" and tail:
            return tail
        return sn or tail or f"order{int(order_id)}"

    @staticmethod
    def _next_attach_seq(order_id: int, doc_type: str, sn: str) -> Tuple[int, set]:
        """同类附件的下一个序号: 取已有 {订单号}_n 的最大 n + 1 (删除后不复用);

        返回 (起始序号, 已有文件名集合), 供同批次上传继续递增并去重
        """
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT file_name FROM order_docs WHERE order_id = ? AND doc_type = ?",
                (int(order_id), doc_type)).fetchall()
        finally:
            conn.close()
        names = {str(r["file_name"] or "") for r in rows}
        used = []
        for name in names:
            m = re.match(rf"^{re.escape(sn)}_(\d+)$", os.path.splitext(name)[0])
            if m:
                used.append(int(m.group(1)))
        return (max(used) + 1 if used else 1), names

    @staticmethod
    def save_docs(order_id: int, doc_type: str, files: List[UploadFile],
                  username: str = "") -> List[Dict[str, Any]]:
        """保存一批单据文件 (同类可多份), 返回新增的文件信息

        展示/下载文件名统一为「amazon订单号_序号.扩展名」(序号按单据类型各自递增);
        磁盘文件仍用 uuid 前缀 + 原始文件名, 避免重名与特殊字符问题。
        """
        OrderDocService._check_type(doc_type)
        if not OrderDocService._order_exists(order_id):
            raise HTTPException(status_code=404, detail="订单不存在")
        if not files:
            raise HTTPException(status_code=400, detail="未选择文件")

        target_dir = _doc_root(order_id)
        os.makedirs(target_dir, exist_ok=True)

        sn = OrderDocService._doc_prefix(order_id, doc_type)
        next_seq, used_names = OrderDocService._next_attach_seq(order_id, doc_type, sn)

        saved: List[Dict[str, Any]] = []
        for f in files:
            raw_name = os.path.basename(f.filename or "file")
            clean_name = re.sub(r'[\\/*?:"<>|]', "_", raw_name).strip() or "file"
            ext = os.path.splitext(clean_name)[1].lower()
            if ext not in ALLOWED_EXTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"「{raw_name}」类型不支持，请上传图片或 PDF/Office/压缩包文件")
            # 计算大小
            f.file.seek(0, 2)
            size = f.file.tell()
            f.file.seek(0)
            if size <= 0:
                raise HTTPException(status_code=400, detail=f"「{raw_name}」内容为空")
            if size > MAX_DOC_SIZE:
                raise HTTPException(status_code=400, detail=f"「{raw_name}」超过 20MB 上限")

            # 展示/下载名: amazon订单号_序号.扩展名 (同类型内递增, 避免与已有名重复)
            display_name = f"{sn}_{next_seq}{ext}"
            while display_name in used_names:
                next_seq += 1
                display_name = f"{sn}_{next_seq}{ext}"
            used_names.add(display_name)
            next_seq += 1

            stored_name = f"{uuid.uuid4().hex[:10]}_{clean_name}"
            path = os.path.join(target_dir, stored_name)
            with open(path, "wb") as buf:
                shutil.copyfileobj(f.file, buf)

            mime = f.content_type or mimetypes.guess_type(clean_name)[0] or "application/octet-stream"
            rel_url = f"/uploads/orders/{int(order_id)}/{stored_name}"
            # 文档类生成首页快照 (图片直接用原图预览, 无需快照)
            thumb_name = ""
            if ext not in IMAGE_EXTS:
                try:
                    thumb_name = make_first_page_thumb(path)
                except Exception:
                    thumb_name = ""
            conn = get_db_connection()
            try:
                cur = conn.execute(
                    "INSERT INTO order_docs (order_id, doc_type, file_name, stored_name, relative_url, "
                    "thumb_name, mime_type, size_bytes, uploaded_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (int(order_id), doc_type, display_name, stored_name, rel_url, thumb_name,
                     mime, size, username or ""))
                conn.commit()
                doc_id = cur.lastrowid
            finally:
                conn.close()
            thumb_url = f"/uploads/orders/{int(order_id)}/{thumb_name}" if thumb_name else ""
            saved.append({
                "id": doc_id, "order_id": int(order_id), "doc_type": doc_type,
                "file_name": display_name, "stored_name": stored_name, "relative_url": rel_url,
                "thumb_name": thumb_name, "thumb_url": thumb_url,
                "preview_url": rel_url if ext in IMAGE_EXTS else thumb_url,
                "mime_type": mime, "size_bytes": size, "size_text": OrderDocService.size_text(size),
                "is_image": ext in IMAGE_EXTS,
            })
        return saved

    @staticmethod
    def _read_uploads(files: List[UploadFile]) -> List[Tuple[str, str, bytes, str]]:
        """一次性读取并校验上传文件, 返回 [(原始名, 清洗文件名, 内容, mime)]

        批量上传要把同一份内容分别写入多个订单, 因此先读入内存复用 (单文件仍受 20MB 限制)
        """
        items: List[Tuple[str, str, bytes, str]] = []
        for f in files:
            raw_name = os.path.basename(f.filename or "file")
            clean_name = re.sub(r'[\\/*?:"<>|]', "_", raw_name).strip() or "file"
            ext = os.path.splitext(clean_name)[1].lower()
            if ext not in ALLOWED_EXTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"「{raw_name}」类型不支持，请上传图片或 PDF/Office/压缩包文件")
            f.file.seek(0, 2)
            size = f.file.tell()
            f.file.seek(0)
            if size <= 0:
                raise HTTPException(status_code=400, detail=f"「{raw_name}」内容为空")
            if size > MAX_DOC_SIZE:
                raise HTTPException(status_code=400, detail=f"「{raw_name}」超过 20MB 上限")
            data = f.file.read()
            mime = f.content_type or mimetypes.guess_type(clean_name)[0] or "application/octet-stream"
            items.append((raw_name, clean_name, data, mime))
        return items

    @staticmethod
    def save_docs_many(order_ids: List[Any], doc_type: str, files: List[UploadFile],
                       username: str = "") -> Dict[str, Any]:
        """把同一批文件分别上传到多个订单的同一类单据

        - 文件只读一次 (内存复用), 每个订单各自重命名/序号/快照
        - 个别订单不存在时记入 failed, 不影响其余订单
        """
        OrderDocService._check_type(doc_type)
        ids: List[int] = []
        for raw in order_ids or []:
            try:
                oid = int(str(raw).strip())
            except (TypeError, ValueError):
                continue
            if oid not in ids:
                ids.append(oid)
        if not ids:
            raise HTTPException(status_code=400, detail="请先勾选要上传的订单")
        if len(ids) > MAX_BATCH_ORDERS:
            raise HTTPException(status_code=400,
                                detail=f"单次最多批量上传 {MAX_BATCH_ORDERS} 单附件")
        items = OrderDocService._read_uploads(files)
        if not items:
            raise HTTPException(status_code=400, detail="未选择文件")

        saved: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        for oid in ids:
            if not OrderDocService._order_exists(oid):
                failed.append({"order_id": oid, "reason": "订单不存在"})
                continue
            shims = [SimpleNamespace(file=io.BytesIO(data), filename=clean_name, content_type=mime)
                     for _raw, clean_name, data, mime in items]
            try:
                saved.extend(OrderDocService.save_docs(oid, doc_type, shims, username=username))
            except HTTPException as exc:
                failed.append({"order_id": oid, "reason": exc.detail})
            except Exception as exc:                      # 单订单失败不影响其余订单
                failed.append({"order_id": oid, "reason": str(exc)})
        return {
            "doc_type": doc_type,
            "orders": len(ids),
            "file_count": len(items),
            "saved": saved,
            "failed": failed,
            "ok_orders": len(ids) - len(failed),
        }

    @staticmethod
    def list_docs(order_id: int, with_thumbs: bool = True) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM order_docs WHERE order_id = ? ORDER BY id DESC", (int(order_id),)).fetchall()
        finally:
            conn.close()
        out = [OrderDocService._row_to_dict(r) for r in rows]
        if with_thumbs:
            # 历史文档懒补首页快照 (仅缺快照的文档, 有异常静默跳过)
            out = [OrderDocService._ensure_thumb(d) for d in out]
        return out

    @staticmethod
    def doc_counts(order_ids: List[int], max_previews: int = 8) -> Dict[int, Dict[str, Dict[str, Any]]]:
        """批量统计各订单各类型单据: {order_id: {doc_type: {count, previews:[{id,url,file_name}]}}}

        previews 按上传时间倒序给出每个文件的预览图 (图片=原图, 文档=首页快照), 最多 max_previews 个,
        供列表内逐张直接预览。
        """
        ids = [int(i) for i in (order_ids or [])]
        out: Dict[int, Dict[str, Dict[str, Any]]] = {
            i: {k: {"count": 0, "previews": []} for k in DOC_TYPE_KEYS} for i in ids}
        if not ids:
            return out
        marks = ",".join("?" * len(ids))
        conn = get_db_connection()
        try:
            rows = conn.execute(
                f"SELECT id, order_id, doc_type, file_name, stored_name, thumb_name "
                f"FROM order_docs WHERE order_id IN ({marks}) ORDER BY id DESC", ids).fetchall()
        finally:
            conn.close()
        for r in rows:
            bucket = out.get(r["order_id"])
            if bucket is None or r["doc_type"] not in bucket:
                continue
            item = bucket[r["doc_type"]]
            item["count"] += 1
            if len(item["previews"]) >= max_previews:
                continue
            ext = os.path.splitext(r["stored_name"] or "")[1].lower()
            url = ""
            if ext in IMAGE_EXTS:
                url = f"/uploads/orders/{r['order_id']}/{r['stored_name']}"
            elif r["thumb_name"]:
                url = f"/uploads/orders/{r['order_id']}/{r['thumb_name']}"
            if url:
                item["previews"].append({"id": r["id"], "url": url, "file_name": r["file_name"] or ""})
        return out

    @staticmethod
    def build_zip(order_id: int, doc_type: str) -> Tuple[bytes, str]:
        """把某订单某类单据打包为 zip, 返回 (zip 字节, 下载文件名)"""
        meta = OrderDocService._check_type(doc_type)
        docs = [d for d in OrderDocService.list_docs(order_id, with_thumbs=False)
                if d["doc_type"] == doc_type]
        if not docs:
            raise HTTPException(status_code=404, detail=f"该订单暂无「{meta['label']}」附件")
        folder = _doc_root(order_id)
        buf = io.BytesIO()
        used: Dict[str, int] = {}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for d in docs:
                name_on_disk = d.get("stored_name") or ""
                path = os.path.join(folder, name_on_disk)
                if not name_on_disk or not os.path.isfile(path):
                    continue
                arc = d.get("file_name") or name_on_disk
                if arc in used:
                    used[arc] += 1
                    base, ext = os.path.splitext(arc)
                    arc = f"{base}({used[arc]}){ext}"
                else:
                    used[arc] = 1
                zf.write(path, arcname=arc)
        buf.seek(0)
        return buf.getvalue(), f"{meta['label']}_{int(order_id)}.zip"

    @staticmethod
    def delete_doc(doc_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM order_docs WHERE id = ?", (int(doc_id),)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="文件不存在或已删除")
            conn.execute("DELETE FROM order_docs WHERE id = ?", (int(doc_id),))
            conn.commit()
            d = dict(row)
        finally:
            conn.close()
        folder = os.path.join(UPLOADS_DIR, "orders", str(d["order_id"]))
        for name in (d.get("stored_name") or "", d.get("thumb_name") or ""):
            path = os.path.join(folder, name) if name else ""
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        return {"id": int(doc_id), "file_name": d["file_name"], "doc_type": d["doc_type"]}

    @staticmethod
    def delete_docs(doc_ids: List[int]) -> Dict[str, Any]:
        """批量删除附件 (含磁盘文件与首页快照); 不存在的 id 记入 missing 不报错

        返回 {"deleted": n, "missing": [id...], "total": 请求数}
        """
        ids = sorted({int(i) for i in (doc_ids or []) if str(i).strip()})
        if not ids:
            raise ValueError("请先选择要删除的附件")
        deleted, missing = 0, []
        for doc_id in ids:
            try:
                OrderDocService.delete_doc(doc_id)
                deleted += 1
            except HTTPException:
                missing.append(doc_id)
        return {"deleted": deleted, "missing": missing, "total": len(ids)}

    @staticmethod
    def get_doc(doc_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM order_docs WHERE id = ?", (int(doc_id),)).fetchone()
        finally:
            conn.close()
        return OrderDocService._row_to_dict(row) if row else None
