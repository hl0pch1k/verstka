"""A generated picture in the template's palette (the organisers: «even generated images use the template palette»):

* the prompt names the palette's colours (`color_name`: «deep navy blue», «bright orange»);
* the picture is then graded toward the palette: a gradient map by lightness — the template's darkest colour for the
  shadows, its accent for the mid-tones, its lightest colour for the lights — blended in at `strength`, so the picture
  keeps its subject and reads in the deck's colours whatever the model made of the prompt;
* `palette_match` — the share of the picture's pixels near the palette or its tints (ΔE76 < 25), kept with the picture;
* `fit_to` — the picture cropped to its frame's exact proportions around what it shows (`focus_crop`: where its detail
  and its colour stand out — the subject —, the middle when nothing does), never stretched, and scaled down."""

from __future__ import annotations

import colorsys
import io
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.strip().lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hex_: str) -> float:
    r, g, b = (v / 255.0 for v in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturation(hex_: str) -> float:
    r, g, b = (v / 255.0 for v in _rgb(hex_))
    return colorsys.rgb_to_hsv(r, g, b)[1]


def _toward(rgb: tuple[int, int, int], to: tuple[int, int, int], *, min_lum: float | None = None, max_lum: float | None = None) -> tuple[int, int, int]:
    """`rgb` mixed toward `to` just enough to be at least `min_lum` (or at most `max_lum`) light."""
    def lum(c) -> float:
        return luminance("%02X%02X%02X" % tuple(int(round(v)) for v in c))

    def ok(c) -> bool:
        return (min_lum is None or lum(c) >= min_lum) and (max_lum is None or lum(c) <= max_lum)

    if ok(rgb):
        return rgb
    for t in np.linspace(0.05, 1.0, 20):
        c = tuple(int(round(a + (b - a) * t)) for a, b in zip(rgb, to))
        if ok(c):
            return c
    return to


@dataclass
class Palette:
    dark: str = "1F2937"
    light: str = "F8FAFC"
    accents: list[str] = field(default_factory=list)

    @property
    def colors(self) -> list[str]:
        return list(dict.fromkeys([self.dark, *self.accents, self.light]))

    def stops(self) -> list[tuple[float, tuple[int, int, int]]]:
        """The gradient map's stops: the dark colour at 0, the strongest accent at its own lightness, the light at 1 —
        the dark one kept dark and the light one light (a dark template's «light» colour #212121 mapped every light of
        the picture to grey, a yellow one to sepia: the pictures came out dull — live runs of 20.10)."""
        out = [(0.0, _toward(_rgb(self.dark), (0, 0, 0), max_lum=0.12))]
        if self.accents:
            acc = self.accents[0]
            y = min(0.7, max(0.3, luminance(acc)))
            out.append((y, _rgb(acc)))
        out.append((1.0, _toward(_rgb(self.light), (255, 255, 255), min_lum=0.9)))
        return out


def palette_of(manifest) -> Palette:
    """The template's palette for pictures: its darkest and lightest colours (backgrounds, text) and its accents, the
    most saturated first. A template without colours gets a neutral grey ramp."""
    tokens = getattr(manifest, "tokens", None)
    colors = [c for c in (getattr(tokens, "colors", None) or []) if getattr(c, "hex", None)]
    if not colors:
        return Palette()
    hexes = [c.hex.upper().lstrip("#") for c in colors]
    by_l = sorted(hexes, key=luminance)
    dark = next((c.hex for c in colors if c.has_role("background.dark")), None) or next((c.hex for c in colors if c.has_role("text.primary")), None) or by_l[0]
    light = next((c.hex for c in colors if c.has_role("background.light")), None) or next((c.hex for c in colors if c.has_role("surface")), None) or by_l[-1]
    if luminance(dark) > luminance(light):
        dark, light = light, dark
    accents = [h for h in (tokens.accents() if hasattr(tokens, "accents") else []) if h]
    if not accents:
        accents = [h for h in hexes if h not in (dark, light) and saturation(h) > 0.25]
    # the most vivid first (saturated and bright: Nature's green and orange before its dark brown, which turned every
    # picture's mid-tones to mud — live runs of 20.10)
    accents = sorted(dict.fromkeys(a.upper().lstrip("#") for a in accents), key=lambda h: -(saturation(h) * max(_rgb(h)) / 255.0))[:3]
    return Palette(dark=dark.upper().lstrip("#"), light=light.upper().lstrip("#"), accents=accents)


_NAMES = ((15, "red"), (40, "orange"), (65, "yellow"), (90, "lime green"), (160, "green"), (190, "teal"), (215, "sky blue"),
          (250, "blue"), (280, "violet"), (320, "magenta"), (345, "pink"), (360, "red"))


def color_name(hex_: str) -> str:
    """A colour in words a text-to-image model understands («deep navy blue», «bright orange», «light grey»)."""
    r, g, b = (v / 255.0 for v in _rgb(hex_))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.12 or v < 0.08:
        if v < 0.15:
            return "near-black"
        if v > 0.93:
            return "white"
        return "light grey" if v > 0.7 else ("grey" if v > 0.4 else "dark grey")
    deg = h * 360
    base = next(name for edge, name in _NAMES if deg <= edge)
    if base == "blue" and v < 0.45:
        base = "navy blue"
    tone = "deep" if v < 0.4 else ("pale" if s < 0.35 and v > 0.8 else ("bright" if s > 0.7 and v > 0.75 else ""))
    return f"{tone} {base}".strip()


def palette_words(pal: Palette) -> str:
    """The palette in words only («deep navy blue, bright teal, white»): a colour code in the prompt is drawn as text."""
    names = [color_name(h) for h in pal.colors]
    return ", ".join(dict.fromkeys(names))


def _gradient_map(y: np.ndarray, stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    xs = np.array([s[0] for s in stops], dtype=np.float32)
    out = np.empty(y.shape + (3,), dtype=np.float32)
    for ch in range(3):
        out[..., ch] = np.interp(y, xs, np.array([s[1][ch] for s in stops], dtype=np.float32))
    return out


def grade(img: Image.Image, pal: Palette, strength: float = 0.3) -> Image.Image:
    """The picture graded toward the palette: a gradient map of its lightness blended in at `strength` (0 — as it is)."""
    strength = max(0.0, min(1.0, float(strength)))
    rgb = img.convert("RGB")
    if strength <= 0:
        return rgb
    a = np.asarray(rgb, dtype=np.float32)
    y = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]) / 255.0
    mapped = _gradient_map(y, pal.stops())
    out = a * (1.0 - strength) + mapped * strength
    # the picture keeps its own lightness (its contrast and its whites): only its hues move toward the palette
    y2 = (0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2]) / 255.0
    k = np.where(y2 > 1e-3, y / np.maximum(y2, 1e-3), 1.0)[..., None]
    out = out * k
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")


