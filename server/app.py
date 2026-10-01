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
from server.services.rbac_service import RbacService
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
    ad_router,
    asin_router,
    knowledge_router,
    prompt_router,
    forwarder_router,
    forwarder_doc_router,
    chudao_router,
    rbac_router,
    alert_router,
    jp_holiday_router,
    db_agent_router,
    ads_analysis_router
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 货代在线登记文档定时采集: 调度器独立文件 services/forwarder_doc_scheduler.py (每60s心跳检查到期)
    from server.services.forwarder_doc_scheduler import start_forwarder_doc_scheduler

    scheduler_task = start_forwarder_doc_scheduler()
    # 店小秘订单剩余发货时间采集: 调度器独立文件 services/dxm_order_scheduler.py (每60s心跳检查到期)
    from server.services.dxm_order_scheduler import start_dxm_order_scheduler

    dxm_scheduler_task = start_dxm_order_scheduler()
    # 每日汇总邮件 (08:15, 货代采集+店小秘8点批次结果): services/daily_digest_scheduler.py
    from server.services.daily_digest_scheduler import start_daily_digest_scheduler

    digest_scheduler_task = start_daily_digest_scheduler()
    # 日本节假日日历同步 + 大节日邮件提醒: services/jp_holiday_scheduler.py (每60s心跳)
    from server.services.jp_holiday_scheduler import start_jp_holiday_scheduler

    jp_holiday_task = start_jp_holiday_scheduler()
    display_host = "127.0.0.1" if SERVER_HOST in ("0.0.0.0", "") else SERVER_HOST
    print(f"🚀 服务已就绪！访问地址: http://{display_host}:{SERVER_PORT}")
    yield
    scheduler_task.cancel()
    dxm_scheduler_task.cancel()
    digest_scheduler_task.cancel()
    jp_holiday_task.cancel()

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
# 手机版 UI 自动分流:
# 手机 UA (或 cookie ui_mode=mobile) 优先渲染 mobile/{页面名}.html 手机版模板;
# 该页未提供手机版时自动回退 PC 版模板, 支持逐页铺设互不影响;
# cookie ui_mode=pc 可在手机上手动切换回桌面版 (页面底部 Tab -> 更多 -> 切换)
# ──────────────────────────────────────────────────────────────
import re as _re

# 宽松匹配: 所有 Android/iPad/鸿蒙一律按手机版处理 (手机浏览器开过"桌面版网站"开关后 UA 会伪装成桌面,
# 此时 UA 无法识别, 需靠页面上的「📱 手机版」入口手动切换)
_MOBILE_UA_RE = _re.compile(r"iPhone|iPod|iPad|Android|Windows Phone|BlackBerry|Opera Mini|IEMobile|HarmonyOS|OpenHarmony|Mobile Safari", _re.I)


def _is_mobile_request(request: Request) -> bool:
    """判断请求是否来自手机: cookie ui_mode 手动指定优先, 否则按 User-Agent 识别"""
    mode = request.cookies.get("ui_mode", "")
    if mode == "mobile":
        return True
    if mode == "pc":
        return False
    return bool(_MOBILE_UA_RE.search(request.headers.get("user-agent", "")))


