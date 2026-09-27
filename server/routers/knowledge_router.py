"""
知识库导航与分段网址管理 REST API 路由
支持管理员在线配置网址用途、网址归属 (含归属图标上传)、固定 5 个分段网址与说明；
list 页面按网址归属分组排序；所有登录用户均可查阅并使用动态参数跳转
"""
import os
import re
import time
from fastapi import APIRouter, File, Form, HTTPException, Depends, UploadFile
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from server.database import get_db_connection
from server.dependencies import get_current_user, require_admin_user
from server.services.file_service import UPLOADS_DIR

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])

# 归属图标允许的扩展名与大小上限 (2MB)
ICON_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}
ICON_MAX_SIZE = 2 * 1024 * 1024


class KnowledgeSiteInput(BaseModel):
    category: str = Field(..., min_length=1, max_length=64, description="网址归属 (必填, 如: 亚马逊/拼多多/店小秘/1688)")
    title: str = Field(..., min_length=1, max_length=128, description="网址用途 (必填)")
    url_parts: List[str] = Field(default_factory=lambda: ["", "", "", "", ""], description="固定 5 个分段网址输入框内容")
    description: Optional[str] = Field("", description="说明 (可选)")
    sort_order: Optional[int] = Field(0, description="排序权重 (越小越靠前)")


def _normalize_parts(parts: Optional[List[str]]) -> List[str]:
    """保证分段列表始终为 5 个元素"""
    raw = parts or []
    cleaned = [str(p if p is not None else "").strip() for p in raw]
    while len(cleaned) < 5:
        cleaned.append("")
    return cleaned[:5]


def _get_category_icon_map(cursor) -> Dict[str, str]:
    """归属名称 -> 图标URL 映射"""
    cursor.execute("SELECT name, icon_path FROM knowledge_categories;")
    return {r["name"]: (r["icon_path"] or "") for r in cursor.fetchall()}


def _upsert_category(cursor, category: str):
    """归属不存在则自动创建 (排在末尾), 存在则跳过"""
    category = (category or "").strip()
    if not category:
        return
    cursor.execute("SELECT id FROM knowledge_categories WHERE name = ?;", (category,))
    if cursor.fetchone():
        return
    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) FROM knowledge_categories;")
    next_sort = (cursor.fetchone()[0] or 0) + 1
    cursor.execute(
        "INSERT INTO knowledge_categories (name, icon_path, sort_order) VALUES (?, '', ?);",
        (category, next_sort)
    )


def _row_to_dict(row, icon_map: Dict[str, str]) -> Dict[str, Any]:
    parts = [
        row["url_part1"] or "",
        row["url_part2"] or "",
        row["url_part3"] or "",
        row["url_part4"] or "",
        row["url_part5"] or "",
    ]
    category = (row["category"] if "category" in row.keys() else "") or ""
    return {
        "id": row["id"],
        "category": category,
        "category_icon": icon_map.get(category, ""),
        "title": row["title"] or "",
        "url_parts": parts,
        "full_url": "".join(parts),
        "has_var": "{var}" in "".join(parts),
        "description": row["description"] or "",
        "sort_order": row["sort_order"] or 0,
        "created_by": row["created_by"] or "",
        "created_at": str(row["created_at"]) if row["created_at"] else "",
        "updated_at": str(row["updated_at"]) if row["updated_at"] else "",
    }


