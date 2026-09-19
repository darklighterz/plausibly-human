#!/usr/bin/env python3
"""human_timing.py — human-plausible timing profiles for browser automation.

THE POINT: speed is for FLEXIBILITY, not for clicking fast. A human does not select
four tiles and press Verify in 8 ms. Raw machine speed is a detection signature, so
the deterministic solver runs at machine speed INTERNALLY (measurement, geometry,
deciding) and then *paces its observable output* at human speed.

Two classes of cost, deliberately separated:

  INTERNAL (keep fast — nobody observes it)
      reading geometry, cropping, deciding, parsing, CDP transport

  OBSERVED (must look human — the page sees and timestamps all of it)
      mouse path shape, per-click dwell, thinking pauses, verify delay

Why pacing is safe: reCAPTCHA samples the pointer trail across the drag/selection and
scores its smoothness and timing. Too fast, too straight, or perfectly regular reads as
a bot. Pauses are NOT free-form sleeps — a real selection has a rhythm.
"""
from __future__ import annotations

import math
import random
import time


PROFILES = {
    # measured human-like bands (seconds). "fast" = a quick but normal person,
    # "typical" = average, "careful" = deliberate.
    "fast":    {"reaction": (0.28, 0.45), "per_tile": (0.16, 0.30),
                "thinking": (0.45, 0.95), "pre_verify": (0.35, 0.70),
                "path_steps": (16, 24), "move_ms": (9, 17)},
    "typical": {"reaction": (0.38, 0.70), "per_tile": (0.25, 0.55),
                "thinking": (0.70, 1.60), "pre_verify": (0.50, 1.05),
                "path_steps": (18, 28), "move_ms": (11, 21)},
    "careful": {"reaction": (0.55, 1.00), "per_tile": (0.40, 0.85),
                "thinking": (1.20, 2.40), "pre_verify": (0.70, 1.50),
                "path_steps": (22, 34), "move_ms": (13, 25)},
}

DEFAULT_PROFILE = "typical"


class Clock:
    """Human-plausible pacing. Tracks internal vs observed time separately."""

    def __init__(self, profile: str = DEFAULT_PROFILE, seed: int | None = None):
        if profile not in PROFILES:
            raise ValueError(f"unknown profile {profile!r}; pick from {list(PROFILES)}")
        self.p = PROFILES[profile]
        self.rng = random.Random(seed)
        self.internal_ms = 0.0     # machine work nobody observes
        self.observed_ms = 0.0     # time the page can see

    # ---- sampling helpers --------------------------------------------------
    def _band(self, key):
        lo, hi = self.p[key]
        # triangular bias toward the low-middle: humans cluster, they don't uniform-sample
        return self.rng.triangular(lo, hi, lo + (hi - lo) * 0.35)

    def reaction(self):
        """Pause after the page presents something, before moving."""
        d = self._band("reaction")
        self.observed_ms += d * 1000
        time.sleep(d)
        return d

    def per_tile(self, jitter: float = 0.18):
        """Gap between selecting consecutive tiles — varied, never a metronome."""
        d = self._band("per_tile") * (1 + self.rng.uniform(-jitter, jitter))
        d = max(0.09, d)
        self.observed_ms += d * 1000
        time.sleep(d)
        return d

    def thinking(self, label: str = ""):
        """The pause a person takes while actually looking at the puzzle."""
        d = self._band("thinking")
        self.observed_ms += d * 1000
        time.sleep(d)
        return d

    def pre_verify(self):
        """A human double-checks before committing. Also hides the model round-trip."""
        d = self._band("pre_verify")
        self.observed_ms += d * 1000
        time.sleep(d)
        return d

    def internal(self, t0: float):
        """Record machine work that is not observable."""
        self.internal_ms += (time.perf_counter() - t0) * 1000

    # ---- motion ------------------------------------------------------------
    def path(self, sx, sy, tx, ty):
        """A human-ish pointer path: eased, slightly bowed, jittered, non-monotonic.

        Returns (points, per_step_seconds). Speed is applied by the caller between
        dispatches, so the *shape* and the *rate* are both human.
        """
        steps = self.rng.randint(*self.p["path_steps"])
        steps = max(8, int(steps * (1 + math.log10(max(1, math.hypot(tx - sx, ty - sy))) - 1) * 0.35))
        bow = self.rng.uniform(-14, 14)
        jitter = self.rng.uniform(0.9, 2.2)
        pts = []
        for i in range(1, steps + 1):
            t = i / steps
            e = 1 - (1 - t) ** 3                       # ease-out
            if t < 0.15:                               # slow start
                e *= 0.55
            bx = (tx - sx) * 0.5 + sy * 0
            by = -abs(t - 0.5) * 2 * bow
            x = sx + (tx - sx) * e + by * 0.25 + self.rng.uniform(-jitter, jitter)
            y = sy + (ty - sy) * e + by + self.rng.uniform(-jitter, jitter)
            pts.append((round(x), round(y), 0))
        pts.append((tx, ty, 0))
        lo, hi = self.p["move_ms"]
        step_s = self.rng.uniform(lo, hi) / 1000.0
        self.observed_ms += step_s * len(pts) * 1000
        return pts, step_s

    def tile_click_gap(self):
        """Small settle between press and release — humans are not instant."""
        d = self.rng.uniform(0.055, 0.140)
        self.observed_ms += d * 1000
        time.sleep(d)
        return d

    def summary(self):
        return (f"internal {self.internal_ms:.0f} ms | observed {self.observed_ms:.0f} ms | "
                f"total {self.internal_ms + self.observed_ms:.0f} ms")


if __name__ == "__main__":
    for name in PROFILES:
        c = Clock(name, seed=7)
        t0 = time.perf_counter()
        c.reaction()
        for _ in range(3):
            pts, step = c.path(100, 100, 400, 300)
            for _ in pts:
                time.sleep(step)
            c.tile_click_gap()
            c.per_tile()
        c.thinking()
        c.pre_verify()
        print(f"{name:<9} 3 tiles -> {c.summary()}")
