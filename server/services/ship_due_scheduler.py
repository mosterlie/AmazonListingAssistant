"""即将发货提醒 - 独立调度器

后台心跳协程, 每 60s 检查一次; 每个自然小时触发一次剩余发货时间检查。
到期判定与发送逻辑见 ShipDueService.maybe_trigger_scheduled / run_once。
"""
import asyncio

from server.services import ship_due_service


async def ship_due_scheduler():
    while True:
        try:
            triggered = await asyncio.to_thread(
                ship_due_service.ShipDueService.maybe_trigger_scheduled)
            if triggered:
                print("⏰ 即将发货提醒检查已触发")
        except Exception as e:
            print(f"⚠️ 即将发货提醒调度心跳异常: {e}")
        await asyncio.sleep(60)


def start_ship_due_scheduler() -> asyncio.Task:
    return asyncio.create_task(ship_due_scheduler())