def _lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0–255, …×3) → CIE Lab (D65)."""
    c = rgb.astype(np.float32) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], dtype=np.float32)
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def palette_match(img: Image.Image, pal: Palette, delta: float = 25.0) -> float:
    """The share of the picture's pixels within ΔE76 `delta` of a palette colour or one of its tints and shades."""
    small = np.asarray(img.convert("RGB").resize((64, 64)), dtype=np.float32).reshape(-1, 3)
    refs = []
    for h in pal.colors:
        c = np.array(_rgb(h), dtype=np.float32)
        for t in (0.0, 0.25, 0.5, 0.75):
            refs.append(c + (255.0 - c) * t)  # tints
            refs.append(c * (1.0 - t))  # shades
    lab_px = _lab(small)
    lab_ref = _lab(np.array(refs, dtype=np.float32))
    d = np.sqrt(((lab_px[:, None, :] - lab_ref[None, :, :]) ** 2).sum(-1)).min(1)
    return round(float((d < delta).mean()), 3)


def saliency(img: Image.Image, side: int = 96) -> np.ndarray:
    """Where the picture shows something (rows × columns of a small copy, summing to 1): its edges (detail) and the
    pixels far in colour from the picture's own mean (a subject on a calm ground), a little weight on the middle."""
    small = img.convert("RGB")
    k = side / max(small.size)
    small = small.resize((max(8, int(small.width * k)), max(8, int(small.height * k))), Image.BILINEAR)
    a = np.asarray(small, dtype=np.float32) / 255.0
    lab = _lab(a.reshape(-1, 3) * 255.0).reshape(a.shape)
    y = lab[..., 0]
    gx = np.abs(np.diff(y, axis=1, prepend=y[:, :1]))
    gy = np.abs(np.diff(y, axis=0, prepend=y[:1, :]))
    edges = gx + gy
    far = np.sqrt(((lab - lab.reshape(-1, 3).mean(0)) ** 2).sum(-1))
    m = edges / (edges.mean() + 1e-6) + far / (far.mean() + 1e-6)
    h, w = m.shape
    yy, xx = np.mgrid[0:h, 0:w]
    prior = np.exp(-(((xx - (w - 1) / 2) / (0.45 * w)) ** 2 + ((yy - (h - 1) / 2) / (0.45 * h)) ** 2))
    m = m * (0.55 + 0.45 * prior)
    return m / (m.sum() + 1e-9)


