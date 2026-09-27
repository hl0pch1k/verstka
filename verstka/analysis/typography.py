"""Typography tokens: font families and a role-labelled size scale."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Optional

from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import EMU_PER_PT
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


_HEADING_CHARS = 90  # a longer paragraph in a title placeholder is body text parked there, not a heading


def _heading_placeholders(shapes: list[ShapeInfo], slide_h: Optional[int]) -> set[str]:
    """Title placeholders that hold a heading — not a brand wordmark («mybrand.» at 37 pt beside a 112 pt headline)."""
    from verstka.analysis.roles import wordmark_heading

    texts = [s for s in shapes if s.has_text]
    out = set()
    for s in shapes:
        if s.ph_type not in ("title", "ctrTitle"):
            continue
        if slide_h and s.has_text and wordmark_heading(s, texts, slide_h) is not None:
            continue
        out.add(s.id)
    return out


def build_type_scale(shapes_per_slide: dict[int, list[ShapeInfo]], chrome_ids_per_slide: Optional[dict[int, set[str]]] = None, *, slide_h: Optional[int] = None) -> Typography:
    """Families, role scale and every size used. With `slide_h` (EMU), a sparse scale is completed by a ladder of sizes
    relative to the slide height (`derived_size_ladder`), merged into `sizes_used`."""
    chrome_ids_per_slide = chrome_ids_per_slide or {}
    chrome_sizes: dict[float, float] = defaultdict(float)
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
        heading_ids = _heading_placeholders(shapes, slide_h)
        for s in shapes:
            if not s.text:
                continue
            if s.id in chrome:
                # page numbers, footers and kept sample marks are set on the slides too: their sizes are the template's
                for p in s.text.paragraphs:
                    for r in p.runs:
                        if r.size_pt and r.text.strip():
                            chrome_sizes[round(r.size_pt, 2)] += len(r.text.strip())
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
                        if s.id in heading_ids and len(p.text) <= _HEADING_CHARS:
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
    for size, n in chrome_sizes.items():
        if n >= 3 and not any(abs(size - u) <= 0.75 for u in sizes_used):
            sizes_used.append(size)
    sizes_used.sort()
    derived: list[float] = []
    if slide_h:
        body = next((st.size_pt for st in scale if st.role == "body"), None)
        derived = derived_size_ladder(sizes_used, body, slide_h)
        if derived:
            sizes_used = sorted(set(sizes_used) | set(derived))
    return Typography(families=families, scale=scale, sizes_used=sizes_used, derived_sizes=derived, left_align_share=round(left_share, 3), line_spacing=line_spacing)


def is_sparse_scale(sizes_used: list[float], body_pt: Optional[float], slide_h: int) -> bool:
    """A template whose own sizes cannot set a dense slide: fewer than 8 sizes in the text band of the slide
    (1.7–20 % of its height), nothing small (the smallest above 2.6 % H) or a body size above 4 % H (a placeholder
    default of 24–32 pt on an 11-inch LibreOffice slide). Measured: the dataset templates have 10–21 band sizes, the
    smallest ≤ 2.2 % H and a body ≤ 3.0 % H — none is sparse."""
    hpt = slide_h / EMU_PER_PT
    band = [s for s in sizes_used if s >= 7 and 0.017 * hpt <= s <= 0.20 * hpt]
    return len(band) < 8 or min(band, default=1e9) > 0.026 * hpt or (body_pt or 0.0) > 0.04 * hpt


def derived_size_ladder(sizes_used: list[float], body_pt: Optional[float], slide_h: int) -> list[float]:
    """The sizes a sparse template lacks: geometric steps (×1.12) from 1.8 % of the slide height up to 20 % of it
    (or the template's largest size), each rounded to 0.5 pt; a step within 4 % of a template size is dropped (the
    template's own size stands for it). Empty for a template whose own scale is fine."""
    if slide_h <= 0 or not is_sparse_scale(sizes_used, body_pt, slide_h):
        return []
    hpt = slide_h / EMU_PER_PT
    top = max([0.20 * hpt] + [s for s in sizes_used if s > 0])
    out: list[float] = []
    step = 0.018 * hpt
    while step <= top * 1.0001:
        r = round(step * 2) / 2
        if r >= 6 and r not in out and not any(abs(r - t) <= 0.04 * t for t in sizes_used):
            out.append(r)
        step *= 1.12
    return out


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
