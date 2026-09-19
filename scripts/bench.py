#!/usr/bin/env python3
"""bench.py — measure CDP call latency: one-shot CLI vs persistent socket.

The CAPTCHA clock is the adversary. A grid solve needs dozens of round-trips (read
tile rects, screenshot, N clicks, verify, re-check). If each one costs a process spawn
plus a WebSocket handshake, the round expires mid-solve, so this quantifies why the
persistent client in cdp.py is not optional.

    bench.py [port]

Set ONE_SHOT_CMD to the shell command of any one-shot CDP CLI to compare against it,
for example:
    export ONE_SHOT_CMD='chrome-agent my-instance Runtime.evaluate'
If it is unset, only the persistent path is measured.
"""
import json
import os
import shlex
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402
from cdp import CDP  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else cfg.CDP_PORT
ONE_SHOT_CMD = os.environ.get("ONE_SHOT_CMD")     # optional comparison target

N = 12


def bench_oneshot():
    """A one-shot CLI: spawns a process and opens a fresh WS per call."""
    if not ONE_SHOT_CMD:
        return []
    argv = shlex.split(ONE_SHOT_CMD) + [
        "Runtime.evaluate", json.dumps({"expression": "1", "returnByValue": True})]
    ts = []
    for _ in range(N):
        t0 = time.perf_counter()
        try:
            subprocess.run(argv, capture_output=True, text=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []
        ts.append((time.perf_counter() - t0) * 1000)
    return ts


def bench_persistent():
    c = CDP(port=PORT, host=cfg.CDP_HOST)
    c.eval("1")                                   # warm
    ts = []
    for _ in range(N):
        t0 = time.perf_counter()
        c.eval("1")
        ts.append((time.perf_counter() - t0) * 1000)
    # batched: N commands in one round-trip window
    t0 = time.perf_counter()
    c.call_many([("Runtime.evaluate", {"expression": "1", "returnByValue": True})] * N)
    batched = (time.perf_counter() - t0) * 1000
    c.close()
    return ts, batched


def click_bench():
    """Instant click (press+release batched) vs a humanized eased path."""
    c = CDP(port=PORT, host=cfg.CDP_HOST)
    c.eval("1")
    t0 = time.perf_counter()
    for _ in range(5):
        c.click(400, 300)
    instant = (time.perf_counter() - t0) / 5 * 1000

    pts = []
    for i in range(22):
        t = i / 21
        e = 1 - (1 - t) ** 3
        pts.append((300 + 100 * e, 200 + 100 * e, 1 if i == 21 else 0))
    t0 = time.perf_counter()
    for _ in range(5):
        c.click_xy_path(pts)
    human = (time.perf_counter() - t0) / 5 * 1000
    c.close()
    return instant, human


def main():
    print(f"target={cfg.CDP_HOST}:{PORT}  n={N}\n")
    o = bench_oneshot()
    p, batched = bench_persistent()
    instant, human = click_bench()

    def line(label, ts):
        print(f"{label:<34} min {min(ts):7.2f}  med {statistics.median(ts):7.2f}  "
              f"max {max(ts):7.2f} ms")

    if o:
        line("one-shot CLI (per call)", o)
    else:
        print("one-shot CLI (per call)            skipped (set ONE_SHOT_CMD to compare)")
    line("persistent socket (per call)", p)
    print(f"{'persistent BATCHED (%d cmds)' % N:<34} total {batched:7.2f} ms  "
          f"({batched/N:.2f} ms/cmd)")
    print()
    print(f"trusted click (batched press+release)  {instant:7.2f} ms")
    print(f"humanized path (22 pts, batched)       {human:7.2f} ms")
    print()
    if o:
        speedup = statistics.median(o) / statistics.median(p)
        print(f"ONE-SHOT -> PERSISTENT SPEEDUP: {speedup:.1f}x per call")
        print(f"a 60-call grid solve: one-shot ~{statistics.median(o)*60/1000:.1f}s "
              f"vs persistent ~{statistics.median(p)*60/1000:.2f}s")
    else:
        print(f"a 60-call grid solve on the persistent socket: "
              f"~{statistics.median(p)*60/1000:.2f}s")


if __name__ == "__main__":
    main()
