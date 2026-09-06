"""
CDP 中间人代理 (兼容层)

背景: Chrome 152+ 移除了 browser-level 的 Browser.setDownloadBehavior 命令
(实测返回 -32000 'Browser context management is not supported'), 而
Playwright(至 1.62) 的 connect_over_cdp 握手必调该命令, 导致连接直接失败。

方案: 本地起一个轻量 ws 代理 ——
  Playwright ──ws──▶ 本地代理(9223) ──ws──▶ 真实 Chrome(9222)
- Playwright → Chrome 方向: 拦截 Browser.setDownloadBehavior 并伪造成功响应,
  其余消息原样透传
- Chrome → Playwright 方向: 全部透传 (事件/响应双向复用同一条 browser ws)

用法: 算子直连失败且错误特征匹配时, 自动降级走代理 (进程级单例常驻)。
"""
import asyncio
import json
import threading
from typing import Optional

import websockets

BLOCKED_METHODS = {"Browser.setDownloadBehavior"}

_proxy: Optional["CdpProxy"] = None
_proxy_lock = threading.Lock()


class CdpProxy:
    """单客户端 ws 中转代理 (全局任务锁保证同一时刻只有一个 Playwright 在连接)"""

    def __init__(self, upstream_url: str, port: int = 9223):
        self.upstream_url = upstream_url
        self.port = port
        self.ws_endpoint = f"ws://127.0.0.1:{port}"
        self._server = None
        self._loop = None
        self._thread = None
        self._upstream = None      # 当前 chrome 连接
        self._ready = threading.Event()

    # ---------- 生命周期 ----------

    def start_background(self, timeout=10):
        """daemon 线程内启动 asyncio loop 与 ws server, 就绪后返回"""
        if self._thread and self._thread.is_alive():
            self._ready.wait(timeout)
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="CdpProxyThread")
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError(f"CDP 代理启动超时 (port {self.port})")

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._server = self._loop.run_until_complete(
                websockets.serve(self._client_handler, "127.0.0.1", self.port,
                                 max_size=50 * 1024 * 1024, ping_interval=20))
            self._ready.set()
            self._loop.run_forever()
        except Exception:
            self._ready.set()
        finally:
            self._loop.close()

    def stop(self):
        async def _shutdown():
            if self._server:
                self._server.close()
                await self._server.wait_closed()
            if self._upstream:
                await self._upstream.close()
        if self._loop and self._thread and self._thread.is_alive():
            asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._server = None
        self._thread = None

    # ---------- 转发 ----------

    async def _ensure_upstream(self):
        if self._upstream is None or (self._upstream.closed if hasattr(self._upstream, "closed") else False):
            self._upstream = await websockets.connect(
                self.upstream_url, max_size=50 * 1024 * 1024, open_timeout=10)
        return self._upstream

    async def _client_handler(self, ws_client):
        """处理一条 Playwright 连接: 双向 pump + 命令拦截"""
        try:
            ws_up = await self._ensure_upstream()
        except Exception as e:
            try:
                await ws_client.close(code=1011, reason=f"upstream connect failed: {e}")
            except Exception:
                pass
            return

        async def pump_up():
            """Playwright → Chrome (拦截被移除的命令)"""
            async for msg in ws_client:
                try:
                    data = json.loads(msg)
                except Exception:
                    await ws_up.send(msg)
                    continue
                if data.get("method") in BLOCKED_METHODS:
                    # 伪造成功响应, 不转发
                    await ws_client.send(json.dumps({"id": data.get("id"), "result": {}}))
                    continue
                await ws_up.send(msg)

        async def pump_down():
            """Chrome → Playwright (全透传)"""
            async for msg in ws_up:
                await ws_client.send(msg)

        up_task = asyncio.ensure_future(pump_up())
        down_task = asyncio.ensure_future(pump_down())
        done, pending = await asyncio.wait(
            {up_task, down_task}, return_when=asyncio.FIRST_EXCEPTION)
        for t in pending:
            t.cancel()
        # 客户端断开时同步断开 upstream, 下个连接重建
        try:
            await ws_up.close()
        except Exception:
            pass
        self._upstream = None
        try:
            await ws_client.close()
        except Exception:
            pass


def get_proxy(cdp_url: str, port: int = 9223) -> CdpProxy:
    """进程级单例: 由 http(s) cdp_url 推导 browser ws 端点并启动代理"""
    global _proxy
    with _proxy_lock:
        if _proxy is None:
            if cdp_url.startswith("ws"):
                upstream = cdp_url
            else:
                import urllib.request
                with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=5) as resp:
                    upstream = json.loads(resp.read())["webSocketDebuggerUrl"]
            _proxy = CdpProxy(upstream, port)
            _proxy.start_background()
        return _proxy


def shutdown_proxy():
    """进程退出时回收 (daemon 线程, 通常无需显式调用)"""
    global _proxy
    with _proxy_lock:
        if _proxy is not None:
            _proxy.stop()
            _proxy = None
