#!/usr/bin/env python3
"""
DB Agent — 数据库代理服务

在「数据库所在的主机」上运行，通过 HTTP 把 SQLite 查询暴露给局域网/远程的
ERP 桌面上件助手，使远程机器可以用 IP/域名 连接数据库，而无需共享文件夹。

使用方法 (主机上)：
    python db_agent.py                        # 默认端口 8765, 使用 data/products.db
    python db_agent.py --port 9000 --db D:\path\products.db --token mysecret

远程桌面应用连接配置：
    主机: 主机IP或域名 (如 192.168.1.10)
    端口: 8765
    访问令牌: 与 --token 一致 (留空表示不校验)

接口：
    GET  /ping             健康检查 {ok, parent_count}
    GET  /file?path=...    按路径获取商品图片文件内容 (二进制, 自动在图片存储目录解析)
    POST /query            {sql, params} 只读查询 → {columns, rows}
    POST /execute          {sql, params} 写操作(自动提交) → {rowcount, lastrowid}
"""
import os
import sys
import json
import argparse
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import server.database as appdb  # noqa: E402

TOKEN = ""  # 由 --token 设置, 空表示不校验


def _is_read_sql(sql: str) -> bool:
    head = (sql or "").lstrip().split(None, 1)
    return bool(head) and head[0].upper() in ("SELECT", "PRAGMA", "WITH", "EXPLAIN")


def _allowed_image_roots():
    """允许被 /file 接口读取的目录白名单 (图片存储根目录 + uploads 目录)"""
    from server.config import UPLOADS_DIR
    roots = [os.path.abspath(UPLOADS_DIR)]
    try:
        import platform
        from server.database import get_setting
        key = "storage_path_win" if platform.system().lower() == "windows" else "storage_path_mac"
        base = get_setting(key, "D:\\products" if key == "storage_path_win" else "/Users/gx/Desktop/products")
        roots.append(os.path.abspath(base))
    except Exception:
        pass
    return roots


def _resolve_safe_image_path(raw_path: str):
    """在主库机器上把请求的图片路径解析为物理文件, 并校验未越出白名单目录"""
    from server.services.file_service import FileService
    resolved = FileService.resolve_image_path(raw_path)
    if not resolved or not os.path.isfile(resolved):
        return None
    real = os.path.normpath(os.path.realpath(resolved)).lower()
    for root in _allowed_image_roots():
        try:
            root_real = os.path.normpath(os.path.realpath(root)).lower()
        except Exception:
            continue
        if real == root_real or real.startswith(root_real + os.sep):
            return resolved
    return None  # 越出白名单 (防任意文件读取)


class DBHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    # ── 响应工具 ──
    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_token(self) -> bool:
        if not TOKEN:
            return True
        return self.headers.get("X-DB-Token", "") == TOKEN

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    # ── 路由 ──
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/")

        if route in ("/ping", ""):
            if not self._check_token():
                return self._json(401, {"error": "token 无效"})
            try:
                conn = appdb.get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM product_items WHERE is_parent = 1;")
                parent_count = cur.fetchone()[0]
                conn.close()
                return self._json(200, {"ok": True, "parent_count": parent_count,
                                        "db_path": appdb.DB_PATH})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        if route == "/file":
            if not self._check_token():
                return self._json(401, {"error": "token 无效"})
            qs = urllib.parse.parse_qs(parsed.query)
            raw_path = (qs.get("path") or [""])[0]
            if not raw_path:
                return self._json(400, {"error": "缺少 path 参数"})
            resolved = _resolve_safe_image_path(raw_path)
            if not resolved:
                return self._json(404, {"error": f"图片未找到: {raw_path}"})
            try:
                with open(resolved, "rb") as f:
                    data = f.read()
            except Exception as e:
                return self._json(500, {"error": f"读取失败: {e}"})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-File-Name", urllib.parse.quote(os.path.basename(resolved)))
            self.end_headers()
            self.wfile.write(data)
            return

        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._check_token():
            return self._json(401, {"error": "token 无效"})
        try:
            body = self._body()
        except Exception as e:
            return self._json(400, {"error": f"请求体解析失败: {e}"})

        sql = (body.get("sql") or "").strip()
        params = body.get("params") or []
        if not sql:
            return self._json(400, {"error": "缺少 sql"})

        if self.path.rstrip() == "/query":
            if not _is_read_sql(sql):
                return self._json(400, {"error": "/query 仅允许 SELECT/PRAGMA/WITH 查询"})
        elif self.path.rstrip() != "/execute":
            return self._json(404, {"error": "not found"})

        try:
            conn = appdb.get_db_connection()
            cur = conn.cursor()
            cur.execute(sql, params if isinstance(params, (list, tuple)) else [params])
            if _is_read_sql(sql):
                columns = [d[0] for d in cur.description] if cur.description else []
                rows = [tuple(r) for r in cur.fetchall()]
                conn.close()
                return self._json(200, {"columns": columns, "rows": rows})
            else:
                conn.commit()
                payload = {"rowcount": cur.rowcount,
                           "lastrowid": cur.lastrowid if hasattr(cur, "lastrowid") else None}
                conn.close()
                return self._json(200, payload)
        except Exception as e:
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    global TOKEN
    parser = argparse.ArgumentParser(description="ERP 商品数据库 HTTP 代理")
    parser.add_argument("--port", type=int, default=8765, help="监听端口 (默认 8765)")
    parser.add_argument("--db", default=os.path.join(BASE_DIR, "data", "products.db"),
                        help="SQLite 数据库文件路径")
    parser.add_argument("--token", default="", help="访问令牌 (可选, 用于简单鉴权)")
    args = parser.parse_args()

    appdb.DB_PATH = os.path.abspath(args.db)
    appdb.init_db()
    TOKEN = args.token.strip()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), DBHandler)
    print(f"✅ DB Agent 已启动")
    print(f"   数据库: {appdb.DB_PATH}")
    print(f"   监听:   0.0.0.0:{args.port}  (远程机器填本机 IP + 此端口)")
    print(f"   鉴权:   {'已启用令牌' if TOKEN else '未启用 (LAN 内可留空)'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
