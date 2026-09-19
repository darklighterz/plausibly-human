# LIMITS.md — what is NOT verified, and the rules for using this

Read this before trusting the repo anywhere that matters. Overclaiming is the failure
mode this document exists to prevent.

## Scope of the evidence

Everything below was measured on **this stack** — a real Chrome driven over CDP, a
persistent profile, headed, on specific public test beds. It is not a general claim
about CAPTCHA systems, which change continuously.

| Gate | Status |
|---|---|
| Cloudflare Turnstile (managed) | **Verified** — trusted click on the widget glass, 773-char token |
| reCAPTCHA v2 checkbox | **Verified** — 7/7 human-paced, no grid provoked, ~2300-char token |
| reCAPTCHA v2 image grid | **Verified** — multi-round solves, 4×4 and 3×3 |
| reCAPTCHA grid classes | **Verified** — bicycles, cars, buses, bridges, crosswalks, traffic lights |

### Explicitly NOT verified

- **hCaptcha** — not tested at all.
- **DataDome** — a hard block on this stack. Not solved, and no claim of solving it.
- **Akamai, PerimeterX, Kasada, Incapsula** — not tested.
- **Cloudflare "interactive" / hard Turnstile modes** — only the managed challenge was
  exercised; a challenge that demands a puzzle was not.
- **reCAPTCHA v3 / Enterprise scoring** — no visible challenge, so nothing here applies.
  v3 is a score, not a puzzle; beating it is a different problem entirely.
- **Mobile-emulation surfaces** — desktop viewport only.

### Sample sizes

Be honest about the thinness of the evidence:

- The model ranking rests on **two grids** (buses, cars) plus later one-off solves. It is
  consistent but small. Re-derive it if a rung starts failing.
- The `fewest` prompt win is **20 test cells** on a synthetic grid, half of them
  deliberately ambiguous. Real tiles behaved better than the synthetic hard case.
- The delay finding (escalation from latency before first interaction) is **three runs**.

## Hard blocks

Some defences are not puzzles and will not yield to this repo. When a site refuses to
serve content after clearance — a hard block page, an endless loop, a challenge that
never resolves — **say so plainly and stop**. Reporting a bot wall as a successful fetch
is the worst failure mode available here: it is worse than an honest failure, because it
corrupts the record that everything else is built on.

## Detection, and why "slow down" is not a bug

Machine-fast input is a **detection signature**. Measured: batched 8.3 ms input
*provoked* an image grid; 780 ms human-paced input passed clean, 7/7.

Consequences for anyone tuning this:

- Do **not** "optimise" the observed path to shave milliseconds. The pauses are the
  feature.
- Do **not** batch observed input for a single round-trip, however tempting the latency
  win.
- Click **promptly** on first interaction. A long pause before the first click escalates
  the challenge just as machine speed does.

Any change that makes this look faster to the page is a regression, even if every
benchmark improves.

## Legal and ethical use

This automates **your own access** to services you are entitled to use:

- your own accounts,
- your own research and testing,
- systems you own or have **written authorisation** to test.

Bypassing a CAPTCHA can violate a site's terms of service. In some jurisdictions,
accessing a system in a manner its owner has expressly prohibited carries legal risk,
regardless of intent.

**Do not** use this to scrape at scale, to create accounts in bulk, to evade rate limits
or bans, to access systems you are not authorised to access, or to help anyone else do
those things. If a user asks for that, decline.

You are responsible for where you point it. The licence is MIT: no warranty, no
liability, no indemnity.

## Maintenance

CAPTCHA vendors change their implementations continuously. Expect these techniques to
decay:

- reCAPTCHA's escalation thresholds and DOM structure,
- Cloudflare's Turnstile mount behaviour,
- model availability (several vision models used during development were **retired**
  and now fail fast with an error that looks like a bad model).

The encounter ledger (`data/serpentine-encounters.jsonl`) plus `scripts/encounter.py` exist
so that decay shows up as data rather than as a mystery failure. Record every gate you
meet; when a rung starts failing, the record is what tells you it is the rung and not
you.
