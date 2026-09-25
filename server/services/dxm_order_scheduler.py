"""
店小秘订单剩余发货时间采集 - 独立调度器
后台心跳协程, 每 60s 检查是否到期 (每自然小时一次, 整点后首个心跳触发), 到期自动触发采集批次。
到期判定与触发逻辑见 DxmOrderService.maybe_trigger_scheduled。
"""
import asyncio

from server.services import dxm_order_service


async def dxm_order_scheduler():
    """调度心跳 (每60s): 到期且空闲则后台线程触发采集批次"""
    while True:
        try:
            triggered = await asyncio.to_thread(
                dxm_order_service.DxmOrderService.maybe_trigger_scheduled)
            if triggered:
                print("⏰ 店小秘订单定时采集批次已触发")
        except Exception as e:
            print(f"⚠️ 店小秘订单调度心跳异常: {e}")
        await asyncio.sleep(60)


def start_dxm_order_scheduler() -> asyncio.Task:
    """启动调度心跳, 返回任务句柄 (服务关闭时由 lifespan cancel)"""
    return asyncio.create_task(dxm_order_scheduler())
