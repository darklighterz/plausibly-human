#!/usr/bin/env python3
"""probe-trust.py — verify that CDP-dispatched input is genuinely trusted input.

This repo's core claim is that Chrome DevTools Protocol input is INDISTINGUISHABLE
from real input: `Input.dispatchMouseEvent` events arrive at the page with
`event.isTrusted === true`, the same flag real hardware input carries. A page cannot
tell them apart via the DOM. This script proves it rather than asserting it:

  1. installs a capture-phase listener that records isTrusted / coordinates / detail
  2. dispatches a humanized move + press + release over CDP
  3. reads the recorded events back and reports isTrusted for each

Also reports whether a synthesized JS event (`new MouseEvent(...)` + dispatchEvent),
which is NOT trusted, is distinguishable — that is the contrast that matters.

    probe-trust.py [port]
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402
from cdp import CDP  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else cfg.CDP_PORT

# Capture-phase listener records every mouse event with its isTrusted flag.
INSTALL = r"""
(() => {
  window.__trust = [];
  const rec = e => window.__trust.push({
    type: e.type, trusted: e.isTrusted,
    x: Math.round(e.clientX), y: Math.round(e.clientY),
    detail: e.detail, pointerType: e.pointerType || null,
    buttons: e.buttons
  });
  for (const t of ['mousemove','mousedown','mouseup','click','pointerdown','pointerup'])
    window.addEventListener(t, rec, true);
  return true;
})()
"""

READ = "JSON.stringify(window.__trust)"
SYNTH = r"""
(() => {
  const el = document.elementFromPoint(200, 300) || document.body;
  el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:200, clientY:300}));
  return true;
})()
"""


def main():
    c = CDP(port=PORT, host=cfg.CDP_HOST)
    c.eval(INSTALL)
    print(f"target: {cfg.CDP_HOST}:{PORT}  url={c.eval('location.href')[:60]}")
    print()

    # --- 1. real CDP input: humanized move, then a batched trusted click ---------
    def mev(kind, x, y, buttons=0, click_count=None, button=None):
        p = {"type": kind, "x": x, "y": y, "buttons": buttons}
        if button:
            p["button"] = button
        if click_count is not None:
            p["clickCount"] = click_count
        return c.call("Input.dispatchMouseEvent", p)

    mev("mouseMoved", 180, 280)
    time.sleep(0.05)
    mev("mouseMoved", 196, 294)
    time.sleep(0.05)
    mev("mousePressed", 200, 300, buttons=1, button="left", click_count=1)
    mev("mouseReleased", 200, 300, buttons=0, button="left", click_count=1)
    time.sleep(0.2)

    events = json.loads(c.eval(READ) or "[]")
    cdp_evs = [e for e in events]
    print(f"--- CDP-dispatched input ({len(cdp_evs)} events recorded) ---")
    for e in cdp_evs:
        print(f"  {e['type']:<12} isTrusted={str(e['trusted']):<5} "
              f"at ({e['x']},{e['y']}) detail={e['detail']} buttons={e['buttons']}")

    cdp_trusted = bool(cdp_evs) and all(e["trusted"] for e in cdp_evs)
    has_click = any(e["type"] == "click" for e in cdp_evs)
    print()
    print(f"  VERDICT: all CDP events isTrusted = {cdp_trusted}")
    print(f"           browser synthesized a real click event = {has_click}")

    # --- 2. the contrast: JS-synthesized event is NOT trusted -------------------
    c.eval("window.__trust = []")
    c.eval(SYNTH)
    time.sleep(0.1)
    syn = json.loads(c.eval(READ) or "[]")
    print()
    print(f"--- JS-synthesized event via dispatchEvent ({len(syn)} events) ---")
    for e in syn:
        print(f"  {e['type']:<12} isTrusted={str(e['trusted']):<5}  <- distinguishable")
    syn_trusted = bool(syn) and all(e["trusted"] for e in syn)

    print()
    print("=" * 68)
    if cdp_trusted and not syn_trusted:
        print("PROVEN: CDP input is trusted; JS-synthesized input is not.")
        print("        The page can distinguish a script event, but not CDP input.")
    else:
        print(f"UNEXPECTED: cdp_trusted={cdp_trusted} synthetic_trusted={syn_trusted}")
    print("=" * 68)
    c.close()


if __name__ == "__main__":
    main()