def render_page(request: Request, name: str, context: dict):
    """统一页面渲染入口: 手机访问优先用 mobile/ 手机版模板, 不存在自动回退 PC 版 (并标记 fallback 供模板提示)"""
    # RBAC: 将用户菜单/按钮权限集注入所有页面模板 (导航按授权渲染 + JS 按钮权限)
    if context is None:
        context = {}
    context = dict(context)
    context.setdefault("user_menus", getattr(request.state, "user_menus", None) or [])
    context.setdefault("user_perms", getattr(request.state, "user_perms", None) or [])
    context.setdefault("user_role_names", getattr(request.state, "user_role_names", None) or [])
    if _is_mobile_request(request):
        mobile_name = f"mobile/{name}"
        if os.path.exists(os.path.join(TEMPLATES_DIR, *mobile_name.split("/"))):
            return templates.TemplateResponse(request=request, name=mobile_name, context=context)
        # 该页暂无手机版: 回退 PC 版并注入标记, base.html 据此显示右下角「手机版首页」悬浮按钮
        context["ui_mobile_fallback"] = True
    return templates.TemplateResponse(request=request, name=name, context=context)


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
app.include_router(asin_router.router)
app.include_router(upload_router.router)
app.include_router(automation_router.router)
app.include_router(pricing_router.router)
app.include_router(settings_router.router)
app.include_router(knowledge_router.router)
app.include_router(prompt_router.router)
app.include_router(forwarder_router.router)
app.include_router(forwarder_doc_router.router)
app.include_router(chudao_router.router)
app.include_router(rbac_router.router)
app.include_router(alert_router.router)
app.include_router(jp_holiday_router.router)
app.include_router(ads_analysis_router.router)
# 内嵌「图片服务 / DB Agent」: /ping、/file、/query、/execute (X-DB-Token 鉴权)
app.include_router(db_agent_router.router)

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
# 原 db_agent 透传路由已移除: /ping、/file、/query、/execute 由
# server/routers/db_agent_router.py 在本进程内直接实现 (单一端口, 无需 8765)
# ──────────────────────────────────────────────────────────────


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

    # ── RBAC: 注入用户菜单/按钮权限集/角色名, 并按菜单授权拦截页面访问 ──
    request.state.user_menus = RbacService.get_user_menus(user)
    request.state.user_perms = RbacService.get_user_perms(user)
    request.state.user_role_names = RbacService.get_user_role_names(user)
    require_admin_page = require_admin
    if not require_admin_page and not RbacService.check_page_allowed(user, request.url.path):
        require_admin_page = True  # 未授权菜单 → 走同一 403 提示页

    if require_admin_page and user.get("role") != "admin":
        target = request.url.path
        hint = "您当前的账号角色无权访问该页面, 请联系管理员开通对应菜单权限。" \
            if RbacService.check_page_allowed(user, "/settings") or user.get("role") == "admin" \
            else "您当前的账号角色为普通用户, 无权访问管理员专属页面 (系统配置/用户管理)。"
        html_403 = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head><meta charset="UTF-8"><title>403 权限不足</title><link rel="stylesheet" href="/static/css/app.css"></head>
        <body style="display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc;">
          <div style="text-align:center; background:#fff; padding:40px; border-radius:12px; border:1px solid #e2e8f0; box-shadow:0 10px 30px rgba(0,0,0,0.05); max-width:460px;">
            <div style="font-size:3rem; margin-bottom:12px;">🚫</div>
            <h2 style="color:#1e293b; margin-bottom:8px;">403 访问受限</h2>
            <p style="color:#64748b; font-size:0.9rem; margin-bottom:24px;">您无权访问 <b>{target}</b>。{hint}</p>
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
    return render_page(request, "login.html", context={})


@app.get("/", summary="默认根路由 (输入地址不带路径默认跳转至商品管理)")
async def root_redirect(request: Request):
    """输入地址不带路径后，默认登录/进入 list 页面"""
    return RedirectResponse(url="/list", status_code=status.HTTP_302_FOUND)


@app.get("/ui-mode/{mode}", summary="切换界面版本 (mobile 手机版 / pc 桌面版), 覆盖 UA 自动分流")
async def switch_ui_mode(request: Request, mode: str):
    """手动指定界面版本并写 cookie (1年有效), 之后从来源页返回"""
    if mode not in ("mobile", "pc"):
        mode = "mobile"
    back = request.query_params.get("next") or request.headers.get("referer") or "/list"
    if not back.startswith("/") and not back.startswith(str(request.base_url)):
        back = "/list"
    resp = RedirectResponse(url=back, status_code=status.HTTP_302_FOUND)
    resp.set_cookie("ui_mode", mode, max_age=365 * 24 * 3600, samesite="lax")
    return resp


