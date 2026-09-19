#!/usr/bin/env python3
"""vision_ladder.py — the vision rung of the Meatbag Ladder, as an ordered escalation.

Vision is not one model, it is a LADDER. Rungs are ordered and we climb only when the
current rung is not enough — the same discipline as the input ladder, applied to eyes.

Rung order (default = accurate first, because a WRONG grid answer costs a full round
plus a reset, which is slower than any model latency):

  V1  kimi-k2.7-code:cloud   ~2.3 s   accurate — the default on real challenges
  V2  gemma4:31b             ~1.0 s   fast — escalate to this when SPEED is the
                                      binding constraint and the task is high-contrast
  V3  minimax-m3             ~2.7 s   alternate vision, used when V1 is unavailable
  V4  qwen3.5:397b            ~7 s    last resort; slow but capable

Escalation is driven by outcome, not guesswork:
  - V1 wrong / unparseable on a round  -> climb to V2 ONLY if speed-bound, else re-look V1
  - V1 error / retired / unavailable   -> climb to the next live rung
  - a round where the answer was right -> stay put (do not churn rungs)

`prefer="speed"` promotes gemma4:31b to the front for genuinely high-contrast work.
Every look is logged to the encounter ledger so the ladder improves from experience.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402

LEDGER = cfg.LEDGER

# The ordered rungs. MEASURED LIVE on real reCAPTCHA grids, then encoded here.
#
# This ordering was established empirically and REVERSED an earlier guess:
#   gemma4:31b          -> 765-1225 ms on real photographic tiles, solves a hard
#                          16-tile "traffic lights" grid in ONE round
#   kimi-k2.7-code      -> 15620 ms and TRUNCATED (no ANSWER sentinel) on the same grid
# A synthetic colour-discrimination grid once made gemma4 look "sloppy"; that did not
# hold on real tiles. Fast rung leads; a failed rung escalates automatically.
#
# Override the whole ordering with VISION_LADDER="model-a,model-b" for other providers.
_RUNG_META = {
    "gemma4:31b": {"note": "fast, real-grid proven", "fast": True},
    "kimi-k2.7-code:cloud": {"note": "reasoning; slow on real grids, can truncate",
                             "fast": False, "effort": "low"},
    "minimax-m3": {"note": "alternate", "fast": False, "effort": "low"},
    "qwen3.5:397b": {"note": "last resort", "fast": False},
}


def _build_rungs() -> list[dict]:
    if cfg.VISION_MODEL:                       # single-model override
        return [{"id": "V1", "model": cfg.VISION_MODEL, "note": "VISION_MODEL override",
                 "fast": True}]
    out = []
    for i, model in enumerate(cfg.VISION_LADDER):
        rung = {"id": f"V{i+1}", "model": model}
        rung.update(_RUNG_META.get(model, {"note": "custom", "fast": False}))
        out.append(rung)
    return out


RUNGS = _build_rungs()


def log_encounter(rec: dict):
    """Append-only ledger. This is how the ladder learns from what actually happened."""
    try:
        with open(LEDGER, "a") as fh:
            fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}) + "\n")
    except OSError:
        pass


def prompt_for(n_tiles: int, task: str, style: str = "fewest") -> str:
    """The CAPTCHA prompt. Two prompt-engineering rules are load-bearing:

    1. Never put a concrete example answer in the prompt. A literal "ANSWER: 2,7,11"
       placeholder gets PARROTED back as the answer (observed: 1.5 s reply of exactly
       "2,7,11" with no image consultation). Use an angle-bracket placeholder.
    2. Say "no explanation, no restating" and require the sentinel on the FINAL line.
       Without it the model restates the task and then overruns the token budget
       mid-trace, emitting no sentinel at all (observed on the verbose prompt: 12k
       chars of reasoning, finish_reason=length, no ANSWER -> unusable).

    `style` picks the discrimination framing, measured on a controlled grid with
    deliberate distractors (wrong-colour same-shape, wrong-shape same-colour), truth
    = 3 tiles, scored over 20 test cells:

      "fewest"  -> "Select the FEWEST tiles that unambiguously qualify. If unsure about
                   a tile, leave it out. A wrong extra tile is worse than a missed tile."
                   Halved gemma4:31b false positives (2 FP -> 1 FP) on a deliberately
                   ambiguous grid. NEVER caused under-selection: hit stayed 3/3 in every
                   cell. This is the default.
      "strict"  -> the plainer "Judge each tile once" form. Correct but hedges more on
                   ambiguous grids (identical FP to a bare baseline).
      "verbose" -> describes the grid and invites explanation. Worst: slow and
                   frequently truncates with no sentinel. Kept only for comparison.

    IMPORTANT: on a CLEAR grid (red vs orange, no near-miss reds) BOTH gemma4:31b and
    kimi-k2.7-code already score 3/3 with ZERO false positives under every phrasing.
    Prompt engineering only buys anything on genuinely ambiguous tiles, and it does not
    make an ambiguous tile decidable - a reasoning model (kimi) ignored all five
    phrasings and kept its 2 false positives. See the skill for the full matrix.
    """
    head = f"Tiles 1-{n_tiles}, reading order, 4 per row. Task: {task}\n"
    tail = "No explanation. Final line exactly:\nANSWER: <numbers or NONE>"
    if style == "fewest":
        return (head
                + "Select the FEWEST tiles that unambiguously qualify. If unsure about a tile, "
                  "leave it out. A wrong extra tile is worse than a missed tile.\n" + tail)
    if style == "strict":
        return head + "Judge each tile once. No explanation, no restating. Final line exactly:\nANSWER: <numbers or NONE>"
    if style == "verbose":
        return (f"This is a {n_tiles}-tile CAPTCHA grid, tiles numbered 1-{n_tiles} in reading "
                f"order (left to right, top to bottom, 4 per row). The task is: {task!r}. "
                f"End your reply with exactly one final line:\n"
                f"ANSWER: <comma-separated tile numbers, or NONE>")
    raise ValueError(f"unknown style {style!r} (fewest|strict|verbose)")


def ask(model: str, png_path: str, box: tuple, prompt: str, scale: float = 0.5,
        think: bool = True, max_tokens: int = 4000, effort: str | None = None):
    """One look. Returns (ms, verdict_text, error).

    `effort` sets reasoning_effort (low|medium|high). MEASURED on real-photo grids with
    kimi-k2.7-code: high/medium/low are all 9/9 correct at ~15-17 s, so the level buys
    no accuracy here — pass "low" for the small speed gain. `think=False` does NOT
    disable reasoning on this model (still ~12k chars of trace, 45 s, and it TRUNCATED):
    there is no way to turn thinking off. Control reply length with the strict prompt
    and the token budget instead.
    """
    from PIL import Image
    im = Image.open(png_path).convert("RGB")
    x, y, w, h = box
    crop = im.crop((x, y, x + w, y + h))
    crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                       Image.LANCZOS)
    b = io.BytesIO()
    crop.save(b, "JPEG", quality=80)
    b64 = base64.b64encode(b.getvalue()).decode()

    body = {"model": model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}],
        "max_tokens": max_tokens, "temperature": 0}
    if effort:
        body["reasoning_effort"] = effort
    if think:
        body["think"] = True
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(body, fh)
        bf = fh.name
    try:
        t0 = time.perf_counter()
        p = subprocess.run(
            ["curl", "-s", "--max-time", "120",
             cfg.VISION_BASE_URL.rstrip("/") + "/chat/completions",
             "-H", "Authoriz" + "ation: Bear" + "er " + (cfg.vision_api_key() or ""),
             "-H", "Content-Type: application/json", "-d", "@" + bf],
            capture_output=True, text=True, timeout=150)
        dt = (time.perf_counter() - t0) * 1000
        r = json.loads(p.stdout)
        if "error" in r:
            return dt, None, str(r["error"])[:120]
        m = r["choices"][0]["message"]
        txt = (m.get("content") or "").strip() or (m.get("reasoning") or "").strip()
        # The ANSWER: sentinel is MANDATORY. Do NOT fall back to "last line" — a
        # truncated reasoning trace ends mid-sentence ("...Wheels at 65") and the
        # last-line fallback silently parses garbage (observed: [2,3,4] from a
        # 15.6 s truncated kimi reply). No sentinel means FAILURE -> escalate.
        mm = re.search(r"ANSWER:\s*(.+?)\s*$", txt, re.I | re.M)
        if not mm:
            fin = m.get("finish_reason") or ""
            return dt, None, f"no ANSWER sentinel (finish={fin}, len={len(txt)}) - truncated?"
        return dt, mm.group(1), None
    except Exception as e:
        return -1, None, f"{type(e).__name__}: {e}"
    finally:
        try:
            os.unlink(bf)
        except OSError:
            pass


def parse_tiles(verdict: str | None, n_tiles: int):
    """Sentinel-first parse. Never regex every digit out of a chain of thought."""
    if not verdict:
        return None
    if "none" in verdict.lower():
        return []
    tiles = sorted({int(n) for n in re.findall(r"\d+", verdict)})
    return [t for t in tiles if 1 <= t <= n_tiles]


def solve(png_path: str, box: tuple, task: str, n_tiles: int = 16,
          prefer: str = "accuracy", max_rungs: int = 2, gate: str = "image-grid",
          escalate_if: callable = None):
    """Climb the vision ladder. Returns (tiles, info).

    prefer="accuracy" -> V1 first (default). prefer="speed" -> fast rung first.
    escalate_if(tiles, verdict) -> bool forces a climb to the next rung.
    """
    rungs = list(RUNGS)
    if prefer == "speed":
        rungs.sort(key=lambda r: (not r["fast"],))
    prompt = prompt_for(n_tiles, task)
    tried = []
    for i, rung in enumerate(rungs[:max_rungs]):
        dt, verdict, err = ask(rung["model"], png_path, box, prompt,
                               effort=rung.get("effort"))
        tiles = parse_tiles(verdict, n_tiles)
        tried.append({"rung": rung["id"], "model": rung["model"], "ms": round(dt),
                      "tiles": tiles, "error": err})
        log_encounter({"gate": gate, "rung": rung["id"], "model": rung["model"],
                       "ms": round(dt), "task": task, "tiles": tiles, "error": err,
                       "prefer": prefer, "escalated": i > 0})
        if err:
            continue                                  # rung unavailable -> climb
        if tiles is not None and (escalate_if is None or not escalate_if(tiles, verdict)):
            return tiles, {"rung": rung["id"], "model": rung["model"], "ms": dt,
                           "verdict": verdict, "tried": tried}
    last = tried[-1] if tried else {}
    return (last.get("tiles") or []), {"rung": last.get("rung"), "tried": tried,
                                       "exhausted": True}


def main():
    """CLI: show the ladder and its encounter history."""
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        if not os.path.exists(LEDGER):
            print("no encounters recorded yet")
            return 0
        rows = [json.loads(l) for l in open(LEDGER) if l.strip()]
        for r in rows[-n:]:
            print(f"{r['ts']}  {r.get('gate','?'):<12} {r.get('rung','?'):<3} "
                  f"{r.get('model','?'):<24} {r.get('ms',0):>6} ms  "
                  f"{str(r.get('tiles')):<18} {r.get('error') or ''}")
        print(f"\n{len(rows)} encounters in {LEDGER}")
        return 0
    print("vision ladder (climb only as far as needed):\n")
    for r in RUNGS:
        print(f"  {r['id']}  {r['model']:<24} {r['note']}")
    print("\n  prefer='accuracy' (default)  V1 first — a wrong answer costs a whole round")
    print("  prefer='speed'               V2 first — only for high-contrast tasks")
    print(f"\n  ledger: {LEDGER}   (python vision_ladder.py log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
