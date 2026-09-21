"""Typography tokens: font families and a role-labelled size scale."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Optional

from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.template import FontUsage, Typography, TypeStep

_SYMBOL_FONTS = {"wingdings", "wingdings 2", "wingdings 3", "symbol", "webdings", "marlett"}


def _cluster_sizes(weights: dict[float, float], tol: float = 0.75) -> list[tuple[float, float]]:
    """Merge nearby sizes; returns [(size, weight)] with the heavier size as representative, sorted desc by size."""
    items = sorted(weights.items(), key=lambda kv: -kv[1])
    clusters: list[list[float]] = []  # [size, weight]
    for size, w in items:
        for cl in clusters:
            if abs(cl[0] - size) <= tol:
                cl[1] += w
                break
        else:
            clusters.append([size, w])
    return sorted(((s, w) for s, w in clusters), key=lambda t: -t[0])


def build_type_scale(shapes_per_slide: dict[int, list[ShapeInfo]], chrome_ids_per_slide: Optional[dict[int, set[str]]] = None) -> Typography:
    chrome_ids_per_slide = chrome_ids_per_slide or {}
    font_chars: Counter = Counter()
    font_bold: Counter = Counter()
    size_chars: dict[float, float] = defaultdict(float)
    bold_by_size: dict[float, float] = defaultdict(float)
    slide_max_sizes: list[float] = []
    title_sizes: Counter = Counter()
    align_chars = Counter()
    spacings: list[float] = []
    for idx, shapes in shapes_per_slide.items():
        chrome = chrome_ids_per_slide.get(idx, set())
        max_on_slide = 0.0
        for s in shapes:
            if s.id in chrome or not s.text:
                continue
            for p in s.text.paragraphs:
                if p.line_spacing:
                    spacings.append(p.line_spacing)
                align_chars[(p.align or "l")] += max(len(p.text), 1)
                for r in p.runs:
                    n = len(r.text.strip())
                    if n == 0:
                        continue
                    if r.font and r.font.lower() not in _SYMBOL_FONTS:
                        font_chars[r.font] += n
                        if r.bold:
                            font_bold[r.font] += n
                    if r.size_pt:
                        size_chars[round(r.size_pt, 2)] += n
                        if r.bold:
                            bold_by_size[round(r.size_pt, 2)] += n
                        max_on_slide = max(max_on_slide, r.size_pt)
                        if s.ph_type in ("title", "ctrTitle"):
                            title_sizes[round(r.size_pt, 2)] += n
        if max_on_slide:
            slide_max_sizes.append(max_on_slide)

    total_chars = sum(font_chars.values()) or 1
    families = [FontUsage(family=f, weight=round(c / total_chars, 4), bold_share=round(font_bold[f] / c, 3)) for f, c in font_chars.most_common()]

    clusters = _cluster_sizes(size_chars)
    total = sum(w for _, w in clusters) or 1.0
    scale: list[TypeStep] = []
    if clusters:
        # h1: mode of per-slide maximum sizes (title placeholders win when present)
        if title_sizes:
            h1 = title_sizes.most_common(1)[0][0]
        else:
            h1 = Counter(round(s, 1) for s in slide_max_sizes).most_common(1)[0][0] if slide_max_sizes else clusters[0][0]
        h1 = min((s for s, _ in clusters), key=lambda s: abs(s - h1))  # snap to cluster
        body_cands = [(s, w) for s, w in clusters if s <= h1 * 0.8]
        body = max(body_cands, key=lambda t: t[1])[0] if body_cands else clusters[-1][0]
        display_cands = [(s, w) for s, w in clusters if s >= h1 * 1.5]
        display = max(display_cands, key=lambda t: t[1])[0] if display_cands else None
        h2_cands = [(s, w) for s, w in clusters if body < s < h1]
        h2 = max(h2_cands, key=lambda t: t[1])[0] if h2_cands else None
        small_cands = [(s, w) for s, w in clusters if body * 0.6 <= s < body and w / total >= 0.005 and s >= 6]
        small = max(small_cands, key=lambda t: t[1])[0] if small_cands else None
        caption_cands = [(s, w) for s, w in clusters if small is not None and body * 0.5 <= s < small and w / total >= 0.003 and s >= 6]
        caption = max(caption_cands, key=lambda t: t[1])[0] if caption_cands else None

        def step(role: str, size: Optional[float]) -> None:
            if size is None:
                return
            w = next((w for s, w in clusters if s == size), 0.0)
            scale.append(TypeStep(role=role, size_pt=size, weight_bold_share=round(bold_by_size.get(size, 0.0) / w, 3) if w else 0.0, count=int(w)))

        step("display", display)
        step("h1", h1)
        step("h2", h2)
        step("body", body)
        step("small", small)
        step("caption", caption)
    total_align = sum(align_chars.values()) or 1
    left_share = (align_chars.get("l", 0) + align_chars.get("just", 0)) / total_align
    line_spacing = round(median(spacings), 2) if spacings else 1.2
    sizes_used = sorted({round(s, 2) for s, w in clusters if w >= 3})
    return Typography(families=families, scale=scale, sizes_used=sizes_used, left_align_share=round(left_share, 3), line_spacing=line_spacing)


def all_sizes(shapes_per_slide: dict[int, list[ShapeInfo]]) -> list[float]:
    """Every distinct size used in the deck (for 'size not in template scale' audits)."""
    sizes: set[float] = set()
    for shapes in shapes_per_slide.values():
        for s in shapes:
            if s.text:
                for p in s.text.paragraphs:
                    for r in p.runs:
                        if r.size_pt and r.text.strip():
                            sizes.add(round(r.size_pt, 2))
    return sorted(sizes)
