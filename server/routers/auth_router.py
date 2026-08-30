"""
用户认证与登录/退出相关 API 路由
"""
from fastapi import APIRouter, Response, Request, HTTPException, status, Depends
from server.models.user_schemas import UserLoginSchema
from server.services.auth_service import AuthService
from server.dependencies import get_current_user_from_request

router = APIRouter(prefix="/api/auth", tags=["用户认证"])


@router.post("/login", summary="用户登录")
async def login(data: UserLoginSchema, response: Response):
    """用户登录接口：验证通过后设置 HttpOnly Cookie 并返回用户信息"""
    try:
        user = AuthService.authenticate_user(data.username, data.password)
        if not user:
            return {"code": 401, "msg": "用户名或密码错误，请核对后重试！", "data": None}

        # 创建 Session Token
        token = AuthService.create_session(user["id"], days_valid=7)

        # 设置安全的 HTTP-only Cookie
        response.set_cookie(
            key="session_token",
            value=token,
            max_age=7 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=False  # 本地开发环境为 False
        )

        return {
            "code": 0,
            "msg": "登录成功！",
            "data": {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "display_name": user["display_name"]
            }
        }
    except ValueError as ve:
        return {"code": 403, "msg": str(ve), "data": None}
    except Exception as e:
        return {"code": 500, "msg": f"登录异常: {str(e)}", "data": None}


@router.post("/logout", summary="退出登录")
async def logout(request: Request, response: Response):
    """用户退出登录：销毁 Session 并清除 Cookie"""
    token = request.cookies.get("session_token")
    if token:
        AuthService.delete_session(token)
    response.delete_cookie("session_token")
    return {"code": 0, "msg": "已成功退出登录", "data": None}


@router.get("/me", summary="获取当前登录用户信息")
async def get_my_info(request: Request):
    """获取当前登录用户信息"""
    user = get_current_user_from_request(request)
    if not user:
        return {"code": 401, "msg": "未登录", "data": None}
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "display_name": user["display_name"]
        }
    }
