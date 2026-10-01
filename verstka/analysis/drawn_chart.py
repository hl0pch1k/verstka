"""Charts a template draws with shapes or pictures instead of a native chart object.

Three drawings are read: columns standing on a common baseline (VK Tech p44: gradient pictures, two shades a column,
a «10» over each and «Текст» under it), bars growing from a common edge — one set or two back to back (VK Tech p41:
the left set grows leftwards from a common right edge, the right set rightwards, the category names between them) —
and a Gantt: bars of one height on rows of their own, shifted along a row of periods under them (VK Tech p52, «Май …
Октябрь»). With them go their value labels, their category labels, their headers and their legend.

The analysis reads such a drawing as one data area, like a native chart (`Pattern.data_box`): the bars of a sample
show the sample's own figures, so new content never keeps them with new labels — the renderer clears the area and
draws a native chart there. A row of equal cards, a staircase of cards with headings inside, a decorative set of
stripes without labels are not charts.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Optional

from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import Bbox, ShapeKind

_NUM_RE = re.compile(r"^\s*[-−–+]?\s*[$€£¥₽]?\s*\d[\d\s.,]*\s*(?:%|[A-Za-zА-Яа-яЁё₽$€£¥]{0,5}\.?)\s*$")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{2,}")
_BAR_GEOMS = {None, "rect", "roundRect", "round1Rect", "round2SameRect", "round2DiagRect", "snip1Rect", "snip2SameRect",
              "flowChartProcess", "flowChartAlternateProcess"}

MIN_AREA = 0.12  # a chart the slide is about: its area against the slide's


def _is_number(text: str) -> bool:
    return bool(_NUM_RE.match(text or ""))


def _bar_like(s: ShapeInfo, W: int, H: int, chrome_ids: set[str]) -> bool:
    """A filled rectangle or a picture that may be a bar: no words of its own (a figure inside it is a value label),
    not turned, not a hairline, not a ground."""
    if s.id in chrome_ids or s.is_placeholder or abs(s.rotation or 0.0) > 1.0:
        return False
    if s.has_text and not _is_number(s.plain_text):
        return False
    if s.kind == ShapeKind.pic:
        pass
    elif s.kind == ShapeKind.sp:
        if not s.fill_hex or s.fill_alpha < 0.3 or s.geometry not in _BAR_GEOMS:
            return False
    else:
        return False
    a = s.bbox.area / float(W * H)
    return 0.0006 <= a <= 0.25 and s.bbox.w >= 0.006 * W and s.bbox.h >= 0.012 * H


def _clusters(items: list, key, tol: float) -> list[list]:
    out: list[list] = []
    for it in sorted(items, key=key):
        if out and abs(key(out[-1][-1]) - key(it)) <= tol:
            out[-1].append(it)
        else:
            out.append([it])
    return out


def _spaced(centers: list[float]) -> bool:
    """Positions spread evenly enough for a chart's categories (no gap more than 2.6 times another)."""
    cs = sorted(centers)
    gaps = [b - a for a, b in zip(cs, cs[1:])]
    return bool(gaps) and min(gaps) > 0 and max(gaps) <= 2.6 * min(gaps)


def _worded_inside(bar: Bbox, texts: list[ShapeInfo]) -> bool:
    """A text with words stands inside the bar: a card with a heading (a staircase of cards), not a bar."""
    for t in texts:
        cx, cy = t.bbox.center
        if bar.contains_point(cx, cy) and _WORD_RE.search(t.plain_text) and not _is_number(t.plain_text):
            return True
    return False


def _union(boxes: list[Bbox]) -> Bbox:
    b = boxes[0]
    for o in boxes[1:]:
        b = b.union(o)
    return b


def _columns(bars: list[ShapeInfo], W: int, H: int) -> list[tuple[list[ShapeInfo], str, int]]:
    """Sets of columns on a common baseline: (bars, "col", series)."""
    out = []
    for cl in _clusters(bars, lambda s: s.bbox.y2, 0.012 * H):
        if len(cl) < 3:
            continue
        mw = median(s.bbox.w for s in cl)
        cl = [s for s in cl if abs(s.bbox.w - mw) <= 0.25 * mw]
        pos = _clusters(cl, lambda s: s.bbox.center[0], 0.35 * mw)
        if len(pos) < 3 or not _spaced([median(s.bbox.center[0] for s in p) for p in pos]):
            continue
        hs = [s.bbox.h for s in cl]
        if max(hs) < 1.1 * min(hs) or median(hs) < 0.8 * mw:
            continue
        out.append((cl, "col", max(len(p) for p in pos)))
    return out