@router.get("", summary="获取所有知识库网站列表 (按网址归属分组排序, 所有已登录用户可见)")
async def list_knowledge_sites(current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取知识库全部条目，按 归属(sort_order) -> 条目(sort_order) -> id 排序"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.* FROM knowledge_sites s
            LEFT JOIN knowledge_categories c ON c.name = s.category
            ORDER BY COALESCE(c.sort_order, 9999) ASC, s.category ASC, s.sort_order ASC, s.id ASC;
        """)
        rows = cursor.fetchall()
        icon_map = _get_category_icon_map(cursor)
        data = [_row_to_dict(r, icon_map) for r in rows]
        return {
            "code": 0,
            "msg": "success",
            "data": data,
            "total": len(data),
            "is_admin": current_user.get("role") == "admin"
        }
    finally:
        conn.close()


@router.post("", summary="新增知识库条目 (仅限管理员)")
async def create_knowledge_site(payload: KnowledgeSiteInput, admin: Dict[str, Any] = Depends(require_admin_user)):
    """新增一条网站配置，网址固定分为 5 段按序拼接；归属必填，新归属自动建档"""
    category = payload.category.strip()
    if not category:
        raise HTTPException(status_code=400, detail="网址归属为必填项！")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="网址用途为必填项！")

    parts = _normalize_parts(payload.url_parts)
    full_url = "".join(parts).strip()
    if not full_url:
        raise HTTPException(status_code=400, detail="网址内容不能为空，请在 5 个输入框中至少填写一段！")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        _upsert_category(cursor, category)
        cursor.execute("""
            INSERT INTO knowledge_sites (category, title, url_part1, url_part2, url_part3, url_part4, url_part5, description, sort_order, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            category, title, parts[0], parts[1], parts[2], parts[3], parts[4],
            (payload.description or "").strip(),
            payload.sort_order or 0,
            admin.get("username", "admin")
        ))
        conn.commit()
        new_id = cursor.lastrowid

        cursor.execute("SELECT * FROM knowledge_sites WHERE id = ?;", (new_id,))
        row = cursor.fetchone()
        icon_map = _get_category_icon_map(cursor)
        return {
            "code": 0,
            "msg": "知识库条目添加成功",
            "data": _row_to_dict(row, icon_map)
        }
    finally:
        conn.close()


@router.put("/{site_id}", summary="修改知识库条目 (仅限管理员)")
async def update_knowledge_site(site_id: int, payload: KnowledgeSiteInput, admin: Dict[str, Any] = Depends(require_admin_user)):
    """修改已有知识库条目 (网址归属、网址用途、5 段网址、说明、排序)"""
    category = payload.category.strip()
    if not category:
        raise HTTPException(status_code=400, detail="网址归属为必填项！")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="网址用途为必填项！")

    parts = _normalize_parts(payload.url_parts)
    full_url = "".join(parts).strip()
    if not full_url:
        raise HTTPException(status_code=400, detail="网址内容不能为空，请在 5 个输入框中至少填写一段！")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM knowledge_sites WHERE id = ?;", (site_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="未找到对应的知识库条目！")

        _upsert_category(cursor, category)
        cursor.execute("""
            UPDATE knowledge_sites
            SET category = ?, title = ?, url_part1 = ?, url_part2 = ?, url_part3 = ?, url_part4 = ?, url_part5 = ?,
                description = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
        """, (
            category, title, parts[0], parts[1], parts[2], parts[3], parts[4],
            (payload.description or "").strip(),
            payload.sort_order or 0,
            site_id
        ))
        conn.commit()

        cursor.execute("SELECT * FROM knowledge_sites WHERE id = ?;", (site_id,))
        row = cursor.fetchone()
        icon_map = _get_category_icon_map(cursor)
        return {
            "code": 0,
            "msg": "知识库条目更新成功",
            "data": _row_to_dict(row, icon_map)
        }
    finally:
        conn.close()


@router.delete("/{site_id}", summary="删除知识库条目 (仅限管理员)")
async def delete_knowledge_site(site_id: int, admin: Dict[str, Any] = Depends(require_admin_user)):
    """删除知识库条目"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title FROM knowledge_sites WHERE id = ?;", (site_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到对应的知识库条目！")

        title = row["title"]
        cursor.execute("DELETE FROM knowledge_sites WHERE id = ?;", (site_id,))
        conn.commit()
        return {
            "code": 0,
            "msg": f"已成功删除知识库网站「{title}」",
            "data": {"id": site_id}
        }
    finally:
        conn.close()


# ============================================================================
# 网址归属管理 (归属列表 / 归属图标上传 / 删除归属)
# ============================================================================

def _category_to_dict(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "icon_path": row["icon_path"] or "",
        "sort_order": row["sort_order"] or 0,
    }


def _save_icon_file(category_name: str, upload: UploadFile) -> str:
    """校验并保存归属图标, 返回可访问的 /uploads/... URL"""
    raw_name = os.path.basename(upload.filename or "")
    ext = os.path.splitext(raw_name)[1].lower()
    if ext not in ICON_ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"图标格式不支持 ({ext or '无扩展名'})，仅支持: png/jpg/jpeg/gif/webp/svg/ico")
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    if size > ICON_MAX_SIZE:
        raise HTTPException(status_code=400, detail="图标文件过大，请上传 2MB 以内的图片！")
    if not size:
        raise HTTPException(status_code=400, detail="图标文件内容为空！")

    slug = re.sub(r"[^0-9A-Za-z]+", "_", category_name).strip("_") or "cat"
    filename = f"kbcat_{slug}_{int(time.time())}{ext}"
    target = os.path.join(UPLOADS_DIR, filename)
    with open(target, "wb") as buf:
        buf.write(upload.file.read())
    return f"/uploads/{filename}"


@router.get("/categories", summary="获取网址归属列表 (所有已登录用户可见)")
async def list_categories(user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, (SELECT COUNT(*) FROM knowledge_sites s WHERE s.category = c.name) AS site_count
            FROM knowledge_categories c ORDER BY c.sort_order ASC, c.id ASC;
        """)
        rows = cursor.fetchall()
        data = []
        for r in rows:
            d = _category_to_dict(r)
            d["site_count"] = r["site_count"] or 0
            data.append(d)
        return {"code": 0, "msg": "success", "data": data, "total": len(data)}
    finally:
        conn.close()


