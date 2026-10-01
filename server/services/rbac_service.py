"""
RBAC 权限体系服务层
- 菜单注册表 MENU_REGISTRY (代码为准, 入库用于角色关联)
- 按钮权限点注册表 PERMISSION_REGISTRY (代码为准)
- 用户菜单/权限集查询 (多角色并集, admin 超管全量)
- 角色 CRUD 与角色菜单/权限点配置
- require_perm FastAPI 依赖 (API 级权限兜底)
"""
from typing import Dict, Any, List

from fastapi import HTTPException, Request

from server.database import get_db_connection
from server.services.auth_service import AuthService

# ══════════════════════════ 菜单注册表 ══════════════════════════
# key 为菜单唯一标识; pages 为该菜单覆盖的页面路径 (用于页面访问拦截)
MENU_REGISTRY: List[Dict[str, Any]] = [
    {"key": "list",                   "name": "商品管理", "icon": "📦", "url": "/list",                "pages": ["/list", "/entry"],            "sort": 1},
    {"key": "tasks",                  "name": "任务管理", "icon": "📋", "url": "/tasks",               "pages": ["/tasks"],                     "sort": 2},
    {"key": "ads",                    "name": "广告管理", "icon": "📣", "url": "/ads",                 "pages": ["/ads"],                       "sort": 3},
    {"key": "ads_analysis",           "name": "广告分析", "icon": "📊", "url": "/ads-analysis",        "pages": ["/ads-analysis"],              "sort": 4},
    {"key": "knowledge",              "name": "知识库",   "icon": "📚", "url": "/knowledge",           "pages": ["/knowledge"],                 "sort": 5},
    {"key": "forwarder_integration",  "name": "运单管理", "icon": "🚚", "url": "/forwarder-integration", "pages": ["/forwarder-integration"],   "sort": 6},
    {"key": "forwarder",              "name": "货代管理", "icon": "🛳️", "url": "/forwarder",          "pages": ["/forwarder"],                 "sort": 7},
    {"key": "japan_calendar",         "name": "日本日历", "icon": "📅", "url": "/japan-calendar",      "pages": ["/japan-calendar"],            "sort": 8},
    {"key": "alert_center",           "name": "告警中心", "icon": "🚨", "url": "/alerts",              "pages": ["/alerts"],                    "sort": 9},
    {"key": "settings",               "name": "系统管理", "icon": "⚙️", "url": "/settings",            "pages": ["/settings"],                  "sort": 10},
    {"key": "users",                  "name": "用户管理", "icon": "👥", "url": "/users",               "pages": ["/users"],                     "sort": 11},
]
MENU_KEYS = {m["key"] for m in MENU_REGISTRY}

# 页面路径 → 菜单key 映射 (页面拦截用)
PAGE_TO_MENU: Dict[str, str] = {}
for _m in MENU_REGISTRY:
    for _p in _m["pages"]:
        PAGE_TO_MENU[_p] = _m["key"]

# ══════════════════════════ 按钮权限点注册表 ══════════════════════════
# key: (名称, 说明, 归属菜单key)
PERMISSION_REGISTRY: Dict[str, Dict[str, str]] = {
    "waybill:delete":      {"name": "运单删除",   "desc": "删除运单库记录",           "menu": "forwarder_integration"},
    "waybill:sync":        {"name": "妙手同步",   "desc": "从妙手ERP同步运单号",      "menu": "forwarder_integration"},
    "waybill:refresh_all": {"name": "全部刷新",   "desc": "一键刷新全部运单状态",     "menu": "forwarder_integration"},
    "product:create":      {"name": "商品新建",   "desc": "录入新商品",               "menu": "list"},
    "product:edit":        {"name": "商品编辑",   "desc": "编辑/复制商品",            "menu": "list"},
    "product:delete":      {"name": "商品删除",   "desc": "删除商品",                 "menu": "list"},
    "publish:run":         {"name": "商品上件",   "desc": "触发店小秘ERP自动上件",    "menu": "list"},
    "ads:create":          {"name": "广告新建",   "desc": "新建广告任务",             "menu": "ads"},
    "ads:operate":         {"name": "广告操作",   "desc": "刷新/重试/删除广告任务",   "menu": "ads"},
}

# ══════════════════════════ 预置角色 ══════════════════════════
BUILTIN_ROLES: List[Dict[str, Any]] = [
    {
        "code": "admin", "name": "管理员", "description": "超级管理员, 拥有全部菜单与按钮权限, 不可修改",
        "menus": sorted(MENU_KEYS), "permissions": sorted(PERMISSION_REGISTRY.keys()),
    },
    {
        "code": "user", "name": "普通用户", "description": "常用页面与操作, 删除类权限默认不授",
        "menus": ["list", "tasks", "knowledge", "forwarder_integration", "japan_calendar", "alert_center"],
        "permissions": ["product:create", "product:edit", "publish:run", "waybill:sync", "waybill:refresh_all"],
    },
]


