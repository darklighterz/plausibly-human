#!/usr/bin/env python3
"""solve-recaptcha.py — reCAPTCHA v2 solve (checkbox, then image grid if served).

Full pipeline against a REAL challenge:

  1. human-paced trusted click on the anchor checkbox (pauses, eased path)
  2. if a grid arms, measure tiles from the bframe
  3. spend the model look as the human "thinking" pause (see human_timing.py)
  4. select the tiles with human pacing, press verify, report

Multi-round aware: reCAPTCHA serves several rounds back to back, sometimes RE-SERVES
the identical prompt, and varies tile count between rounds (16 and 9 both occur), so
this re-reads the prompt and the tile geometry every round until a token appears.

Deterministic code does everything except naming the tiles; the vision ladder is the
only model call (see vision_ladder.py for the rung ordering and why).

Config: CDP_PORT / CDP_HOST, CAPTCHA_PACE, ROUNDS, URL, GRID_SHOT (screenshot path).

    solve-recaptcha.py [cdp-port]
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402
from cdp import CDP  # noqa: E402
from human_timing import Clock  # noqa: E402
import vision_ladder as vl  # noqa: E402

CDP_PORT = int(next((a for a in sys.argv[1:] if a.isdigit()), cfg.CDP_PORT))
PACE = cfg.PACE
MAX_ROUNDS = int(os.environ.get("ROUNDS", "6"))
URL = os.environ.get("URL", "https://www.google.com/recaptcha/api2/demo")
# Grid screenshot target. Kept out of /tmp by default so a fresh clone has no magic
# paths; override GRID_SHOT to redirect.
GRID_SHOT = os.environ.get("GRID_SHOT", os.path.join(cfg.REPO_ROOT, "data", "grid.png"))

PROBE = r"""
(()=>{
  const out={state:'none'};
  const anchors=[...document.querySelectorAll('iframe')].filter(f=>(f.src||'').includes('/recaptcha/api2/anchor'));
  const bfs=[...document.querySelectorAll('iframe')].filter(f=>(f.src||'').includes('/recaptcha/api2/bframe'));
  const g=document.querySelector('textarea[name="g-recaptcha-response"],#g-recaptcha-response');
  out.token=g?(g.value||'').length:0;
  if(anchors.length){
    const f=anchors[0], fr=f.getBoundingClientRect();
    out.anchor={x:Math.round(fr.x),y:Math.round(fr.y),w:Math.round(fr.width),h:Math.round(fr.height)};
    try{
      const d=f.contentDocument, cb=d&&d.querySelector('.recaptcha-checkbox');
      if(cb){ out.checked=cb.getAttribute('aria-checked');
        const cr=cb.getBoundingClientRect();
        out.cb={x:Math.round(fr.x+cr.x+cr.width/2), y:Math.round(fr.y+cr.y+cr.height/2)};
      } else out.checked=null;
    }catch(e){ out.anchorErr=e.name; }
  }
  if(bfs.length){
    const b=bfs[0], br=b.getBoundingClientRect();
    out.bframe={x:Math.round(br.x),y:Math.round(br.y),w:Math.round(br.width),h:Math.round(br.height),
                armed: br.y > -100};
    try{
      const d=b.contentDocument;
      if(d){
        const tiles=[...d.querySelectorAll('.rc-imageselect-tile')].map(t=>{
          const r=t.getBoundingClientRect();
          return [Math.round(br.x+r.x+r.width/2), Math.round(br.y+r.y+r.height/2)];});
        out.tiles=tiles;
        const pd=d.querySelector('.rc-imageselect-desc-no-canonical')||d.querySelector('.rc-imageselect-desc');
        out.prompt=pd?pd.textContent.trim():'';
        const btn=d.querySelector('#recaptcha-verify-button');
        if(btn){ const rr=btn.getBoundingClientRect();
          out.btn={x:Math.round(br.x+rr.x+rr.width/2), y:Math.round(br.y+rr.y+rr.height/2),
                   text:btn.textContent.trim()}; }
        out.bframeErr=null;
      } else out.bframeErr='nodoc';
    }catch(e){ out.bframeErr=e.name; }
  }
  return JSON.stringify(out);
})()
"""


def grid_crop_box(st):
    """Region to send to the model: the challenge frame, full."""
    b = st.get("bframe") or {}
    return (b.get("x", 0), b.get("y", 0), b.get("w", 400), b.get("h", 580))


def main():
    c = CDP(port=CDP_PORT, host=cfg.CDP_HOST)
    clock = Clock(PACE)
    st = c.js(PROBE)
    print(f"start: token={st.get('token')} checked={st.get('checked')} bframe_armed="
          f"{(st.get('bframe') or {}).get('armed')}")

    # --- if not yet armed, human-paced click on the checkbox -----------------
    if not (st.get("bframe") or {}).get("armed") and st.get("checked") != "true":
        cb = st.get("cb")
        if not cb:
            print("FAIL: no reachable checkbox:", st)
            return 2
        print(f"clicking checkbox at ({cb['x']},{cb['y']}) with {PACE} pacing")
        clock.reaction()
        pts, step = clock.path(cb["x"] - 160, cb["y"] + 110, cb["x"], cb["y"])
        for (px, py, _b) in pts:
            c.mouse(px, py, "mouseMoved", buttons=0)
            time.sleep(step)
        c.mouse(cb["x"], cb["y"], "mousePressed", click_count=1, buttons=1)
        clock.tile_click_gap()
        c.mouse(cb["x"], cb["y"], "mouseReleased", click_count=1, buttons=0)
        time.sleep(random.uniform(1.0, 1.8))

    # --- solve rounds --------------------------------------------------------
    from PIL import Image  # noqa: F401  (kept for cropping below)

    for rnd in range(1, MAX_ROUNDS + 1):
        st = c.js(PROBE)
        if st.get("token", 0) > 20:
            print(f"\n*** PASS after {rnd-1} round(s) — token {st['token']} chars ***")
            print(f"PACE {PACE}: {clock.summary()}")
            c.close()
            return 0
        bf = st.get("bframe") or {}
        if not bf.get("armed"):
            print(f"round {rnd}: no armed grid (state={st.get('state')}) — waiting")
            time.sleep(2.5)
            continue
        tiles = st.get("tiles") or []
        prompt = st.get("prompt") or ""
        if len(tiles) != 16:
            print(f"round {rnd}: {len(tiles)} tiles, prompt={prompt!r}")
        print(f"round {rnd}: '{prompt}' | {len(tiles)} tiles")

        # spend the model look as the human think-pause, via the VISION LADDER
        clock.thinking()
        c.shot(GRID_SHOT)
        box = grid_crop_box(st)
        task = prompt
        t_v0 = time.perf_counter()
        tiles_picked, info = vl.solve(GRID_SHOT, box, task,
                                      n_tiles=len(tiles),
                                      prefer=os.environ.get("VISION_PREFER", "accuracy"),
                                      gate="image-grid")
        dt = info.get("ms", 0)
        clock.internal(t_v0)
        # enforce a human think floor: if vision beat it, wait out the remainder
        human_think_s = random.uniform(1.1, 2.3)
        if dt / 1000.0 < human_think_s:
            rem = human_think_s - dt / 1000.0
            time.sleep(rem)
            clock.observed_ms += rem * 1000
        print(f"  vision[rung {info.get('rung')} {info.get('model')}] {dt:.0f} ms "
              f"-> tiles {tiles_picked}")
        if info.get("tried") and len(info["tried"]) > 1:
            print(f"    escalated through: "
                  f"{[(t['rung'], t.get('error') or t.get('tiles')) for t in info['tried']]}")
        picked = tiles_picked

        # human-paced selection
        prev = None
        for i, n in enumerate(picked):
            x, y = tiles[n - 1]
            pts, step = clock.path(prev[0], prev[1], x, y) if prev else clock.path(
                x - 130, y + 80, x, y)
            for (px, py, _b) in pts:
                c.mouse(px, py, "mouseMoved", buttons=0)
                time.sleep(step)
            c.mouse(x, y, "mousePressed", click_count=1, buttons=1)
            clock.tile_click_gap()
            c.mouse(x, y, "mouseReleased", click_count=1, buttons=0)
            prev = (x, y)
            if i < len(picked) - 1:
                clock.per_tile()

        btn = st.get("btn")
        if btn and prev:
            clock.pre_verify()
            bpts, bs = clock.path(prev[0], prev[1], btn["x"], btn["y"])
            for (px, py, _b) in bpts:
                c.mouse(px, py, "mouseMoved", buttons=0)
                time.sleep(bs)
            c.mouse(btn["x"], btn["y"], "mousePressed", click_count=1, buttons=1)
            clock.tile_click_gap()
            c.mouse(btn["x"], btn["y"], "mouseReleased", click_count=1, buttons=0)
        time.sleep(random.uniform(1.2, 2.2))

    st = c.js(PROBE)
    ok = st.get("token", 0) > 20
    print(f"\nfinal: token={st.get('token')} checked={st.get('checked')} "
          f"armed={(st.get('bframe') or {}).get('armed')}")
    print(f"PACE {PACE}: {clock.summary()}")
    c.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
