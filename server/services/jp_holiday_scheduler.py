"""
日本节假日调度器 — 后台心跳协程 (每60s):
1. 日历同步: 当年+次年数据缺失或今天未同步过 → 从 date.nager.at 拉取
2. 节日提醒: 开关开启 + advance_days 内有节日 + 今天未发 → 后台线程发邮件
具体逻辑见 JpHolidayService.sync_due / maybe_send_reminder。
"""
import asyncio

from server.services import jp_holiday_service


async def jp_holiday_scheduler():
    """调度心跳 (每60s): 日历同步 + 大节日邮件提醒"""
    while True:
        try:
            synced = await asyncio.to_thread(
                jp_holiday_service.JpHolidayService.sync_due)
            if synced and not synced.get("skipped"):
                print("🇯🇵 日本节假日日历已同步:", synced.get("years"))
        except Exception as e:
            print(f"⚠️ 日本节假日同步心跳异常: {e}")
        try:
            triggered = await asyncio.to_thread(
                jp_holiday_service.JpHolidayService.maybe_send_reminder)
            if triggered:
                print("🇯🇵 日本节日提醒邮件任务已触发")
        except Exception as e:
            print(f"⚠️ 日本节日提醒心跳异常: {e}")
        await asyncio.sleep(60)


def start_jp_holiday_scheduler() -> asyncio.Task:
    """启动调度心跳, 返回任务句柄 (服务关闭时由 lifespan cancel)"""
    return asyncio.create_task(jp_holiday_scheduler())
