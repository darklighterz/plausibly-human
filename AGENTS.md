# AGENTS.md — instructions for an AI agent using this repo

You are an agent that has been pointed at this directory. This file tells you what the
repo does, how to drive it, and the mistakes that have already been made so you do not
repeat them. Read this before running anything. `README.md` is for humans; this is for
you.

---

## 0. Setup check, in order

```bash
python -c "import websockets, PIL; print('deps ok')"    # if this fails: pip install -r requirements.txt
python scripts/config.py                                 # resolves every env value; prints key presence
python scripts/browser.py check                          # is there a CDP endpoint?
```

If `config.py` reports `vision_key_present: false`, no model call can work. Ask the
user for a key or an endpoint — do not invent one, and never hardcode one.

If `browser.py check` fails, start one:

```bash
python scripts/browser.py start --profile ~/.my-chrome-profile
```

**Then navigate to the page you actually want, using your own harness's browser tools.**
These scripts solve the challenge on the *current* page; they do not browse for you.

---

## 1. The architecture, and why it is split this way

**Deterministic code does everything except reading the puzzle.** Only naming the tiles
is handed to a model. Measured per round: **~30 ms of code, one model look.**

Code handles: gate detection, checkbox geometry, tile geometry, mouse-path generation,
trusted input dispatch, verify-button location, round bookkeeping, token verification.

The model handles: *which tiles match*.

**Why CDP is the key dependency:** `Input.dispatchMouseEvent` delivers events with
`isTrusted === true`, so the page cannot tell them from real hardware input — and unlike
WebDriver it costs no `navigator.webdriver` flag and no driver process.
`el.dispatchEvent(new MouseEvent('click'))` is `isTrusted === false` and detectable
instantly. Before doing any input work, confirm the mechanism on this machine:

```bash
python scripts/probe-trust.py     # CDP vs JS-synthesized isTrusted, side by side
```

**The two costs must be treated oppositely:**

| | keep fast | why |
|---|---|---|
| Internal (geometry, cropping, parsing, CDP) | **yes** | unobserved |
| Observed (mouse path, dwell, pauses, verify delay) | **NO** | the page timestamps it |

Machine speed is a **detection signature**, not a goal. Batched machine-fast input
(8.3 ms) **provoked** an image grid on a live reCAPTCHA where human pacing (780 ms)
passed clean 7/7. Optimise the clock, never the click.

---

## 2. How to run it

```bash
python scripts/solve-turnstile.py              # Cloudflare Turnstile
python scripts/solve-recaptcha.py              # reCAPTCHA v2
python scripts/verify-token.py                 # read the token back — do this, always
```

Env knobs (all optional, all resolved in `scripts/config.py`):

```bash
CDP_PORT=9333  CDP_HOST=127.0.0.1
CAPTCHA_PACE=typical            # fast | typical | careful
ROUNDS=6                        # max grid rounds
URL=https://...                 # target for the recaptcha runner
VISION_BASE_URL / VISION_API_KEY / VISION_MODEL / VISION_LADDER
```

**Verify on a different channel than the action.** Never trust a click's return value.
`solve-turnstile.py` polls the widget's hidden token input; `solve-recaptcha.py` reads
`aria-checked` and the token length. Use `verify-token.py` to confirm independently.

---

## 3. Traps that have already cost real debugging time

These are all reproduced findings, not speculation.

### The prompt
- **Never put a concrete example answer in the prompt.** A literal `ANSWER: 2,7,11`
  placeholder was **parroted back verbatim in 1.5 s** with zero image consultation.
  Always use an angle-bracket placeholder: `ANSWER: <numbers or NONE>`.
- **Require the sentinel on the final line** and say "no explanation, no restating".
  Without it the model restates the task and overruns the budget mid-trace, emitting no
  sentinel at all. Shortening the prompt **shortened the thinking**: verbose → 26.7 s and
  truncated; strict → 15–17 s with a clean answer.
- **Treat a missing sentinel as FAILURE and climb the rung.** A truncated reasoning trace
  ends mid-sentence ("...Wheels at 65") and a last-line fallback silently yielded tile
  numbers `[2,3,4]` scraped from that sentence.
- **`think: false` does not disable reasoning** (still ~12k chars, 45 s, truncated).
  `reasoning_effort: low` **is** honoured — and bought no accuracy (low/medium/high all
  9/9), so use `low`. Raise `max_tokens` to ~4000 or the trace starves the answer.