def _bars(bars: list[ShapeInfo], W: int, H: int) -> list[tuple[list[ShapeInfo], str, int]]:
    """Sets of bars from a common left edge or a common right edge: (bars, "bar", series)."""
    out = []
    seen: set[str] = set()
    for key in (lambda s: s.bbox.x, lambda s: s.bbox.x2):
        for cl in _clusters(bars, key, 0.012 * W):
            if len(cl) < 3:
                continue
            mh = median(s.bbox.h for s in cl)
            cl = [s for s in cl if abs(s.bbox.h - mh) <= 0.25 * mh and s.id not in seen]
            if len(cl) < 3:
                continue
            pos = _clusters(cl, lambda s: s.bbox.center[1], 0.35 * mh)
            if len(pos) < 3 or not _spaced([median(s.bbox.center[1] for s in p) for p in pos]):
                continue
            ws = [s.bbox.w for s in cl]
            if max(ws) < 1.1 * min(ws) or median(ws) < 1.5 * mh:
                continue
            seen.update(s.id for s in cl)
            out.append((cl, "bar", max(len(p) for p in pos)))
    return out


def _gantt(bars: list[ShapeInfo], texts: list[ShapeInfo], W: int, H: int) -> list[tuple[list[ShapeInfo], str, int]]:
    """Bars of one height on rows of their own, starting at different places, over a row of three or more periods."""
    if len(bars) < 3:
        return []
    mh = median(s.bbox.h for s in bars)
    cl = [s for s in bars if abs(s.bbox.h - mh) <= 0.2 * mh and s.bbox.w >= 1.5 * s.bbox.h]
    rows = _clusters(cl, lambda s: s.bbox.center[1], 0.35 * mh)
    if len(rows) < 3 or any(len(r) > 2 for r in rows):
        return []
    starts = _clusters(cl, lambda s: s.bbox.x, 0.02 * W)
    if len(starts) < 2:
        return []
    box = _union([s.bbox for s in cl])
    axis = [t for t in texts if box.y2 - 0.01 * H <= t.bbox.center[1] <= box.y2 + 0.15 * H and box.x - 0.08 * W <= t.bbox.center[0] <= box.x2 + 0.08 * W]
    axis_rows = [r for r in _clusters(axis, lambda t: t.bbox.center[1], 0.015 * H) if len(r) >= 3]
    if not axis_rows:
        return []
    span = max(t.bbox.center[0] for t in axis_rows[0]) - min(t.bbox.center[0] for t in axis_rows[0])
    if span < 0.4 * box.w:
        return []
    return [(cl, "gantt", 1)]


def _labels(kind: str, bars: list[ShapeInfo], texts: list[ShapeInfo], W: int, H: int) -> list[ShapeInfo]:
    """The texts that label the bars: values over, inside or beside them, categories under or beside them."""
    box = _union([s.bbox for s in bars])
    out = []
    for t in texts:
        cx, cy = t.bbox.center
        if kind == "col":
            near = any(b.bbox.x - 0.6 * b.bbox.w <= cx <= b.bbox.x2 + 0.6 * b.bbox.w for b in bars)
            if near and box.y - 0.12 * H <= cy <= box.y2 + 0.12 * H:
                out.append(t)
        elif kind == "bar":
            near = any(b.bbox.y - 0.3 * b.bbox.h <= cy <= b.bbox.y2 + 0.3 * b.bbox.h for b in bars)
            if near and box.x - 0.25 * W <= cx <= box.x2 + 0.25 * W:
                out.append(t)
        else:  # gantt: the row names beside the rows, the periods under them
            row = any(b.bbox.y - 0.3 * b.bbox.h <= cy <= b.bbox.y2 + 0.3 * b.bbox.h for b in bars) and box.x - 0.3 * W <= cx <= box.x2 + 0.05 * W
            axis = box.y2 - 0.01 * H <= cy <= box.y2 + 0.15 * H and box.x - 0.08 * W <= cx <= box.x2 + 0.08 * W
            if row or axis:
                out.append(t)
    return out