@app.get("/entry", response_class=HTMLResponse, summary="商品录入工作台页面")
async def render_entry_page(request: Request):
    """渲染商品录入工作台 (需登录)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "entry.html", context={
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
    return render_page(request, "list.html", context={
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

    return render_page(request, "settings.html", context={
        "active_page": "settings",
        "current_user": user
    })


@app.get("/users", response_class=HTMLResponse, summary="用户账号管理与权限配置页面")
async def render_users_page(request: Request):
    """渲染用户管理页面 (仅限管理员访问)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=True)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "users.html", context={
        "active_page": "users",
        "current_user": user
    })


@app.get("/forwarder", response_class=HTMLResponse, summary="货代管理页面")
async def render_forwarder_page(request: Request):
    """渲染货代管理页面 (需登录; 管理员可维护, 普通用户仅查看)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "forwarder.html", context={
        "active_page": "forwarder",
        "current_user": user
    })


@app.get("/forwarder-integration", response_class=HTMLResponse, summary="运单管理页面 (运单查询/轨迹跟踪)")
async def render_forwarder_integration_page(request: Request):
    """渲染运单管理页面 (需登录; 子菜单样式与系统管理一致, 初岛国际物流 API 对接)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "forwarder_integration.html", context={
        "active_page": "forwarder_integration",
        "current_user": user
    })


@app.get("/japan-calendar", response_class=HTMLResponse, summary="日本节假日日历页面")
async def render_japan_calendar_page(request: Request):
    """渲染日本节假日日历页面 (需登录; 提醒配置仅管理员可改)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "japan_calendar.html", context={
        "active_page": "japan_calendar",
        "current_user": user
    })


@app.get("/alert-tasks", summary="告警任务配置 (已并入系统管理)")
async def redirect_alert_tasks():
    """旧入口重定向: 告警任务已并入系统管理页 #alert_tasks 标签"""
    return RedirectResponse(url="/settings#alert_tasks", status_code=status.HTTP_302_FOUND)


@app.get("/reminders", summary="提醒任务配置 (已并入系统管理)")
async def redirect_reminders():
    """旧入口重定向: 提醒任务已并入系统管理页 #reminders 标签"""
    return RedirectResponse(url="/settings#reminders", status_code=status.HTTP_302_FOUND)


@app.get("/alerts", response_class=HTMLResponse, summary="告警中心页面")
async def render_alert_center_page(request: Request):
    """渲染告警中心页面 (需登录, 全员可看)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "alert_center.html", context={
        "active_page": "alert_center",
        "current_user": user
    })


@app.get("/tasks", response_class=HTMLResponse, summary="任务管理与成果登记看板页面")
async def render_tasks_page(request: Request):
    """渲染任务管理页面 (需登录，管理员可见全量，普通用户仅见分配给自己的任务)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "tasks.html", context={
        "active_page": "tasks",
        "current_user": user
    })


@app.get("/knowledge", response_class=HTMLResponse, summary="知识库与分段网址导航页面")
async def render_knowledge_page(request: Request):
    """渲染知识库导航页面 (所有登录用户均可见)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "knowledge.html", context={
        "active_page": "knowledge",
        "current_user": user
    })


@app.get("/ads-analysis", response_class=HTMLResponse, summary="广告分析页面 (数据导入/在线产品/广告研判)")
async def render_ads_analysis_page(request: Request):
    """渲染广告分析页面 (需登录; 菜单可见性由 RBAC 角色配置控制)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "ads_analysis.html", context={
        "active_page": "ads_analysis",
        "current_user": user
    })


@app.get("/ads", response_class=HTMLResponse, summary="赛狐广告投放任务管理页面")
async def render_ads_page(request: Request):
    """渲染广告管理页面 (需登录; 菜单/按钮级权限由 RBAC 角色配置控制)"""
    user, redirect_resp = get_page_auth_user(request, require_admin=False)
    if redirect_resp:
        return redirect_resp

    return render_page(request, "ads.html", context={
        "active_page": "ads",
        "current_user": user
    })


def start_server():
    """启动本地开发服务器"""
    # reload=True 会使 Chrome 从 multiprocessing worker 派生时 sandbox 初始化失败
    # (退出码 21), 且代码热重载会中断运行中的任务; 生产固定关闭。
    uvicorn.run("server.app:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)


if __name__ == "__main__":
    start_server()
