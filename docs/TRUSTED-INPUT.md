# TRUSTED-INPUT.md — the fallback ladder for reaching a page

**Why this document exists.** CDP is the current route (see README → *Why CDP is the key
dependency*). But CAPTCHA vendors upgrade, and if CDP specifically becomes a detection
signal, we need to know **what else works, what it costs, and how to switch** — decided in
advance, with the measurements already taken, rather than under pressure mid-solve.

Read this before changing the input mechanism. It is ordered by how little work the
switch is: start at the top.

## The property that matters

Every route below that lands input in the **browser input pipeline** produces
`isTrusted === true`. That is the whole requirement, and it is the one thing you must
re-verify after any change:

```bash
python scripts/probe-trust.py        # CDP route: isTrusted=true vs JS-synthesized=false
python scripts/test-alt-routes.py    # OS-level routes: xdotool / ydotool
```

**Trust is never the differentiator between the good options.** They all achieve it. What
separates them is whether you can still **map coordinates to elements and read state
back** — which is what makes a 9-tile grid solvable rather than a blind click. CDP gives
you both; the OS-level routes give you trust but no DOM.

## Tier ladder

### Tier 0 — CDP, direct browser launch ← *current*

```bash
python scripts/browser.py start --profile ~/.my-chrome-profile
```

- **Trust:** yes — `isTrusted=true`, browser synthesizes full pointer ordering.
- **DOM:** full.
- **Fingerprint:** clean. No `navigator.webdriver`, no driver process.
- **Cost:** zero. This is what the repo does now.
- **Switch trigger:** none. Stay here until something demonstrably fails.

### Tier 1 — CDP via Playwright or Puppeteer

Both drive CDP underneath, so trust and DOM are unchanged. You gain their element
selectors, auto-waiting and path helpers; you pay for a heavier process tree.

- **Trust:** yes.
- **DOM:** full.
- **Fingerprint:** **must be checked.** Playwright sets `navigator.webdriver` by default;
  launching with `--disable-blink-features=AutomationControlled` (which `browser.py`
  already uses) and avoiding the automation default channel is the usual mitigation.
  Playwright also exposes `connectOverCDP()`, which **attaches to an already-running
  Chrome** — that is the interesting mode, because the browser then looks exactly like
  Tier 0 while you get Playwright's ergonomics.
- **Switch effort:** low; Playwright is installed on this machine and `connectOverCDP`
  needs no changes to how Chrome is launched.

### Tier 2 — WebDriver / Selenium

- **Trust:** yes (ChromeDriver drives CDP).
- **DOM:** full.
- **Fingerprint:** **worse than tiers 0–1.** Sets `navigator.webdriver = true` and runs a
  driver binary in the process tree. Requires explicit hardening.
- **Switch effort:** medium. Selenium and `geckodriver` are present here; `chromedriver`
  is not, so this route needs an install first.
- **When it is worth it:** if a vendor is *specifically* detecting CDP-attached sessions
  but not WebDriver sessions. That is unusual but not impossible.

### Tier 3 — WebDriver BiDi

The modern replacement for the classic WebDriver wire protocol; bidirectional, CDP-like in
capability, standardised. Browser support is the constraint.

- **Trust:** yes.
- **DOM:** full.
- **Switch effort:** high — new API, less mature tooling, and support varies by browser
  build. Worth knowing about; not worth moving to unless tiers 0–2 all fail.

### Tier 4 — OS-level X11 input (`xdotool`) ← *measured TRUSTED on this machine*

Fake input injected at the X server level, as if from hardware. **Completely outside the
browser**, so nothing about it is a browser-automation signal.

```bash
xdotool mousemove <screen_x> <screen_y> && xdotool click 1
```

- **Trust:** **YES — verified.** The probe fired at a viewport point and recorded
  4 events (`mousemove`, `mousedown`, `mouseup`, `click`), all `isTrusted=True`.
- **DOM:** **none.** This is the cost. You must compute screen coordinates yourself
  (`window.screenX + clientX`, and account for `devicePixelRatio`) and you get no
  element lookup and no state read.
- **Requirement:** an X display. X11 works (`XDG_SESSION_TYPE=x11` here); pure Wayland
  needs the XWayland bridge or Tier 5 instead.
- **Present on this machine:** yes.
- **Best combined with:** reading geometry over CDP (read-only, low-risk) and *only*
  the clicks through xdotool. That keeps DOM mapping while moving the input injection
  outside the browser.

### Tier 5 — Kernel-level `uinput` (`ydotool`)

Injects at the kernel input layer — below the display server, so it works headless and
on Wayland. Requires the `ydotoold` daemon and `/dev/uinput` permissions.

