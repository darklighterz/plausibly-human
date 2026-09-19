#!/usr/bin/env python3
"""config.py — ONE place for every environment-specific value.

This repo is HARNESS AGNOSTIC. Nothing here assumes Hermes, Claude Code, opencode,
Cursor, Aider, or any other agent runtime. Everything that differs between machines
or harnesses is resolved here, from environment variables, so a fresh clone works
anywhere:

    export CDP_PORT=9333                 # Chrome DevTools Protocol port
    export CDP_HOST=127.0.0.1            # where that Chrome listens
    export VISION_BASE_URL=https://ollama.com/v1   # any OpenAI-compatible endpoint
    export VISION_API_KEY=...            # bearer token for that endpoint
    export VISION_MODEL=gemma4:31b       # single-model override (bypasses the ladder)
    export VISION_LADDER=gemma4:31b,kimi-k2.7-code:cloud
    export CATTCHA_PACE=typical          # fast | typical | careful
    export DISPLAY=:1                    # X display, headed Chrome only

API keys are read from the environment FIRST, then from a few well-known config
locations as a convenience for agent harnesses that keep one. A key is never
hardcoded and never logged.
"""
from __future__ import annotations

import os
import re

# ---------------------------------------------------------------- CDP / browser
CDP_HOST = os.environ.get("CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("CDP_PORT", "9333"))
CDP_TIMEOUT = float(os.environ.get("CDP_TIMEOUT", "20"))

# Where a browser binary lives, if the helper has to start one itself. Any
# Chromium-family build works. Leave unset to use whatever is on PATH.
CHROME_BIN = os.environ.get("CHROME_BIN") or os.environ.get("CHROME_PATH")

# ---------------------------------------------------------------- vision model
# Any OpenAI-compatible /chat/completions endpoint that accepts image_url parts.
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "https://ollama.com/v1")
VISION_MODEL = os.environ.get("VISION_MODEL")          # single-model override

# The ordered escalation ladder. Defaults reproduce the measured best ordering;
# override with VISION_LADDER="model-a,model-b,model-c" on any other provider.
_DEFAULT_LADDER = "gemma4:31b,kimi-k2.7-code:cloud,minimax-m3,qwen3.5:397b"
VISION_LADDER = [m.strip() for m in
                 os.environ.get("VISION_LADDER", _DEFAULT_LADDER).split(",") if m.strip()]

# ---------------------------------------------------------------- pacing
PACE = os.environ.get("CAPTCHA_PACE", "typical")        # fast | typical | careful

# ---------------------------------------------------------------- paths
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
LEDGER = os.environ.get("CAPTCHA_LEDGER", os.path.join(REPO_ROOT, "data",
                                                       "ladder-encounters.jsonl"))


def _read_key_from_configs() -> str | None:
    """Convenience only: pick up a key from common harness config locations.

    Order matters — env var wins, so an explicit export always overrides a
    discovered file. Every candidate is optional; first match wins.
    """
    candidates = [
        os.path.expanduser("~/.hermes/config.yaml"),      # Hermes
        os.path.expanduser("~/.config/opencode/config.json"),  # opencode
        os.path.expanduser("~/.claude/settings.json"),    # Claude Code
        os.path.expanduser("~/.config/aider/.aider.conf.yml"),
    ]
    # a bearer token for ollama-cloud is 32 hex + "." + base62-ish suffix
    pat = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_\-]{10,}")
    for path in candidates:
        try:
            with open(path) as fh:
                txt = fh.read()
        except OSError:
            continue
        m = pat.search(txt)
        if m:
            return m.group(0)
    return None


def vision_api_key() -> str | None:
    """Resolve the vision API key: environment first, then known configs."""
    for var in ("VISION_API_KEY", "OLLAMA_API_KEY", "OPENAI_API_KEY",
                "OPENROUTER_API_KEY"):
        v = os.environ.get(var)
        if v:
            return v.strip()
    return _read_key_from_configs()


def describe() -> dict:
    """Non-secret summary, for setup checks and bug reports."""
    key = vision_api_key()
    return {
        "cdp": f"{CDP_HOST}:{CDP_PORT}",
        "vision_base_url": VISION_BASE_URL,
        "vision_model_override": VISION_MODEL or None,
        "vision_ladder": VISION_LADDER,
        "vision_key_present": bool(key),
        "vision_key_source": ("env" if any(os.environ.get(v) for v in
                                           ("VISION_API_KEY", "OLLAMA_API_KEY",
                                            "OPENAI_API_KEY", "OPENROUTER_API_KEY"))
                              else ("config-file" if key else "MISSING")),
        "pace": PACE,
        "ledger": LEDGER,
        "display": os.environ.get("DISPLAY", "(unset)"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(describe(), indent=2))
