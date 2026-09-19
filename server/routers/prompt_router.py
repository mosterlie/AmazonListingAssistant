"""
提示词模板管理 REST API 路由
支持管理员维护多套提示词模板 (新增/修改/删除)；所有登录用户均可查阅并一键复制
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from server.database import get_db_connection
from server.dependencies import get_current_user, require_admin_user

router = APIRouter(prefix="/api/prompts", tags=["Prompt Templates"])


class PromptTemplateInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="模板名称 (必填)")
    content: str = Field(..., min_length=1, description="提示词内容 (必填)")
    description: Optional[str] = Field("", description="用途说明 (可选)")
    sort_order: Optional[int] = Field(0, description="排序权重 (越小越靠前)")


def _row_to_dict(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"] or "",
        "content": row["content"] or "",
        "description": row["description"] or "",
        "sort_order": row["sort_order"] or 0,
        "created_by": row["created_by"] or "",
        "created_at": str(row["created_at"]) if row["created_at"] else "",
        "updated_at": str(row["updated_at"]) if row["updated_at"] else "",
    }


@router.get("", summary="获取所有提示词模板 (所有已登录用户可见)")
async def list_prompt_templates(current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取全部提示词模板，按 sort_order ASC, id ASC 排序"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM prompt_templates ORDER BY sort_order ASC, id ASC;")
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


@router.post("", summary="新增提示词模板 (仅限管理员)")
async def create_prompt_template(payload: PromptTemplateInput, admin: Dict[str, Any] = Depends(require_admin_user)):
    """新增一套提示词模板"""
    name = payload.name.strip()
    content = payload.content.strip()
    if not name:
        raise HTTPException(status_code=400, detail="模板名称为必填项！")
    if not content:
        raise HTTPException(status_code=400, detail="提示词内容不能为空！")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO prompt_templates (name, content, description, sort_order, created_by)
            VALUES (?, ?, ?, ?, ?);
        """, (name, content, (payload.description or "").strip(), payload.sort_order or 0, admin.get("username", "admin")))
        conn.commit()
        new_id = cursor.lastrowid

        cursor.execute("SELECT * FROM prompt_templates WHERE id = ?;", (new_id,))
        return {
            "code": 0,
            "msg": "提示词模板添加成功",
            "data": _row_to_dict(cursor.fetchone())
        }
    finally:
        conn.close()


@router.put("/{prompt_id}", summary="修改提示词模板 (仅限管理员)")
async def update_prompt_template(prompt_id: int, payload: PromptTemplateInput, admin: Dict[str, Any] = Depends(require_admin_user)):
    """修改已有提示词模板 (名称/内容/说明/排序)"""
    name = payload.name.strip()
    content = payload.content.strip()
    if not name:
        raise HTTPException(status_code=400, detail="模板名称为必填项！")
    if not content:
        raise HTTPException(status_code=400, detail="提示词内容不能为空！")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM prompt_templates WHERE id = ?;", (prompt_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="未找到对应的提示词模板！")

        cursor.execute("""
            UPDATE prompt_templates
            SET name = ?, content = ?, description = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
        """, (name, content, (payload.description or "").strip(), payload.sort_order or 0, prompt_id))
        conn.commit()

        cursor.execute("SELECT * FROM prompt_templates WHERE id = ?;", (prompt_id,))
        return {
            "code": 0,
            "msg": "提示词模板更新成功",
            "data": _row_to_dict(cursor.fetchone())
        }
    finally:
        conn.close()


@router.delete("/{prompt_id}", summary="删除提示词模板 (仅限管理员)")
async def delete_prompt_template(prompt_id: int, admin: Dict[str, Any] = Depends(require_admin_user)):
    """删除提示词模板"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM prompt_templates WHERE id = ?;", (prompt_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到对应的提示词模板！")

        name = row["name"]
        cursor.execute("DELETE FROM prompt_templates WHERE id = ?;", (prompt_id,))
        conn.commit()
        return {
            "code": 0,
            "msg": f"已成功删除提示词模板「{name}」",
            "data": {"id": prompt_id}
        }
    finally:
        conn.close()
