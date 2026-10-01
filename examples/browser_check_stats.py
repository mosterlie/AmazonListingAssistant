# -*- coding: utf-8 -*-
"""统计结果弹窗新功能 E2E: 批量复制/清除重复项/恢复/计划参数/自定义分组"""
import asyncio, sys
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
        errs = []
        page.on("console", lambda m: errs.append(m.text[:160]) if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append(f"PAGEERROR {str(e)[:160]}"))
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))   # confirm 自动确认

        await page.goto("http://127.0.0.1:8000/login", wait_until="domcontentloaded")
        await page.evaluate(f"() => {{ document.cookie = 'session_token={token}; path=/'; }}")
        await page.goto("http://127.0.0.1:8000/ads-analysis", wait_until="networkidle")
        await asyncio.sleep(2)
        await page.click("#resStatBtn")
        await asyncio.sleep(2.5)

        def q(expr): return page.evaluate(expr)

        print("[1] 重复项区域")
        print("   批量复制按钮:", await q("() => !!document.querySelector('.ads-dup-tip .ads-stat-copy[data-copy]')"))
        print("   可点击复制的重复ASIN数:", await q("() => document.querySelectorAll('.ads-dup-tip .ads-asin.ads-copy[data-copy]').length"))
        print("   各组合 清除重复项 按钮数:", await q("() => document.querySelectorAll('[data-act=\"exclude\"]').length"))

        print("[2] 未投广区域")
        print("   明细表行数:", await q("() => document.querySelectorAll('.ads-stat-table tbody tr').length"))
        print("   计划输入框数:", await q("() => document.querySelectorAll('input[data-plan-asin]').length"))
        rows = await q("() => [...document.querySelectorAll('.ads-stat-table tbody tr')].slice(0,2).map(tr=>({asin:tr.querySelector('input[data-plan-field]').dataset.planAsin, budget:tr.querySelector('input[data-plan-field=\"budget\"]').value, bid:tr.querySelector('input[data-plan-field=\"bid\"]').value}))")
        print("   前两行:", rows)
        # 给第一个有输入的品登记计划参数 (300/15) 并保存
        async def save_plan(idx, budget, bid):
            await q(f"""() => {{
                const tr = document.querySelectorAll('.ads-stat-table tbody tr')[{idx}];
                tr.querySelector('input[data-plan-field="budget"]').value = '{budget}';
                tr.querySelector('input[data-plan-field="bid"]').value = '{bid}';
            }}""")
            await page.click(f".ads-stat-table tbody tr:nth-child({idx+1}) [data-act='plan-save']")
            await asyncio.sleep(2)
        first = rows[0]["asin"] if rows else ""
        await save_plan(0, "300", "15")
        print(f"   登记 {first} → 待投放分组数:", await q("() => document.querySelectorAll('.ads-stat-block').length && document.body.innerText.includes('③ 待投放分组')"))

        print("[3] 自定义分组")
        await page.click("[data-act='group-new']")
        await page.fill("#statGroupBudget", "111")
        await page.fill("#statGroupBid", "9")
        await page.fill("#statGroupAsins", "B0TEST0001, B0TEST0002\nB0TEST0003")
        await page.click("[data-act='group-save']")
        await asyncio.sleep(2.5)
        print("   分组表单可见:", await q("() => document.getElementById('statGroupForm').style.display !== 'none'"))
        print("   自定义分组块数:", await q("() => document.querySelectorAll('[data-act=\"group-del\"]').length"))
        print("   分组内容:", await q("() => [...document.querySelectorAll('[data-act=\"group-del\"]')].map(e=>e.closest('.ads-stat-sub').innerText.split('\\n')[0])"))

        print("[4] 清除重复项 + 恢复")
        has_excl = await q("() => !!document.querySelector('[data-act=\"exclude\"]')")
        if has_excl:
            before = await q("() => document.getElementById('statBody').innerText.match(/② [^\\n]*共 (\\d+) 个/) ? RegExp.$1 : ''")
            await page.click("[data-act='exclude']")
            await asyncio.sleep(2.5)
            restored = await q("() => !!document.querySelector('[data-act=\"restore\"]')")
            after = await q("() => document.getElementById('statBody').innerText.match(/② [^\\n]*共 (\\d+) 个/) ? RegExp.$1 : ''")
            print(f"   清除前 {before} 个 → 清除后 {after} 个 | 出现恢复按钮: {restored}")
            await page.click("[data-act='restore']")
            await asyncio.sleep(2.5)
            back = await q("() => document.getElementById('statBody').innerText.match(/② [^\\n]*共 (\\d+) 个/) ? RegExp.$1 : ''")
            gone = await q("() => !document.querySelector('[data-act=\"restore\"]')")
            print(f"   恢复后: {back} 个 | 恢复按钮消失: {gone}")
        else:
            print("   无重复项可清除")

        # 删除测试分组
        n = await q("() => document.querySelectorAll('[data-act=\"group-del\"]').length")
        if n:
            await page.click("[data-act='group-del']")
            await asyncio.sleep(2.5)
            print("   删除后残留分组数:", await q("() => document.querySelectorAll('[data-act=\"group-del\"]').length"))

        await page.screenshot(path="/Users/gx/Desktop/mypro/browser_toolkit/examples/ads_统计结果_v3.png", full_page=True)
        print("控制台报错:", errs[:4] or "无")
        await page.close()

asyncio.run(main())
