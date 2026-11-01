"""订单管理页 + 用户管理并入系统管理 的 UI 验证 (headless Chromium)"""
import asyncio
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8000"


async def login(page):
    await page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    await page.fill("#usernameInput", "admin")
    await page.fill("#passwordInput", "admin")
    await page.click("#loginSubmitBtn")
    await page.wait_for_url(lambda u: "/login" not in u, timeout=15000)


async def main():
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1500, "height": 950})
        page = await ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        await login(page)

        # ── 订单管理 ──
        await page.goto(f"{BASE}/orders", wait_until="networkidle")
        await page.wait_for_selector("#orderTableBody tr", timeout=15000)
        await page.wait_for_timeout(600)
        row_count = await page.locator("#orderTableBody tr").count()
        badge = await page.inner_text("#orderTotalBadge")
        chips = await page.locator("#orderStatBar span").count()
        print(f"[订单列表] 行数={row_count} 徽章={badge} 状态统计chip={chips}")
        await page.screenshot(path="examples/orders_list.png")

        # 详情弹窗
        await page.locator("#orderTableBody button:has-text('详情')").first.click()
        await page.wait_for_selector("#orderDetailModal", state="visible", timeout=10000)
        await page.wait_for_timeout(700)
        detail_text = await page.inner_text("#orderDetailBody")
        has_items = "商品明细" in detail_text
        print(f"[订单详情] 打开成功 含商品明细={has_items} 文本长度={len(detail_text)}")
        await page.screenshot(path="examples/orders_detail.png")
        await page.click("#orderDetailModal .custom-modal-footer button")
        await page.wait_for_timeout(300)

        # 同步弹窗
        await page.click("#orderSyncBtn")
        await page.wait_for_selector("#orderSyncModal", state="visible")
        checks = await page.locator("#syncStatusChecks input:checked").count()
        print(f"[同步弹窗] 状态勾选项={checks}")
        await page.screenshot(path="examples/orders_sync_modal.png")
        await page.click("#orderSyncModal .custom-modal-footer .btn-outline")

        # 分页
        pager = await page.inner_text("#orderPageInfo")
        print(f"[分页] {pager}")

        # ── 系统管理 → 用户管理 tab ──
        await page.goto(f"{BASE}/settings", wait_until="networkidle")
        nav_users = await page.locator('.settings-nav-item[data-tab="users"]').count()
        await page.click('.settings-nav-item[data-tab="users"]')
        await page.wait_for_timeout(900)
        panel_visible = await page.is_visible('.settings-panel[data-panel="users"] .users-panel')
        user_rows = await page.locator("#userTableBody tr").count()
        badge_text = await page.inner_text("#userTotalCountBadge")
        print(f"[系统管理] 用户管理tab={nav_users} 面板可见={panel_visible} 用户行={user_rows} 徽章={badge_text}")
        await page.screenshot(path="examples/settings_users_tab.png")

        # 全局导航不再出现「用户管理」
        nav_text = await page.inner_text(".nav-links")
        print("[顶部导航]", " ".join(nav_text.split()))
        print("[导航含用户管理]", "用户管理" in nav_text)

        # /users 独立页仍可用且高亮系统管理
        await page.goto(f"{BASE}/users", wait_until="networkidle")
        active = await page.inner_text(".nav-item.active")
        print(f"[独立用户页] 高亮菜单={active.strip()}")

        await browser.close()

    print("\nJS 错误:", errors or "无")


if __name__ == "__main__":
    asyncio.run(main())
