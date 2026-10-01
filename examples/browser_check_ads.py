# -*- coding: utf-8 -*-
"""浏览器冒烟: 打开广告分析页(注入登录态), 检查渲染与JS报错并截图"""
import asyncio, re, sys
sys.path.insert(0, '/Users/gx/Desktop/mypro/browser_toolkit')
from playwright.async_api import async_playwright


def read_token():
    for line in open('/tmp/ads_cookie.txt', encoding='utf-8'):
        if 'session_token' in line:
            return line.split()[-1]
    return ""


async def main():
    token = read_token()
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception as e:
            if "setDownloadBehavior" in str(e) or "context management" in str(e):
                from core.cdp_proxy import get_proxy
                browser = await p.chromium.connect_over_cdp(get_proxy("http://127.0.0.1:9222").ws_endpoint)
            else:
                raise
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        errors, logs = [], []
        page.on("console", lambda m: (errors if m.type == "error" else logs).append(m.text[:200]))
        page.on("pageerror", lambda e: errors.append(f"PAGEERROR: {str(e)[:200]}"))
        # 注入登录态 (CDP 代理模式下 add_cookies 不可用, 走 document.cookie)
        await page.goto("http://127.0.0.1:8000/login", wait_until="domcontentloaded")
        await page.evaluate(f"() => {{ document.cookie = 'session_token={token}; path=/'; }}")
        await page.goto("http://127.0.0.1:8000/ads-analysis", wait_until="networkidle")
        await asyncio.sleep(2.5)
        if "/login" in page.url:
            print("!! 未登录, 跳过渲染检查")
            await page.close()
            return

        active_tab = await page.evaluate("() => (document.querySelector('#adsSubnav .ads-subnav-item.active')||{}).dataset?.tab")
        res_rows = await page.evaluate("() => document.querySelectorAll('#resBody tr').length")
        badge = await page.inner_text("#resCountBadge")
        pager = await page.inner_text("#resPager")
        pname = await page.evaluate("() => document.querySelector('#resHead th:nth-child(3)')?.innerText || ''")
        print(f"激活页签: {active_tab} | 研判行数: {res_rows} | 徽标: {badge.strip()}")
        print(f"分页: {' '.join(pager.split())[:60]}")
        print(f"第3列表头: {pname!r}")
        await page.screenshot(path="/Users/gx/Desktop/mypro/browser_toolkit/examples/ads_研究页.png")

        # 切到在线产品-子
        await page.click('#adsSubnav .ads-subnav-item[data-tab="products"]')
        await asyncio.sleep(2)
        prod_rows = await page.evaluate("() => document.querySelectorAll('#prodBody tr').length")
        print(f"产品-子 行数: {prod_rows} | 徽标: {(await page.inner_text('#prodCountBadge')).strip()}")

        # 切到在线产品-父
        await page.click('#adsSubnav .ads-subnav-item[data-tab="parents"]')
        await asyncio.sleep(2)
        par_rows = await page.evaluate("() => document.querySelectorAll('#parBody tr').length")
        print(f"产品-父 行数: {par_rows} | 最新日期标注: {(await page.inner_text('#parLatestDate')).strip()}")

        # 统计结果弹窗
        await page.click('#adsSubnav .ads-subnav-item[data-tab="research"]')
        await asyncio.sleep(1.2)
        await page.click("#resStatBtn")
        await asyncio.sleep(2.5)
        stat_open = await page.evaluate("() => document.getElementById('statModal').classList.contains('open')")
        blocks = await page.evaluate("() => document.querySelectorAll('#statBody .ads-stat-block').length")
        asins = await page.evaluate("() => document.querySelectorAll('#statBody .ads-stat-asin').length")
        print(f"统计弹窗: open={stat_open} 区块={blocks} ASIN块={asins}")
        await page.screenshot(path="/Users/gx/Desktop/mypro/browser_toolkit/examples/ads_统计弹窗.png")

        print(f"控制台报错: {errors[:5] or '无'}")
        await page.close()
        print("浏览器冒烟完成")

asyncio.run(main())
