#!/usr/bin/env python3
"""ascii-view.py — render an image region as an ASCII luminance map.

Lets a text-only agent inspect layout without a vision model. Each character is
one pixel block; darker pixels get heavier glyphs. Good for locating UI chrome
(borders, checkboxes, text baselines) in a screenshot.

    ascii-view.py <png> [x y w h] [scale]
"""
import sys
from PIL import Image

png = sys.argv[1]
im = Image.open(png).convert("L")
if len(sys.argv) > 5:
    x, y, w, h = (int(v) for v in sys.argv[2:6])
    im = im.crop((x, y, x + w, y + h))
scale = int(sys.argv[6]) if len(sys.argv) > 6 else 4
im = im.resize((max(1, im.size[0] // scale), max(1, im.size[1] // scale)), Image.LANCZOS)

RAMP = "@%#*+=-:. "          # dark -> light
px = im.load()
W, H = im.size
print(f"region {W}x{H} cells (1 cell = {scale}px), origin in full image")
print("    " + "".join(str((i // 10) % 10) for i in range(W)))
print("    " + "".join(str(i % 10) for i in range(W)))
for row in range(H):
    line = "".join(RAMP[min(9, px[col, row] * 10 // 256)] for col in range(W))
    print(f"{row:3} {line}")
