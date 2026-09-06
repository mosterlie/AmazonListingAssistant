"""
商品维护与 ERP 自动化服务 - FastAPI 核心应用入口
"""
import os
import sys
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from server.config import BASE_DIR, DATA_DIR, UPLOADS_DIR, SERVER_HOST, SERVER_PORT
from server.database import init_db
from server.services.product_service import ProductService
from server.services.auth_service import AuthService
from server.dependencies import get_current_user_from_request
from server.routers import (
    product_router,
    upload_router,
    automation_router,
    pricing_router,
    settings_router,
    auth_router,
    user_router,
    task_router,
    ad_router
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print(f"🚀 服务已就绪！访问地址: http://{SERVER_HOST}:{SERVER_PORT}")
    yield

# 1. 实例化 FastAPI 应用
app = FastAPI(
    title="跨境电商商品维护与店小秘 ERP 自动化上件中台",
    description="提供商品基础信息录入、多变体属性管理、变体矩阵笛卡尔积计算、智能物流运费比价、日元售价测算、系统参数配置、用户登录认证、权限管理、本地图片上传与店小秘 ERP 自动化上件驱动接口",
    version="1.1.0",
    lifespan=lifespan
)

# 2. 静态目录与模板引擎配置
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ──────────────────────────────────────────────────────────────
# HTML 页面禁用浏览器缓存: 防止模板页(引用旧版本号 JS)被缓存,
# 导致前端旧逻辑提交缺失新字段 (如系统设置新增项保存不上)
# ──────────────────────────────────────────────────────────────
@app.middleware("http")
async def no_cache_html(request, call_next):
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# 3. 注册 REST API 路由
app.include_router(auth_router.router)
app.include_router(user_router.router)
app.include_router(product_router.router)
app.include_router(task_router.router)
app.include_router(ad_router.router)
app.include_router(upload_router.router)
app.include_router(automation_router.router)
app.include_router(pricing_router.router)
app.include_router(settings_router.router)

from fastapi.responses import FileResponse
from fastapi import HTTPException, Query
from server.services.file_service import FileService

@app.get("/api/images/preview", summary="预览本地图片")
def preview_image_alias(path: str = Query(..., description="图片相对路径或文件名")):
    abs_path = FileService.resolve_image_path(path)
    if abs_path and os.path.exists(abs_path) and os.path.isfile(abs_path):
        import mimetypes
        mime_type, _ = mimetypes.guess_type(abs_path)
        return FileResponse(abs_path, media_type=mime_type or "image/jpeg")
    raise HTTPException(status_code=404, detail=f"Image not found: {path}")


# ──────────────────────────────────────────────────────────────
# db_agent 透传路由: 让异地桌面上件助手复用现有 SakuraFrp 隧道 (8000),
# 无需为 db_agent 8765 单独开隧道。鉴权由 db_agent 的 X-DB-Token 校验。
# ──────────────────────────────────────────────────────────────
import urllib.request as _urlreq
import urllib.error as _urlerr
from starlette.responses import Response
from fastapi.concurrency import run_in_threadpool

DB_AGENT_BASE = "http://127.0.0.1:8765"


def _db_agent_call(method: str, path: str, token: str, query: str = "", body: bytes = b""):
    """转发请求到本机 db_agent, 原样返回响应 (含二进制文件与错误 JSON)"""
    if not token:
        raise HTTPException(status_code=401, detail="缺少 X-DB-Token 请求头")
    url = f"{DB_AGENT_BASE}{path}" + (f"?{query}" if query else "")
    headers = {"X-DB-Token": token}
    data = None
    if method == "POST":
        headers["Content-Type"] = "application/json"
        data = body
    req = _urlreq.Request(url, data=data, headers=headers, method=method)
    try:
        with _urlreq.urlopen(req, timeout=60) as resp:
            return Response(content=resp.read(), status_code=resp.status,
                            media_type=resp.headers.get("Content-Type", "application/json"))
    except _urlerr.HTTPError as e:
        return Response(content=e.read(), status_code=e.code, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"db_agent 服务不可达: {e}")


@app.get("/ping", summary="db_agent 透传: 连接测试")
async def db_agent_ping(request: Request):
    return await run_in_threadpool(
        _db_agent_call, "GET", "/ping", request.headers.get("X-DB-Token", ""), request.url.query)


@app.get("/file", summary="db_agent 透传: 图片文件下载")
async def db_agent_file(request: Request):
    return await run_in_threadpool(
        _db_agent_call, "GET", "/file", request.headers.get("X-DB-Token", ""), request.url.query)


@app.post("/query", summary="db_agent 透传: 只读 SQL 查询")
async def db_agent_query(request: Request):
    body = await request.body()
    return await run_in_threadpool(
        _db_agent_call, "POST", "/query", request.headers.get("X-DB-Token", ""), request.url.query, body)


@app.post("/execute", summary="db_agent 透传: 写入 SQL 执行")
async def db_agent_execute(request: Request):
    body = await request.body()
    return await run_in_threadpool(
        _db_agent_call, "POST", "/execute", request.headers.get("X-DB-Token", ""), request.url.query, body)


# 4. 辅助鉴权函数
def get_page_auth_user(request: Request, require_admin: bool = False):
    """
    检查页面访问用户的登录态与管理员角色：
    - 未登录：返回 (None, RedirectResponse to /login)
    - 权限不足：返回 (user, HTMLResponse 403)
    - 正常：返回 (user, None)
    """
    user = get_current_user_from_request(request)
    if not user:
        next_url = request.url.path
        if next_url == "/":
            next_url = "/list"
        if request.url.query:
            next_url += f"?{request.url.query}"
        return None, RedirectResponse(url=f"/login?next={next_url}", status_code=status.HTTP_302_FOUND)

    if require_admin and user.get("role") != "admin":
        html_403 = """
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head><meta charset="UTF-8"><title>403 权限不足</title><link rel="stylesheet" href="/static/css/app.css"></head>
        <body style="display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc;">
          <div style="text-align:center; background:#fff; padding:40px; border-radius:12px; border:1px solid #e2e8f0; box-shadow:0 10px 30px rgba(0,0,0,0.05); max-width:460px;">
            <div style="font-size:3rem; margin-bottom:12px;">🚫</div>
            <h2 style="color:#1e293b; margin-bottom:8px;">403 访问受限</h2>
            <p style="color:#64748b; font-size:0.9rem; margin-bottom:24px;">您当前的账号角色为普通用户，无权访问管理员专属页面（系统配置/用户管理）。</p>
            <a href="/list" class="btn btn-primary" style="display:inline-block; text-decoration:none;">返回商品管理</a>
          </div>
        </body>
        </html>
        """
        return user, HTMLResponse(content=html_403, status_code=status.HTTP_403_FORBIDDEN)

    return user, None


# 5. 前端页面路由

@app.get("/login", response_class=HTMLResponse, summary="用户登录页面")
async def render_login_page(request: Request):
    """渲染登录页面，已登录则直接跳转商品列表页"""
    user = get_current_user_from_request(request)
    if user:
        return RedirectResponse(url="/list", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.get("/", summary="默认根路由 (输入地址不带路径默认跳转至商品管理)")
async def root_redirect(request: Request):
    """输入地址不带路径后，默认登录/进入 list 页面"""
    return RedirectResponse(url="/list", status_code=status.HTTP_302_FOUND)


@app.get("/entry", response_class=HTMLResponse, summary="商品录入工作台页面")
async def render_entry_page(request: Request):
    """渲染商品录入工作台 (需登录)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return templates.TemplateResponse(request=request, name="entry.html", context={
        "active_page": "entry",
        "current_user": user
    })


@app.get("/list", response_class=HTMLResponse, summary="商品管理页面")
async def render_list_page(request: Request):
    """渲染商品列表与状态看板 (需登录)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    products = ProductService.list_products(limit=50, offset=0)
    return templates.TemplateResponse(request=request, name="list.html", context={
        "active_page": "list",
        "products": products,
        "current_user": user
    })


@app.get("/settings", response_class=HTMLResponse, summary="系统管理与全局参数配置页面")
async def render_settings_page(request: Request):
    """渲染系统管理页面 (仅限管理员访问)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=True)
    if redirect_resp:
        return redirect_resp

    return templates.TemplateResponse(request=request, name="settings.html", context={
        "active_page": "settings",
        "current_user": user
    })


@app.get("/users", response_class=HTMLResponse, summary="用户账号管理与权限配置页面")
async def render_users_page(request: Request):
    """渲染用户管理页面 (仅限管理员访问)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=True)
    if redirect_resp:
        return redirect_resp

    return templates.TemplateResponse(request=request, name="users.html", context={
        "active_page": "users",
        "current_user": user
    })


@app.get("/tasks", response_class=HTMLResponse, summary="任务管理与成果登记看板页面")
async def render_tasks_page(request: Request):
    """渲染任务管理页面 (需登录，管理员可见全量，普通用户仅见分配给自己的任务)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return templates.TemplateResponse(request=request, name="tasks.html", context={
        "active_page": "tasks",
        "current_user": user
    })


@app.get("/ads", response_class=HTMLResponse, summary="赛狐广告投放任务管理页面")
async def render_ads_page(request: Request):
    """渲染广告管理页面 (仅管理员)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=True)
    if redirect_resp:
        return redirect_resp

    return templates.TemplateResponse(request=request, name="ads.html", context={
        "active_page": "ads",
        "current_user": user
    })


def start_server():
    """启动本地开发服务器"""
    uvicorn.run("server.app:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)


if __name__ == "__main__":
    start_server()