@router.post("/categories", summary="新增/更新网址归属 (可同时上传归属图标, 仅限管理员)")
async def save_category(
    name: str = Form(..., description="归属名称 (存在则更新其图标)"),
    icon: Optional[UploadFile] = File(None, description="归属图标文件 (可选)"),
    admin: Dict[str, Any] = Depends(require_admin_user),
):
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="归属名称为必填项！")
    if len(name) > 64:
        raise HTTPException(status_code=400, detail="归属名称过长 (最多 64 字)！")

    icon_url = ""
    if icon is not None and (icon.filename or "").strip():
        icon_url = _save_icon_file(name, icon)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM knowledge_categories WHERE name = ?;", (name,))
        existed = cursor.fetchone()
        if existed:
            if icon_url:
                cursor.execute(
                    "UPDATE knowledge_categories SET icon_path = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?;",
                    (icon_url, name)
                )
            conn.commit()
            msg = f"归属「{name}」图标已更新" if icon_url else f"归属「{name}」已存在"
        else:
            cursor.execute("SELECT COALESCE(MAX(sort_order), 0) FROM knowledge_categories;")
            next_sort = (cursor.fetchone()[0] or 0) + 1
            cursor.execute(
                "INSERT INTO knowledge_categories (name, icon_path, sort_order) VALUES (?, ?, ?);",
                (name, icon_url, next_sort)
            )
            conn.commit()
            msg = f"归属「{name}」已创建" + ("并上传图标" if icon_url else "")
        cursor.execute("SELECT * FROM knowledge_categories WHERE name = ?;", (name,))
        return {"code": 0, "msg": msg, "data": _category_to_dict(cursor.fetchone())}
    finally:
        conn.close()


@router.delete("/categories/{cat_id}", summary="删除网址归属 (有条目引用时禁止删除, 仅限管理员)")
async def delete_category(cat_id: int, admin: Dict[str, Any] = Depends(require_admin_user)):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM knowledge_categories WHERE id = ?;", (cat_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到对应的网址归属！")
        name = row["name"]
        cursor.execute("SELECT COUNT(*) FROM knowledge_sites WHERE category = ?;", (name,))
        used = cursor.fetchone()[0] or 0
        if used:
            raise HTTPException(status_code=400, detail=f"归属「{name}」下还有 {used} 个网址条目，请先移除或改归属后再删除！")
        cursor.execute("DELETE FROM knowledge_categories WHERE id = ?;", (cat_id,))
        conn.commit()
        return {"code": 0, "msg": f"已删除归属「{name}」", "data": {"id": cat_id}}
    finally:
        conn.close()


# ============================================================================
# 知识库文档 (上传各类文档 / 列表 / 下载 / 删除)
# ============================================================================

DOC_ALLOWED_EXTS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".md", ".csv",
    ".zip", ".rar", ".7z",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
}
DOC_MAX_SIZE = 20 * 1024 * 1024  # 单文件 20MB


def _ext_label(ext: str) -> str:
    mapping = {
        ".pdf": "PDF", ".doc": "Word", ".docx": "Word",
        ".xls": "Excel", ".xlsx": "Excel", ".csv": "CSV",
        ".ppt": "PPT", ".pptx": "PPT",
        ".txt": "文本", ".md": "Markdown",
        ".zip": "压缩包", ".rar": "压缩包", ".7z": "压缩包",
        ".png": "图片", ".jpg": "图片", ".jpeg": "图片", ".gif": "图片", ".webp": "图片", ".svg": "图片",
    }
    return mapping.get(ext, ext.lstrip(".").upper() or "文件")


