# SETUP.md — harness-specific notes

The repo is deliberately plain Python + CDP, so any harness that can run a shell command
can drive it. The only things that differ between harnesses are **how you launch a
browser** and **where a model credential lives**. Both are handled by `config.py`.

## The universal contract

Whatever harness you use, three things must be true:

1. A Chromium is listening on `CDP_PORT` with `--remote-debugging-port`.
   **This is the key dependency**: it is what delivers trusted input
   (`event.isTrusted === true`) together with DOM control. Nothing else in this repo
   reaches a page at all.
2. The scripts can reach `VISION_BASE_URL` with `VISION_API_KEY`.
3. You navigate the page yourself; the scripts solve the challenge **on the current page**.

```bash
python scripts/config.py          # confirms 1–2 and prints key presence
python scripts/browser.py check   # confirms 1 specifically
python scripts/probe-trust.py     # confirms input is TRUSTED, not script-synthesized
```

### If you use a different browser, keep this property

Any Chromium fork works (Chrome, Chromium, Brave, Edge). What you must preserve is the
**trusted-input property**, regardless of how you launch it:

- Prefer a direct launch over a driver. CDP from a plain browser process has no
  `navigator.webdriver` flag and no driver binary in the process tree.
- **Never pass `--enable-automation`** — it sets `navigator.webdriver = true`, which is
  precisely the flag you spent the CDP route avoiding. `browser.py` does not pass it.
- If you route through Selenium/Playwright instead, input is still trusted (both drive CDP
  underneath), but check the fingerprint yourself — Playwright and Selenium set
  `navigator.webdriver` unless configured not to. `probe-trust.py` will tell you what your
  launch actually produces.

---

## Bare shell / no agent

```bash
python scripts/browser.py start --profile ~/.my-chrome-profile
# navigate however you like (or via any CDP call), then:
python scripts/solve-recaptcha.py
python scripts/verify-token.py
```

`browser.py` deliberately does not manage your logins beyond the profile directory. Point
`--profile` at an existing Chrome profile to reuse sessions.

---

## Hermes

Hermes keeps a key in `~/.hermes/config.yaml`; `config.py` reads it automatically as a
convenience (environment still wins). Two ways to give Hermes a browser:

- **Its own browser tool.** Let Hermes navigate, then run these scripts against whatever
  CDP port its browser exposes via `CDP_PORT`. Hermes' bundled browser is `agent-browser`,
  which is *not* CDP-on-a-port by default — prefer the next option for these scripts.
- **Bring your own Chrome and let Hermes drive it.** Launch a persistent Chrome with
  `browser.py start`, then have Hermes run `scripts/*.py`. This is the mode the stack was
  built and measured in.

Skill note: if you use Hermes, keep the CAPTCHA/captcha-specific operational knowledge in
a skill (Hermes auto-loads skills by relevance) and keep this repo as the executable
substrate. The skill holds *judgement*; the repo holds *mechanism*.

---

## Claude Code

Standard environment-variable driven:

```bash
pip install -r requirements.txt
export VISION_API_KEY=...
python scripts/browser.py start --profile ~/.my-chrome-profile
```

If you keep the key in `~/.claude/settings.json`, `config.py` will find it — but an
exported `VISION_API_KEY` is clearer and always takes precedence.

Claude Code's own browser tooling does not expose a CDP port by default, so launch Chrome
yourself via `browser.py` and let the scripts talk to it.

---

## opencode

opencode config often lives at `~/.config/opencode/config.json`; `config.py` checks there
for a key. Otherwise export it:

```bash
export VISION_API_KEY=...
export CDP_PORT=9333
```

Nothing opencode-specific is required beyond that — it is just a shell command away from
these scripts.

---

## Cursor / Aider / other agents

Same contract. Two practical notes:

- **Aider**: put `VISION_API_KEY` in the environment you launch it with; Aider's `.env`
  is fine for local use but never commit it.
- **Cursor**: its terminal inherits your shell environment, so an `export` in your shell
  profile is enough.

---

## Containers / CI / headless

Works, with caveats:

```bash
python scripts/browser.py start --headless
```

**Headless is more detectable.** Headless Chrome advertises `HeadlessChrome` in the user
agent and falls back to `SwiftShader` for WebGL. Both are trivially visible to a page.
Use `--headless=new` (which `browser.py` does) and expect a harder time than headed. If
you control the environment, run headed under Xvfb instead:

```bash
xvfb-run -s "-screen 0 1920x1080x24" python scripts/solve-recaptcha.py
```

`DISPLAY` is respected by `browser.py` through the environment, so Xvfb needs no code
change.

---

## Verifying your environment end to end

```bash
python scripts/config.py            # no MISSING keys, sane target
python scripts/browser.py check     # CDP alive, protocol version printed
python scripts/cdp.py 9333          # prints connect + per-call latency
python scripts/probe-trust.py       # CDP input isTrusted=true, JS-synthesized=false
```

`cdp.py`'s self-test should report roughly **`0.7 ms/call`** steady-state. If it reports
`~140 ms`, you are falling back to one-shot CLI calls and the timings in `README.md` will
not hold — the persistent client is what makes the clock winnable.

Then a real check:

```bash
python scripts/solve-turnstile.py   # against a Turnstile test page
python scripts/verify-token.py      # token length is your proof
```
