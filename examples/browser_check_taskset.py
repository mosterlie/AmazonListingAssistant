# -*- coding: utf-8 -*-
"""E2E: 统计结果(未投广输入/本地自定义分组/本地清除重复项/生成广告任务集) + 投放页任务集区块"""
import asyncio, sys
sys.path.insert(0, '/Users/gx/Desktop/mypro/browser_toolkit')
from playwright.async_api import async_playwright


def tok():
    for line in open('/tmp/ads_cookie.txt', encoding='utf-8'):
        if 'session_token' in line:
            return line.split()[-1]
    return ""


async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception:
            from core.cdp_proxy import get_proxy
            b = await p.chromium.connect_over_cdp(get_proxy("http://127.0.0.1:9222").ws_endpoint)
        pg = await b.contexts[0].new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text[:140]) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)[:140]))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto("http://127.0.0.1:8000/login", wait_until="domcontentloaded")
        await pg.evaluate(f"() => {{ document.cookie = 'session_token={tok()}; path=/'; }}")
        await pg.goto("http://127.0.0.1:8000/ads-analysis", wait_until="networkidle")
        await asyncio.sleep(2)
        await pg.click("#resStatBtn")
        await asyncio.sleep(2.5)
        q = pg.evaluate

        print("[②未投广] 表格行数:", await q("() => document.querySelectorAll('#statBody tr[data-un-asin]').length"),
              "| 输入框数:", await q("() => document.querySelectorAll('#statBody input[data-plan-field]').length"),
              "| 首行:", await q("() => (document.querySelector('#statBody tr[data-un-asin]') || {}).dataset?.unAsin || ''"))

        print("[重复项] 清除按钮数:", await q("() => document.querySelectorAll('[data-act=\"exclude\"]').length"))
        # 在某区域清除重复项 → 恢复按钮出现 (本地)
        if await q("() => !!document.querySelector('[data-act=\"exclude\"]')"):
            await pg.click("[data-act='exclude']")
            await asyncio.sleep(0.6)
            print("          清除后出现恢复按钮:", await q("() => !!document.querySelector('[data-act=\"restore\"]')"))
            await pg.click("[data-act='restore']")
            await asyncio.sleep(0.5)
            print("          恢复后按钮消失:", await q("() => !document.querySelector('[data-act=\"restore\"]')"))

        print("[③自定义分组] 初始块数:", await q("() => ADS.stat.custom.length"))
        await pg.click("[data-act='group-new']")
        await pg.fill("#statGroupBudget", "188")
        await pg.fill("#statGroupBid", "8")
        await pg.fill("#statGroupAsins", "B0TEST0001,B0TEST0002,B0TEST0002")
        await pg.click("[data-act='group-save']")
        await asyncio.sleep(0.8)
        print("          新增后:", await q("() => ADS.stat.custom.map(g => g.budget + '/' + g.bid + ':' + g.asins.length).join(', ')"),
              "| 是否为内存态(无id字段):", await q("() => ADS.stat.custom.every(g => !('id' in g))"))

        print("[④生成任务集] 表单按钮:", await q("() => !!document.querySelector('[data-act=\"set-new\"]')"))
        await pg.click("[data-act='set-new']")
        await asyncio.sleep(1.2)
        print("          预览:", (await q("() => document.getElementById('statSetPreview').innerText")).replace("\n", " | ")[:190])
        await pg.fill("#statSetName", "测试集-UI")
        print("          店铺选项:", await q("() => [...document.getElementById('statSetShop').options].map(o=>o.value).join('/')"),
              "| 日期:", await q("() => document.getElementById('statSetDate').value"))
        await pg.click("[data-act='set-save']")
        await asyncio.sleep(3.5)
        print("          当前URL:", pg.url.replace("http://127.0.0.1:8000", ""))

        # part B: 投放页任务集
        if "/ads" in pg.url and "/ads-analysis" not in pg.url:
            await asyncio.sleep(2.5)
            print("[投放页] 任务集面板可见:", await q("() => document.getElementById('adTaskSetPanel').style.display !== 'none'"))
            print("         任务集卡片数:", await q("() => document.querySelectorAll('#adTaskSetList > div').length"))
            print("         整套执行按钮:", await q("() => [...document.querySelectorAll('#adTaskSetList button')].filter(b=>b.innerText.includes('整套执行')).map(b=>b.innerText.trim()).join(' / ')"))
            print("         集内任务行:", await q("() => document.querySelectorAll('#adTaskSetList [onclick^=\"runAdTask(\"]').length"))
            await pg.screenshot(path="/Users/gx/Desktop/mypro/browser_toolkit/examples/ads_任务集.png", full_page=False)

        # part C: 清理测试任务集
        sets = await q("() => fetch('/api/ads/task-sets').then(r=>r.json()).then(j=>j.data.map(s=>({id:s.id,name:s.set_name})))")
        for s in sets:
            if "测试集" in s["name"]:
                await q(f"() => fetch('/api/ads/task-sets/{s['id']}', {{method:'DELETE'}}).then(r=>r.json())")
                print("         已清理:", s)
        print("控制台报错:", errs[:4] or "无")
        await pg.close()

asyncio.run(main())
