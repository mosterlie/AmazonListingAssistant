"""
货代在线登记文档定时采集 - 独立调度器
从 app.py lifespan 迁出: 后台心跳协程, 每 60s 检查是否到期, 到期自动触发采集批次。
到期判定与触发逻辑见 ForwarderDocService.maybe_trigger_scheduled (daily/interval 两种模式,
配置存于系统设置 doc_sync, UI 在 系统管理 → 货代在线登记文档定时采集)。
"""
import asyncio

from server.services import forwarder_doc_service


async def forwarder_doc_scheduler():
    """调度心跳 (每60s): 到期且空闲则后台线程触发采集批次"""
    while True:
        try:
            triggered = await asyncio.to_thread(
                forwarder_doc_service.ForwarderDocService.maybe_trigger_scheduled)
            if triggered:
                print("⏰ 货代文档定时采集批次已触发")
        except Exception as e:
            print(f"⚠️ 货代文档调度心跳异常: {e}")
        await asyncio.sleep(60)


def start_forwarder_doc_scheduler() -> asyncio.Task:
    """启动调度心跳, 返回任务句柄 (服务关闭时由 lifespan cancel)"""
    return asyncio.create_task(forwarder_doc_scheduler())
