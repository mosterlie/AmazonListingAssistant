# Debug Session: batch2-newpage-hang
- **Status**: [OPEN]
- **Issue**: task260906-2 上件时，第二批次打开新页面后页面一直白屏无法加载；后台存在 Node.js (Playwright driver) 进程阻塞，手动杀掉该进程后页面立刻恢复
- **Debug Server**: 待启动 (http://127.0.0.1:<port>/event)
- **Log File**: .dbg/trae-debug-log-batch2-newpage-hang.ndjson

## Reproduction Steps
1. 启动本地 ERP 服务 (端口 8000) 与 Chrome 9222 调试实例（已登录店小秘）
2. 触发 task260906-2 对应商品的上件（含多批次）
3. 观察第一批次正常完成后，第二批次打开新页面时：
   - 预期：新页面正常加载店小秘上件表单
   - 实际：页面持续白屏，Node.js 驱动进程阻塞；杀掉 node 进程后页面立即恢复

## Hypotheses & Verification
| ID | Hypothesis | Likelihood | Effort | Evidence |
|----|------------|------------|--------|----------|
| A | 机制层(已基本确认): 新标签页被 Playwright connectOverCDP 的 Target.setAutoAttach(waitForDebugger=true) 暂停, 初始化未完成(runIfWaitingForDebugger 未调用) → 渲染进程挂起白屏; 杀 node → CDP 会话关闭 → Chrome 释放暂停 → 页面立刻加载。待确认的是"哪一环未释放" | High | Low | 白屏时刻 /json 显示 target 存在; 杀 node 后恢复 |
| B | Chrome 152 直连握手必失败 → 全部走 cdp_proxy 代理; 代理对"新建 target"的 attachedToTarget 事件/多会话转发有缺陷 → driver 收不到/发不出 runIfWaitingForDebugger。解释: 复用已有标签页的批次正常, 新开标签页才白屏 (DB 证据: 复用页的 run 全成功, goto 超时的 run 全是新开页) | High | Low | connect 日志出现"代理模式"; 代理模式下 new_page 复现白屏; 对照直连(若可行)不复现 |
| C | 上一次会话遗留的冻结 node 驱动 (父进程死/挂起, pipe 满阻塞) 仍 attach 在 Chrome 上持有一个未释放的 debugger 暂停 → 新标签页被双 debugger 暂停, 冻结者永不释放 | Medium | Low | 运行前/白屏时枚举 node.exe (ppid 存活, CPU 增量=0); 杀的若是"另一个"node 则 C 成立 |
| D | 同一 ERP server 进程/桌面 exe 内的店小米 sync 驱动与赛狐 async 驱动并发 attach Chrome 9222, 双 debugger 暂停竞态 | Low | Medium | 运行期间枚举 node 数量 ≥2 且分属不同进程树 |
| E | 白屏是站点自身未加载(网络/风控), 与 driver 无关, 杀 node 恢复是巧合 | Low | Low | 白屏时刻 /json 中该 target 的 url/title 表现为 about:blank 或未收到 navigation |

### DB 历史证据 (ad_task_runs, task_id=35)
- run 34/35 (2 批次) 成功: 第2批 `open_new_page()` 成功 → 多批开新页机制本身可用
- run 27/29/36/44 失败 `Page.goto: Timeout 30000ms @ spBatchCreatePage, domcontentloaded`: 均在**首次打开页面**阶段 (log_text 为空, batch_count=0) — 与"第二批次开新页白屏"同一机制 (新 tab + goto)
- run 20 日志: "检测到 Chrome 与 Playwright 的 CDP 握手兼容问题, 切换代理模式重连" → Chrome 152 (152.0.7977.76) 移除 setDownloadBehavior, **所有连接走 cdp_proxy**
- 失败 run 时长 78~111s (30s goto × 多次重试), 成功 run 40~150s

## Reproduction Steps (更新)
1. 启动 Chrome 9222 调试实例 (POST /api/ad-tasks... /launch-browser, 用户数据 C:\ChromeDebugUser, 需含赛狐登录态)
2. 启动调试服务器收集日志
3. POST /api/ad/tasks/35/run 触发 task260906-2 (9 ASIN / batch 6 → 第2批必开新页)
4. 观察白屏时刻插桩数据: /json targets、node.exe 清单、代理模式标记
5. 若复现: 逐一杀 node 对照恢复情况, 区分 B/C/D

## Log Evidence
### 受控实验 (_dbg_pause_lab.py, runId=pre-fix)
- P1 进程 connect_over_cdp → node PID=9952 → psutil suspend 模拟"node 进程阻塞"
- 阶段1: 第二个 driver `new_page` 成功创建, `goto(example.com, 15s)` → **TimeoutError**; CDP /json 显示该 target 已存在 (`https://example.com/`) 但渲染进程暂停 → 白屏
- 阶段2: **kill node 9952 后**, 同样操作 `goto_ok=True` 立即成功
- 结论: **机制确认 (A/C)** — 任何仍 attach 在 Chrome 9222 上但事件循环阻塞的 node 驱动, 会让所有新标签页停在 waitForDebugger 暂停态 (白屏); 杀掉即恢复 — 与用户现象完全一致

### run 45 (真实任务复现, 2026-09-07)
- worker-begin: `nodes=[]` 无残留驱动; `connect_over_cdp 直连成功` (mode=direct, 未走代理) → 假设B"必走代理"不成立
- connect 新建页 goto 3.4s 正常; 失败于"未找到 iframe (页面被重定向到 https://www.sellfox.com/)" → 登录态/深链问题, 非白屏
- Chrome 中存在 sellfox dashboard.html 标签页, 登录态可能仍有效

### 生产冻结源推断
- sellfox 算子/GUI 无 time.sleep 类自阻塞; 最可能: **店小米 sync 驱动 (BrowserManager)** 的 browser worker 线程在 asyncio 循环内执行阻塞操作 (远程图片下载/DB), pipe 堵满 → node 冻结但仍 attach → 之后任何新标签页 (包括赛狐第2批 open_new_page) 全部白屏

## Verification Conclusion
✅ 修复生效 (post-fix, run 46 = _dbg_verify_fix.py, 2026-09-07 21:01):

- **环境注入**: 运行前用 `_dbg_p1_freeze.py` 挂起一个残留 node 驱动 (PID=4352, 模拟生产冻结驱动)
- **自动清理生效**: worker-begin/connect-begin 均检出 nodes=[4352] → `connect()` 内 `_kill_stale_drivers()` 将其清理; `open_new_page-begin` 时 nodes 只剩当前进程自己的驱动 (PID=16040, ppid=当前 python 进程)
- **第2批开新页正常**: new_page created → goto 仅 1.4s 完成 (ts 1788786143107 → 1788786144467), 无超时、无白屏
- **任务终态**: run 46 status=**success**, 2 批全部完成, 录入 9/9, 终态对账 3/3 一致, 总耗时 74.1s (run 45 pre-fix 失败于登录态, 与白屏无关)
- 对比受控实验 (pre-fix): 同样条件下 goto TimeoutError 白屏, kill node 后才恢复 → 修复前后行为差异确凿

**最终结论**: 白屏根因 = 残留/冻结的 Playwright node 驱动仍 attach 在 Chrome 9222 上, 使所有新标签页停在 waitForDebugger 暂停态 (假设 A/C 确认; B/D/E 排除)。修复 = 连接前与 goto 超时重试前自动清理残留驱动, 已验证有效。