def detect_drawn_chart(shapes: list[ShapeInfo], slide_w: int, slide_h: int, chrome_ids: Optional[set[str]] = None) -> Optional[tuple]:
    """(area, ids, None, "chart", hint) of a chart the slide draws with shapes or pictures, None when it has none.

    `hint`: how the drawing reads — {"direction": "col" | "bar" | "gantt", "bars": n, "series": n, "label_pt": size of
    its category labels, "value_pt": size of its value labels, "colors": fills of its bars (drawn shapes only)}."""
    W, H = slide_w, slide_h
    chrome_ids = chrome_ids or set()
    slide_area = float(W * H)
    texts = [s for s in shapes if s.has_text and s.id not in chrome_ids and not (s.is_placeholder and s.ph_type in ("title", "ctrTitle", "sldNum", "dt", "ftr"))
             and len(s.plain_text.strip()) <= 40 and s.bbox.area / slide_area <= 0.03]
    cands = [s for s in shapes if _bar_like(s, W, H, chrome_ids)]
    cands = [s for s in cands if not _worded_inside(s.bbox, texts)]
    if len(cands) < 3:
        return None
    sets = _columns(cands, W, H) + _bars(cands, W, H)
    if not sets:
        sets = _gantt(cands, texts, W, H)
    found: list[tuple[list[ShapeInfo], str, int, list[ShapeInfo]]] = []
    for bars, kind, series in sets:
        labels = _labels(kind, bars, texts, W, H)
        n_pos = len(_clusters(bars, (lambda s: s.bbox.center[0]) if kind == "col" else (lambda s: s.bbox.center[1]), 0.35 * median((s.bbox.w if kind == "col" else s.bbox.h) for s in bars)))
        if len(labels) < max(2, n_pos // 2):
            continue  # stripes without figures or names: decoration, not a chart
        found.append((bars, kind, series, labels))
    if not found:
        return None
    # two sets side by side over the same rows (bars back to back) or one beside another read as one chart
    found.sort(key=lambda f: -len(f[0]))
    main = found[0]
    keep = [main]
    mbox = _union([s.bbox for s in main[0]])
    for f in found[1:]:
        b = _union([s.bbox for s in f[0]])
        beside = min(b.y2, mbox.y2) - max(b.y, mbox.y) >= 0.5 * min(b.h, mbox.h)
        above = min(b.x2, mbox.x2) - max(b.x, mbox.x) >= 0.5 * min(b.w, mbox.w)
        if beside or above:
            keep.append(f)
    bars = [s for f in keep for s in f[0]]
    labels = list({t.id: t for f in keep for t in f[3]}.values())
    ids = {s.id for s in bars} | {t.id for t in labels}
    area = _union([s.bbox for s in bars] + [t.bbox for t in labels])
    if area.area < MIN_AREA * slide_area:
        return None
    # what stands inside the drawing — the legend's dots and names, the frames of the labels — and what stands right
    # on top of it — the header pill of a set of bars — belongs to it; the heading, the furniture and the ground never do
    pad_x, pad_y = 0.015 * W, 0.02 * H
    for _ in range(2):
        for s in shapes:
            if s.id in ids or s.id in chrome_ids or s.bbox.area <= 0 or s.bbox.area >= 0.6 * area.area:
                continue
            if s.is_placeholder and s.ph_type in ("title", "ctrTitle", "subTitle", "sldNum", "dt", "ftr"):
                continue
            if s.has_text and len(s.plain_text.strip()) > 60:
                continue
            cx, cy = s.bbox.center
            inside = area.x - pad_x <= cx <= area.x2 + pad_x and area.y - pad_y <= cy <= area.y2 + pad_y
            on_top = area.x <= cx <= area.x2 and area.y - 0.03 * H <= s.bbox.y2 <= area.y + 0.01 * H and s.bbox.h <= 0.1 * H
            if inside or on_top:
                ids.add(s.id)
                area = area.union(s.bbox)
    # label boxes run wider than their figures (a «10» in a box twice its bar's width hangs over the slide's edge):
    # the area is the drawing's, inside the slide
    bx = _union([s.bbox for s in bars])
    x0 = area.x if area.x >= 0 else max(bx.x - int(0.01 * W), 0)
    x1 = area.x2 if area.x2 <= W else min(bx.x2 + int(0.01 * W), W)
    y0, y1 = max(area.y, 0), min(area.y2, H)
    area = Bbox(x=int(x0), y=int(y0), w=int(max(x1 - x0, 1)), h=int(max(y1 - y0, 1)))
    kind = main[1]
    cats = [t for t in labels if not _is_number(t.plain_text)]
    vals = [t for t in labels if _is_number(t.plain_text)]

    def size(ts: list[ShapeInfo]) -> Optional[float]:
        sz = [t.text.dominant_size_pt for t in ts if t.text is not None and t.text.dominant_size_pt]
        return round(median(sz), 1) if sz else None

    colors = []
    for s in sorted(bars, key=lambda s: (s.bbox.x, s.bbox.y)):
        if s.kind == ShapeKind.sp and s.fill_hex and s.fill_hex not in colors:
            colors.append(s.fill_hex)
    hint = {"direction": kind, "bars": len(bars), "series": max(f[2] for f in keep) if kind != "bar" or len(keep) == 1 else len(keep),
            "label_pt": size(cats), "value_pt": size(vals), "colors": colors[:6]}
    return area, ids, None, "chart", hint
