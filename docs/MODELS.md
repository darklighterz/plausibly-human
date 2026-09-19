# MODELS.md — the vision rung of the Serpentine Loop

Vision is the **only** place a model is used, and it is an ordered rung set: climb only as
far as needed. A failed rung escalates; a good rung is remembered, so the next pass at the
same gate starts higher up the board. Everything measured here was measured on real reCAPTCHA grids (bicycles,
cars, buses, bridges, crosswalks) unless stated otherwise.

## The rungs

| Rung | Model | Measured on real tiles | Role |
|---|---|---|---|
| **V1** | **`gemma4:31b`** | **765–1225 ms** | fast, real-grid proven — leads |
| V2 | `kimi-k2.7-code:cloud` | 15 620 ms, truncated | reasoning; second opinion |
| V3 | `minimax-m3` | ~2.7 s | alternate |
| V4 | `qwen3.5:397b` | ~7 s | last resort |

Escalation is by **outcome**, not guesswork: a failed or unparseable rung climbs; a
correct rung stays put. `vision_ladder.solve()` implements this and logs every look.

### Why the fast model leads

This reversed an earlier guess, so the evidence matters. On a real 16-tile
*"Select all squares with buses"* grid:

- `kimi-k2.7-code` — **15 620 ms, `finish_reason=length`, no `ANSWER:` sentinel**. Unusable.
- `gemma4:31b` — **1 005 ms**, clean answer.

And on the hardest class tested, a 16-tile **traffic lights** grid, gemma solved it in
**one round at 843 ms** with no escalation.

A wrong answer costs a round *plus* a reset, so a 15 s model that sometimes truncates is
slower in practice than a 1 s model that answers. Fast rung first, escalate on failure.

### A withdrawn conclusion, kept on the record

An earlier version of this repo claimed gemma4:31b was "inaccurate on subtle
discrimination" and demoted it below kimi. That came from **one synthetic grid** of
similar reds/oranges where gemma said `2,7,11,12,14,16` against a truth of `2,7,11`.

It did not reproduce on real tiles. Synthetic colour-discrimination grids do not
represent real reCAPTCHA imagery. **Trust evidence from real gates; do not rank a model
from a synthetic case.**

## Using a different provider

Everything routes through `VISION_BASE_URL` — any OpenAI-compatible
`/chat/completions` endpoint that accepts `image_url` content parts:

```bash
export VISION_BASE_URL=https://ollama.com/v1          # default
export VISION_BASE_URL=https://openrouter.ai/api/v1   # or anything else
export VISION_LADDER="model-a,model-b"
export VISION_MODEL=model-a                            # single-model override
export VISION_API_KEY=...
```

`config.py` resolves the key from the environment first, then from a few known harness
config locations as a convenience. Environment always wins.

## Parameter behaviour (measured, `kimi-k2.7-code`)

| Setting | Effect |
|---|---|
| `think: true` | accepted; makes the reply clean in some cases |
| **`think: false`** | **does NOT disable reasoning** — still ~12.4k chars of trace, 45 s, truncated |
| `reasoning_effort: high` | 17 140 ms, 9/9 correct |
| `reasoning_effort: medium` | 17 519 ms, 9/9 correct |
| **`reasoning_effort: low`** | **15 066 ms, 9/9 correct** — use this |
| `max_tokens: 3000` | a full trace leaves no room for the answer |
| `max_tokens: 4000` | enough |

There is **no thinking-off switch** on that model. Control length with the prompt and
the token budget.

## Payload size does not matter

39 KB PNG and 8 KB JPEG both took ~2.3 s — the cost is inference, not bandwidth. Shrink
the crop for politeness, not for speed.

## Prompt engineering: what actually helps

Scored on a controlled grid with deliberate distractors on two axes (wrong-colour
same-shape, wrong-shape same-colour), truth = 3 tiles, 20 test cells.

**On a clear grid** (red vs orange): both models scored **3/3 with ZERO false positives
under every phrasing**. Nothing to fix.

**On a deliberately ambiguous grid** (blood-red vs crimson triangles):

| prompt | gemma4:31b | kimi-k2.7-code |
|---|---|---|
| baseline | 3/3, 2 FP | 3/3, 2 FP |
| define colour+shape | 3/3, 2 FP | 3/3, 2 FP |
| binary 1/0 per tile | 3/3, 2 FP | 3/3, 2 FP |
| **fewest** (default) | 3/3, **1 FP** | 3/3, 2 FP |
| distractor-aware | 3/3, **1 FP** | 3/3, 2 FP |

Three conclusions:

1. The **fewest** framing halved gemma's false positives (2 → 1, reproduced) and is also
   the **fastest** variant. It is the default.
2. **No prompt caused under-selection** — hit count stayed 3/3 in all 20 cells.
   Tightening was risk-free: it only removed distractors.
3. **A reasoning model ignores prompt phrasing.** kimi kept exactly 2 FP under all five
   phrasings; its trace drives the answer, not the instruction. Do not spend prompt
   budget tuning a reasoning model's discrimination.

No prompt made an ambiguous tile *decidable*. 1 FP was the floor.

## Prompt styles

`vision_ladder.prompt_for(n_tiles, task, style=...)`:

- `"fewest"` (default) — the discrimination framing above
- `"strict"` — plainer "judge each tile once"; correct, hedges more
- `"verbose"` — describes the grid and invites explanation. **Worst**: slow, frequently
  truncates with no sentinel. Kept only for comparison.