class RbacService:
    """角色/菜单/权限 业务层"""

    # ─────────────── 用户权限查询 ───────────────
    @staticmethod
    def _effective_role_ids(user: Dict[str, Any], cursor) -> List[int]:
        """用户生效角色ID: 显式绑定优先; 无绑定时兜底「普通用户」角色 (新建用户未分配不失权)"""
        cursor.execute("SELECT role_id FROM user_roles WHERE user_id = ?;", (user["id"],))
        ids = [r["role_id"] for r in cursor.fetchall()]
        if ids:
            return ids
        cursor.execute("SELECT id FROM roles WHERE code = 'user';")
        row = cursor.fetchone()
        return [row["id"]] if row else []

    @staticmethod
    def get_user_role_ids(user: Dict[str, Any]) -> List[int]:
        conn = get_db_connection()
        cursor = conn.cursor()
        ids = RbacService._effective_role_ids(user, cursor)
        conn.close()
        return ids

    @staticmethod
    def get_user_menus(user: Dict[str, Any]) -> List[str]:
        """用户可见菜单key集合: 多角色并集; admin超管/管理员角色全量"""
        if user.get("role") == "admin":
            return sorted(MENU_KEYS)
        ids = RbacService.get_user_role_ids(user)
        if not ids:
            return []
        conn = get_db_connection()
        cursor = conn.cursor()
        marks = ",".join("?" * len(ids))
        cursor.execute(f"SELECT DISTINCT menu_key FROM role_menus WHERE role_id IN ({marks});", ids)
        keys = [r["menu_key"] for r in cursor.fetchall() if r["menu_key"] in MENU_KEYS]
        conn.close()
        return sorted(set(keys))

    @staticmethod
    def get_user_perms(user: Dict[str, Any]) -> List[str]:
        """用户按钮权限点集合: 多角色并集; admin超管全量"""
        if user.get("role") == "admin":
            return sorted(PERMISSION_REGISTRY.keys())
        ids = RbacService.get_user_role_ids(user)
        if not ids:
            return []
        conn = get_db_connection()
        cursor = conn.cursor()
        marks = ",".join("?" * len(ids))
        cursor.execute(f"SELECT DISTINCT perm_key FROM role_permissions WHERE role_id IN ({marks});", ids)
        keys = [r["perm_key"] for r in cursor.fetchall() if r["perm_key"] in PERMISSION_REGISTRY]
        conn.close()
        return sorted(set(keys))

    @staticmethod
    def get_user_role_names(user: Dict[str, Any]) -> List[str]:
        """用户实际绑定的角色名列表 (右上角徽章显示用): 多角色并集; 无绑定兜底「普通用户」"""
        ids = RbacService.get_user_role_ids(user)
        if not ids:
            return ["普通用户"]
        conn = get_db_connection()
        cursor = conn.cursor()
        marks = ",".join("?" * len(ids))
        cursor.execute(f"SELECT DISTINCT name FROM roles WHERE id IN ({marks});", ids)
        names = [r["name"] for r in cursor.fetchall()]
        conn.close()
        return sorted(names) if names else ["普通用户"]

    @staticmethod
    def check_page_allowed(user: Dict[str, Any], path: str) -> bool:
        """页面访问拦截: path 属于某菜单且用户未授权该菜单 → False"""
        menu_key = PAGE_TO_MENU.get(path)
        if not menu_key:
            return True
        return menu_key in RbacService.get_user_menus(user)

    @staticmethod
    def user_has_perm(user: Dict[str, Any], perm_key: str) -> bool:
        """函数内权限判断 (用于按参数区分的端点, 如 ids 为空才需要全量刷新权限)"""
        if not user:
            return False
        if user.get("role") == "admin" or perm_key not in PERMISSION_REGISTRY:
            return True
        return perm_key in RbacService.get_user_perms(user)

    # ─────────────── 角色 CRUD ───────────────
    @staticmethod
    def list_roles() -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles ORDER BY is_builtin DESC, id ASC;")
        roles = [dict(r) for r in cursor.fetchall()]
        for role in roles:
            rid = role["id"]
            cursor.execute("SELECT menu_key FROM role_menus WHERE role_id = ?;", (rid,))
            role["menus"] = [r["menu_key"] for r in cursor.fetchall()]
            cursor.execute("SELECT perm_key FROM role_permissions WHERE role_id = ?;", (rid,))
            role["permissions"] = [r["perm_key"] for r in cursor.fetchall()]
            cursor.execute("""
                SELECT COUNT(1) AS c FROM user_roles ur
                JOIN users u ON u.id = ur.user_id AND u.status = 'active'
                WHERE ur.role_id = ?;
            """, (rid,))
            role["user_count"] = cursor.fetchone()["c"]
        conn.close()
        return roles

    @staticmethod
    def create_role(code: str, name: str, description: str = "") -> Dict[str, Any]:
        code = code.strip()
        name = name.strip()
        if not code or not name:
            raise ValueError("角色标识与名称均必填")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM roles WHERE code = ? OR name = ?;", (code, name))
        if cursor.fetchone():
            conn.close()
            raise ValueError(f"角色标识或名称已存在: {code}")
        cursor.execute(
            "INSERT INTO roles (code, name, description, is_builtin) VALUES (?, ?, ?, 0);",
            (code, name, description.strip()))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"id": new_id, "code": code, "name": name, "description": description.strip(),
                "is_builtin": 0, "menus": [], "permissions": [], "user_count": 0}

    @staticmethod
    def delete_role(role_id: int) -> None:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE id = ?;", (role_id,))
        role = cursor.fetchone()
        if not role:
            conn.close()
            raise ValueError("角色不存在")
        if role["is_builtin"]:
            conn.close()
            raise ValueError("内置角色不可删除")
        cursor.execute("SELECT COUNT(1) AS c FROM user_roles WHERE role_id = ?;", (role_id,))
        if cursor.fetchone()["c"] > 0:
            conn.close()
            raise ValueError("该角色仍有用户绑定, 请先解绑")
        cursor.execute("DELETE FROM role_menus WHERE role_id = ?;", (role_id,))
        cursor.execute("DELETE FROM role_permissions WHERE role_id = ?;", (role_id,))
        cursor.execute("DELETE FROM roles WHERE id = ?;", (role_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def update_role_config(role_id: int, menus: List[str], permissions: List[str]) -> None:
        """配置角色的菜单与按钮权限 (内置 admin 角色拒绝修改, 防自锁)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles WHERE id = ?;", (role_id,))
        role = cursor.fetchone()
        if not role:
            conn.close()
            raise ValueError("角色不存在")
        if role["code"] == "admin":
            conn.close()
            raise ValueError("管理员角色为全量权限, 不可修改")
        menu_keys = [m for m in menus if m in MENU_KEYS]
        perm_keys = [p for p in permissions if p in PERMISSION_REGISTRY]
        cursor.execute("DELETE FROM role_menus WHERE role_id = ?;", (role_id,))
        cursor.execute("DELETE FROM role_permissions WHERE role_id = ?;", (role_id,))
        for mk in dict.fromkeys(menu_keys):
            cursor.execute("INSERT INTO role_menus (role_id, menu_key) VALUES (?, ?);", (role_id, mk))
        for pk in dict.fromkeys(perm_keys):
            cursor.execute("INSERT INTO role_permissions (role_id, perm_key) VALUES (?, ?);", (role_id, pk))
        conn.commit()
        conn.close()

    # ─────────────── 用户角色分配 ───────────────
    @staticmethod
    def get_user_roles(user_id: int) -> List[int]:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT role_id FROM user_roles WHERE user_id = ?;", (user_id,))
        ids = [r["role_id"] for r in cursor.fetchall()]
        conn.close()
        return ids

    @staticmethod
    def set_user_roles(user_id: int, role_ids: List[int]) -> None:
        """配置用户角色 (多对多); 用户管理页仅超管可操作"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = ?;", (user_id,))
        if not cursor.fetchone():
            conn.close()
            raise ValueError("用户不存在")
        valid_ids = []
        for rid in role_ids:
            cursor.execute("SELECT id, code FROM roles WHERE id = ?;", (rid,))
            row = cursor.fetchone()
            if row:
                valid_ids.append(row["id"])
        cursor.execute("DELETE FROM user_roles WHERE user_id = ?;", (user_id,))
        for rid in dict.fromkeys(valid_ids):
            cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?);", (user_id, rid))
        conn.commit()
        conn.close()


# ══════════════════════════ FastAPI 依赖: API 级权限兜底 ══════════════════════════
def require_perm(perm_key: str):
    """路由依赖: 校验当前用户具备指定按钮权限点; admin 超管/未注册权限直接通过"""
    def _checker(request: Request):
        user = AuthService.get_user_by_session_token(request.cookies.get("session_token", ""))
        if not user:
            raise HTTPException(status_code=401, detail="未登录或会话已过期")
        if user.get("role") == "admin" or perm_key not in PERMISSION_REGISTRY:
            return user
        if perm_key in RbacService.get_user_perms(user):
            return user
        raise HTTPException(status_code=403, detail=f"无操作权限: {PERMISSION_REGISTRY[perm_key]['name']}")
    return _checker