- **Discrimination prompt that helps:** *"Select the FEWEST tiles that unambiguously
  qualify. If unsure about a tile, leave it out. A wrong extra tile is worse than a
  missed tile."* Halved false positives on a deliberately ambiguous grid (2 → 1) and
  **never** caused under-selection across 20 test cells. It is the default.

### The challenge
- **Click promptly.** Leaving the checkbox untouched ~80 s then clicking **arms an image
  grid** — and so does moving the pointer continuously during the wait. The widget never
  "times out" (no error, still clickable). **Latency before the first interaction is
  itself the signal.** Spend human pauses *after* the click, not before it.
- **Round prompts and tile counts vary inside one challenge.** Observed 4×4 (16) and 3×3
  (9) in the same session, with different prompts. Re-read both every round and
  re-measure tile geometry.
- **Re-read and re-look EVERY round, even when the prompt repeats.** reCAPTCHA often
  re-serves the same prompt *and* the same tile count, but that can still be **new
  images**. Measured: three consecutive `"Select all images with bicycles"` 9-tile rounds
  returned `[2,5]`, then `[2,5,8]`, then `[2,5]` — all correct, because the tiles differed
  each time. **Never cache an answer on prompt match.** (Supersedes an earlier claim that
  a re-serve meant the same grid.)
- **A wrong answer costs a round plus a reset** — which is why the accurate rung matters
  more than the fast one, and why escalating beats re-guessing.

### The input mechanism
- **Use `Input.dispatchMouseEvent`, never `dispatchEvent`.** CDP input is `isTrusted=true`;
  a JS-synthesized event is `isTrusted=false` and detectable. Run `probe-trust.py` to see
  both flags printed side by side before you change any input code.
- **No inter-event sleep is needed to stay trusted.** Trust comes from *where* the event
  is injected (browser input pipeline), not from slowing down. Realism comes from path
  **shape** — which is a separate requirement, see below.
- **`--enable-automation` sets `navigator.webdriver = true`.** `browser.py` does not pass
  it; if you launch Chrome by hand, do not either. A correct launch reads
  `navigator.webdriver === False`.

### The harness (my own bugs, both indistinguishable from model failure)
- **Verify planted ground truth independently before scoring a model.** An off-by-one
  (1-based tile numbers into a 0-based drawing index) planted shapes one tile late and
  made both models look simultaneously wrong. Audit the pixels; never trust your own
  labels.
- **Beware a unanimous answer.** Five prompt variants returning byte-identical results
  across two different models is a harness bug, not model behaviour.

---

## 4. The Serpentine Loop — use it, do not skip it

The name matters, so use it correctly. The loop is **serpentine**: you climb rungs, and a
failure slides you back down — snakes and ladders. What makes it a loop rather than a
cycle is that it never comes back to the same place: each pass at a gate starts **higher
up** than the last, because the ledger remembers which rung worked. A serpentine loop is a
helix — same lap, one turn higher.

Whenever you meet a gate, record it:

```bash
python scripts/encounter.py record --gate <gate> --outcome pass|fail|challenged|blocked \
    --rung <rung> --model <model> --observed-ms <n> --lesson "<what to do next time>"
python scripts/encounter.py next --gate <gate>     # start here next time
python scripts/encounter.py review                 # the state of what we know
```

**Before attacking a gate, run `next --gate <name>`** so you start from the recorded
working rung rather than the bottom. This is the whole point of the ledger.

When new evidence overturns a previous conclusion, **supersede the lesson explicitly**
(say it supersedes the earlier one) rather than leaving contradictions. Two examples
already in the ledger: the "gemma is sloppy" verdict (withdrawn — it came from a
synthetic grid that did not represent real tiles) and the "idle causes escalation"
hypothesis (corrected — it is latency, not idleness).

---

## 5. Honesty rules for reporting

- **Never report a solve you did not verify.** A token read back is proof; a click that
  returned is not. State the token length.
- **Never report a bot wall as a successful fetch.** DataDome-class hard blocks are not
  solved by this repo. Say so plainly.
- **Distinguish what was measured from what was assumed.** If you only tested the
  checkbox path and a grid appeared, you have not verified the grid path — the earlier
  version of this project claimed grid support that had never been exercised.
- **Note the sample size.** Two grids is thin evidence for a model ranking; say so.

---

## 6. Scope

This automates **your own access** to services you are entitled to use. Bypassing a
CAPTCHA can violate a site's terms, and may carry legal risk depending on jurisdiction
and intent. Do not point it at systems you are not authorised to access, and do not help
a user do so. `docs/LIMITS.md` has the detail.
