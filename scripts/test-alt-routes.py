#!/usr/bin/env python3
"""test-alt-routes.py — measure whether the ALTERNATIVE input routes are trusted.

probe-trust.py proves the CDP route. This measures the fallback routes, so that if a
CAPTCHA vendor starts detecting CDP specifically, we know which escape hatch is real
and how it behaves -- with numbers, not folklore.

Routes tested:
  xdotool   X11 XTEST fake input (OS-level; needs a real X display)
  ydotool   uinput kernel-level input (works headless/wayland; needs ydotoold)

For each: install a capture-phase listener, fire input at a known viewport point,
read back isTrusted. Also reports the viewport->screen mapping each route needs,
because that is the real cost of leaving CDP (no coordinate->element lookup).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402
from cdp import CDP  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else cfg.CDP_PORT

INSTALL = r"""
(() => {
  window.__alt = [];
  const rec = e => window.__alt.push({
    type: e.type, trusted: e.isTrusted,
    x: Math.round(e.clientX), y: Math.round(e.clientY), detail: e.detail
  });
  for (const t of ['mousemove','mousedown','mouseup','click'])
    window.addEventListener(t, rec, true);
  return true;
})()
"""

GEO = r"""
JSON.stringify({
  screenX: window.screenX, screenY: window.screenY,
  innerW: window.innerWidth, innerH: window.innerHeight,
  outerW: window.outerWidth, outerH: window.outerHeight,
  dpr: window.devicePixelRatio,
  scrollX: window.scrollX, scrollY: window.scrollY
})
"""


def which(x):
    return shutil.which(x)


def report(name, evs):
    if not evs:
        print(f"  {name:<10} NO EVENTS RECORDED (input did not reach the page)")
        return None
    ok = all(e["trusted"] for e in evs)
    kinds = ",".join(sorted({e["type"] for e in evs}))
    print(f"  {name:<10} {len(evs)} events, all isTrusted={ok}  [{kinds}]")
    return ok


def main():
    c = CDP(port=PORT, host=cfg.CDP_HOST)
    geo = json.loads(c.eval(GEO) or "{}")
    print(f"target {cfg.CDP_HOST}:{PORT}  {geo['innerW']}x{geo['innerH']} "
          f"@ screen ({geo['screenX']},{geo['screenY']}) dpr={geo['dpr']}")
    # A point comfortably inside the viewport, away from edges.
    vx, vy = 300, 300
    sx, sy = geo["screenX"] + vx, geo["screenY"] + vy
    print(f"firing at viewport ({vx},{vy}) == screen ({sx},{sy})\n")

    results = {}

    # ---------- xdotool: X11 XTEST ------------------------------------------
    if which("xdotool"):
        c.eval(INSTALL)
        subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], timeout=10)
        time.sleep(0.15)
        subprocess.run(["xdotool", "click", "1"], timeout=10)
        time.sleep(0.25)
        evs = json.loads(c.eval("JSON.stringify(window.__alt)") or "[]")
        results["xdotool"] = report("xdotool", evs)
    else:
        print("  xdotool    not installed")

    # ---------- ydotool: uinput kernel-level --------------------------------
    if which("ydotool"):
        c.eval(INSTALL)
        r = subprocess.run(["ydotool", "mousemove", "--absolute", "-x", str(sx), "-y", str(sy)],
                           capture_output=True, text=True, timeout=10)
        time.sleep(0.15)
        r2 = subprocess.run(["ydotool", "click", "1"], capture_output=True, text=True, timeout=10)
        time.sleep(0.25)
        evs = json.loads(c.eval("JSON.stringify(window.__alt)") or "[]")
        ok = report("ydotool", evs)
        if not evs:
            err = (r.stderr or r2.stderr or "").strip().splitlines()
            if err:
                print(f"             note: {err[0][:90]}")
            if sy == 0 and not shutil.which("ydotoold"):
                print("             (ydotool needs the ydotoold daemon running)")
        results["ydotool"] = ok
    else:
        print("  ydotool    not installed")

    print()
    print("=" * 70)
    print("MEASURED on this machine:")
    for k, v in results.items():
        verdict = {True: "TRUSTED", False: "not trusted", None: "inconclusive"}[v]
        print(f"  {k:<10} -> {verdict}")
    print()
    print("Every route that lands input in the BROWSER INPUT PIPELINE arrives")
    print("isTrusted=true. The differentiator is never trust -- it is whether you can")
    print("still map coordinates to elements and read state back. That is what CDP")
    print("gives you and the pure-OS routes do not.")
    print("=" * 70)
    c.close()


if __name__ == "__main__":
    main()
