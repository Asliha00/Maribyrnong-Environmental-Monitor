"""
Build frontend/src/assets/login-illustration-dark-transparent.webp from the team's original
login-illustration-dark.png (which is never modified). DECISIONS.md D-036.

Why: the original's background is not exactly the page colour (and the first dark export's glow
reached the file edge), which showed as a faint rectangle around the image.

How:
1. Find the artwork (pixels clearly different from the background) and crop to it plus a margin,
   so the file's empty space is dropped. No hard-coded numbers: a new export just needs a re-run.
2. "Colour to alpha" against the page navy: each pixel becomes artwork colour + opacity, chosen so
   that drawn over #040E25 it reproduces the original pixel (to within a few levels of red, the one
   channel where the page is brighter than some of the background). The artwork is unchanged.
3. Only the faint glow (low opacity) is faded to nothing, along an ellipse, so it ends without
   a straight edge. Solid artwork pixels are protected, so the cityscape is not faded or darkened.

    python scripts/make_login_dark_art.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "assets"
SOURCE = ASSETS / "login-illustration-dark.png"
TARGET = ASSETS / "login-illustration-dark-transparent.webp"
PAGE = np.array([0x04, 0x0E, 0x25], dtype=float)   # --login-page in dark mode (index.css)
MARGIN = 50                                        # px of background kept around the artwork


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def colour_to_alpha(rgb: np.ndarray, bg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Smallest opacity per pixel such that colour over `bg` gives back the pixel.

    Standard colour-to-alpha (the larger of the "brighter" and "darker" opacities), except that
    red is left out of the "darker" side: the page navy's red is just 4, so a background pixel
    with red 1 would otherwise need 75% opacity and show as a box. That costs at most 4 levels
    of red."""
    up = np.where(rgb > bg, (rgb - bg) / (255.0 - bg), 0.0).max(axis=2)
    down = np.where(rgb[..., 1:] < bg[1:], (bg[1:] - rgb[..., 1:]) / bg[1:], 0.0).max(axis=2)
    alpha = np.maximum(up, down)
    safe = np.maximum(alpha, 1e-6)[..., None]
    colour = np.where(alpha[..., None] > 0, (rgb - bg) / safe + bg, bg)
    return np.clip(colour, 0, 255), alpha


def artwork_box(rgb: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box of the artwork: pixels more than 40 levels from the border's median colour."""
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    far = np.abs(rgb - np.median(border, axis=0)).max(axis=2) > 40
    rows, cols = np.where(far.sum(axis=1) > 3)[0], np.where(far.sum(axis=0) > 3)[0]  # ignore specks
    h, w = far.shape
    return (max(cols[0] - MARGIN, 0), max(rows[0] - MARGIN, 0),
            min(cols[-1] + 1 + MARGIN, w), min(rows[-1] + 1 + MARGIN, h))


def main() -> None:
    full = np.asarray(Image.open(SOURCE).convert("RGB"), dtype=float)
    box = artwork_box(full)
    rgb = full[box[1]:box[3], box[0]:box[2]]
    colour, alpha = colour_to_alpha(rgb, PAGE)

    h, w = alpha.shape
    y, x = np.mgrid[0:h, 0:w].astype(float)
    # The glow is a soft halo that runs past the crop. Fade it along an ellipse (1 in the middle,
    # 0 by the crop's edge midpoints and corners), so it dies away with no straight edge.
    r = np.hypot((x - (w - 1) / 2) / (w / 2), (y - (h - 1) / 2) / (h / 2))
    halo = 1 - smoothstep(0.55, 1.0, r)
    solid = smoothstep(0.30, 0.60, alpha)            # artwork, not glow: never faded
    alpha = alpha * np.maximum(halo, solid)
    alpha[[0, -1], :] = 0                            # the outermost pixels are always clear
    alpha[:, [0, -1]] = 0

    out = np.dstack([colour, alpha * 255]).round().astype(np.uint8)
    Image.fromarray(out, "RGBA").save(TARGET, "WEBP", lossless=True, method=6, exact=True)
    print(f"wrote {TARGET.name}: crop {box} of the source, {w}x{h} (aspect {w / h:.3f}), "
          f"{TARGET.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