@router.get("/documents", summary="获取知识库文档列表 (所有已登录用户可见)")
async def list_documents(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM knowledge_documents ORDER BY created_at DESC, id DESC;")
        rows = cursor.fetchall()
        data = [
            {
                "id": r["id"],
                "name": r["name"],
                "ext": r["ext"] or "",
                "ext_label": _ext_label(r["ext"] or ""),
                "size": r["size"] or 0,
                "description": r["description"] or "",
                "uploaded_by": r["uploaded_by"] or "",
                "created_at": str(r["created_at"]) if r["created_at"] else "",
                "download_url": f"/api/knowledge/documents/{r['id']}/download",
            }
            for r in rows
        ]
        return {
            "code": 0,
            "msg": "success",
            "data": data,
            "total": len(data),
            "is_admin": current_user.get("role") == "admin"
        }
    finally:
        conn.close()


@router.post("/documents", summary="上传知识库文档 (支持多文件, 仅限管理员)")
async def upload_documents(
    files: List[UploadFile] = File(..., description="文档文件 (可多选)"),
    description: str = Form("", description="文档说明 (可选, 应用于本批)"),
    admin: Dict[str, Any] = Depends(require_admin_user),
):
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的文档文件！")

    saved, skipped = [], []
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        for upload in files:
            raw_name = os.path.basename(upload.filename or "").strip()
            if not raw_name:
                skipped.append({"name": "(未命名)", "reason": "文件名为空"})
                continue
            ext = os.path.splitext(raw_name)[1].lower()
            if ext not in DOC_ALLOWED_EXTS:
                skipped.append({"name": raw_name, "reason": f"格式 {ext or '未知'} 不支持"})
                continue

            upload.file.seek(0, 2)
            size = upload.file.tell()
            upload.file.seek(0)
            if size <= 0:
                skipped.append({"name": raw_name, "reason": "文件内容为空"})
                continue
            if size > DOC_MAX_SIZE:
                skipped.append({"name": raw_name, "reason": "超过 20MB 上限"})
                continue

            slug = re.sub(r"[^0-9A-Za-z]+", "_", os.path.splitext(raw_name)[0]).strip("_") or "doc"
            filename = f"kbdoc_{slug}_{int(time.time() * 1000)}{ext}"
            target = os.path.join(UPLOADS_DIR, filename)
            with open(target, "wb") as buf:
                buf.write(upload.file.read())

            cursor.execute("""
                INSERT INTO knowledge_documents (name, filename, ext, size, description, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (raw_name, filename, ext, size, (description or "").strip(), admin.get("username", "admin")))
            saved.append(raw_name)

        conn.commit()
        if not saved:
            detail = "；".join(f"{s['name']}: {s['reason']}" for s in skipped) or "未知原因"
            raise HTTPException(status_code=400, detail=f"没有可上传的文件 — {detail}")
        msg = f"成功上传 {len(saved)} 个文档"
        if skipped:
            msg += "，跳过: " + "；".join(f"{s['name']}({s['reason']})" for s in skipped)
        return {"code": 0, "msg": msg, "data": {"saved": saved, "skipped": skipped}}
    finally:
        conn.close()


@router.get("/documents/{doc_id}/download", summary="下载知识库文档 (所有已登录用户)")
async def download_document(doc_id: int, current_user: Dict[str, Any] = Depends(get_current_user)):
    from fastapi.responses import FileResponse
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM knowledge_documents WHERE id = ?;", (doc_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到对应的文档记录！")
        abs_path = os.path.join(UPLOADS_DIR, row["filename"])
        if not os.path.isfile(abs_path):
            raise HTTPException(status_code=404, detail="文档文件已不存在，可能被清理，请联系管理员重新上传！")
        return FileResponse(abs_path, filename=row["name"])
    finally:
        conn.close()


@router.delete("/documents/{doc_id}", summary="删除知识库文档 (仅限管理员)")
async def delete_document(doc_id: int, admin: Dict[str, Any] = Depends(require_admin_user)):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, filename FROM knowledge_documents WHERE id = ?;", (doc_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到对应的文档记录！")
        name = row["name"]
        cursor.execute("DELETE FROM knowledge_documents WHERE id = ?;", (doc_id,))
        conn.commit()
        # 数据库记录删除后清理物理文件 (失败不影响结果)
        abs_path = os.path.join(UPLOADS_DIR, row["filename"])
        try:
            if os.path.isfile(abs_path):
                os.remove(abs_path)
        except OSError:
            pass
        return {"code": 0, "msg": f"已删除文档「{name}」", "data": {"id": doc_id}}
    finally:
        conn.close()
