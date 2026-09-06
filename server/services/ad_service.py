"""
广告投放任务业务逻辑服务层 (AdTaskService)

职责:
  1. 广告任务 CRUD 与参数校验 (对应赛狐 SP 批量创建广告录入页字段)
  2. 「自动投放」执行调度: 前置校验 → 后台线程驱动赛狐算子 → 登记执行结果
"""
import asyncio
import json
import sys
import threading
import time
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from server.database import get_db_connection, get_setting
from server.models.ad_schemas import (
    ASIN_PATTERN, ASIN_MAX_COUNT, CREATE_MODES, BID_STRATEGIES,
    AdTaskCreateSchema, AdTaskUpdateSchema, parse_asins,
)

# ──────────────────────────────────────────────────────────────
# 内存运行状态表: {task_id: {"running","run_id","logs","done","success","msg","started_at"}}
# 用于前端增量轮询实时日志
# ──────────────────────────────────────────────────────────────
_run_states: Dict[int, Dict[str, Any]] = {}
_state_lock = threading.Lock()

# 当前阶段固定不提交 (执行到提交前停下, 供人工检查)
SUBMIT_ENABLED = False

CDP_URL = "http://127.0.0.1:9222"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _safe_json_loads(text: str, default):
    try:
        return json.loads(text) if text else default
    except Exception:
        return default


