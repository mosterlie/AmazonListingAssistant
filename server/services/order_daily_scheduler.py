"""
每日订单同步 - 独立调度器

后台心跳协程, 每 60s 检查是否到期 (默认每日 02:00, 可在 system_settings 改),
到期自动在后台线程执行: 妙手同步 → 初岛轨迹 → 佐川轨迹 → 履约同步 → 发货文档回补。
到期判定与执行逻辑见 OrderDailySyncService.maybe_trigger_scheduled / run。
"""
import asyncio

from server.services import order_daily_sync_service


async def order_daily_sync_scheduler():
    """调度心跳 (每60s): 到期且空闲则后台线程执行每日同步"""
    while True:
        try:
            triggered = await asyncio.to_thread(
                order_daily_sync_service.OrderDailySyncService.maybe_trigger_scheduled)
            if triggered:
                print("⏰ 每日订单同步任务已触发 (妙手同步 + 轨迹 + 佐川)")
        except Exception as e:
            print(f"⚠️ 每日订单同步调度心跳异常: {e}")
        await asyncio.sleep(60)


def start_order_daily_sync_scheduler() -> asyncio.Task:
    """启动调度心跳, 返回任务句柄 (服务关闭时由 lifespan cancel)"""
    return asyncio.create_task(order_daily_sync_scheduler())
