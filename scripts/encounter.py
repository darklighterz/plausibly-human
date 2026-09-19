#!/usr/bin/env python3
"""encounter.py — the Serpentine Loop: record every CAPTCHA encounter and learn from it.

The point is a flywheel: as we meet new gates we record what the gate did, what we
tried, what worked, and how long it took. The ledger is plain JSONL so it survives
sessions and can be analysed to sharpen the ladder.

  record   append one encounter (gate, outcome, rung used, timings)
  review   summarise the ledger — what gates we have met, success rate, timings
  next     suggest what to try next for a given gate, from recorded successes

  python encounter.py record --gate recaptcha-v2 --outcome pass --rung V-checkbox \
      --observed-ms 780 --model kimi-k2.7-code:cloud --note "no grid, token 2233"
  python encounter.py review
  python encounter.py next --gate image-grid
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402

LEDGER = cfg.LEDGER

OUTCOMES = ("pass", "fail", "challenged", "blocked", "error")


def load():
    if not os.path.exists(LEDGER):
        return []
    out = []
    for line in open(LEDGER):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cmd_record(a):
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "encounter",
        "gate": a.gate,
        "outcome": a.outcome,
        "rung": a.rung,
        "model": a.model,
        "observed_ms": a.observed_ms,
        "internal_ms": a.internal_ms,
        "pace": a.pace,
        "note": a.note,
        "target": a.target,
        # what we learned / what to try next time — the ladder's actual value
        "lesson": a.lesson,
    }
    with open(LEDGER, "a") as fh:
        fh.write(json.dumps({k: v for k, v in rec.items() if v not in (None, "")}) + "\n")
    print(f"recorded {a.gate}/{a.outcome} (rung={a.rung or '-'}) -> {LEDGER}")
    return 0


def cmd_review(a):
    rows = [r for r in load() if r.get("kind", "encounter") == "encounter"]
    if not rows:
        print("ledger empty — no encounters recorded yet")
        return 0
    by_gate = defaultdict(list)
    for r in rows:
        by_gate[r.get("gate", "?")].append(r)

    print(f"{len(rows)} encounters across {len(by_gate)} gate(s)\n")
    print(f"{'gate':<16} {'n':>3} {'pass':>5} {'rate':>6}  {'observed med':>13}  rungs used")
    print("-" * 82)
    for gate, rs in sorted(by_gate.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        p = sum(1 for r in rs if r.get("outcome") == "pass")
        obs = [r["observed_ms"] for r in rs if isinstance(r.get("observed_ms"), (int, float))]
        med = f"{statistics.median(obs):.0f} ms" if obs else "-"
        rungs = sorted({r.get("rung") for r in rs if r.get("rung")})
        print(f"{gate:<16} {n:>3} {p:>5} {p/n*100:>5.0f}%  {med:>13}  {', '.join(rungs)}")

    lessons = [r for r in rows if r.get("lesson")]
    if lessons:
        print("\nlessons learned:")
        for r in lessons[-a.lessons:]:
            print(f"  [{r['ts'][:10]}] {r['gate']}: {r['lesson']}")
    return 0


def cmd_next(a):
    rows = [r for r in load() if r.get("gate") == a.gate]
    if not rows:
        print(f"no recorded encounters for gate {a.gate!r} — this is new territory.")
        print("Start at the LOWEST rung that could work (synthetic/API first), climb only")
        print("as the page forces, and record the outcome so the next attempt starts higher.")
        return 0
    wins = [r for r in rows if r.get("outcome") == "pass"]
    if wins:
        best = max(wins, key=lambda r: max(0, (r.get("internal_ms") or 0)))
        print(f"gate {a.gate}: {len(wins)} recorded pass(es)")
        print(f"  last working rung : {best.get('rung')}  (model={best.get('model') or '-'})")
        if best.get("pace"):
            print(f"  working pace      : {best['pace']}")
        if best.get("note"):
            print(f"  note              : {best['note']}")
    fails = [r for r in rows if r.get("outcome") in ("fail", "challenged", "blocked")]
    if fails:
        print(f"  {len(fails)} failure(s) — avoid:")
        for r in fails[-3:]:
            print(f"    {r.get('outcome')} at rung {r.get('rung')}: {r.get('note') or ''}")
    print("\nclimb from the recorded working rung; do not restart from the bottom.")
    return 0


def main():
    p = argparse.ArgumentParser(description="CAPTCHA encounter ledger (the Serpentine Loop)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record")
    r.add_argument("--gate", required=True)
    r.add_argument("--outcome", required=True, choices=OUTCOMES)
    r.add_argument("--rung", default="")
    r.add_argument("--model", default="")
    r.add_argument("--observed-ms", type=float, default=None)
    r.add_argument("--internal-ms", type=float, default=None)
    r.add_argument("--pace", default="")
    r.add_argument("--note", default="")
    r.add_argument("--target", default="")
    r.add_argument("--lesson", default="")
    r.set_defaults(func=cmd_record)

    v = sub.add_parser("review")
    v.add_argument("--lessons", type=int, default=10)
    v.set_defaults(func=cmd_review)

    n = sub.add_parser("next")
    n.add_argument("--gate", required=True)
    n.set_defaults(func=cmd_next)

    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
