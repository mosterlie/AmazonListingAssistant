"""
货代管理业务服务层 (ForwarderService)

货代基本信息 + 在线链接维护:
  - 全员可查看列表, 仅管理员可增/改/删 (鉴权在路由层)
  - 在线链接以 JSON 存储: [{"label": "...", "url": "..."}], 页面点击后新页签打开
  - website=货代网址; reg_user/reg_password=货代系统注册凭据,
    两者仅管理员可见 (include_secret 控制, 非管理员响应中剥离)
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.database import get_db_connection
from server.models.forwarder_schemas import ForwarderUpsertSchema


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_url(url: str) -> str:
    """补全协议头: 无 http(s):// 前缀的链接默认按 https 处理"""
    url = (url or "").strip()
    if url and not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _dump_links(links: List[dict]) -> str:
    cleaned = [{"label": (lk.get("label") or "").strip(),
                "url": _normalize_url(lk.get("url"))}
               for lk in (links or []) if (lk.get("url") or "").strip()]
    return json.dumps(cleaned, ensure_ascii=False)


def _safe_links(text: str) -> List[dict]:
    try:
        links = json.loads(text) if text else []
    except Exception:
        return []
    return [lk for lk in links if isinstance(lk, dict) and lk.get("url")]


class ForwarderService:
    """货代管理: 列表 / 新增 / 更新 / 删除"""

    @staticmethod
    def _to_dict(row, include_secret: bool = False) -> Dict[str, Any]:
        d = dict(row)
        d["links"] = _safe_links(d.pop("links_json", "[]"))
        if not include_secret:
            # 注册用户/密码仅管理员可见
            d.pop("reg_user", None)
            d.pop("reg_password", None)
        return d

    @staticmethod
    def list_forwarders(include_secret: bool = False) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM forwarders ORDER BY sort_order, id"
            ).fetchall()
        finally:
            conn.close()
        return [ForwarderService._to_dict(r, include_secret) for r in rows]

    @staticmethod
    def get_forwarder(fid: int, include_secret: bool = False) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM forwarders WHERE id = ?", (fid,)).fetchone()
        finally:
            conn.close()
        return ForwarderService._to_dict(row, include_secret) if row else None

    @staticmethod
    def create_forwarder(data: ForwarderUpsertSchema, operator: str = "") -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "INSERT INTO forwarders "
                "(name, contact, phone, website, reg_user, reg_password, "
                " shipping_address, settlement_method, "
                " remark, links_json, sort_order, created_by, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (data.name.strip(), data.contact.strip(), data.phone.strip(),
                 _normalize_url(data.website), data.reg_user.strip(), data.reg_password.strip(),
                 data.shipping_address.strip(), data.settlement_method.strip(),
                 data.remark.strip(), _dump_links(data.links),
                 data.sort_order, operator, _now_str()),
            )
            fid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return ForwarderService.get_forwarder(fid, include_secret=True)

    @staticmethod
    def update_forwarder(fid: int, data: ForwarderUpsertSchema, operator: str = "") -> Dict[str, Any]:
        if not ForwarderService.get_forwarder(fid, include_secret=True):
            raise ValueError(f"货代不存在 (id={fid})")
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE forwarders SET name = ?, contact = ?, phone = ?, "
                "website = ?, reg_user = ?, reg_password = ?, "
                "shipping_address = ?, settlement_method = ?, "
                "remark = ?, links_json = ?, sort_order = ?, updated_at = ? WHERE id = ?",
                (data.name.strip(), data.contact.strip(), data.phone.strip(),
                 _normalize_url(data.website), data.reg_user.strip(), data.reg_password.strip(),
                 data.shipping_address.strip(), data.settlement_method.strip(),
                 data.remark.strip(), _dump_links(data.links),
                 data.sort_order, _now_str(), fid),
            )
            conn.commit()
        finally:
            conn.close()
        return ForwarderService.get_forwarder(fid, include_secret=True)

    @staticmethod
    def delete_forwarder(fid: int) -> None:
        if not ForwarderService.get_forwarder(fid, include_secret=True):
            raise ValueError(f"货代不存在 (id={fid})")
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM forwarders WHERE id = ?", (fid,))
            conn.commit()
        finally:
            conn.close()
