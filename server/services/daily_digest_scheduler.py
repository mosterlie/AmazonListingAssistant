"""
每日汇总邮件 - 独立调度器 (监控与邮件解耦后的邮件任务)
后台心跳协程, 每 60s 检查: 开关开启 + 今天未发 + 到达 digest_time (默认 08:15) → 触发发送。
触发判定与发送逻辑见 DailyDigestService.maybe_trigger_scheduled / send_digest。
"""
import asyncio

from server.services import daily_digest_service


async def daily_digest_scheduler():
    """调度心跳 (每60s): 到期且未发过则后台线程发送汇总邮件"""
    while True:
        try:
            triggered = await asyncio.to_thread(
                daily_digest_service.DailyDigestService.maybe_trigger_scheduled)
            if triggered:
                print("⏰ 每日汇总邮件任务已触发 (08:15)")
        except Exception as e:
            print(f"⚠️ 每日汇总邮件调度心跳异常: {e}")
        await asyncio.sleep(60)


def start_daily_digest_scheduler() -> asyncio.Task:
    """启动调度心跳, 返回任务句柄 (服务关闭时由 lifespan cancel)"""
    return asyncio.create_task(daily_digest_scheduler())
