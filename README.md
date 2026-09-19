# captcha-meatbag

Solve CAPTCHA challenges in a real browser, at a speed that is fast where nobody is
watching and human where the page is.

**Harness agnostic.** Nothing here depends on Hermes, Claude Code, opencode, Cursor,
Aider or any other agent runtime. It is plain Python talking to Chrome over the
DevTools Protocol. Any agent that can run a shell command can use it, and so can you.

---

## The one idea worth understanding first

There are two kinds of cost in this problem, and they must be treated oppositely:

| | keep it fast | why |
|---|---|---|
| **Internal** — geometry, cropping, deciding, parsing, CDP transport | **yes** | nobody observes it |
| **Observed** — mouse path, per-click dwell, thinking pauses, verify delay | **no** | the page timestamps all of it |

Machine speed is *not* the goal — it is a **detection signature**. Measured on a live
reCAPTCHA v2 checkbox, same target, two ways:

| Approach | Observed input phase | Result |
|---|---|---|
| Machine speed, all input batched into one round-trip | **8.3 ms** | **image grid SERVED** |
| Human-paced | 780 ms | **PASS, no grid** — 7/7 attempts |

So: speed buys you **flexibility** (beating the challenge clock). It must not be spent
on clicking fast. Code does the deterministic work at machine speed; the only thing
handed to a model is reading the puzzle.

Per round that works out to roughly **30 ms of code and one model look**.

---

## Quickstart

```bash
git clone <this repo> && cd captcha-meatbag
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 1. a Chromium with CDP enabled (bring a persistent profile to keep logins)
python scripts/browser.py start --profile ~/.my-chrome-profile
python scripts/browser.py check

# 2. credentials for whatever vision endpoint you use
export VISION_API_KEY=...           # any OpenAI-compatible endpoint

# 3. confirm the environment resolves
python scripts/config.py
```

Then solve something:

```bash
python scripts/solve-turnstile.py            # Cloudflare Turnstile checkbox
python scripts/solve-recaptcha.py            # reCAPTCHA v2 (checkbox, and grid if served)
python scripts/verify-token.py               # did it work? read the token back
```

Navigating the browser is your harness's job (or `browser.py` plus any CDP call).
These scripts solve **the challenge on the page you are already on**.

---

## What is verified, and what is not

Measured live on this stack. Do not read this as a claim about every site.

| Gate | Result |
|---|---|
| Cloudflare Turnstile (managed) | **PASS** — trusted click on the widget glass, 773-char token |
| reCAPTCHA v2 checkbox | **PASS 7/7** human-paced, no grid provoked, ~2300-char token |
| reCAPTCHA v2 image grid | **PASS** — multi-round, both 4×4 (16 tile) and 3×3 (9 tile) |
| Hard grid classes | bicycles, cars, buses, bridges, crosswalks, **traffic lights** all solved |

The `traffic lights` solve is the strongest single data point: 16 tiles, small
low-contrast targets routinely confused with car lamps and reflectors, solved in
**one round at 843 ms**.

**Not verified:** other vendors (DataDome, Akamai, hCaptcha, PerimeterX) are **not**
covered. Hard blocks remain hard. See `docs/LIMITS.md` — read it before trusting this
anywhere that matters.

---

## Models

Vision is the only place a model is used, and it is an **ordered ladder**: climb only as
far as needed. Default ordering, measured on real grids:

| Rung | Model | Measured | Role |
|---|---|---|---|
| **V1** | **`gemma4:31b`** | **765–1225 ms** | fast, real-grid proven — leads |
| V2 | `kimi-k2.7-code:cloud` | 15 000+ ms, truncates | reasoning; true second opinion |
| V3 | `minimax-m3` | ~2.7 s | alternate |
| V4 | `qwen3.5:397b` | ~7 s | last resort |

Why the *fast* model leads: a wrong grid answer costs a full round **plus** a reset, and
at 15 s the reasoning model was still slower *and* hit the token cap mid-trace. Gemma
returns in about a second, so it is both the quicker and the more reliable rung here.

**Any OpenAI-compatible endpoint works** — this is not tied to one provider:

```bash
export VISION_BASE_URL=https://ollama.com/v1     # default
export VISION_LADDER="gemma4:31b,my-model:latest"
export VISION_MODEL=my-model                     # single-model override
```

Reasoning models need care; the rules that matter are in `docs/MODELS.md`, and two of
them are load-bearing:

- **`think: false` does not turn thinking off** on `kimi-k2.7-code` (still ~12k chars of
  trace, 45 s, truncated). `reasoning_effort: low|medium|high` **is** honoured — and on
  real grids it bought no accuracy (all three levels 9/9), so use `low` for the speed.
- **The `ANSWER:` sentinel is mandatory.** A reasoning model that runs out of tokens
  returns an unterminated sentence, and a "last line" fallback will silently parse
  garbage out of it.

---

## The improving loop

Every encounter is recorded, so the ladder sharpens from what actually happened instead
of being re-derived each time:

```bash
python scripts/encounter.py record --gate image-grid --outcome pass --rung V1 \
    --observed-ms 2641 --lesson "traffic lights 16-tile, one round"
python scripts/encounter.py review          # what we have met, pass rate, timings
python scripts/encounter.py next --gate image-grid   # where the NEXT attempt should start
```

`data/ladder-encounters.jsonl` is the append-only ledger (shipped populated with real
findings). When evidence overturns a rung's rank, **supersede the lesson explicitly**
rather than leaving two contradictory entries.

---

## Layout

```
scripts/
  config.py           all environment-specific values, in one place
  cdp.py              persistent CDP client (~0.74 ms/call vs ~142 ms one-shot)
  human_timing.py     human pacing profiles; internal vs observed time accounting
  vision_ladder.py    ordered vision rungs + prompt engineering
  solve-turnstile.py  Cloudflare Turnstile
  solve-recaptcha.py  reCAPTCHA v2 (checkbox + image grid)
  verify-token.py     read the response token back
  encounter.py        the improving loop (record / review / next)
  browser.py          start/check/stop a CDP Chromium
  bench.py            measure CDP latency
  ascii-view.py       render an image region as a luminance map (layout debugging)
data/
  ladder-encounters.jsonl
docs/
  MODELS.md           vision models, prompts, and the traps
  LIMITS.md           what is NOT verified; the ethics and legal notes
  SETUP.md            harness-specific notes (Hermes, Claude Code, opencode, ...)
```

## Dependencies

Two: `websockets` (persistent CDP transport) and `Pillow` (crop the grid for the
model). `curl` for the vision call — swap it for `urllib` if you prefer. Everything
else is stdlib. See `requirements.txt`.

---

## Ethics and legality

This is a tool for **automating your own access** to services you are entitled to use —
your own accounts, your own research, your own testing of your own or authorised
systems. Bypassing a CAPTCHA on a site can violate its terms of service, and in some
jurisdictions accessing a system in a manner its owner has prohibited can carry legal
risk. You are responsible for where you point it. Read `docs/LIMITS.md`.

Licence: MIT.
