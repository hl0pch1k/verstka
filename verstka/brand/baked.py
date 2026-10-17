"""Логотипы партнёров, впечатанные в фоновые картинки шаблона.

У ЛЦТ четыре знака организаторов («Правительство Москвы», «Бизнес Москвы»…) нарисованы прямо на фоне мастера и
слайдов: это не фигуры и не картинки, их не уберёшь как логотип шаблона. Если брендбук важнее и у него свои логотипы,
колода другого бренда не несёт чужих знаков: ряд небольших знаков в верхней или нижней полосе фоновой картинки, на
спокойном (градиентном) фоне, закрашивается тем же фоном — построчной растяжкой цвета между строками над и под рядом.
Пёстрый фон (фото), одиночный знак, крупная надпись, что-то посреди картинки — не трогаются."""

from __future__ import annotations

import io
import logging
import re
from typing import Optional

from verstka.brand.package import A, P, R, Package

log = logging.getLogger(__name__)

PxBox = tuple[int, int, int, int]  # x0, y0, x1, y1 в точках картинки (включительно)
_WORK_W = 960  # ширина, на которой ищутся знаки
_DEV = 28.0  # отличие точки от сглаженного фона (0–255), с которого точка — часть знака
_BAND = 0.2  # верхняя и нижняя полосы — доля высоты


def background_media(pkg: Package) -> dict[str, list[str]]:
    """Картинки фона (`p:bg` с картинкой) → части, где они фон."""
    out: dict[str, list[str]] = {}
    for n in pkg.names():
        if not re.match(r"^ppt/(slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml$", n):
            continue
        root = pkg.xml(n)
        bg = root.find(f"{{{P}}}cSld/{{{P}}}bg") if root is not None else None
        blip = bg.find(f".//{{{A}}}blip") if bg is not None else None
        if blip is None:
            continue
        media = pkg.rels(n).get(blip.get(f"{{{R}}}embed") or "", ("", None))[1]
        if media and pkg.has(media):
            out.setdefault(media, []).append(n)
    return out


def find_marks(data: bytes) -> list[tuple[float, float, float, float]]:
    """Ряд знаков в верхней или нижней полосе картинки — рамки (x0, y0, x1, y1) долями картинки; [] — нет или фон
    под ними неспокойный."""
    try:
        import numpy as np
        from PIL import Image, ImageFilter

        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:  # noqa: BLE001
        return []
    w0, h0 = im.size
    if w0 < 200 or h0 < 120:
        return []
    small = im.convert("L").resize((_WORK_W, max(1, round(_WORK_W * h0 / w0))))
    g = np.asarray(small, dtype=float)
    smooth = np.asarray(small.filter(ImageFilter.GaussianBlur(24)), dtype=float)
    dev = np.abs(g - smooth)
    H, W = g.shape
    out: list[tuple[float, float, float, float]] = []
    for r0, r1 in ((0, int(_BAND * H)), (int((1 - _BAND) * H), H)):
        mask = dev[r0:r1] > _DEV
        cols = np.where(mask.any(axis=0))[0]
        if cols.size == 0:
            continue
        runs: list[list[int]] = [[int(cols[0]), int(cols[0])]]
        for c in cols[1:]:
            if c - runs[-1][1] <= 0.02 * W:
                runs[-1][1] = int(c)
            else:
                runs.append([int(c), int(c)])
        boxes: list[PxBox] = []
        for c0, c1 in runs:
            sub = mask[:, c0:c1 + 1]
            ys = np.where(sub.any(axis=1))[0]
            y0, y1 = int(ys[0]), int(ys[-1])
            bw, bh = c1 - c0 + 1, y1 - y0 + 1
            if not (0.015 * H <= bh <= 0.12 * H and 0.02 * W <= bw <= 0.3 * W):
                continue
            if sub[y0:y1 + 1].mean() < 0.03:
                continue  # редкий шум, а не знак
            boxes.append((c0, r0 + y0, c1, r0 + y1))
        if len(boxes) < 2:
            continue  # одиночный знак — может быть частью рисунка; трогаем только ряд знаков
        centres = [(b[1] + b[3]) / 2 for b in boxes]
        if max(centres) - min(centres) > 0.05 * H or sum(b[2] - b[0] for b in boxes) > 0.5 * W:
            continue
        pad = max(2, int(0.006 * W))
        ok = True
        for x0, y0, x1, y1 in boxes:
            # строки над и под рядом — ровный фон: соседние точки почти одинаковы (у градиента — доли единицы, у фото —
            # десятки)
            rows = [g[y, x0:x1 + 1] for y in (y0 - pad - 2, y0 - pad, y1 + pad, y1 + pad + 2) if 0 <= y < H]
            if not rows or max(float(np.abs(np.diff(r)).mean()) for r in rows) > 2.0:
                ok = False  # под знаками не ровный фон, а рисунок: закрасить нечем
                break
        if not ok:
            continue
        for x0, y0, x1, y1 in boxes:
            out.append((max(0, x0 - pad) / W, max(0, y0 - pad) / H, min(W - 1, x1 + pad) / W, min(H - 1, y1 + pad) / H))
    return out


