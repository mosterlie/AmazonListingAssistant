"""
内嵌「图片服务 / DB Agent」路由 (原独立进程 db_agent.py:8765 已合并进 ERP 服务)

供异地「桌面上件助手」(desktop_app.py) 通过 ERP 的单一端口 (默认 8000) 访问主库机器的
SQLite 数据库与商品图片，不再需要单独运行 db_agent.py 或为其额外开一条隧道。

接口与合并前 db_agent.py 保持完全一致 (桌面助手客户端无需改动, 只需把端口由 8765 改为 8000):
    GET  /ping             健康检查 {ok, parent_count, db_path}
    GET  /file?path=...    商品图片下载 (二进制, 白名单目录校验防越权读取)
    POST /query            只读查询 {sql, params} → {columns, rows}
    POST /execute          写操作(自动提交) {sql, params} → {rowcount, lastrowid}

鉴权: 请求头 X-DB-Token, 取值来自系统设置 db_agent_token (默认 erp2024)。
本路由组刻意不使用 Cookie 会话鉴权 —— 自定义请求头无法被浏览器跨站伪造。
"""
import json
import os
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from server.config import DB_AGENT_TOKEN, DB_PATH
from server.database import get_db_connection, get_setting
from server.services.file_service import FileService

router = APIRouter(tags=["内嵌图片服务 (原 db_agent 8765)"])

_READ_PREFIXES = ("SELECT", "PRAGMA", "WITH", "EXPLAIN")


def _is_read_sql(sql: str) -> bool:
    head = (sql or "").lstrip().split(None, 1)
    return bool(head) and head[0].upper() in _READ_PREFIXES


def _json_error(status_code: int, message: str) -> JSONResponse:
    """与原 db_agent 一致的错误体 {"error": "..."} (桌面助手按该字段解析失败原因)"""
    return JSONResponse(status_code=status_code, content={"error": message})


def _current_token() -> str:
    """当前生效令牌: 系统设置优先, 读取失败回退配置默认值"""
    try:
        token = (get_setting("db_agent_token", "") or "").strip()
        if token:
            return token
    except Exception:
        pass
    return (DB_AGENT_TOKEN or "").strip()


def _auth_error(request: Request) -> Optional[JSONResponse]:
    """校验 X-DB-Token: 通过返回 None, 否则返回 401 响应"""
    expected = _current_token()
    if not expected:
        return None  # 令牌留空 = 不校验 (仅建议内网使用)
    if request.headers.get("X-DB-Token", "") != expected:
        return _json_error(401, "token 无效")
    return None


async def _parse_sql_body(request: Request) -> Tuple[Optional[JSONResponse], Optional[Tuple[str, Any]]]:
    """解析请求体 {"sql": ..., "params": [...]}; 失败返回 (错误响应, None)"""
    try:
        raw = await request.body()
        body = json.loads(raw.decode("utf-8") or "{}") if raw else {}
        if not isinstance(body, dict):
            body = {}
    except Exception as e:
        return _json_error(400, f"请求体解析失败: {e}"), None

    sql = (body.get("sql") or "").strip()
    if not sql:
        return _json_error(400, "缺少 sql"), None
    params = body.get("params") or []
    return None, (sql, params)


def _execute_sql(sql: str, params: Any) -> Any:
    """执行 SQL: 只读语句返回 {columns, rows}, 写语句自动提交并返回 {rowcount, lastrowid}"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql, params if isinstance(params, (list, tuple)) else [params])
        if _is_read_sql(sql):
            columns: List[str] = [d[0] for d in cur.description] if cur.description else []
            rows = [tuple(r) for r in cur.fetchall()]
            conn.close()
            return {"columns": columns, "rows": rows}
        conn.commit()
        payload: Dict[str, Any] = {"rowcount": cur.rowcount}
        if hasattr(cur, "lastrowid"):
            payload["lastrowid"] = cur.lastrowid
        conn.close()
        return payload
    except Exception as e:
        return _json_error(500, f"{type(e).__name__}: {e}")


@router.get("/ping", summary="内嵌图片服务: 连接测试")
def db_agent_ping(request: Request):
    bad = _auth_error(request)
    if bad:
        return bad
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM product_items WHERE is_parent = 1;")
        parent_count = cur.fetchone()[0]
        conn.close()
        return {"ok": True, "parent_count": parent_count, "db_path": DB_PATH}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@router.get("/file", summary="内嵌图片服务: 商品图片下载")
def db_agent_file(request: Request, path: str = ""):
    """按相对/绝对路径返回商品图片二进制内容 (仅限白名单目录内文件)"""
    bad = _auth_error(request)
    if bad:
        return bad

    raw_path = (path or "").strip()
    if not raw_path:
        return _json_error(400, "缺少 path 参数")

    resolved = FileService.resolve_safe_image_path(raw_path)
    if not resolved:
        return _json_error(404, f"图片未找到: {raw_path}")

    try:
        with open(resolved, "rb") as f:
            data = f.read()
    except Exception as e:
        return _json_error(500, f"读取失败: {e}")

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"X-File-Name": urllib.parse.quote(os.path.basename(resolved))},
    )


@router.post("/query", summary="内嵌图片服务: 只读 SQL 查询")
async def db_agent_query(request: Request):
    bad = _auth_error(request)
    if bad:
        return bad
    err, parsed = await _parse_sql_body(request)
    if err:
        return err
    sql, params = parsed
    if not _is_read_sql(sql):
        return _json_error(400, "/query 仅允许 SELECT/PRAGMA/WITH 查询")
    return await run_in_threadpool(_execute_sql, sql, params)


@router.post("/execute", summary="内嵌图片服务: 写 SQL 执行")
async def db_agent_execute(request: Request):
    bad = _auth_error(request)
    if bad:
        return bad
    err, parsed = await _parse_sql_body(request)
    if err:
        return err
    sql, params = parsed
    return await run_in_threadpool(_execute_sql, sql, params)
