"""Sample slides for a template that brings (almost) none: a PowerPoint template (.potx) or theme usually holds its
master and layouts and no slide at all, or a single empty title slide; a Google Slides theme may hold a cover only.

The analysis learns a template from its slides (type scale, colours, the cleanest canvas for the composer, the cover
and divider samples the renderer clones), so a template without slides left it nothing to learn from: every deck on a
bare .potx came out broken. Here the workspace copy of such a template (never the person's file) gets one sample
slide per useful layout, placeholders filled with neutral Russian text the way a template's author fills them. The
original is kept next to it (original.pptx) so a new analysis starts from it again.

Which layouts: the title slide, title and content, section header, two content, comparison, title only, content or
picture with caption — in the master's order, each kind once, vertical-text layouts skipped; at most MAX_SAMPLES."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MIN_SLIDES = 2  # a template with fewer slides than this (none, or a cover alone) gets samples from its layouts
MAX_SAMPLES = 9
SAMPLE_MARK = "verstka-sample"  # the name of a sample slide (its cSld/@name), so a re-analysis knows them

# a layout's kind by its placeholders and name: (kind, name keywords) — the order is the samples' order
_TITLE = ("title", "ctrTitle")
_BODY = ("body", "obj", None)  # «None»: a placeholder without type is a body (content) placeholder

SAMPLE_TEXT = {
    "cover_title": "Название презентации",
    "cover_sub": "Подзаголовок презентации · 2026",
    "title": "Заголовок слайда",
    "section": "Название раздела",
    "section_sub": "Короткое описание раздела",
    "bullets": ["Первый пункт: коротко о главном", "Второй пункт с пояснением в одну строку", "Третий пункт и вывод"],
    "left": ["Первый тезис слева", "Второй тезис с деталью"],
    "right": ["Тезис справа", "Ещё один факт"],
    "caption": "Подпись: несколько слов о картинке или о содержании слайда",
    "compare_a": "Вариант А",
    "compare_b": "Вариант Б",
}


def _ph_type(sh) -> Optional[str]:
    try:
        t = sh.placeholder_format.type
    except (ValueError, AttributeError):
        return None
    name = str(t).split(".")[-1].split(" ")[0].lower() if t is not None else "body"
    return {"center_title": "ctrTitle", "subtitle": "subTitle", "object": "obj"}.get(name, name)


def _vertical(sh) -> bool:
    body = sh._element.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr")
    return body is not None and (body.get("vert") or "horz") not in ("horz",)


def layout_kind(layout) -> Optional[str]:
    """«cover», «content», «section», «two», «comparison», «title_only», «caption» — or None for a layout that makes no
    useful sample (blank, vertical text, a picture only)."""
    name = (layout.name or "").lower()
    phs = list(layout.placeholders)
    types = [_ph_type(p) for p in phs]
    if any(_vertical(p) for p in phs if _ph_type(p) in ("body", "obj", "title")):
        return None
    has_title = any(t in _TITLE for t in types)
    ctr = "ctrTitle" in types or "title slide" in name or "титульн" in name
    bodies = [p for p, t in zip(phs, types) if t in ("body", "obj")]
    if ctr and has_title:
        return "cover"
    if "section" in name or "раздел" in name:
        return "section" if has_title else None
    if not has_title:
        return None
    if "comparison" in name or "сравнен" in name or len(bodies) >= 4:
        return "comparison"
    if "caption" in name or "подпис" in name:
        return "caption"
    if len(bodies) >= 2 and ("two" in name or "два" in name or "2" in name or len(bodies) == 2):
        return "two"
    if not bodies:
        return "title_only" if "title only" in name or "только заголовок" in name or len(phs) <= 3 else None
    return "content"


_ORDER = ["cover", "content", "section", "two", "comparison", "title_only", "caption"]


def _fill(tf, lines) -> None:
    if isinstance(lines, str):
        lines = [lines]
    tf.text = lines[0]
    for ln in lines[1:]:
        tf.add_paragraph().text = ln


def _fill_slide(slide, kind: str) -> None:
    T = SAMPLE_TEXT
    titles = [p for p in slide.placeholders if _ph_type(p) in _TITLE]
    subs = [p for p in slide.placeholders if _ph_type(p) == "subTitle"]
    bodies = [p for p in slide.placeholders if _ph_type(p) in ("body", "obj") and p.has_text_frame]
    bodies.sort(key=lambda p: ((p.left or 0), (p.top or 0)))
    if titles:
        titles[0].text_frame.text = {"cover": T["cover_title"], "section": T["section"]}.get(kind, T["title"])
    if kind == "cover":
        target = subs[0] if subs else (bodies[0] if bodies else None)
        if target is not None:
            target.text_frame.text = T["cover_sub"]
        return
    if kind == "section":
        target = subs[0] if subs else (bodies[0] if bodies else None)
        if target is not None:
            target.text_frame.text = T["section_sub"]
        return
    if kind == "comparison" and len(bodies) >= 4:
        # the two small heads over the two bodies (smaller boxes first by height)
        heads = sorted(bodies, key=lambda p: (p.height or 0))[:2]
        rest = [b for b in bodies if b not in heads]
        for h, text in zip(sorted(heads, key=lambda p: p.left or 0), (T["compare_a"], T["compare_b"])):
            h.text_frame.text = text
        for b, lines in zip(sorted(rest, key=lambda p: p.left or 0), (T["left"], T["right"])):
            _fill(b.text_frame, lines)
        return
    if kind == "two" and len(bodies) >= 2:
        _fill(bodies[0].text_frame, T["left"])
        _fill(bodies[1].text_frame, T["right"])
        return
    if kind == "caption":
        texts = [b for b in bodies]
        if texts:
            # the caption box is the smaller one; a content box (if any) gets the bullets
            texts.sort(key=lambda p: (p.width or 0) * (p.height or 0))
            texts[0].text_frame.text = T["caption"]
            for b in texts[1:]:
                _fill(b.text_frame, T["bullets"])
        return
    if bodies:
        _fill(bodies[0].text_frame, T["bullets"])


def plan_samples(prs) -> list:
    """The layouts to instantiate: one per useful kind the template's own slides do not already use, in _ORDER."""
    used_kinds = set()
    for s in prs.slides:
        k = layout_kind(s.slide_layout)
        if k:
            used_kinds.add(k)
    picked: dict[str, object] = {}
    for master in prs.slide_masters:
        for layout in master.slide_layouts:
            k = layout_kind(layout)
            if k and k not in used_kinds and k not in picked:
                picked[k] = layout
    return [picked[k] for k in _ORDER if k in picked][:MAX_SAMPLES]


