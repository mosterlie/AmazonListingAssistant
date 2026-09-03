"""
任务管理业务逻辑服务层 (TaskService)
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from server.database import get_db_connection
from server.models.task_schemas import TaskCreateSchema, TaskUpdateSchema, TaskSubmitSchema


class TaskService:
    """任务管理核心业务：派发任务、成果登记、关联商品及权限隔离"""

    @staticmethod
    def create_task(data: TaskCreateSchema, current_user: Dict[str, Any]) -> Dict[str, Any]:
        """
        管理员派发新任务
        :param data: 任务派发参数
        :param current_user: 当前登录管理员信息
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            assigned_by = current_user.get("username", "admin")
            assigned_to = data.assigned_to.strip()

            # 查询被指派人的真实姓名/昵称
            cursor.execute("SELECT display_name FROM users WHERE username = ?;", (assigned_to,))
            user_row = cursor.fetchone()
            assigned_to_name = (user_row["display_name"] if user_row and user_row["display_name"] else assigned_to)

            # 自动提炼任务标题
            title = (data.title or "").strip()
            if not title:
                title = f"任务-{datetime.now().strftime('%m%d%H%M')}"

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
            INSERT INTO tasks (
                title, reference_url, instructions,
                assigned_by, assigned_to, assigned_to_name,
                assigned_at, result_url, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', 'pending', ?, ?)
            """, (
                title, data.reference_url.strip(), (data.instructions or "").strip(),
                assigned_by, assigned_to, assigned_to_name,
                now_str, now_str, now_str
            ))

            task_id = cursor.lastrowid
            conn.commit()
            return TaskService.get_task_by_id(task_id)
        finally:
            conn.close()

    @staticmethod
    def list_tasks(
        current_user: Dict[str, Any],
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        assigned_to_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        查询任务列表 (所有人可见全部任务, 编辑权限另行控制)
        - assigned_to_filter: 执行人筛选 (管理员专用, 普通用户传参忽略)
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clauses = []
            params = []

            # 1. 执行人筛选 (仅管理员可按成员过滤; 普通用户可见全部)
            is_admin = (current_user.get("role") == "admin")
            if is_admin and assigned_to_filter and assigned_to_filter.strip():
                where_clauses.append("assigned_to = ?")
                params.append(assigned_to_filter.strip())

            # 2. 状态过滤
            if status_filter and status_filter.strip() and status_filter.strip() != "all":
                where_clauses.append("status = ?")
                params.append(status_filter.strip())

            # 3. 关键词模糊检索
            if search and search.strip():
                s = f"%{search.strip()}%"
                where_clauses.append("""
                (title LIKE ? OR reference_url LIKE ? OR instructions LIKE ? OR result_url LIKE ? OR product_title LIKE ? OR product_parent_sku LIKE ?)
                """)
                params.extend([s, s, s, s, s, s])

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            sql = f"SELECT * FROM tasks {where_sql} ORDER BY id DESC"

            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_task_by_id(task_id: int, current_user: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """根据 ID 获取任务明细"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM tasks WHERE id = ?;", (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            task_dict = dict(row)
            return task_dict
        finally:
            conn.close()

    @staticmethod
    def submit_task_deliverable(task_id: int, data: TaskSubmitSchema, current_user: Dict[str, Any]) -> Dict[str, Any]:
        """
        登记成果信息与关联商品，自动流转任务状态：
        - 仅登记成果链接未关联商品：状态为 'pending' (待处理)
        - 关联已录入商品 (product_id > 0)：状态自动变为 'completed' (已完成)
        """
        task = TaskService.get_task_by_id(task_id, current_user)
        if not task:
            raise ValueError("任务不存在！")
        # 编辑权限控制: 仅任务执行人本人或管理员可登记成果
        is_admin = (current_user.get("role") == "admin")
        if not is_admin and task.get("assigned_to") != current_user.get("username", ""):
            raise ValueError("只有该任务的执行人才能登记成果！")

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            result_url = (data.result_url or "").strip()
            product_id = int(data.product_id or 0)
            if not result_url:
                raise ValueError("成品链接为必填项，请输入成品链接！")
            if not product_id or product_id <= 0:
                raise ValueError("关联的品为必填项，请选择已录入的商品！")

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            product_title = ""
            product_parent_sku = ""
            product_main_image = ""

            # 从 product_items (is_parent = 1) 查询
            cursor.execute("""
            SELECT id, title, parent_sku, main_image 
            FROM product_items 
            WHERE id = ? AND is_parent = 1;
            """, (product_id,))
            p_row = cursor.fetchone()

            if not p_row:
                raise ValueError("所选关联商品不存在或已被删除！")

            # 校验该商品是否已被其它任务关联 (同一商品只能被一个任务关联)
            cursor.execute(
                "SELECT id, title FROM tasks WHERE product_id = ? AND id != ?;",
                (product_id, task_id)
            )
            other = cursor.fetchone()
            if other:
                raise ValueError(f"该商品已被任务 #{other['id']}《{other['title']}》关联，不能重复关联！")

            product_title = p_row["title"] or ""
            product_parent_sku = p_row["parent_sku"] or ""
            product_main_image = p_row["main_image"] or ""
            status = "completed"  # 登记成果且关联商品后即为已完成

            cursor.execute("""
            UPDATE tasks SET
                result_url = ?,
                submitted_at = ?,
                product_id = ?,
                product_title = ?,
                product_parent_sku = ?,
                product_main_image = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?;
            """, (
                result_url, now_str, product_id,
                product_title, product_parent_sku, product_main_image,
                status, now_str, task_id
            ))

            conn.commit()
            return TaskService.get_task_by_id(task_id)
        finally:
            conn.close()

    @staticmethod
    def update_task(task_id: int, data: TaskUpdateSchema) -> Dict[str, Any]:
        """管理员修改任务派发信息"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM tasks WHERE id = ?;", (task_id,))
            task = cursor.fetchone()
            if not task:
                raise ValueError("指定任务不存在！")

            fields = []
            params = []

            if data.title is not None:
                fields.append("title = ?")
                params.append(data.title.strip())

            if data.reference_url is not None:
                fields.append("reference_url = ?")
                params.append(data.reference_url.strip())

            if data.instructions is not None:
                fields.append("instructions = ?")
                params.append(data.instructions.strip())

            if data.assigned_to is not None:
                new_to = data.assigned_to.strip()
                cursor.execute("SELECT display_name FROM users WHERE username = ?;", (new_to,))
                u = cursor.fetchone()
                assigned_to_name = (u["display_name"] if u and u["display_name"] else new_to)
                fields.append("assigned_to = ?")
                params.append(new_to)
                fields.append("assigned_to_name = ?")
                params.append(assigned_to_name)

            if not fields:
                return dict(task)

            fields.append("updated_at = ?")
            params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            params.append(task_id)

            cursor.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?;", params)
            conn.commit()
            return TaskService.get_task_by_id(task_id)
        finally:
            conn.close()

    @staticmethod
    def delete_task(task_id: int) -> bool:
        """管理员删除任务"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM tasks WHERE id = ?;", (task_id,))
            affected = cursor.rowcount
            conn.commit()
            return affected > 0
        finally:
            conn.close()

    @staticmethod
    def get_product_options(task_id: Optional[int] = None, keyword: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取供任务关联选择的已录入商品列表下拉选项
        - 仅返回尚未被任何任务关联的商品 (tasks.product_id 未引用)
        - task_id 非空时，额外放行该任务当前已关联的商品 (便于重新登记)
        - keyword 非空时，按 Parent SKU / SKU / 标题模糊过滤
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            sql = """
            SELECT id, title, parent_sku, store_account, main_image, created_at
            FROM product_items
            WHERE is_parent = 1
              AND (id = ? OR id NOT IN (SELECT product_id FROM tasks WHERE product_id IS NOT NULL AND product_id > 0))
            """
            params: List[Any] = [task_id if task_id else 0]

            if keyword and keyword.strip():
                kw = f"%{keyword.strip()}%"
                sql += " AND (parent_sku LIKE ? OR sku LIKE ? OR title LIKE ?)"
                params.extend([kw, kw, kw])

            sql += " ORDER BY id DESC;"
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
