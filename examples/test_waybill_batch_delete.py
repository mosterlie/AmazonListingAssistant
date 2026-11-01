"""运单管理 - 批量选择/批量删除 UI 端到端验证

流程: 插入两条临时运单 -> 登录 -> 勾选单行(验证批量条出现) -> 全选 -> 取消 ->
      仅勾选临时行 -> 批量删除(含确认弹窗) -> 校验列表与数据库均已删除 -> 截图
"""
import asyncio
from datetime import datetime

from playwright.async_api import async_playwright

from server.database import get_db_connection

BASE = "http://127.0.0.1:8000"
TAG = "UITEST"


def insert_temp_rows():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    ids = []
    try:
        for suffix in ("A", "B"):
            cur = conn.execute(
                "INSERT INTO forwarder_waybills (tracking_number, source, created_by, created_at, updated_at) "
                "VALUES (?, 'paste', 'uitest', ?, ?)", (f"{TAG}-{suffix}", now, now))
            ids.append(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return ids


def count_rows(ids):
    conn = get_db_connection()
    try:
        marks = ",".join("?" * len(ids))
        return conn.execute(
            f"SELECT COUNT(*) FROM forwarder_waybills WHERE id IN ({marks})", ids).fetchone()[0]
    finally:
        conn.close()


async def main():
    ids = insert_temp_rows()
    print("临时运单 id:", ids)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        await page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        await page.fill("#usernameInput", "admin")
        await page.fill("#passwordInput", "admin")
        await page.click("#loginSubmitBtn")
        await page.wait_for_url(lambda u: "/login" not in u, timeout=15000)

        await page.goto(f"{BASE}/forwarder-integration", wait_until="networkidle")
        await page.wait_for_selector("#wbTableBody .wb-row-check", timeout=15000)
        total = await page.locator("#wbTableBody .wb-row-check").count()
        print(f"表格行数: {total}")

        # 1) 勾选单行 -> 批量条出现
        await page.locator("#wbTableBody .wb-row-check").first.check()
        bar_visible = await page.is_visible("#wbBatchBar")
        info = await page.inner_text("#wbSelInfo")
        print(f"[单行勾选] 批量条可见={bar_visible} 文案={info}")
        await page.screenshot(path="examples/waybill_batch_bar.png")

        # 2) 全选
        await page.check("#wbCheckAll")
        all_info = await page.inner_text("#wbSelInfo")
        all_checked = await page.locator("#wbTableBody .wb-row-check:checked").count()
        print(f"[全选] 文案={all_info} 已勾选行={all_checked}")

        # 3) 取消全选
        await page.uncheck("#wbCheckAll")
        cleared = await page.locator("#wbTableBody .wb-row-check:checked").count()
        bar_after = await page.is_visible("#wbBatchBar")
        print(f"[取消全选] 已勾选行={cleared} 批量条可见={bar_after}")

        # 4) 仅勾选临时行 -> 批量删除
        for rid in ids:
            await page.check(f'#wbTableBody .wb-row-check[data-id="{rid}"]')
        print(f"[勾选临时行] 文案={await page.inner_text('#wbSelInfo')}")
        await page.screenshot(path="examples/waybill_batch_selected.png")

        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await page.click("#wbBatchDeleteBtn")
        await page.wait_for_timeout(1500)
        toast = await page.evaluate("() => (document.querySelector('.toast-msg') || {}).innerText || ''")

        left_in_table = await page.locator(
            f'#wbTableBody .wb-row-check[data-id="{ids[0]}"], #wbTableBody .wb-row-check[data-id="{ids[1]}"]').count()
        db_left = count_rows(ids)
        print(f"[批量删除] 提示={toast.strip()!r} 表格残留={left_in_table} 数据库残留={db_left}")
        await page.screenshot(path="examples/waybill_batch_deleted.png")

        await browser.close()

    ok = left_in_table == 0 and db_left == 0 and bar_visible and all_checked == total and cleared == 0
    print("\n结果:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