def ensure_samples(source: Path, original: Optional[Path] = None) -> int:
    """Give the template at `source` sample slides from its layouts when it has fewer than MIN_SLIDES slides. `original`
    (default: source's folder / original.pptx) keeps the file as it came; a template already analysed with samples is
    rebuilt from it. Returns the number of sample slides added (0: the template has enough slides of its own)."""
    from pptx import Presentation

    source = Path(source)
    original = Path(original) if original else source.with_name("original.pptx")
    base = original if original.exists() else source
    try:
        prs = Presentation(str(base))
    except Exception as e:  # noqa: BLE001 - a package python-pptx cannot open is analysed as it is (it may still render)
        log.warning("samples: %s not opened (%s)", base.name, e)
        return 0
    if len(prs.slides) >= MIN_SLIDES:
        return 0
    layouts = plan_samples(prs)
    if not layouts:
        return 0
    if not original.exists():
        shutil.copyfile(source, original)
    added = 0
    for layout in layouts:
        kind = layout_kind(layout)
        try:
            slide = prs.slides.add_slide(layout)
            slide._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}cSld").set("name", f"{SAMPLE_MARK}:{kind}")
            _fill_slide(slide, kind)
            added += 1
        except Exception:  # noqa: BLE001 - a layout python-pptx cannot instantiate is skipped
            log.debug("samples: layout %r skipped", getattr(layout, "name", "?"), exc_info=True)
    if added:
        prs.save(str(source))
        log.info("samples: %d sample slide(s) from layouts added to %s", added, source.name)
    return added


def is_sample(slide_xml_name: Optional[str]) -> bool:
    return bool(slide_xml_name) and bool(re.match(rf"^{SAMPLE_MARK}:", slide_xml_name or ""))