def erase(data: bytes, boxes: list[tuple[float, float, float, float]]) -> Optional[bytes]:
    """Картинка без знаков: в каждой рамке цвет каждого столбца тянется от строки над рамкой к строке под ней (у края
    картинки — одна строка). None — не вышло."""
    try:
        import numpy as np
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        fmt = (im.format or "PNG").upper()
        mode = im.mode
        arr = np.asarray(im.convert("RGBA"), dtype=float).copy()
    except Exception:  # noqa: BLE001
        return None
    H, W = arr.shape[:2]
    for fx0, fy0, fx1, fy1 in boxes:
        x0, x1 = int(fx0 * W), min(W - 1, int(round(fx1 * W)))
        y0, y1 = int(fy0 * H), min(H - 1, int(round(fy1 * H)))
        if x1 <= x0 or y1 <= y0:
            continue
        top = arr[max(0, y0 - 3):y0, x0:x1 + 1].mean(axis=0) if y0 >= 1 else None
        bot = arr[y1 + 1:min(H, y1 + 4), x0:x1 + 1].mean(axis=0) if y1 + 1 < H else None
        if top is None and bot is None:
            continue
        top = bot if top is None else top
        bot = top if bot is None else bot
        # строки-опоры сглажены вдоль строки: зерно фона не тянется вниз полосами
        k = max(3, (x1 - x0) // 40) | 1
        ker = np.ones(k) / k

        def smooth(row):
            pad = np.pad(row, ((k // 2, k // 2), (0, 0)), mode="edge")
            return np.stack([np.convolve(pad[:, c], ker, mode="valid") for c in range(row.shape[1])], axis=1)

        top, bot = smooth(top), smooth(bot)
        t = np.linspace(0.0, 1.0, y1 - y0 + 1)[:, None, None]
        arr[y0:y1 + 1, x0:x1 + 1] = top[None] * (1 - t) + bot[None] * t
    out = Image.fromarray(np.clip(np.rint(arr), 0, 255).astype("uint8"), "RGBA")
    if mode != "RGBA":
        out = out.convert("RGB" if fmt in ("JPEG", "JPG") or mode in ("RGB", "P", "L") else mode)
    buf = io.BytesIO()
    out.save(buf, format="JPEG" if fmt in ("JPEG", "JPG") else "PNG", **({"quality": 92} if fmt in ("JPEG", "JPG") else {"compress_level": 6}))
    return buf.getvalue()


def partner_marks(pkg: Package) -> dict[str, list[tuple[float, float, float, float]]]:
    """Фоновые картинки шаблона с рядом впечатанных знаков → рамки знаков."""
    out = {}
    for media in background_media(pkg):
        boxes = find_marks(pkg.read(media))
        if boxes:
            out[media] = boxes
    return out


def erase_partner_marks(pkg: Package) -> tuple[int, int]:
    """Закрашивает ряды знаков на фоновых картинках в пакете; (знаков, картинок)."""
    marks = images = 0
    for media, boxes in partner_marks(pkg).items():
        new = erase(pkg.read(media), boxes)
        if new is None:
            continue
        pkg.data[media] = new
        pkg.added.pop(media, None)
        marks += len(boxes)
        images += 1
    return marks, images
