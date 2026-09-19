"""Playwright 驱动守护 — 统一清理残留/冻结的 node 驱动进程

背景 (见 debug-batch2-newpage-hang.md):
    connect_over_cdp 会让 Playwright 对每个新标签页下发 Target.setAutoAttach(waitForDebugger=true),
    须由 driver 主动 runIfWaitingForDebugger 释放。若 driver 事件循环被阻塞
    (闲置事件堆积致 pipe 写满 / 线程卡死), 新标签页将永远停在调试暂停态
    → 白屏、goto 超时; 杀掉驱动即立即恢复。

    单进程整合版 (unified_app) 内同时存在三类驱动:
      1) 上件管线 BrowserEngine/BrowserManager 的 sync 驱动 (每次上件新建, 结束关闭)
      2) 广告投放 SellfoxAdOperator 的 async 驱动 (每次投放新建)
      3) 赛狐 Bridge 常驻 BrowserManager 的 sync 驱动 (启动调试浏览器/打开赛狐页)
    既有清理逻辑 (core.browser_manager.cleanup_stale_drivers 只清本进程登记过的;
    core.sellfox_ad_operator._kill_stale_drivers 跳过 ppid==本进程) 覆盖不到同进程的
    闲置/冻结驱动 —— 于是出现 "用 playwright 打开一个网页后, 再打开新页面就白屏"。

本模块提供跨进程 + 同进程的统一清理, 与"闲置驱动优雅下线"能力。
"""

import os
import time
import threading

_NODE_NAMES = ('node.exe', 'node')


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:
        return False


def _iter_driver_procs():
    """枚举所有 Playwright node 驱动进程 (cmdline 含 run-driver)"""
    try:
        import psutil
    except Exception:
        return
    me = os.getpid()
    for p in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline']):
        try:
            name = (p.info.get('name') or '').lower()
            if name not in _NODE_NAMES:
                continue
            cmd = ' '.join(p.info.get('cmdline') or [])
            if 'run-driver' not in cmd:
                continue
            yield {
                'pid': p.info.get('pid'),
                'ppid': p.info.get('ppid'),
                'same_process': p.info.get('ppid') == me,
                'proc': p,
            }
        except Exception:
            continue


def list_drivers() -> list:
    """列出当前所有 Playwright 驱动进程 (调试用)"""
    return [
        {'pid': d['pid'], 'ppid': d['ppid'], 'same_process': d['same_process']}
        for d in _iter_driver_procs()
    ]


def kill_drivers(keep_pids=None, protect_active_foreign=True, sample_gap=1.2) -> list:
    """强杀 Playwright 驱动进程, 返回被杀 PID 列表。

    :param keep_pids: 需保留的 PID (当前会话正在使用的驱动)
    :param protect_active_foreign: True 时保留"其它进程仍在活跃使用"的驱动
           (父进程存活 且 采样期内有 CPU 活动), 避免误伤并行运行的其它自动化程序;
           本进程自己的驱动与"无活动(闲置/冻结)"的驱动一律清理
    """
    keep = {int(x) for x in (keep_pids or [])}
    drivers = [d for d in _iter_driver_procs() if d['pid'] not in keep]
    if not drivers:
        return []

    protect = set()
    if protect_active_foreign:
        foreign = [d for d in drivers if not d['same_process']]
        if foreign:
            base = {}
            for d in foreign:
                try:
                    t = d['proc'].cpu_times()
                    base[d['pid']] = t.user + t.system
                except Exception:
                    base[d['pid']] = None
            time.sleep(sample_gap)
            for d in foreign:
                b = base.get(d['pid'])
                if b is None:
                    continue
                try:
                    t = d['proc'].cpu_times()
                    now = t.user + t.system
                except Exception:
                    continue
                if now - b > 0.05 and _pid_alive(d['ppid']):
                    protect.add(d['pid'])

    killed = []
    for d in drivers:
        if d['pid'] in protect:
            continue
        try:
            d['proc'].kill()
            killed.append(d['pid'])
        except Exception:
            pass
    return killed


def detach_browser_manager(bm, timeout=6.0) -> dict:
    """停止 BrowserManager 的 Playwright 驱动 (不影响用户的 Chrome 及其标签页)

    注意: sync Playwright 对象只能在创建它的线程中使用, 因此 stop 必须派发回
    BrowserManager 的专属工作线程执行; 超时(驱动已冻结/线程卡死)则硬杀兜底。
    返回 {"stopped": bool, "killed": [pid, ...]}
    """
    info = {'stopped': False, 'killed': []}
    if bm is None:
        return info

    pw = getattr(bm, 'playwright', None)
    if pw is not None:
        try:
            from core.browser_manager import _unregister_driver_pid
            _unregister_driver_pid(pw)
        except Exception:
            pass

        def _do_stop():
            try:
                pw.stop()
                return True
            except Exception:
                return False

        try:
            # 派发回 BrowserManager 专属工作线程执行 (sync 对象线程亲和)
            info['stopped'] = bool(bm.run_on_browser_thread(_do_stop, timeout=timeout))
        except Exception:
            info['stopped'] = False

    for attr in ('playwright', 'browser', 'context'):
        try:
            setattr(bm, attr, None)
        except Exception:
            pass

    try:
        bm._task_queue.put(None)   # 唤醒可能阻塞在队列上的工作线程, 令其退出
    except Exception:
        pass

    if not info['stopped']:
        # stop 失败/超时: 硬杀兜底, 避免冻结驱动继续占用调试会话
        info['killed'] = kill_drivers()
    return info


def spawn_background_cleanup(log=None, delay=0.0, protect_active_foreign=True):
    """后台执行一次驱动清理 (不阻塞调用方), 可选写日志"""

    def work():
        try:
            if delay:
                time.sleep(delay)
            killed = kill_drivers(protect_active_foreign=protect_active_foreign)
            if killed and log:
                log(f"🧹 已清理 {len(killed)} 个残留自动化驱动进程 {killed} (避免新标签页白屏)")
        except Exception:
            pass

    threading.Thread(target=work, daemon=True, name='DriverGuardCleanup').start()