```bash
ydotoold &                                   # daemon first
ydotool mousemove --absolute -x X -y Y
ydotool click 1
```

- **Trust:** expected yes (kernel-level), but **NOT yet measured here** — the test came
  back *inconclusive* because `ydotoold` was not running
  (`notice: ydotoold backend unavailable`). `/dev/uinput` exists and is root-only.
- **DOM:** none, same as Tier 4.
- **Present on this machine:** the binary is; the daemon is not running.
- **To verify:** start `ydotoold`, re-run `scripts/test-alt-routes.py`. Do not claim this
  route works until that prints TRUSTED.

### Tier 6 — Real hardware

An actual USB HID device (microcontroller, Raspberry Pi as a USB gadget, KVM-style
injector). Indistinguishable from a human at every software layer because it *is*
hardware.

- **Trust:** maximal.
- **DOM:** none.
- **Cost:** hardware, wiring, and a coordinate-mapping problem. Overkill today.
- **When:** only if every software tier is defeated at once. If it ever comes to this,
  the answer is probably to stop, not to buy parts.

### Tier 7 — Vision-driven OS input (the DOM-less escape hatch)

The interesting generalisation: if you leave the browser entirely (Tiers 4–6), you lose
element lookup — but **you do not need it.** You can close that gap with the vision model
that already exists in this repo:

1. Screenshot the screen (not the page).
2. Ask the model to locate the target — this is the same skill as naming grid tiles,
   applied to "find the checkbox" or "read the prompt text".
3. Inject the click at those screen coordinates via xdotool/uinput.

This keeps the architecture intact (deterministic code + one model look) while making the
input path fully external to the browser. The trade is precision: element geometry gives
exact pixels, a model locates approximately, so verify-after-act becomes mandatory.

## Decision tree: what to do when a route starts failing

1. **Did trust change, or did something else?** Run `probe-trust.py` first. If
   `isTrusted` is still `true`, the input path is not your problem — look at timing,
   fingerprint or the challenge itself instead. Do not switch routes on a hunch.
2. **Is it the browser fingerprint, not the input?** Check `navigator.webdriver`,
   the UA string, `plugins.length`, and WebGL. A UA containing `HeadlessChrome` or
   `navigator.webdriver === true` will fail regardless of how you click. Fix the launch
   flags before changing the route.
3. **Is it CDP-specific?** If and only if a vendor demonstrably detects CDP-attached
   sessions: try Tier 1 with `connectOverCDP` (attach to a browser launched exactly as
   Tier 0 launches it), then Tier 4 (xdotool) keeping CDP for reads only.
4. **Only then** consider Tiers 5–6.

Change one variable at a time, and record the outcome in the ledger
(`scripts/encounter.py`) — a route switch is exactly the kind of thing that belongs in
`data/serpentine-encounters.jsonl`, with the measured result.

## What is measured vs. what is documented

Be precise about this when reporting; a documented-but-untested route is not a fallback.

| Route | Trust | Status on this machine |
|---|---|---|
| CDP direct (Tier 0) | trusted | **MEASURED** — 7 events all `isTrusted=true` |
| JS `dispatchEvent` | **not trusted** | **MEASURED** — `isTrusted=false` |
| xdotool (Tier 4) | trusted | **MEASURED** — 4 events all `isTrusted=true` |
| Playwright/Puppeteer (Tier 1) | trusted | documented; package installed, not measured |
| Selenium/WebDriver (Tier 2) | trusted | documented; `geckodriver` only, no `chromedriver` |
| WebDriver BiDi (Tier 3) | trusted | documented only |
| ydotool/uinput (Tier 5) | expected | **INCONCLUSIVE** — `ydotoold` not running |
| Hardware HID (Tier 6) | maximal | documented only |
| Vision-driven OS input (Tier 7) | inherits Tier 4–6 | designed, not built |

## Fingerprint hygiene (applies to every tier)

Cheap to check, and the most common reason a good input route still fails:

- **Never pass `--enable-automation`** — sets `navigator.webdriver = true`.
- Use `--disable-blink-features=AutomationControlled` (the repo's `browser.py` does).
- Run **headed** where you can; headless advertises `HeadlessChrome` and falls back to
  `SwiftShader` for WebGL.
- Use a **persistent profile** so clearance cookies survive between solves.
- Verify: `navigator.webdriver === false`, UA free of `HeadlessChrome`,
  `navigator.plugins.length > 0`, `window.chrome` present.

## Scripts

```bash
python scripts/probe-trust.py        # prove CDP input is trusted vs JS-synthesized
python scripts/test-alt-routes.py    # measure xdotool / ydotool trust, with coordinates
```
