#!/usr/bin/env python3
"""browser.py — start / check / stop a Chromium with CDP enabled.

Deliberately tiny and harness-agnostic. It does not manage profiles, logins, or
fingerprints for you — bring your own profile if you want persistent logins:

    CDP_PROFILE=~/.my-chrome-profile  python scripts/browser.py start

Why the flags below matter (all measured, not folklore):

  --user-data-dir=<dir>              a PERSISTENT profile means solved clearance
                                     cookies survive, so you re-solve far less often
  --disable-blink-features=AutomationControlled
                                     without this the page can see
                                     navigator.webdriver === true
  --remote-debugging-port=<port>     what this whole repo talks to

Run headed where you can. Headless Chrome advertises "HeadlessChrome" in the
user agent and falls back to SwiftShader for WebGL, both of which are easy to
detect. If you must run headless, pass --headless=new and expect a harder time.

    browser.py start [--port N] [--profile DIR] [--headless]
    browser.py check
    browser.py stop
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402

CANDIDATES = [
    os.environ.get("CHROME_BIN"),
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
]


def find_browser() -> str | None:
    for c in CANDIDATES:
        if not c:
            continue
        p = shutil.which(c) if not os.path.isabs(c) else (c if os.path.exists(c) else None)
        if p:
            return p
    return None


def cdp_alive(port: int, host: str = None) -> dict | None:
    host = host or cfg.CDP_HOST
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/json/version", timeout=3) as r:
            return json.load(r)
    except Exception:                                          # noqa: BLE001
        return None


def cmd_check(a):
    info = cdp_alive(a.port)
    if info:
        print(f"CDP alive on {cfg.CDP_HOST}:{a.port}")
        print(f"  browser : {info.get('Browser')}")
        print(f"  protocol: {info.get('Protocol-Version')}")
        try:
            with urllib.request.urlopen(
                    f"http://{cfg.CDP_HOST}:{a.port}/json", timeout=3) as r:
                targets = json.load(r)
            pages = [t for t in targets if t.get("type") == "page"]
            print(f"  pages   : {len(pages)}")
            for t in pages[:3]:
                print(f"    - {(t.get('url') or '')[:70]}")
        except Exception:                                      # noqa: BLE001
            pass
        return 0
    print(f"no CDP endpoint on {cfg.CDP_HOST}:{a.port}")
    print(f"  start one with: {os.path.basename(__file__)} start")
    return 1


def cmd_start(a):
    if cdp_alive(a.port):
        print(f"already running on port {a.port}")
        return 0
    exe = find_browser()
    if not exe:
        print("no Chromium-family browser found. Install one, or set CHROME_BIN.")
        return 2
    profile = a.profile or os.environ.get("CDP_PROFILE")
    args = [exe, f"--remote-debugging-port={a.port}",
            "--no-first-run", "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled"]
    if profile:
        os.makedirs(profile, exist_ok=True)
        args.append(f"--user-data-dir={os.path.expanduser(profile)}")
    if a.headless:
        args.append("--headless=new")
    if a.window:
        args.append(f"--window-size={a.window}")
    print(f"launching: {exe}")
    print(f"  port    : {a.port}")
    print(f"  profile : {os.path.expanduser(profile) if profile else '(temporary)'}")
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for i in range(20):
        time.sleep(1)
        if cdp_alive(a.port):
            print(f"CDP up after {i+1}s")
            return 0
    print("FAILED: no CDP endpoint appeared. Check DISPLAY / that the profile is not locked.")
    return 1


def cmd_stop(a):
    """Best-effort: kill the browser attached to this CDP port."""
    stopped = False
    try:
        if shutil.which("pgrep"):
            out = subprocess.run(["pgrep", "-f", f"remote-debugging-port={a.port}"],
                                 capture_output=True, text=True).stdout.split()
            for pid in out:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    stopped = True
                except (ValueError, ProcessLookupError, PermissionError):
                    pass
    except Exception:                                          # noqa: BLE001
        pass
    print("stopped" if stopped else "no matching process found")
    return 0


def main():
    p = argparse.ArgumentParser(description="start/check/stop a CDP-enabled Chromium")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("start", cmd_start), ("check", cmd_check), ("stop", cmd_stop)):
        sp = sub.add_parser(name)
        sp.add_argument("--port", type=int, default=cfg.CDP_PORT)
        if name == "start":
            sp.add_argument("--profile", default=None,
                            help="persistent user-data-dir (or set CDP_PROFILE)")
            sp.add_argument("--headless", action="store_true")
            sp.add_argument("--window", default="1876,893")
        sp.set_defaults(func=fn)
    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
