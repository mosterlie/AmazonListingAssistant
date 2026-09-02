"""
用户鉴权、会话管理与用户 CRUD 业务层
"""
import hashlib
import secrets
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from server.database import get_db_connection, get_setting
from server.models.user_schemas import UserCreateSchema, UserUpdateSchema


class AuthService:
    """用户认证与会话服务"""

    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
        """使用 PBKDF2-HMAC-SHA256 对密码进行加盐哈希"""
        if not salt:
            salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()
        return pwd_hash, salt

    @staticmethod
    def verify_password(password: str, pwd_hash: str, salt: str) -> bool:
        """校验密码是否匹配"""
        test_hash, _ = AuthService.hash_password(password, salt)
        return secrets.compare_digest(test_hash, pwd_hash)

    @staticmethod
    def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
        """根据用户名密码进行登录认证"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?);", (username.strip(),))
        user_row = cursor.fetchone()
        conn.close()

        if not user_row:
            return None

        user = dict(user_row)
        if user.get("status") == "disabled":
            raise ValueError("该账号已被禁用，请联系管理员启用！")

        if not AuthService.verify_password(password, user["password_hash"], user["salt"]):
            return None

        # 清除敏感字段
        user.pop("password_hash", None)
        user.pop("salt", None)
        return user

    @staticmethod
    def get_session_expire_hours() -> float:
        """
        从系统配置获取 Session 有效时长 (小时)
        若 <= 0 则表示永久有效 (永不过期)
        """
        try:
            val = get_setting("session_expire_hours", 1.0)
            val_f = float(val)
            return val_f if val_f >= 0 else 0.0
        except Exception:
            return 1.0

    @staticmethod
    def create_session(user_id: int, hours_valid: Optional[float] = None) -> tuple[str, datetime, int]:
        """
        为用户创建有效 Session Token 并持久化到数据库
        若 hours_valid <= 0 则设为永久有效 (100 年有效期)
        返回: (token, expires_at_datetime, max_age_seconds)
        """
        if hours_valid is None:
            hours_valid = AuthService.get_session_expire_hours()
        hours_valid = float(hours_valid)

        is_permanent = (hours_valid <= 0)
        token = secrets.token_urlsafe(32)

        if is_permanent:
            # 永久有效：设置 100 年后过期，Cookie 设置 10 年 (315360000 秒)
            expires_at = datetime.utcnow() + timedelta(days=36500)
            max_age_seconds = 315360000
        else:
            hours_valid = max(0.01, hours_valid)
            expires_at = datetime.utcnow() + timedelta(hours=hours_valid)
            max_age_seconds = int(hours_valid * 3600)

        expires_at_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 自动清理已过期的旧 session
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("DELETE FROM user_sessions WHERE expires_at < ?;", (now_str,))

        cursor.execute("""
        INSERT INTO user_sessions (token, user_id, expires_at)
        VALUES (?, ?, ?);
        """, (token, user_id, expires_at_str))
        conn.commit()
        conn.close()
        return token, expires_at, max_age_seconds

    @staticmethod
    def get_user_by_session_token(token: str) -> Optional[Dict[str, Any]]:
        """根据 Session Token 获取对应的用户信息（严格核验是否过期，支持永久有效与动态配置）"""
        if not token:
            return None

        now_dt = datetime.utcnow()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT u.id, u.username, u.role, u.display_name, u.status, u.created_at, s.created_at AS session_created_at, s.expires_at
        FROM user_sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ?;
        """, (token,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        is_expired = False
        curr_expire_hours = AuthService.get_session_expire_hours()

        # 若当前全局设置为永久有效 (<= 0)，则永不过期
        if curr_expire_hours <= 0:
            is_expired = False
        else:
            # 1. 检查数据库记录的过期时间
            expires_at_str = row["expires_at"]
            if expires_at_str and str(expires_at_str) < now_str:
                is_expired = True

            # 2. 动态对比当前最新配置的有效时长 (实时生效，即便修改配置也无需重新登录立即对齐)
            session_created_str = row["session_created_at"]
            if not is_expired and session_created_str:
                try:
                    created_dt = datetime.strptime(str(session_created_str)[:19], "%Y-%m-%d %H:%M:%S")
                    if (now_dt - created_dt).total_seconds() > (curr_expire_hours * 3600):
                        is_expired = True
                except Exception:
                    pass

        if is_expired:
            # 及时从数据库删除过期 session
            cursor.execute("DELETE FROM user_sessions WHERE token = ?;", (token,))
            conn.commit()
            conn.close()
            return None

        conn.close()

        user = dict(row)
        # 检查账号状态
        if user.get("status") == "disabled":
            return None

        return user

    @staticmethod
    def delete_session(token: str):
        """退出登录：销毁 Session"""
        if not token:
            return
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE token = ?;", (token,))
        conn.commit()
        conn.close()

    # =========================================================================
    # 用户管理 CRUD (管理员权限专用)
    # =========================================================================

    @staticmethod
    def list_users() -> List[Dict[str, Any]]:
        """查询所有用户列表"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id, username, display_name, role, status, created_at, updated_at
        FROM users
        ORDER BY id ASC;
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 查询单个用户"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id, username, display_name, role, status, created_at, updated_at
        FROM users
        WHERE id = ?;
        """, (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def create_user(data: UserCreateSchema) -> Dict[str, Any]:
        """管理员创建新用户"""
        username = data.username.strip()
        conn = get_db_connection()
        cursor = conn.cursor()

        # 检查用户名重复
        cursor.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(?);", (username,))
        if cursor.fetchone():
            conn.close()
            raise ValueError(f"用户名 '{username}' 已存在，无法重复创建！")

        pwd_hash, salt = AuthService.hash_password(data.password)
        cursor.execute("""
        INSERT INTO users (username, password_hash, salt, role, display_name, status)
        VALUES (?, ?, ?, ?, ?, ?);
        """, (username, pwd_hash, salt, data.role, data.display_name or "", data.status))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return AuthService.get_user_by_id(new_id)

    @staticmethod
    def update_user(user_id: int, data: UserUpdateSchema) -> Dict[str, Any]:
        """管理员更新用户信息或重置密码"""
        user = AuthService.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"用户 ID {user_id} 不存在！")

        conn = get_db_connection()
        cursor = conn.cursor()

        update_fields = []
        params = []

        if data.display_name is not None:
            update_fields.append("display_name = ?")
            params.append(data.display_name.strip())

        if data.role is not None:
            # 保护：如果是初始 admin 用户，不允许修改为普通用户
            if user["username"] == "admin" and data.role != "admin":
                conn.close()
                raise ValueError("系统初始 admin 用户必须保持管理员角色！")
            update_fields.append("role = ?")
            params.append(data.role)

        if data.status is not None:
            # 保护：如果是初始 admin 用户，不允许禁用
            if user["username"] == "admin" and data.status == "disabled":
                conn.close()
                raise ValueError("系统初始 admin 用户不允许被禁用！")
            update_fields.append("status = ?")
            params.append(data.status)

        if data.password:
            pwd_hash, salt = AuthService.hash_password(data.password)
            update_fields.append("password_hash = ?")
            params.append(pwd_hash)
            update_fields.append("salt = ?")
            params.append(salt)

        if update_fields:
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(user_id)
            sql = f"UPDATE users SET {', '.join(update_fields)} WHERE id = ?;"
            cursor.execute(sql, tuple(params))
            conn.commit()

        conn.close()
        return AuthService.get_user_by_id(user_id)

    @staticmethod
    def delete_user(user_id: int, current_user_id: int) -> bool:
        """管理员删除用户"""
        user = AuthService.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"用户 ID {user_id} 不存在！")

        if user_id == current_user_id:
            raise ValueError("无法删除当前正在登录的账号！")

        if user["username"] == "admin":
            raise ValueError("系统默认超级管理员账号 admin 不允许删除！")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?;", (user_id,))
        cursor.execute("DELETE FROM user_sessions WHERE user_id = ?;", (user_id,))
        conn.commit()
        conn.close()
        return True
