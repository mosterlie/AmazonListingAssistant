# -*- coding: utf-8 -*-
"""E2E: 投放页任务集作为一条记录 + 展开子任务 + 整套执行(仅拦截确认框, 不真正执行)"""
import asyncio, sys, json
sys.path.insert(0, '/Users/gx/Desktop/mypro/browser_toolkit')
from playwright.async_api import async_playwright


def tok():
    for l in open('/tmp/ads_cookie.txt', encoding='utf-8'):
        if 'session_token' in l:
            return l.split()[-1]
    return ""


async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception:
            from core.cdp_proxy import get_proxy
            b = await p.chromium.connect_over_cdp(get_proxy("http://127.0.0.1:9222").ws_endpoint)
        pg = await b.contexts[0].new_page()
        errs, dialogs = [], []
        pg.on("console", lambda m: errs.append(m.text[:140]) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)[:140]))

        def on_dialog(d):
            dialogs.append(d.message)
            asyncio.ensure_future(d.dismiss())      # 一律取消, 避免真的执行投放
        pg.on("dialog", on_dialog)

        await pg.goto("http://127.0.0.1:8000/login", wait_until="domcontentloaded")
        await pg.evaluate(f"() => {{ document.cookie = 'session_token={tok()}; path=/'; }}")

        # 造一个任务集 (3 个子任务)
        created = await pg.evaluate("""() => fetch('/api/ads/task-sets', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({set_name:'E2E-任务集', shop_name:'金梧汇辰', start_date:'2026-10-01',
                tasks:[{task_name:'E2E-组合1',budget:'300',bid:'30',asins:['B0HHHPQQC4','B0HJ1P27Y6']},
                       {task_name:'E2E-组合2',budget:'200',bid:'20',asins:['B0HL42PYNT']},
                       {task_name:'E2E-组合3',budget:'150',bid:'15',asins:['B0HL77574M']}]})
        }).then(r=>r.json()).then(j=>j.data)""")
        print("[准备] 任务集:", created["set_id"], "任务:", [t["id"] for t in created["tasks"]])

        await pg.goto("http://127.0.0.1:8000/ads", wait_until="networkidle")
        await asyncio.sleep(3)
        q = pg.evaluate
        child_ids = [t["id"] for t in created["tasks"]]
        info = await q(f"""() => {{
            const rows = [...document.querySelectorAll('#adTableBody tr')];
            const setRow = rows.find(r => r.innerText.includes('E2E-任务集'));
            const childAtTop = {json.dumps(child_ids)}.filter(id => rows.some(r => !r.innerText.includes('└') && r.innerText.startsWith('#' + id)));
            return {{ total: rows.length,
                     hasSetRow: !!setRow,
                     setRowText: setRow ? setRow.innerText.replace(/\\s+/g,' ').slice(0,150) : '',
                     childAtTop: childAtTop,
                     statAll: document.getElementById('adStatAll').innerText,
                     statPending: document.getElementById('adStatPending').innerText }};
        }}""")
        print("[列表] 行数:", info["total"], "| 任务集行存在:", info["hasSetRow"], "| 子任务出现在顶层:", info["childAtTop"] or "无")
        print("       任务集行:", info["setRowText"])
        print("[统计] 全部记录:", info["statAll"], "| 待执行:", info["statPending"])

        # 展开子任务
        await pg.click("#adTableBody tr:has-text('E2E-任务集') button:has-text('子任务')")
        await asyncio.sleep(1)
        exp = await q(f"""() => {{
            const rows = [...document.querySelectorAll('#adTableBody tr')];
            const shown = {json.dumps(child_ids)}.filter(id => rows.some(r => r.innerText.includes('#' + id) && r.innerText.includes('└')));
            return {{ shown: shown, rows: rows.length, hasTag: rows.some(r => r.innerText.includes('🗂️ 任务集 #' + {created['set_id']})) }};
        }}""")
        print("[展开] 显示的子任务:", exp["shown"], "| 含任务集标记:", exp["hasTag"], "| 总行数:", exp["rows"])
        await pg.screenshot(path="/Users/gx/Desktop/mypro/browser_toolkit/examples/ads_任务集列表.png", full_page=False)

        # 整套执行 → 拦截确认框
        dialogs.clear()
        await pg.click("#adTableBody tr:has-text('E2E-任务集') button:has-text('整套执行')")
        await asyncio.sleep(1.5)
        print("[整套执行] 确认框内容:", (dialogs[0] if dialogs else "无").replace("\n", " | ")[:150])
        runs = await q(f"""() => fetch('/api/ads/tasks/{child_ids[0]}/runs').then(r=>r.json()).then(j=>(j.data||[]).length).catch(()=> 'n/a')""")
        print("[整套执行] 因取消, 任务 #%s 执行记录数:" % child_ids[0], runs)

        # 清理
        await q(f"() => fetch('/api/ads/task-sets/{created['set_id']}', {{method:'DELETE'}}).then(r=>r.json())")
        left = await q("() => fetch('/api/ads/task-sets').then(r=>r.json()).then(j=>j.data.length)")
        print("[清理] 剩余任务集:", left)
        print("控制台报错:", errs[:4] or "无")
        await pg.close()

asyncio.run(main())
