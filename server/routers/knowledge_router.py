"""
知识库导航与分段网址管理 REST API 路由
支持管理员在线配置网站名称、固定 5 个分段网址与说明；所有登录用户均可查阅并使用动态参数跳转
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from server.database import get_db_connection
from server.dependencies import get_current_user, require_admin_user

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])


class KnowledgeSiteInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=128, description="网站名称 (必填)")
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


def _row_to_dict(row) -> Dict[str, Any]:
    parts = [
        row["url_part1"] or "",
        row["url_part2"] or "",
        row["url_part3"] or "",
        row["url_part4"] or "",
        row["url_part5"] or "",
    ]
    return {
        "id": row["id"],
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


@router.get("", summary="获取所有知识库网站列表 (所有已登录用户可见)")
async def list_knowledge_sites(current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取知识库全部条目，按 sort_order ASC, id ASC 排序"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM knowledge_sites ORDER BY sort_order ASC, id ASC;")
        rows = cursor.fetchall()
        data = [_row_to_dict(r) for r in rows]
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
    """新增一条网站配置，网址固定分为 5 段按序拼接"""
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="网站名称为必填项！")

    parts = _normalize_parts(payload.url_parts)
    full_url = "".join(parts).strip()
    if not full_url:
        raise HTTPException(status_code=400, detail="网址内容不能为空，请在 5 个输入框中至少填写一段！")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO knowledge_sites (title, url_part1, url_part2, url_part3, url_part4, url_part5, description, sort_order, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            title, parts[0], parts[1], parts[2], parts[3], parts[4],
            (payload.description or "").strip(),
            payload.sort_order or 0,
            admin.get("username", "admin")
        ))
        conn.commit()
        new_id = cursor.lastrowid

        cursor.execute("SELECT * FROM knowledge_sites WHERE id = ?;", (new_id,))
        row = cursor.fetchone()
        return {
            "code": 0,
            "msg": "知识库条目添加成功",
            "data": _row_to_dict(row)
        }
    finally:
        conn.close()


@router.put("/{site_id}", summary="修改知识库条目 (仅限管理员)")
async def update_knowledge_site(site_id: int, payload: KnowledgeSiteInput, admin: Dict[str, Any] = Depends(require_admin_user)):
    """修改已有知识库条目 (网站名称、5 段网址、说明、排序)"""
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="网站名称为必填项！")

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

        cursor.execute("""
            UPDATE knowledge_sites
            SET title = ?, url_part1 = ?, url_part2 = ?, url_part3 = ?, url_part4 = ?, url_part5 = ?,
                description = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
        """, (
            title, parts[0], parts[1], parts[2], parts[3], parts[4],
            (payload.description or "").strip(),
            payload.sort_order or 0,
            site_id
        ))
        conn.commit()

        cursor.execute("SELECT * FROM knowledge_sites WHERE id = ?;", (site_id,))
        row = cursor.fetchone()
        return {
            "code": 0,
            "msg": "知识库条目更新成功",
            "data": _row_to_dict(row)
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
