#!/usr/bin/env python3
"""solve-turnstile.py — solve a Cloudflare Turnstile checkbox plausibly-humanly.

The whole point: the checkbox is unreachable by DOM (closed shadow root -> cross-origin
iframe -> inner shadow root). So don't grab it. Ask the browser where the iframe sits,
work out where the checkbox is on that glass, and fire a TRUSTED click at that viewport
point — Chrome routes it into the cross-origin frame for us.

Rungs used:
  Rung 1 (free)      DOM.getBoxModel  -> find the widget box via the pierced DOM
  Rung 2 (trusted)   Input.dispatchMouseEvent -> a real click the page cannot fake-detect
  Rung 3 (human)     eased approach path with jitter, dwell before press

Verifies through a DIFFERENT channel than the action: after clicking it does not trust
the click return value — it polls the widget's response token input.

Two limits measured on a live Cloudflare interstitial (1337x, cookieless profile):
  * This rung cannot see widget STATE. The challenge iframe is cross-origin, so there
    is no DOM and no pixels for it: while Cloudflare serves the SPINNER variant the
    click is a no-op (3 wasted attempts measured). If nothing passes after a couple of
    tries, fall back to a pixel pass that detects spinner-vs-checkbox and waits.
  * Coordinates here are VIEWPORT coordinates, which is the point — do NOT convert them
    to screen space. That mapping was measured ~20 px x / ~26 px y off, and screen
    captures are also vulnerable to window occlusion.

Transport: this uses the persistent CDP client (cdp.py), not a one-shot CLI. A one-shot
CLI costs ~142 ms per call versus ~0.74 ms here, and the challenge clock is the adversary.

Config: CDP_PORT / CDP_HOST, CAPTCHA_PACE.

    solve-turnstile.py [--dry-run]
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402
from cdp import CDP  # noqa: E402
from human_timing import Clock  # noqa: E402

DRY = "--dry-run" in sys.argv
_c = None


def conn() -> CDP:
    """One persistent client, reused for every call."""
    global _c
    if _c is None:
        _c = CDP(port=cfg.CDP_PORT, host=cfg.CDP_HOST)
    return _c


def cdp(method, params=None):
    """CDP call over the persistent socket. Kept as a thin wrapper so the rest of this
    script reads the same as the original one-shot version."""
    try:
        return conn().call(method, params or {})
    except Exception as e:                                    # noqa: BLE001
        return {"_err": f"{type(e).__name__}: {e}"}


def box_of_widget():
    """Find the Turnstile iframe box via the pierced DOM (sees through shadow roots)."""
    d = cdp("DOM.getDocument", {"depth": -1, "pierce": True})
    root = d.get("result", d).get("root")

    def walk(n):
        if n.get("nodeName") == "IFRAME":
            attrs = dict(zip(n.get("attributes", [])[0::2], n.get("attributes", [])[1::2]))
            src = attrs.get("src", "")
            if "challenges.cloudflare.com" in src or "turnstile" in src:
                return n.get("backendNodeId"), src
        for k in ("children", "shadowRoots"):
            for c in n.get(k, []) or []:
                r = walk(c)
                if r:
                    return r
        if n.get("contentDocument"):
            return walk(n["contentDocument"])
        return None

    hit = walk(root) if root else None
    if not hit:
        return None, None
    backend, src = hit
    resp = cdp("DOM.getBoxModel", {"backendNodeId": backend})
    # NOTE: getBoxModel returns {"model": {...}} with NO "result" wrapper. Unwrapping
    # with .get("result", {}) silently yields {} and looks like "no widget found".
    model = resp.get("model") or resp.get("result", {}).get("model") or resp.get("result", {})
    q = model.get("content") or model.get("border")
    if not q:
        return None, None
    xs, ys = q[0::2], q[1::2]
    return {"x": min(xs), "y": min(ys), "w": max(xs) - min(xs), "h": max(ys) - min(ys)}, src


def token():
    """Read the widget's response token straight from the page's hidden inputs."""
    js = ("(()=>{const r=document.querySelector('input[name=\"cf-turnstile-response\"]'),"
          "g=document.querySelector('input[name=\"g-recaptcha-response\"]');"
          "return JSON.stringify({cf:(r&&r.value||'').length,gr:(g&&g.value||'').length,"
          "body:document.body.innerText.replace(/\\n+/g,' | ').slice(0,180)});})()")
    v = conn().eval(js)
    if isinstance(v, str):
        import json
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return {"raw": v[:200]}
    return v if isinstance(v, dict) else {"raw": str(v)[:200]}


def stray_targets():
    """Page targets on this CDP endpoint (see main() for why this is checked).

    With more than one page target a single-target transport can resolve the WRONG
    tab — and a mis-click that opened a tab is the usual way one appears. Measured
    on a live gate: a read returned an EMPTY body/title, which a naive success check
    accepted as "solved" on a page that had not been solved at all.
    """
    import json
    import urllib.request
    try:
        tg = json.load(urllib.request.urlopen(
            f"http://{cfg.CDP_HOST}:{cfg.CDP_PORT}/json", timeout=5))
    except Exception:
        return None
    return [t for t in tg if t.get("type") == "page"]


def human_move(tx, ty, steps=22):
    """Rung 3: eased approach from the lower-left with jitter, like a hand."""
    sx, sy = tx - random.randint(180, 260), ty + random.randint(120, 190)
    for i in range(1, steps + 1):
        t = i / steps
        ease = 1 - (1 - t) ** 3                       # ease-out cubic
        # slight downward bow in the path, plus per-step jitter
        bow = -abs(t - 0.5) * 14
        x = sx + (tx - sx) * ease + random.uniform(-1.8, 1.8)
        y = sy + (ty - sy) * ease + bow + random.uniform(-1.8, 1.8)
        cdp("Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": round(x), "y": round(y), "buttons": 0})
        time.sleep(random.uniform(0.008, 0.020))
    # settle: a tiny overshoot then back, then dwell
    for dx, dy in ((2.5, -1.5), (-1.2, 0.6), (0, 0)):
        cdp("Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": round(tx + dx), "y": round(ty + dy), "buttons": 0})
        time.sleep(random.uniform(0.012, 0.030))


def click(tx, ty):
    cdp("Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": tx, "y": ty, "button": "left", "clickCount": 1})
    time.sleep(random.uniform(0.06, 0.13))
    cdp("Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": tx, "y": ty, "button": "left", "clickCount": 1})


def main():
    print(f"target: {cfg.CDP_HOST}:{cfg.CDP_PORT}")
    pages = stray_targets()
    if pages is not None and len(pages) > 1:
        # A single-target transport can resolve the wrong tab, and an EMPTY read then
        # looks like success. Measured on a live gate: a mis-click opened a tab and a
        # naive check passed on a page that had not been solved. Close strays over raw
        # HTTP (no websocket): GET /json/close/<targetId>
        print(f"WARNING: {len(pages)} page targets — reads may come from the wrong tab")
        for p in pages:
            print(f"   {p['id'][:8]}  {p.get('url','')[:70]}")
        print("   close strays first: curl http://%s:%s/json/close/<targetId>"
              % (cfg.CDP_HOST, cfg.CDP_PORT))

    before = token()
    print(f"before: {before}")

    box, src = None, None
    # Cloudflare re-mounts the widget, so there are windows with no iframe present.
    for attempt in range(1, 11):
        box, src = box_of_widget()
        if box:
            break
        print(f"  (widget not mounted yet, retry {attempt}/10)")
        time.sleep(1.5)
    if not box:
        print("FAIL: no Turnstile iframe found (widget not mounted?)")
        return 2
    print(f"iframe box: x={box['x']:.0f} y={box['y']:.0f} w={box['w']:.0f} h={box['h']:.0f}")
    print(f"iframe src: {src[:110]}")

    # checkbox sits ~24px in from the left edge, vertically centred
    tx = round(box["x"] + 24)
    ty = round(box["y"] + box["h"] / 2)
    print(f"target checkbox point: ({tx}, {ty})   [iframe.x+24, iframe.y+h/2]")
    if DRY:
        print("dry-run: not clicking")
        return 0

    human_move(tx, ty)
    click(tx, ty)
    print("trusted click dispatched; verifying via token input (different channel)")

    for i in range(1, 11):
        time.sleep(1.5)
        now = token()
        state = {k: now.get(k) for k in ("cf", "gr")}
        print(f"  t+{i*1.5:>4.1f}s  token={state}  body={str(now.get('body'))[:100]}")
        if (now.get("cf") or 0) > 20 or (now.get("gr") or 0) > 20:
            print(f"\nPASS — token issued ({now.get('cf')} / {now.get('gr')} chars)")
            return 0
    print("\nNO TOKEN after 15s — escalated to a challenge, or the click missed")
    print("final state:", token())
    return 1


if __name__ == "__main__":
    sys.exit(main())
