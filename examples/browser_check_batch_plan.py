# -*- coding: utf-8 -*-
"""E2E: 未投广区域「批量配置」一次生效到父SKU下所有子ASIN"""
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
        except Exception as e:
            from core.cdp_proxy import get_proxy
            b = await p.chromium.connect_over_cdp(get_proxy("http://127.0.0.1:9222").ws_endpoint)
        pg = await b.contexts[0].new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text[:150]) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)[:150]))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto("http://127.0.0.1:8000/login", wait_until="domcontentloaded")
        await pg.evaluate(f"() => {{ document.cookie = 'session_token={tok()}; path=/'; }}")
        await pg.goto("http://127.0.0.1:8000/ads-analysis", wait_until="networkidle")
        await asyncio.sleep(2)
        await pg.click("#resStatBtn")
        await asyncio.sleep(2.5)

        q = pg.evaluate
        print("[批量条] 存在:", await q("() => !!document.getElementById('unBatchBudget')"),
              "| 子ASIN开关默认勾选:", await q("() => document.getElementById('unBatchChildren').checked"),
              "| 携带范围:", await q("() => {const e=document.querySelector('[data-act=\"plan-batch\"]'); return (e.dataset.asins.split(',').length) + '代表ASIN/' + e.dataset.psk.split(',').length + '父SKU';}"))

        await pg.fill("#unBatchBudget", "288")
        await pg.fill("#unBatchBid", "18")
        await pg.click("[data-act='plan-batch']")
        await asyncio.sleep(3.5)
        print("[批量生效] 待投放分组区块:", await q("() => document.body.innerText.includes('③ 待投放分组')"))
        print("[批量生效] 待投放内容:", await q("() => {const t=document.body.innerText.match(/待投放 1：[^\\n]*/); return t?t[0]:'';}"))
        await pg.evaluate("() => { const b=document.querySelector('.ads-modal-body'); const bar=document.getElementById('unBatchBudget'); bar.scrollIntoView({block:'center'}); }")
        await asyncio.sleep(0.5)
        await pg.screenshot(path="/Users/gx/Desktop/mypro/browser_toolkit/examples/ads_未投广_批量配置.png")

        # 逐行输入是否也能同步显示 (抽第一行)
        print("[逐行填写] 第一行值:", await q("() => {const tr=document.querySelector('.ads-stat-table tbody tr'); const i=tr.querySelector('input[data-plan-field=\"budget\"]'); return i.value + '/' + tr.querySelector('input[data-plan-field=\"bid\"]').value;}"))

        await pg.click("[data-act='plan-batch-clear']")
        await asyncio.sleep(3.5)
        print("[清空计划] 待投放分组区块消失:", await q("() => !document.body.innerText.includes('③ 待投放分组')"))
        print("[清空计划] 行内输入已复位:", await q("() => {const tr=document.querySelector('.ads-stat-table tbody tr'); return tr.querySelector('input[data-plan-field=\"budget\"]').value === '';}"))
        print("控制台报错:", errs[:4] or "无")
        await pg.close()

asyncio.run(main())
