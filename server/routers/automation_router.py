import threading
import time
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field
from server.services.erp_bridge import ERPBridgeService
from server.services.deepseek_service import DeepSeekService

router = APIRouter(prefix="/api/automation", tags=["店小秘自动化上件与 AI 辅助"])


class DeepSeekPromptSchema(BaseModel):
    prompt: str = Field(..., description="待发送至 DeepSeek 的提示词")
    target_url: Optional[str] = Field(None, description="指定 DeepSeek 会话链接")


# ──────────────────────────────────────────────────────────────
# 内存状态表：按 product_id 存储当前上件任务的运行状态与实时日志
# ──────────────────────────────────────────────────────────────
_publish_tasks: dict = {}   # {product_id: {"running": bool, "done": bool, "success": bool, "msg": str, "logs": [str], "seen": int}}
_task_lock = threading.Lock()


def _run_publish_in_thread(product_id: int):
    """在后台线程中执行真实上件，实时将日志写入内存状态表"""
    with _task_lock:
        _publish_tasks[product_id] = {
            "running": True, "done": False,
            "success": False, "msg": "",
            "logs": ["🚀 后台线程已启动，正在连接 CDP 浏览器..."],
            "seen": 0,
            "started_at": time.time()
        }

    def on_log(line: str):
        """erp_bridge 每产生一条日志，立即追加到任务状态供前端轮询"""
        with _task_lock:
            state = _publish_tasks.get(product_id)
            if state is not None:
                state["logs"].append(line)

    try:
        res = ERPBridgeService.publish_product_to_erp(product_id, log_callback=on_log)
        with _task_lock:
            state = _publish_tasks.get(product_id, {})
            state["running"] = False
            state["done"] = True
            state["success"] = res.get("success", False)
            state["msg"] = res.get("msg", "")
            # 兜底：若流式回调未生效（日志几乎为空），用后端完整日志替换
            if len(state.get("logs", [])) <= 1 and res.get("logs"):
                state["logs"] = ["🚀 后台线程已启动，正在连接 CDP 浏览器..."] + res["logs"]
            state["logs"].append(("✅" if res.get("success") else "❌") + f" 任务结束: {res.get('msg', '')}")
    except Exception as e:
        with _task_lock:
            state = _publish_tasks.get(product_id, {})
            state["running"] = False
            state["done"] = True
            state["success"] = False
            state["msg"] = str(e)
            state["logs"].append(f"❌ 上件异常: {e}")


@router.post("/publish/{product_id}", summary="触发商品全自动上件到店小秘 ERP（异步后台执行）")
def publish_product(product_id: int):
    """
    立即返回任务已受理，在后台线程执行真实自动化上件。
    前端通过 GET /api/automation/publish-status/{product_id} 轮询进度。
    """
    with _task_lock:
        existing = _publish_tasks.get(product_id)
        if existing and existing.get("running"):
            return {"code": 1, "msg": f"商品 #{product_id} 正在上件中，请稍候...", "data": {"status": "running"}}
        
        # 同步初始化任务状态，防止前端轮询瞬间读到上一次任务残留的 done=True 状态
        _publish_tasks[product_id] = {
            "running": True,
            "done": False,
            "success": False,
            "msg": "",
            "logs": ["🚀 后台线程已启动，正在连接 CDP 浏览器..."],
            "seen": 0,
            "started_at": time.time()
        }

    t = threading.Thread(target=_run_publish_in_thread, args=(product_id,), daemon=True)
    t.start()
    return {"code": 0, "msg": "上件任务已在后台启动，请轮询状态接口获取进度", "data": {"status": "started", "product_id": product_id}}


@router.get("/publish-status/{product_id}", summary="实时查询商品上件任务状态与增量日志")
def get_publish_status(product_id: int, since: int = 0):
    """
    返回当前上件任务状态与从第 since 行开始的新增日志（增量轮询）。
    - since=0 表示返回所有日志
    - since=N 表示只返回第 N 行之后的新日志行
    """
    with _task_lock:
        state = _publish_tasks.get(product_id)
    if not state:
        return {"code": 1, "msg": "未找到该商品的上件任务（可能尚未触发）", "data": None}

    all_logs = state.get("logs", [])
    new_logs = all_logs[since:]
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "product_id": product_id,
            "running": state.get("running", False),
            "done": state.get("done", False),
            "success": state.get("success", False),
            "result_msg": state.get("msg", ""),
            "total_log_lines": len(all_logs),
            "new_logs": new_logs,
        }
    }


@router.get("/publish-logs/{product_id}", summary="获取商品上件执行日志（数据库历史记录）")
def get_publish_logs(product_id: int):
    """查询指定商品的自动化上件历史与最新执行日志"""
    from server.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM publish_logs WHERE product_id = ? ORDER BY id DESC LIMIT 20", (product_id,))
        rows = cursor.fetchall()
        logs = [dict(r) for r in rows]
        return {"code": 0, "msg": "success", "data": logs}
    finally:
        conn.close()


@router.post("/deepseek-generate", summary="自动跳转 DeepSeek 填入提示词、提交、点击复制并回填")
def generate_deepseek_prompt(data: DeepSeekPromptSchema):
    """调起 Chrome 浏览器打开 DeepSeek 目标会话，自动填入提示词、点击发送并在完成后点击复制"""
    res = DeepSeekService.send_prompt_to_deepseek(prompt=data.prompt, target_url=data.target_url)
    return {"code": 0 if res.get("success") else 1, "msg": res.get("msg"), "data": res.get("data", {})}
