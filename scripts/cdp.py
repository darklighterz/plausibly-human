#!/usr/bin/env python3
"""cdp.py — persistent CDP client. The speed baseline's replacement for one-shot CLI.

chrome-agent's one-shot mode spawns a process and opens a fresh WebSocket per call
(~measured in bench.py). Every extra round-trip costs the CAPTCHA clock, and a grid
solve needs dozens of them. This holds ONE WebSocket and reuses it.

    from cdp import CDP
    c = CDP(port=9333)          # sync facade
    c.call("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
    c.click(400, 300)           # trusted mousePressed+mouseReleased
    c.close()
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.request

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None


def _ws_url(host: str, port: int, target: str | None = None) -> str:
    """Resolve the debugger WebSocket URL for a port (optionally a specific target)."""
    with urllib.request.urlopen(f"http://{host}:{port}/json", timeout=5) as r:
        targets = json.load(r)
    if target:
        for t in targets:
            if target in (t.get("url") or "") or target == t.get("title"):
                return t["webSocketDebuggerUrl"]
        raise LookupError(f"no target matching {target!r}")
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise LookupError("no page target")
    return pages[0]["webSocketDebuggerUrl"]


class _Loop(threading.Thread):
    """Private event loop in its own thread so the sync facade can be used anywhere."""

    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        self.loop.run_forever()


class CDP:
    def __init__(self, port: int = 9333, target: str | None = None, timeout: float = 20.0,
                 host: str = "127.0.0.1"):
        self.port = port
        self.host = host
        self.timeout = timeout
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._loop = _Loop()
        self._loop.start()
        self._loop.ready.wait(5)
        self._url = _ws_url(host, port, target)
        self._ws = None
        self._run(self._connect())

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop.loop).result(self.timeout * 3)

    async def _connect(self):
        self._ws = await websockets.connect(self._url, max_size=200 * 1024 * 1024)
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                mid = msg.get("id")
                if mid is not None and mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        fut.set_result(msg)
        except Exception:
            pass

    async def _call(self, method: str, params: dict | None = None):
        self._id += 1
        mid = self._id
        fut = self._loop.loop.create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        msg = await asyncio.wait_for(fut, timeout=self.timeout)
        if "error" in msg:
            raise RuntimeError(f"CDP error: {msg['error']}")
        return msg.get("result", {})

    async def _call_many(self, calls: list[tuple[str, dict]]):
        """Fire several commands without awaiting between them — one round-trip window."""
        futures = []
        for method, params in calls:
            self._id += 1
            mid = self._id
            fut = self._loop.loop.create_future()
            self._pending[mid] = fut
            futures.append(fut)
            await self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        out = []
        for fut in futures:
            msg = await asyncio.wait_for(fut, timeout=self.timeout)
            out.append(msg.get("result", {}) if "error" not in msg else {"_error": msg["error"]})
        return out

    # ---- sync facade -------------------------------------------------------
    def call(self, method: str, params: dict | None = None):
        return self._run(self._call(method, params))

    def call_many(self, calls):
        return self._run(self._call_many(calls))

    def eval(self, js: str, await_promise: bool = False):
        p = {"expression": js, "returnByValue": True}
        if await_promise:
            p["awaitPromise"] = True
        r = self.call("Runtime.evaluate", p)
        # Runtime.evaluate nests as {"result": {"type":..., "value":...}} at the call
        # layer, but some shapes arrive already unwrapped — accept both.
        inner = r.get("result", r) if isinstance(r, dict) else {}
        if isinstance(inner, dict) and "exceptionDetails" in inner:
            raise RuntimeError(str(inner["exceptionDetails"])[:300])
        if isinstance(r, dict) and "exceptionDetails" in r:
            raise RuntimeError(str(r["exceptionDetails"])[:300])
        return inner.get("value") if isinstance(inner, dict) else None

    def js(self, js: str):
        """Evaluate and JSON-decode the result."""
        v = self.eval(js)
        if v is None:
            return None
        try:
            return json.loads(v)
        except (TypeError, json.JSONDecodeError):
            return v

    def mouse(self, x, y, kind="mouseMoved", button="left", click_count=0, buttons=0):
        return self.call("Input.dispatchMouseEvent", {
            "type": kind, "x": x, "y": y, "button": button,
            "clickCount": click_count, "buttons": buttons})

    def click(self, x, y):
        """Trusted instant click: press+release dispatched back-to-back (no sleeping)."""
        self.call_many([
            ("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                          "button": "left", "clickCount": 1, "buttons": 1}),
            ("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                          "button": "left", "clickCount": 1, "buttons": 0}),
        ])

    def click_xy_path(self, points):
        """Stream a whole mouse path (move*/press/release) in ONE round-trip window."""
        calls = [("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": round(x),
                                               "y": round(y), "buttons": b})
                 for x, y, b in points]
        return self.call_many(calls)

    def shot(self, path: str):
        import base64
        r = self.call("Page.captureScreenshot", {"format": "png"})
        data = r.get("data") or r.get("result", {}).get("data")
        if not data:
            return False
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(data))
        return True

    def navigate(self, url: str):
        return self.call("Page.navigate", {"url": url})

    def close(self):
        try:
            self._run(self._ws.close())
        except Exception:
            pass
        self._loop.loop.call_soon_threadsafe(self._loop.loop.stop)


if __name__ == "__main__":
    import sys as _s
    t0 = time.perf_counter()
    _port = int(_s.argv[1]) if len(_s.argv) > 1 else 9333
    c = CDP(port=_port)
    t_conn = time.perf_counter() - t0
    t0 = time.perf_counter()
    title = c.eval("document.title")
    t_first = time.perf_counter() - t0
    n = 20
    t0 = time.perf_counter()
    for _ in range(n):
        c.eval("1")
    per = (time.perf_counter() - t0) / n * 1000
    print(f"connect: {t_conn*1000:.1f} ms | first eval: {t_first*1000:.1f} ms | "
          f"steady eval: {per:.2f} ms/call | title={title!r}")
    c.close()