def _num_str(value: Any) -> str:
    """数值转字符串并去掉无意义小数: 300.0 → '300', 15.5 → '15.5'
    (赛狐输入框回填后页面会规范化文本, 多带 '.0' 会导致值校验失败)"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(f)) if f == int(f) else str(f)


class AdTaskService:
    """广告投放任务核心业务"""

    # ================= 校验 =================

    @staticmethod
    def validate_payload(payload: Dict[str, Any]) -> List[str]:
        """
        统一入参校验 (新增/编辑/执行前三处复用)。
        :param payload: 归一化后的字段字典
        :return: 错误信息列表, 空列表表示校验通过
        """
        errors: List[str] = []

        task_name = (payload.get("task_name") or "").strip()
        if not task_name:
            errors.append("任务名称不能为空")

        shop_name = (payload.get("shop_name") or "").strip()
        if not shop_name:
            errors.append("店铺名称不能为空")

        create_mode = (payload.get("create_mode") or "").strip()
        if create_mode not in CREATE_MODES:
            errors.append(f"创建方式仅支持: {' / '.join(CREATE_MODES)}")

        bid_strategy = (payload.get("bid_strategy") or "").strip()
        if bid_strategy not in BID_STRATEGIES:
            errors.append(f"竞价策略仅支持: {' / '.join(BID_STRATEGIES)}")

        # 每日预算 / 默认竞价
        try:
            budget = float(payload.get("daily_budget"))
            if budget <= 0:
                errors.append("每日预算必须大于 0")
        except (TypeError, ValueError):
            errors.append("每日预算必须为数字")

        try:
            bid = float(payload.get("default_bid"))
            if bid <= 0:
                errors.append("默认竞价必须大于 0")
        except (TypeError, ValueError):
            errors.append("默认竞价必须为数字")

        # 起止时间
        start_date = (payload.get("start_date") or "").strip()
        end_date = (payload.get("end_date") or "").strip()
        if not start_date:
            errors.append("开始时间不能为空")
        else:
            try:
                datetime.strptime(start_date, "%Y-%m-%d")
            except Exception:
                errors.append("开始时间格式非法，需为 YYYY-MM-DD")
        if end_date:
            try:
                d_end = datetime.strptime(end_date, "%Y-%m-%d")
                if start_date:
                    try:
                        d_start = datetime.strptime(start_date, "%Y-%m-%d")
                        if d_end < d_start:
                            errors.append("结束时间不能早于开始时间")
                    except Exception:
                        pass
            except Exception:
                errors.append("结束时间格式非法，需为 YYYY-MM-DD")

        # ASIN 列表
        asins: List[str] = payload.get("asins") or []
        if not asins:
            errors.append("ASIN 列表不能为空，请至少输入 1 个 ASIN")
        else:
            if len(asins) > ASIN_MAX_COUNT:
                errors.append(f"ASIN 数量超过上限 {ASIN_MAX_COUNT}，当前 {len(asins)} 个")
            bad = [a for a in asins if not ASIN_PATTERN.match(a)]
            if bad:
                sample = "、".join(bad[:5]) + ("..." if len(bad) > 5 else "")
                errors.append(f"存在 {len(bad)} 个非法 ASIN (需为 10 位字母/数字): {sample}")

        # 批次数量 (语义: 每批最多处理的 ASIN 数; 超过 ASIN 总数时等价于单批完成, 不拦截)
        try:
            batch_size = int(payload.get("batch_size") or 0)
        except (TypeError, ValueError):
            batch_size = 0
            errors.append("批次数量必须为整数")
        if batch_size < 0:
            errors.append("批次数量不能为负数")

        return errors

    @staticmethod
    def validate_for_run(task: Dict[str, Any]) -> List[str]:
        """执行「自动投放」前的运行时校验 (在入参校验基础上追加环境与状态校验)"""
        errors = AdTaskService.validate_payload({
            "task_name": task.get("task_name"),
            "shop_name": task.get("shop_name"),
            "create_mode": task.get("create_mode"),
            "bid_strategy": task.get("bid_strategy"),
            "daily_budget": task.get("daily_budget"),
            "default_bid": task.get("default_bid"),
            "start_date": task.get("start_date"),
            "end_date": task.get("end_date"),
            "asins": _safe_json_loads(task.get("asins_json", "[]"), []),
            "batch_size": task.get("batch_size"),
        })
        if errors:
            return errors

        # 店铺必须在系统配置的店铺列表中 (防止手输错字导致选错店铺)
        stores = get_setting("store_accounts", []) or []
        shop_names = [str(s.get("store_name", "")).strip() for s in stores if isinstance(s, dict)]
        if shop_names and task.get("shop_name") not in shop_names:
            errors.append(
                f"店铺「{task.get('shop_name')}」不在系统店铺列表中 "
                f"({'、'.join(shop_names)})，请到「系统管理」维护或修正任务店铺"
            )

        # CDP 调试浏览器必须可用 (赛狐算子通过 CDP 驱动页面)
        if not AdTaskService.check_cdp_available():
            errors.append(
                f"未检测到 CDP 调试浏览器 ({CDP_URL})，请先启动调试浏览器并登录赛狐 ERP"
            )

        return errors

    @staticmethod
    def check_cdp_available(timeout: float = 3.0) -> bool:
        """检测 9222 调试端口是否可用"""
        try:
            with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ================= 查询 =================

    @staticmethod
    def list_tasks(status: Optional[str] = None, search: Optional[str] = None,
                   shop_name: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            where, params = [], []
            if status and status.strip() and status.strip() != "all":
                where.append("status = ?")
                params.append(status.strip())
            if shop_name and shop_name.strip():
                where.append("shop_name = ?")
                params.append(shop_name.strip())
            if search and search.strip():
                s = f"%{search.strip()}%"
                where.append("(task_name LIKE ? OR shop_name LIKE ? OR asins_json LIKE ?)")
                params.extend([s, s, s])
            sql = f"SELECT * FROM ad_campaign_tasks {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY id DESC"
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [AdTaskService._decorate(dict(r)) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_task(task_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM ad_campaign_tasks WHERE id = ?;", (task_id,))
            row = cursor.fetchone()
            return AdTaskService._decorate(dict(row)) if row else None
        finally:
            conn.close()

    @staticmethod
    def _decorate(task: Dict[str, Any]) -> Dict[str, Any]:
        """补充派生字段: ASIN 列表/数量预览, 便于前端直接渲染"""
        asins = _safe_json_loads(task.get("asins_json", "[]"), [])
        task["asins"] = asins
        task["asin_count"] = len(asins)
        # 内存状态优先: 页面刷新后也能反映真实运行情况
        with _state_lock:
            st = _run_states.get(task.get("id"))
        task["running"] = bool(st and st.get("running"))
        return task

    @staticmethod
    def list_runs(task_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM ad_task_runs WHERE task_id = ? ORDER BY id DESC LIMIT ?;",
                (task_id, limit))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_run(run_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM ad_task_runs WHERE id = ?;", (run_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ================= 写入 =================

    @staticmethod
    def create_task(data: AdTaskCreateSchema, current_user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        asins = parse_asins(data.asins_text, dedup=bool(data.auto_dedup))
        errors = AdTaskService.validate_payload({
            "task_name": data.task_name,
            "shop_name": data.shop_name,
            "create_mode": data.create_mode,
            "bid_strategy": data.bid_strategy,
            "daily_budget": data.daily_budget,
            "default_bid": data.default_bid,
            "start_date": data.start_date,
            "end_date": data.end_date,
            "asins": asins,
            "batch_size": data.batch_size,
        })
        if errors:
            raise ValueError(errors[0])

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            now = _now_str()
            cursor.execute("""
            INSERT INTO ad_campaign_tasks (
                task_name, shop_name, create_mode, start_date, end_date,
                daily_budget, bid_strategy, default_bid,
                asins_json, asin_count, batch_size, auto_dedup,
                status, last_result, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', ?, ?, ?)
            """, (
                data.task_name.strip(), data.shop_name.strip(), data.create_mode,
                data.start_date, (data.end_date or "").strip(),
                data.daily_budget, data.bid_strategy, data.default_bid,
                json.dumps(asins, ensure_ascii=False), len(asins),
                int(data.batch_size or 0), 1 if data.auto_dedup else 0,
                (current_user or {}).get("username", ""), now, now,
            ))
            task_id = cursor.lastrowid
            conn.commit()
            return AdTaskService.get_task(task_id)
        finally:
            conn.close()

    @staticmethod
    def update_task(task_id: int, data: AdTaskUpdateSchema) -> Dict[str, Any]:
        task = AdTaskService.get_task(task_id)
        if not task:
            raise ValueError("指定广告任务不存在！")

        def _pick(new_val, old_val):
            return old_val if new_val is None else new_val

        auto_dedup = _pick(data.auto_dedup, bool(task.get("auto_dedup")))
        if data.asins_text is not None:
            asins = parse_asins(data.asins_text, dedup=bool(auto_dedup))
        else:
            asins = _safe_json_loads(task.get("asins_json", "[]"), [])
            # 未重新粘贴 ASIN 但开启了去重: 对存量列表补一次去重
            if auto_dedup:
                seen = set()
                asins = [a for a in asins if not (a in seen or seen.add(a))]
        payload = {
            "task_name": _pick(data.task_name, task.get("task_name")),
            "shop_name": _pick(data.shop_name, task.get("shop_name")),
            "create_mode": _pick(data.create_mode, task.get("create_mode")),
            "bid_strategy": _pick(data.bid_strategy, task.get("bid_strategy")),
            "daily_budget": _pick(data.daily_budget, task.get("daily_budget")),
            "default_bid": _pick(data.default_bid, task.get("default_bid")),
            "start_date": _pick(data.start_date, task.get("start_date")),
            "end_date": _pick(data.end_date, task.get("end_date")),
            "asins": asins,
            "batch_size": _pick(data.batch_size, task.get("batch_size")),
        }
        errors = AdTaskService.validate_payload(payload)
        if errors:
            raise ValueError(errors[0])

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
            UPDATE ad_campaign_tasks SET
                task_name = ?, shop_name = ?, create_mode = ?,
                start_date = ?, end_date = ?, daily_budget = ?,
                bid_strategy = ?, default_bid = ?, asins_json = ?,
                asin_count = ?, batch_size = ?, auto_dedup = ?, updated_at = ?
            WHERE id = ?;
            """, (
                payload["task_name"].strip(), payload["shop_name"].strip(), payload["create_mode"],
                payload["start_date"], payload["end_date"] or "", float(payload["daily_budget"]),
                payload["bid_strategy"], float(payload["default_bid"]),
                json.dumps(asins, ensure_ascii=False), len(asins),
                int(payload["batch_size"] or 0), 1 if auto_dedup else 0,
                _now_str(), task_id,
            ))
            conn.commit()
            return AdTaskService.get_task(task_id)
        finally:
            conn.close()

    @staticmethod
    def delete_task(task_id: int) -> bool:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM ad_task_runs WHERE task_id = ?;", (task_id,))
            cursor.execute("DELETE FROM ad_campaign_tasks WHERE id = ?;", (task_id,))
            affected = cursor.rowcount
            conn.commit()
            return affected > 0
        finally:
            conn.close()

    @staticmethod
    def get_options() -> Dict[str, Any]:
        """前端下拉选项: 店铺列表 / 创建方式 / 竞价策略 / 今日日期 / 自动任务名"""
        stores = get_setting("store_accounts", []) or []
        shop_names = [str(s.get("store_name", "")).strip()
                      for s in stores if isinstance(s, dict) and s.get("store_name")]
        # 自动任务名: task + 2位年份 + 4位日期 + "-" + 今日第n个任务
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) AS c FROM ad_campaign_tasks "
                "WHERE date(created_at) = date('now', 'localtime');")
            n = (cursor.fetchone()["c"] or 0) + 1
        finally:
            conn.close()
        now = datetime.now()
        auto_task_name = f"task{now.strftime('%y%m%d')}-{n}"
        return {
            "shop_names": shop_names,
            "create_modes": CREATE_MODES,
            "bid_strategies": BID_STRATEGIES,
            "today": _today_str(),
            "next_task_name": auto_task_name,
            "submit_enabled": SUBMIT_ENABLED,
        }

    # ================= 自动投放 =================

    @staticmethod
    def start_run(task_id: int, operator: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        触发「自动投放」: 校验 → 建执行记录 → 后台线程驱动赛狐算子 → 登记结果。
        立即返回, 前端通过 GET /api/ads/tasks/{id}/run-status 轮询。
        """
        task = AdTaskService.get_task(task_id)
        if not task:
            raise ValueError("指定广告任务不存在！")

        errors = AdTaskService.validate_for_run(task)
        if errors:
            raise ValueError(errors[0])

        with _state_lock:
            st = _run_states.get(task_id)
            if st and st.get("running"):
                raise RuntimeError("该任务正在执行中，请等待执行结束后再试")
            # 全局单任务锁: 所有自动化共用同一个 CDP 浏览器与赛狐页面,
            # 并行执行会互相抢占标签页/向导状态导致数据错乱, 必须串行
            for other_id, other_st in _run_states.items():
                if other_id != task_id and other_st.get("running"):
                    raise RuntimeError(
                        f"另一个任务 #{other_id} 正在执行中，同一浏览器同一时间只能运行一个自动投放任务，"
                        "请等待其结束后再试（或先在列表页终止该任务）"
                    )

        asins = _safe_json_loads(task.get("asins_json", "[]"), [])
        batch_size = int(task.get("batch_size") or 0) or None
        operator_name = (operator or {}).get("username", "")

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            now = _now_str()
            cursor.execute("""
            INSERT INTO ad_task_runs (
                task_id, task_name, status, submitted, batch_count,
                total_asins, operator, started_at
            ) VALUES (?, ?, 'running', ?, ?, ?, ?, ?)
            """, (task_id, task.get("task_name", ""), 0 if not SUBMIT_ENABLED else 1,
                  0, len(asins), operator_name, now))
            run_id = cursor.lastrowid
            cursor.execute("""
            UPDATE ad_campaign_tasks SET status = 'running', last_run_id = ?,
                last_result = '执行中...', last_run_at = ?, updated_at = ? WHERE id = ?;
            """, (run_id, now, now, task_id))
            conn.commit()
        finally:
            conn.close()

        with _state_lock:
            _run_states[task_id] = {
                "running": True, "done": False, "success": False,
                "run_id": run_id, "msg": "", "logs": [], "seen": 0,
                "started_at": time.time(),
            }

        t = threading.Thread(
            target=AdTaskService._run_worker,
            args=(task_id, run_id, task, asins, batch_size, operator_name),
            daemon=True,
        )
        t.start()
        return {"task_id": task_id, "run_id": run_id, "status": "started", "total_asins": len(asins)}

    @staticmethod
    def _run_worker(task_id: int, run_id: int, task: Dict[str, Any],
                    asins: List[str], batch_size: Optional[int], operator_name: str):
        """后台线程入口: 驱动 asyncio 算子并登记结果"""

        def on_log(line: str):
            with _state_lock:
                st = _run_states.get(task_id)
                if st is not None:
                    st["logs"].append(str(line))

        started = time.time()
        result: Optional[Dict[str, Any]] = None
        error_msg = ""
        try:
            result = asyncio.run(AdTaskService._execute(
                task_id=task_id, task=task, asins=asins, batch_size=batch_size, on_log=on_log))
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            on_log(f"❌ 自动投放异常: {error_msg}")

        duration_ms = int((time.time() - started) * 1000)
        status, result_msg = AdTaskService._summarize(result, error_msg, task)
        AdTaskService._finish_run(task_id, run_id, result, status, result_msg, duration_ms)
        with _state_lock:
            st = _run_states.setdefault(task_id, {})
            st.update({
                "running": False, "done": True,
                "success": status == "success", "msg": result_msg, "run_id": run_id,
            })

    @staticmethod
    async def _execute(task_id: int, task: Dict[str, Any], asins: List[str],
                       batch_size: Optional[int], on_log) -> Dict[str, Any]:
        """创建算子 → 连接浏览器 → 跑批 → 关闭驱动"""
        root = str(_project_root())
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.sellfox_ad_operator import SellfoxAdOperator

        op = SellfoxAdOperator(on_log=on_log)
        # 注册到运行状态表, 供终止接口定位算子实例
        with _state_lock:
            st = _run_states.get(task_id)
            if st is not None:
                st["op"] = op
        try:
            await op.connect(visit=True, login_timeout=90)
            on_log(f"▶ 开始投放: 店铺={task.get('shop_name')} / "
                   f"创建方式={task.get('create_mode')} / ASIN {len(asins)} 个")
            return await op.run_batch(
                asins=asins,
                batch_size=batch_size,
                submit=SUBMIT_ENABLED,
                shop=task.get("shop_name", ""),
                budget=_num_str(task.get("daily_budget", 300)),
                bid=_num_str(task.get("default_bid", 15)),
                bid_strategy=task.get("bid_strategy", "动态竞价-只降低"),
                create_mode=task.get("create_mode", "所有产品合并创建广告"),
                start_date=(task.get("start_date") or "").strip() or None,
                end_date=(task.get("end_date") or "").strip() or None,
            )
        finally:
            await op.close()

    @staticmethod
    def request_stop(task_id: int) -> bool:
        """
        请求终止正在执行的任务。
        置内存 stop 标志并通知算子; 算子在长轮询循环与关键步骤间检查该标志,
        当前 ASIN 录入环节结束后即停止 (已录入数据保持现状)。
        :return: True=受理; False=任务未在执行
        """
        with _state_lock:
            st = _run_states.get(task_id)
            if not st or not st.get("running"):
                return False
            st["stop_requested"] = True
            op = st.get("op")
        if op is not None:
            op.request_stop()
        return True

    @staticmethod
    def _summarize(result: Optional[Dict[str, Any]], error_msg: str,
                   task: Dict[str, Any]) -> Tuple[str, str]:
        """根据执行结果判定状态并生成人类可读的结果摘要"""
        if error_msg:
            return "failed", f"执行异常: {error_msg}"
        if not result:
            return "failed", "未获得执行结果"

        total = result.get("total_asins", 0)
        entered = result.get("entered_count", 0)
        skipped = result.get("skipped_count", 0)
        audit = result.get("audit") or {}
        tail = ("已提交" if result.get("submitted")
                else f"未提交({result.get('batch_count', 0)} 批均已停在提交前, 待人工逐个标签页确认)")

        msg = (f"共 {total} 个 ASIN，成功录入 {entered} 条，跳过 {skipped} 条；"
               f"终态对账: 页面已配置 {audit.get('configured', 0)} 条"
               f"(期望 {audit.get('expected', 0)} 条)"
               f"{'一致' if audit.get('match') else ' 不一致，请人工核对'}；{tail}")

        if result.get("aborted"):
            stage = result.get("fail_stage") or ""
            if "终止" in stage:
                if entered > 0:
                    return "partial", f"用户终止: {msg}"
                return "failed", f"用户终止: {msg}"
            if entered > 0:
                return "partial", f"中途中断({stage}): {msg}"
            return "failed", f"中断于 {stage}: {msg}"
        if result.get("success"):
            return "success", msg
        if entered > 0:
            return "partial", msg
        return "failed", msg or "未录入任何 ASIN"

    @staticmethod
    def _finish_run(task_id: int, run_id: int, result: Optional[Dict[str, Any]],
                    status: str, result_msg: str, duration_ms: int):
        """登记执行结果: 写 ad_task_runs 并回写任务最新状态"""
        logs = []
        skips = []
        audit = {}
        if result:
            logs = result.get("logs") or []
            skips = result.get("skips") or []
            audit = result.get("audit") or {}

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            now = _now_str()
            cursor.execute("""
            UPDATE ad_task_runs SET
                status = ?, submitted = ?, batch_count = ?, total_asins = ?,
                entered_count = ?, skipped_count = ?, skip_detail_json = ?,
                verify_json = ?, result_msg = ?, log_text = ?,
                finished_at = ?, duration_ms = ?
            WHERE id = ?;
            """, (
                status, 1 if result and result.get("submitted") else 0,
                (result or {}).get("batch_count", 0),
                (result or {}).get("total_asins", 0),
                (result or {}).get("entered_count", 0),
                len(skips),
                json.dumps(skips, ensure_ascii=False),
                json.dumps(audit, ensure_ascii=False),
                result_msg,
                "\n".join(logs[-2000:]),
                now, duration_ms, run_id,
            ))
            cursor.execute("""
            UPDATE ad_campaign_tasks SET status = ?, last_run_id = ?,
                last_result = ?, last_run_at = ?, updated_at = ? WHERE id = ?;
            """, (status, run_id, result_msg[:500], now, now, task_id))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_run_status(task_id: int, since: int = 0) -> Dict[str, Any]:
        """增量轮询执行状态与日志"""
        with _state_lock:
            st = _run_states.get(task_id)
        if not st:
            return {"found": False, "running": False, "done": False,
                    "success": False, "msg": "", "total_log_lines": 0, "new_logs": [], "run_id": 0}

        logs = st.get("logs", [])
        return {
            "found": True,
            "run_id": st.get("run_id", 0),
            "running": bool(st.get("running")),
            "done": bool(st.get("done")),
            "success": bool(st.get("success")),
            "msg": st.get("msg", ""),
            "total_log_lines": len(logs),
            "new_logs": logs[since:],
            "elapsed_sec": round(time.time() - st.get("started_at", time.time()), 1),
        }


def _project_root() -> str:
    """返回项目根目录 (使 core 包可导入)"""
    import os
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