def _window(profile: np.ndarray, keep: float) -> float:
    """The start (a share of the length) of the window of `keep` of a 1-D profile that holds most of it; ties keep
    the middle."""
    n = len(profile)
    if keep >= 1.0 or n < 2:
        return 0.0
    win = max(1, int(round(keep * n)))
    c = np.concatenate([[0.0], np.cumsum(profile)])
    sums = c[win:] - c[:-win]
    mid = (n - win) / 2
    best = max(range(len(sums)), key=lambda i: (round(float(sums[i]), 4), -abs(i - mid)))
    return best / n


def focus_crop(img: Image.Image, target: float) -> tuple[int, int, int, int]:
    """The crop box (left, top, right, bottom) of proportions `target` (w/h) that keeps what the picture shows."""
    iw, ih = img.size
    m = saliency(img)
    if iw / ih > target:
        cw = max(1, int(round(ih * target)))
        x0 = int(round(_window(m.sum(0), cw / iw) * iw))
        x0 = min(max(0, x0), iw - cw)
        return x0, 0, x0 + cw, ih
    ch = max(1, int(round(iw / target)))
    y0 = int(round(_window(m.sum(1), ch / ih) * ih))
    y0 = min(max(0, y0), ih - ch)
    return 0, y0, iw, y0 + ch


def _detail_rows(img: Image.Image, side: int = 160) -> np.ndarray:
    """The share of detailed pixels (a lightness step over 3 ΔL to a neighbour) in each row of a small copy."""
    small = img.convert("RGB")
    k = side / max(small.size)
    small = small.resize((max(8, int(small.width * k)), max(8, int(small.height * k))), Image.BILINEAR)
    a = np.asarray(small, dtype=np.float32)
    y = _lab(a.reshape(-1, 3)).reshape(a.shape)[..., 0]
    gx = np.abs(np.diff(y, axis=1, prepend=y[:, :1]))
    gy = np.abs(np.diff(y, axis=0, prepend=y[:1, :]))
    return np.where(gx + gy > 3.0, 1.0, 0.0).mean(1)


EMPTY_BAND = 0.22  # a crop whose top and bottom rows without detail take more than this share of it is zoomed in
MAX_ZOOM = 1.35


def trim_empty(img: Image.Image, max_zoom: float = MAX_ZOOM) -> Image.Image:
    """The picture zoomed in (its proportions kept, at most `max_zoom`) when a band without detail — an empty sky, a
    blank wall over a small scene — takes much of its top or bottom: the image model drew a bakery counter at the
    bottom of a blue sky (live runs of 20.10); the window keeps the detailed rows and, across, what the picture shows."""
    rows = _detail_rows(img)
    busy = rows > 0.04
    n = len(rows)
    if not busy.any() or n < 8:
        return img
    top, bot = int(np.argmax(busy)), n - int(np.argmax(busy[::-1]))
    if (top + n - bot) / n <= EMPTY_BAND:
        return img
    cw, ch = img.size
    keep_h = min(ch, max(ch / max_zoom, (bot - top) / n * ch * 1.12))
    keep_w = keep_h * cw / ch
    cy = (top + bot) / 2 / n * ch
    t = min(max(0.0, cy - keep_h / 2), ch - keep_h)
    sal = saliency(img).sum(0)
    xs = np.linspace(0, cw, len(sal))
    cx = float((sal * xs).sum() / max(float(sal.sum()), 1e-9))
    left = min(max(0.0, cx - keep_w / 2), cw - keep_w)
    return img.crop((int(left), int(t), int(left + keep_w), int(t + keep_h)))


def fit_to(img: Image.Image, w: float, h: float, max_side: int = 1600, *, focus: bool = True, trim: bool = False) -> Image.Image:
    """The picture cropped to w:h (never stretched) — around what it shows (`focus_crop`), or around its centre —,
    zoomed in past an empty band at its top or bottom when `trim` (`trim_empty`), then scaled down to at most
    `max_side` px."""
    img = img.convert("RGB")
    iw, ih = img.size
    target = w / h if h > 0 else 1.0
    if abs(iw / ih - target) > 0.005:
        if focus:
            img = img.crop(focus_crop(img, target))
        elif iw / ih > target:
            cw = max(1, int(round(ih * target)))
            x0 = (iw - cw) // 2
            img = img.crop((x0, 0, x0 + cw, ih))
        else:
            ch = max(1, int(round(iw / target)))
            y0 = (ih - ch) // 2
            img = img.crop((0, y0, iw, y0 + ch))
    if trim:
        img = trim_empty(img)
    iw, ih = img.size
    k = min(1.0, max_side / max(iw, ih))
    if k < 1.0:
        img = img.resize((max(1, int(iw * k)), max(1, int(ih * k))), Image.LANCZOS)
    return img


def encode(img: Image.Image, quality: int = 88) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=int(quality), optimize=True, progressive=True)
    return buf.getvalue()


def open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def describe(pal: Optional[Palette]) -> dict:
    return {"dark": pal.dark, "light": pal.light, "accents": pal.accents} if pal else {}
