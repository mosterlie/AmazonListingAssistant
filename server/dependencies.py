"""
FastAPI 认证与角色权限鉴权依赖项
"""
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status, Depends
from server.services.auth_service import AuthService


def get_current_user_from_request(request: Request) -> Optional[Dict[str, Any]]:
    """从 Cookie 或 Authorization Header 中提取并校验当前会话用户"""
    # 1. 尝试从 Cookie 中读取 session_token
    token = request.cookies.get("session_token")

    # 2. 若 Cookie 无，尝试从 Header 中读取 (Authorization: Bearer <token>)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        return None

    return AuthService.get_user_by_session_token(token)


async def get_current_user(request: Request) -> Dict[str, Any]:
    """必须已登录的用户依赖项 (API 路由专用)"""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户未登录或登录会话已过期，请重新登录！"
        )
    return user


async def require_admin_user(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """必须为管理员角色依赖项 (API 路由专用)"""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足！该功能仅限系统管理员访问。"
        )
    return user
