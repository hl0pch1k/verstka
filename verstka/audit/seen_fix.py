"""«Исправить слайд» по замечанию «Взгляда дизайнера» — правки на месте того, что модель увидела на готовом слайде.

Замечание модели (check `design_review`, audit/eyes.py) не называет элементов: «тёмно-серый заголовок на чёрном блоке»,
«текст мелкий», «слово разорвано», «текст обрезан». Раньше его лечил только дизайнер, переложив слайд заново, —
обложку, разделитель и финальный слайд он не перекладывает, а цвет текста новая вёрстка выбирала той же ошибкой: кнопка
отвечала «Слайд остался прежним: замечания остались» (замечание владельца 18.10, п. 8).

Здесь каждое такое замечание правится на месте по измерению, без подгонки под шаблон:

* `low_contrast` — фон под каждым текстом читается дважды: на картинке слайда (так его видят превью, PDF и модель:
  LibreOffice, например, рисует прозрачную часть картинки шаблона с эффектом «оттенки серого» чёрной) и по слоям файла
  (`layers.letter_grounds`: так его покажет PowerPoint). Текст получает цвет шаблона, который читается на обоих (WCAG:
  4,5:1, крупный 3:1); если такого нет — подложку цвета фона с картинки и цвет, который на ней читается: слайд выглядит
  одинаково в превью, PDF и PowerPoint.
* `too_small` — текст мельче основного размера шаблона поднимается до него (или до наименьшего читаемого), если блок
  его вмещает.
* `word_broken`, `text_cut` — разрядка капители снимается, затем кегль уменьшается шагами, пока самое длинное слово
  не встанет в строку и текст — в блок, но не ниже основного размера шаблона.

Чего на месте не исправить (наложение, пустоты, лишний элемент, текст, которому не хватает места даже без разрядки),
возвращается с причиной по-русски — её говорит кнопка.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from lxml import etree

log = logging.getLogger(__name__)

# what the rules fix in place, by the review's code (eyes.CODES)
INPLACE_CODES = frozenset({"low_contrast", "too_small", "word_broken", "text_cut", "overlap"})
# why the rest cannot be fixed in place (the person's words)
NOT_INPLACE: dict[str, str] = {
    "overlap": "наложение блоков, кроме текста, на месте не развести",
    "cramped": "плотный текст на месте не разгрузить",
    "unbalanced": "пустоты и перекос на месте не исправить",
    "leftover": "лишний элемент на месте не убрать",
    "chart_unreadable": "диаграмму на месте не упростить",
}
_CHROME_PH = ("sldNum", "ftr", "dt")
_SHRINK = 0.92  # one step of a shrink
_PLATE_SHARE = 0.55
_APART = 3.0  # grounds of one text this far apart (contrast) get a plate rather than a colour between them  # the share of the box a ground colour covers on the image to be the plate's colour


def code_of(issue: Any) -> Optional[str]:
    """The review's code of a «Взгляд дизайнера» remark (None for any other remark)."""
    if getattr(issue, "check_id", None) != "design_review":
        return None
    det = getattr(issue, "details", None) or {}
    c = det.get("code") if isinstance(det, dict) else None
    return str(c) if c else None


@dataclass
class SeenFix:
    """What the in-place fixes of the review's remarks did on one slide."""

    records: list[dict] = field(default_factory=list)  # {"slide", "kind", "element_id", "result"} like autofix._xml_fixes
    cured: set[str] = field(default_factory=set)  # codes measured as fixed (or with nothing left to fix)
    left: dict[str, str] = field(default_factory=dict)  # code → why it stays
    # codes the rules found nothing to change for (the measure reads the slide as fine, the model did not): the slide
    # is laid out again for them — a remark never leaves the slide as it was
    untouched: set[str] = field(default_factory=set)

    @property
    def titled(self) -> bool:
        """The slide's heading was among what was changed."""
        return any(r.get("role") == "title" for r in self.records)

    def why(self) -> Optional[str]:
        return "; ".join(dict.fromkeys(self.left.values())) or None

    def why_for(self, frame: bool, name: Optional[str] = None) -> str:
        """Why the slide stayed as it was, and what the person can do (the button's line)."""
        said = self.why() or "замечание на месте не исправить"
        said = said[:1].upper() + said[1:]
        if frame:
            return f"{said}, а другие образцы шаблона для {name or 'этого слайда'} выходят хуже — выберите другой вариант презентации или напишите помощнику, что поменять"
        return f"{said}, а другие образцы шаблона выходят хуже — напишите пожелание к слайду или выберите другой вариант"


def seen_words(code: str) -> str:
    """The review's words of a code: «текст плохо читается на фоне»."""
    from verstka.audit.eyes import CODES

    return CODES.get(code, code)


# ---------------------------------------------------------------------------- measuring


def _contrast(a: str, b: str) -> float:
    from verstka.schemas.common import contrast_ratio

    try:
        return contrast_ratio(a, b)
    except ValueError:
        return 21.0


def image_ground(image: Any, box: tuple[int, int, int, int], slide_w: int, slide_h: int) -> Optional[tuple[str, float]]:
    """(colour, share) of the ground the box shows on the slide's picture: the commonest colour (8 levels a channel) of
    its pixels and the share of the box it covers — the letters are the minority. None for a box off the picture."""
    from verstka.schemas.common import rgb_to_hex

    x, y, w, h = box
    W, H = image.size
    l, t = max(0, int(x / slide_w * W)), max(0, int(y / slide_h * H))
    r, b = min(W, int((x + w) / slide_w * W)), min(H, int((y + h) / slide_h * H))
    if r - l < 2 or b - t < 2:
        return None
    crop = image.convert("RGB").crop((l, t, r, b))
    if crop.width * crop.height > 40000:
        k = (crop.width * crop.height / 40000) ** 0.5
        crop = crop.resize((max(2, int(crop.width / k)), max(2, int(crop.height / k))))
    bins: dict[tuple[int, int, int], list[int]] = {}
    raw = crop.tobytes()
    px = [raw[k:k + 3] for k in range(0, len(raw), 3)]
    for p in px:
        key = (p[0] >> 5, p[1] >> 5, p[2] >> 5)
        acc = bins.setdefault(key, [0, 0, 0, 0])
        acc[0] += 1
        acc[1] += p[0]
        acc[2] += p[1]
        acc[3] += p[2]
    n, sr, sg, sb = max(bins.values(), key=lambda v: v[0])
    return rgb_to_hex(round(sr / n), round(sg / n), round(sb / n)).upper(), n / float(len(px))


def _snap(hex_: str, cands: Iterable[str]) -> str:
    """The candidate colour `hex_` is all but equal to (contrast under 1.1:1), else `hex_` itself."""
    near = min(cands, key=lambda c: _contrast(c, hex_), default=None)
    return near if near is not None and _contrast(near, hex_) < 1.1 else hex_


def _need(size: float, bold: bool) -> float:
    return 3.0 if size >= 18 or (bold and size >= 14) else 4.5  # WCAG: large text is 18 pt, or 14 pt bold


def _candidates(manifest: Any, have: Optional[str]) -> list[str]:
    toks = manifest.tokens
    roles = ("text.primary", "text.secondary", "background.light", "background.dark")
    out = [toks.color_for(r) for r in roles] + [c.hex for c in toks.colors if any(str(r).startswith("accent.") for r in c.roles)] + ["FFFFFF", "000000"]
    if have:
        out.insert(0, have)
    return [c.upper() for c in dict.fromkeys(c for c in out if c)]


def best_color(cands: Iterable[str], grounds: Iterable[str]) -> tuple[Optional[str], float]:
    """The colour that reads best on every one of `grounds` (the largest least contrast), and that contrast."""
    gs = [g for g in grounds if g]
    best, worst = None, 0.0
    for c in cands:
        m = min((_contrast(c, g) for g in gs), default=21.0)
        if m > worst + 1e-6:
            best, worst = c, m
    return best, worst


# ---------------------------------------------------------------------------- the XML


def _q(tag: str) -> str:
    from verstka.analysis.xmlns import q

    return q(tag)


def set_plate(el: etree._Element, hex_: str) -> bool:
    """A solid fill of `hex_` on the shape (its geometry kept; a placeholder without one is a rectangle)."""
    spPr = el.find(_q("p:spPr"))
    if spPr is None:
        return False
    for t in ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"):
        for old in spPr.findall(_q(t)):
            spPr.remove(old)
    fill = etree.Element(_q("a:solidFill"))
    etree.SubElement(fill, _q("a:srgbClr")).set("val", hex_.upper())
    pos = 0
    for k, child in enumerate(spPr):
        if child.tag in (_q("a:xfrm"), _q("a:custGeom"), _q("a:prstGeom")):
            pos = k + 1
    spPr.insert(pos, fill)
    return True


def _rprs(el: etree._Element) -> list[etree._Element]:
    """Every run property of the shape's text (runs, fields, line breaks, paragraph ends); a run without one gets one."""
    out: list[etree._Element] = []
    for tag in ("a:r", "a:fld"):
        for r in el.iter(_q(tag)):
            rPr = r.find(_q("a:rPr"))
            if rPr is None:
                rPr = etree.Element(_q("a:rPr"))
                r.insert(0, rPr)
            out.append(rPr)
    out.extend(el.iter(_q("a:endParaRPr")))
    for br in el.iter(_q("a:br")):
        rPr = br.find(_q("a:rPr"))
        if rPr is not None:
            out.append(rPr)
    return out


def set_sizes(el: etree._Element, factor: float, base_pt: float) -> None:
    """Every run `factor` times its size (a run whose size is inherited: `base_pt` times it)."""
    for rPr in _rprs(el):
        cur = int(rPr.get("sz")) / 100.0 if rPr.get("sz") else base_pt
        rPr.set("sz", str(max(100, int(round(cur * factor * 2)) * 50)))


def set_spacing_off(el: etree._Element) -> None:
    for rPr in _rprs(el):
        rPr.set("spc", "0")


# ---------------------------------------------------------------------------- fit


def _avail(e: Any) -> tuple[float, float]:
    """(width, height) in pt the text of element `e` has inside its insets."""
    from verstka.schemas.common import EMU_PER_PT

    l, t, r, b = e.insets_emu
    return max(1.0, (e.bbox.w - l - r) / EMU_PER_PT), max(1.0, (e.bbox.h - t - b) / EMU_PER_PT)


def _words_fit(e: Any, family: Optional[str], factor: float, spc: float) -> bool:
    from verstka.rendering.fonts import text_width_pt

    width, _ = _avail(e)
    for p in e.paragraphs:
        for r in p.runs:
            size = (r.size_pt or e.dominant_size or 14.0) * factor
            for word in r.text.split():
                if text_width_pt(word, r.font or family, size, r.bold, caps=e.caps, spc_pt=spc * factor) > width * 0.98:
                    return False
    return True


def _scaled(e: Any, factor: float, spc: float) -> Any:
    """Element `e` with its runs `factor` times their size and letter-spacing `spc` times `factor`."""
    if factor == 1.0 and spc == e.spc_pt:
        return e
    paras = [p.model_copy(update={"runs": [r.model_copy(update={"size_pt": r.size_pt * factor if r.size_pt else None}) for r in p.runs]}) for p in e.paragraphs]
    return e.model_copy(update={"paragraphs": paras, "spc_pt": spc * factor})


def _need_height(e: Any, family: Optional[str], factor: float, spc: float) -> float:
    """The height (pt) the text of `e` takes at its box's width, its sizes `factor` times, letter-spacing `spc` — as
    the audit measures it (`text_height_needed_pt`)."""
    from verstka.audit.checks.common import text_height_needed_pt

    return text_height_needed_pt(_scaled(e, factor, spc))[0]


def _height_fits(e: Any, family: Optional[str], factor: float, spc: float, room: Optional[float] = None) -> bool:
    return _need_height(e, family, factor, spc) <= (room if room is not None else _avail(e)[1]) * 1.05


_GAP = 0.012  # the gap (share of the slide's width) a narrowed text keeps from what it ran into
_BIG = 0.4  # a template layer this share of the slide or more is a ground, not something a text runs into


def free_box(e: Any, slide_ir: Any, slide_w: int, slide_h: int) -> Any:
    """The box of text `e` cut short of what it runs into on the slide: another block, a picture, a shape of the
    layout (a circle at the heading's end) — its right edge stops before the first thing that starts right of the
    text's start, its bottom before the first thing that starts below the text's middle. A card the text stands on
    (holding most of the text's box) and a ground covering a large part of the slide are no obstacles."""
    from verstka.schemas.common import Bbox

    b = e.bbox
    x2, y2 = b.x2, b.y2
    gap_x, gap_y = int(_GAP * slide_w), int(_GAP * slide_h)
    others = [o for o in slide_ir.elements if o is not e and not o.nested and o.type in ("text", "picture", "shape", "chart", "table", "group")]
    others += [o for o in getattr(slide_ir, "template_elements", []) or [] if o.type in ("picture", "shape") and o.bbox.area < _BIG * slide_w * slide_h]
    for o in others:
        ob = o.bbox
        ix = min(b.x2, ob.x2) - max(b.x, ob.x)
        iy = min(b.y2, ob.y2) - max(b.y, ob.y)
        if ix <= 0 or iy <= 0 or ix * iy < 0.02 * max(1, b.area):
            continue
        if ix * iy >= 0.8 * b.area:
            continue  # the text stands on it
        if o.type == "text" and not o.has_text and not o.fill_hex:
            continue
        if ob.x > b.x + 0.3 * b.w:
            x2 = min(x2, ob.x - gap_x)
        elif ob.y > b.y + 0.5 * b.h:
            y2 = min(y2, ob.y - gap_y)
    if (x2, y2) == (b.x2, b.y2):
        return b
    return Bbox(x=b.x, y=b.y, w=max(1, x2 - b.x), h=max(1, y2 - b.y))


def ink_below(image: Any, e: Any, slide_ir: Any, slide_w: int, slide_h: int) -> float:
    """How far (share of the box's height) the letters of text `e` run below its box on the slide's picture: the rows
    under the box, across its width, down to the next block below it, that carry ink unlike their own ground — a gap
    of two lines ends them. 0 when nothing runs out (the measure of the fonts may be wrong; the picture is not)."""
    W, H = image.size
    b = e.bbox
    l, r = max(0, int(b.x / slide_w * W)), min(W, int(b.x2 / slide_w * W))
    top, bottom = int(b.y / slide_h * H), int(b.y2 / slide_h * H)
    if r - l < 4 or bottom - top < 2 or bottom >= H - 1:
        return 0.0
    limit = H
    for o in slide_ir.elements:
        if o is e or o.bbox.y < b.y2 or o.bbox.x2 <= b.x or o.bbox.x >= b.x2:
            continue
        limit = min(limit, int(o.bbox.y / slide_h * H))
    line_px = max(2, int((e.dominant_size or 12.0) * 1.2 * 12700 / slide_h * H))
    gray = image.convert("L")
    last, gap = bottom, 0
    for y in range(bottom + 1, min(H, limit)):
        row = gray.crop((l, y, r, y + 1)).tobytes()
        ground = max(set(row), key=row.count)
        inked = sum(1 for v in row if abs(v - ground) > 60) >= max(2, 0.004 * len(row))
        if inked:
            last, gap = y, 0
        else:
            gap += 1
            if gap > 2 * line_px:
                break
    return (last - bottom) / float(max(1, bottom - top))


# ---------------------------------------------------------------------------- the fix


def _holder(e: Any, slide_ir: Any, slide_area: Optional[float] = None) -> Any:
    """The filled card or panel text `e` stands on (holding most of its box; of several stacked — a plate on a panel —
    the largest that is not a ground of the slide), or None."""
    best = None
    big = 0.5 * slide_area if slide_area else None
    for o in slide_ir.elements:
        if o is e or o.type not in ("shape", "text") or not o.fill_hex:
            continue
        ob, b = o.bbox, e.bbox
        ix = min(b.x2, ob.x2) - max(b.x, ob.x)
        iy = min(b.y2, ob.y2) - max(b.y, ob.y)
        if ix > 0 and iy > 0 and ix * iy >= 0.8 * b.area and ob.area > b.area and (big is None or ob.area < big) and (best is None or ob.area > best.bbox.area):
            best = o
    return best


def fix_spill(pptx: Path, n: int, manifest: Any, image: Optional[Path], render: Optional[Callable[[Path], Optional[Path]]] = None,
              rounds: int = 3) -> tuple[list[dict], set[str], bool]:
    """Text whose letters run below its box on the slide's picture (the fonts' measure says it fits — a code font the
    renderer sets wider, wrapping every long line): first the box takes the whole card it stands on (inside the card's
    own padding), then the text is set smaller by what still runs out, on the template's scale, never under its least
    size. With `render` the slide is rendered again after each round and measured again. Returns (records, the
    elements changed, whether some text still runs out)."""
    from PIL import Image
    from pptx import Presentation

    from verstka.audit.autofix import _text_floors
    from verstka.audit.ir import build_deck_ir
    from verstka.rendering.deck import set_element_pos, slide_shape_elements

    _, least = _text_floors(manifest)
    typo = manifest.tokens.typography
    scale = sorted({float(x) for x in (typo.sizes_used or [st.size_pt for st in typo.scale])})
    records: list[dict] = []
    touched: set[str] = set()
    widened: set[str] = set()
    still = False
    for k in range(rounds):
        if image is None or not Path(image).exists():
            break
        with Image.open(image) as im:
            shot = im.convert("RGB")
        ir = build_deck_ir(pptx, with_images=False)
        sl = ir.slides[n - 1]
        prs = Presentation(str(pptx))
        by_id = slide_shape_elements(prs.slides[n - 1])
        changed, still = False, False
        for e in sl.elements:
            if e.type != "text" or not e.has_text or e.nested or e.ph_type in _CHROME_PH or str(e.id) not in by_id:
                continue
            out_by = ink_below(shot, e, sl, ir.slide_w, ir.slide_h)
            if out_by < 0.02:
                continue
            el = by_id[str(e.id)]
            card = _holder(e, sl, float(ir.slide_w) * ir.slide_h)
            if card is not None and str(e.id) not in widened:
                pad = max(0, min(e.bbox.x - card.bbox.x, e.bbox.y - card.bbox.y))
                w = card.bbox.x2 - pad - e.bbox.x
                h = card.bbox.y2 - pad - e.bbox.y
                widened.add(str(e.id))
                if w > e.bbox.w * 1.03 or h > e.bbox.h * 1.03:
                    set_element_pos(el, w=max(w, e.bbox.w), h=max(h, e.bbox.h))
                    records.append({"slide": n, "kind": "fit_text", "element_id": str(e.id), "result": "Блок текста растянут на всю карточку: текст выходил за блок", "role": "text"})
                    touched.add(str(e.id))
                    changed = True
                    continue
            size = e.dominant_size or 12.0
            want = size / (1.0 + out_by) * 0.97
            got = [x for x in scale if least - 0.01 <= x <= want + 0.01]
            new = got[-1] if got else max(least, round(want * 2) / 2)
            if new >= size - 0.01:
                still = True
                continue
            set_sizes(el, new / size, size)
            records.append({"slide": n, "kind": "fit_text", "element_id": str(e.id), "result": f"Шрифт уменьшен до {new:g} пт: текст выходил за блок", "role": "text"})
            touched.add(str(e.id))
            changed = True
        if not changed:
            break
        prs.save(str(pptx))
        image = render(pptx) if render is not None else None
        if image is None:
            break
    return records, touched, still


def fix_seen(pptx: Path, n: int, codes: Iterable[str], manifest: Any, image: Optional[Path] = None, shown: Iterable[Path] = (),
             render: Optional[Callable[[Path], Optional[Path]]] = None) -> SeenFix:
    """Fix in place, on slide `n` of `pptx` (saved over), what the review's `codes` name. `image` — the slide's picture
    rendered now, `shown` — the pictures of it the person and the model saw (the variant's preview): `low_contrast`
    reads the ground on them, `text_cut` the letters below a box. `render(pptx)` — the slide's picture again after a
    change (the spill is measured again). Codes this module cannot fix in place come back in `left` with the reason."""
    from PIL import Image
    from pptx import Presentation

    from verstka.audit.autofix import _recolor, _text_floors
    from verstka.audit.checks.common import is_chrome_like
    from verstka.audit.ir import build_deck_ir
    from verstka.rendering.deck import slide_shape_elements
    from verstka.rendering.layers import letter_grounds

    out = SeenFix()
    codes = set(c for c in codes if c)
    for c in sorted(codes - INPLACE_CODES):
        out.left[c] = NOT_INPLACE.get(c, "это замечание на месте не исправить")
    todo = codes & INPLACE_CODES
    if not todo:
        return out
    n_spill, spilled, spill_left = 0, set(), False
    if "text_cut" in todo:
        recs, spilled, spill_left = fix_spill(pptx, n, manifest, image, render)
        out.records.extend(recs)
        n_spill = len(recs)
        if recs and render is not None and "low_contrast" in todo:
            image = render(pptx)  # the ground is read on the slide as it is now
    ir = build_deck_ir(pptx, with_images=False)
    if not 1 <= n <= len(ir.slides):
        return out
    prs = Presentation(str(pptx))
    slide = prs.slides[n - 1]
    by_id = slide_shape_elements(slide)
    family = manifest.tokens.typography.primary_family
    body, least = _text_floors(manifest)
    typo = manifest.tokens.typography
    scale = sorted({float(x) for x in (typo.sizes_used or [st.size_pt for st in typo.scale])})

    def on_scale(pt: float, lo: float) -> Optional[float]:
        """The template's largest size in [lo, pt] (a size off its scale is a remark of its own)."""
        got = [x for x in scale if lo - 0.01 <= x <= pt + 0.01]
        return got[-1] if got else None
    texts = [
        e for e in ir.slides[n - 1].elements
        if e.type == "text" and e.has_text and not e.nested and e.ph_type not in _CHROME_PH and not is_chrome_like(e, ir, manifest) and str(e.id) in by_id
    ]
    changed = False

    def done(kind: str, e: Any, text: str) -> None:
        out.records.append({"slide": n, "kind": kind, "element_id": str(e.id), "result": text, "role": "title" if e.ph_type in ("title", "ctrTitle") else "text"})

    # the type and the box first: a shrink, a narrower box or a larger size change where the letters stand
    geo = todo & {"word_broken", "text_cut", "overlap"}
    if geo:
        from verstka.rendering.deck import set_element_pos

        stuck = moved = False
        n0 = len(out.records) - n_spill
        for e in texts:
            if str(e.id) in spilled:
                continue
            box = free_box(e, ir.slides[n - 1], ir.slide_w, ir.slide_h) if "overlap" in geo or "word_broken" in geo or "text_cut" in geo else e.bbox
            narrowed = box != e.bbox
            e2 = e.model_copy(update={"bbox": box}) if narrowed else e
            # a narrowed box takes no more height than the text took before (it would run into what is below)
            room = max(_avail(e)[1], _need_height(e, family, 1.0, e.spc_pt)) if narrowed else None
            # a box that grows with its text or shrinks it on overflow never cuts it
            sized = e.autofit in ("norm", "shape", "sp")
            check = (lambda f, s, e2=e2, room=room, sized=sized: _words_fit(e2, family, f, s) and (sized or ("text_cut" not in geo and room is None) or _height_fits(e2, family, f, s, room)))
            if not narrowed and check(1.0, e.spc_pt):
                continue
            el = by_id[str(e.id)]
            spc = e.spc_pt
            size = e.dominant_size or 14.0
            floor = min(size, max(body, least))
            f, s = 1.0, e.spc_pt
            if not check(f, s) and spc > 0.5:
                s = 0.0
            while size * f * _SHRINK >= floor - 0.01 and not check(f, s):
                f *= _SHRINK
            snapped = on_scale(size * f, floor) if f < 1.0 else None
            if snapped and check(snapped / size, s):
                f = snapped / size
            if not check(f, s):
                stuck = True
                continue
            said = []
            if narrowed:
                set_element_pos(el, w=box.w, h=box.h if box.h != e.bbox.h else None)
                said.append("блок текста отодвинут от соседнего элемента")
                moved = True
            if s != spc:
                set_spacing_off(el)
                said.append("снята разрядка букв")
            if f < 1.0:
                set_sizes(el, f, size)
                said.append(f"шрифт уменьшен до {size * f:.0f} пт")
            done("fit_text", e, ("; ".join(said) or "текст уложен в блок").capitalize())
            changed = True
        acted = len(out.records) > n0
        if spill_left:
            stuck = True
        for c in ("word_broken", "text_cut"):
            if c in geo:
                if stuck:
                    out.left[c] = "текст не встаёт в блок даже мельче — сократите его или выберите другой вариант"
                elif acted:
                    out.cured.add(c)
                else:
                    out.untouched.add(c)
        if "overlap" in geo:
            if moved and not stuck:
                out.cured.add("overlap")
            elif not acted:
                out.untouched.add("overlap")
            else:
                out.left["overlap"] = NOT_INPLACE["overlap"]

    if "too_small" in todo:
        stuck = False
        n0 = len(out.records)
        for e in texts:
            size = e.dominant_size or 14.0
            target = max(least, body)
            if size >= target - 0.25:
                continue
            el = by_id[str(e.id)]
            f = target / size
            while f > 1.0 and not _height_fits(e, family, f, e.spc_pt):
                f = max(1.0, f * _SHRINK) if size * f * _SHRINK >= least else 1.0
            snapped = on_scale(size * f, size + 0.5) if f > 1.0 else None
            if snapped:
                f = snapped / size
            if f > 1.0 + 1e-3:
                set_sizes(el, f, size)
                done("grow_text", e, f"Шрифт увеличен до {size * f:.0f} пт")
                changed = True
                if size * f < least - 0.25:
                    stuck = True
            elif size < least - 0.25:
                stuck = True
        if stuck:
            out.left["too_small"] = "крупнее текст в блок не встанет — сократите текст или выберите другой вариант"
        elif len(out.records) > n0:
            out.cured.add("too_small")
        else:
            out.untouched.add("too_small")

    if "low_contrast" in todo:
        pics = []
        for path in (image, *(shown or ())):
            if path is not None and Path(path).exists():
                with Image.open(path) as im:
                    pics.append(im.convert("RGB"))
        if not pics:
            out.left["low_contrast"] = "не получилось снять картинку слайда, чтобы проверить фон"
        else:
            palette = manifest.tokens.palette()
            stuck = False
            n0 = len(out.records)
            for e in texts:
                el = by_id[str(e.id)]
                box = (e.bbox.x, e.bbox.y, e.bbox.w, e.bbox.h)
                # the ground on every picture: the slide as rendered now and as the person (and the model) saw it — a
                # renderer may paint a template's picture otherwise from one run to the next
                seen = [g for g in (image_ground(p, box, ir.slide_w, ir.slide_h) for p in pics) if g is not None]
                if not seen:
                    continue
                color = (e.dominant_color or manifest.tokens.color_for("text.primary") or "000000").upper()
                size = e.dominant_size or 14.0
                bold = any(r.bold for p in e.paragraphs for r in p.runs if r.text.strip())
                need = _need(size, bold)
                try:
                    probes = sorted(letter_grounds(slide, el, family), key=lambda g: _contrast(color, g))
                except Exception:  # noqa: BLE001 - the pictures alone then
                    probes = []
                # the file's own grounds (PowerPoint): the second worst probe — one probe on a speck is no line
                filed = probes[1] if len(probes) >= 3 else (probes[0] if probes else None)
                grounds = [g for g, _ in seen] + ([filed] if filed else [])
                if min(_contrast(color, g) for g in grounds) >= need:
                    continue
                cands = _candidates(manifest, None)
                best, worst = best_color(cands, grounds)
                # grounds far apart (black in one render, white in another): a colour between them is dull on both —
                # the plate makes them one ground
                apart = max(_contrast(a, b) for a in grounds for b in grounds) >= _APART
                if best and worst >= need and not apart:
                    if _recolor(el, "text", None, best, palette):
                        done("recolor", e, f"Цвет текста заменён на #{best} — читается на фоне")
                        changed = True
                    continue
                # no colour reads on every ground: a plate of the ground the person saw (the worst for the text), and
                # the colour that reads on it — the slide then looks alike in the previews, the PDF and PowerPoint
                ground, share = min(seen, key=lambda g: _contrast(color, g[0]))
                if share >= _PLATE_SHARE:
                    plate = _snap(ground, cands)  # a near-black seen through JPEG noise is the template's black
                else:
                    plate = best_color([c for c in (manifest.tokens.color_for("background.dark"), manifest.tokens.color_for("background.light"), "000000", "FFFFFF") if c], [color])[0] or "000000"
                text, cr = best_color(cands, [plate])
                if text and cr >= need and set_plate(el, plate):
                    _recolor(el, "text", None, text, palette)
                    done("plate", e, f"Под текст положена подложка #{plate}, текст #{text}")
                    changed = True
                else:
                    stuck = True
            if stuck:
                out.left["low_contrast"] = "цвет текста, который читается на этом фоне, подобрать не удалось"
            elif len(out.records) > n0:
                out.cured.add("low_contrast")
            else:
                out.untouched.add("low_contrast")

    if changed:
        prs.save(str(pptx))
    return out


def slide_picture(pptx: Path, n: int, out_dir: Path, timeout_s: float = 120.0) -> Optional[Path]:
    """Slide `n` of `pptx` as the previews render it (LibreOffice); None when it cannot be rendered."""
    from verstka.audit.eyes import slide_images

    try:
        return slide_images(Path(pptx), Path(out_dir), dpi=60, timeout_s=timeout_s).get(n)
    except Exception as e:  # noqa: BLE001 - no LibreOffice: no picture
        log.warning("slide fix: no picture of slide %d: %s", n, e)
        return None


def relook(image: Path, n: int, *, providers: Any, skills: Any, headline: str = "", form: str = "слайд") -> Optional[list[str]]:
    """The review's codes of the serious problems the model sees on the fixed slide (one per problem); None when it
    could not look."""
    from verstka.analysis.classify import image_bytes_for_vlm

    if providers is None or skills is None or not providers.has("vlm"):
        return None
    try:
        res = skills.run("slide_design_review", providers, {"slide_index": n, "deck_title": "", "form": form, "headline": headline, "data_note": ""},
                         images=[image_bytes_for_vlm(image)])
        return [p.code for p in res.parsed.major()]
    except Exception as e:  # noqa: BLE001 - not looked
        log.info("slide fix: the review of slide %d failed: %s", n, str(e)[:160])
        return None


# ---------------------------------------------------------------------------- «Ключевая цифра почти не крупнее подписи»


def fix_figure_label(pptx: Path, n: int, issue: Any, manifest: Any) -> Optional[dict]:
    """The rules' remark «цифра почти не крупнее своей подписи» fixed by its own recipe, in place: the number that
    starts the figure's paragraph («1213 боевых кораблей, 4126 десантных судов») gets a line of its own at a size of
    the template's scale at least FIG_RATIO times the label's, the words go on under it at their size. When the card
    cannot hold it, the card's other text is set at the template's body size first, then the box takes the card it
    stands on; otherwise nothing changes (None) and the slide goes to the designer. Returns the fix record."""
    import copy

    from pptx import Presentation

    from verstka.analysis.xmlns import q
    from verstka.audit.autofix import _text_floors
    from verstka.audit.checks.common import text_height_needed_pt, usable_height_pt
    from verstka.audit.ir import build_deck_ir
    from verstka.rendering.clone_check import _LEAD_FIG_RE, FIG_RATIO
    from verstka.rendering.deck import set_element_pos, slide_shape_elements

    det = getattr(issue, "details", None) or {}
    ids = list(getattr(issue, "element_ids", None) or [])
    if issue.check_id != "figure_label_ratio" or not ids or "figure_pt" not in det or "label_pt" not in det:
        return None
    label_pt = float(det["label_pt"])
    body, least = _text_floors(manifest)
    typo = manifest.tokens.typography
    scale = sorted({float(x) for x in (typo.sizes_used or [st.size_pt for st in typo.scale])})

    def big_for(lab: float) -> float:
        need = FIG_RATIO * lab
        up = [x for x in scale if x >= need - 0.01]
        return up[0] if up else float(int(need + 0.999))

    ir = build_deck_ir(pptx, with_images=False)
    sl = ir.slides[n - 1]
    e = next((x for x in sl.elements if str(x.id) == str(ids[0])), None)
    prs = Presentation(str(pptx))
    el = slide_shape_elements(prs.slides[n - 1]).get(str(ids[0]))
    if e is None or el is None:
        return None
    paras = el.findall(".//" + q("a:p"))
    k_fig, m = next(((k, _LEAD_FIG_RE.match("".join(t.text or "" for t in p.iter(q("a:t"))))) for k, p in enumerate(paras)
                     if (mm := _LEAD_FIG_RE.match("".join(t.text or "" for t in p.iter(q("a:t"))))) and any(ch.isdigit() for ch in mm.group(1))), (None, None))
    if k_fig is None or k_fig >= len(e.paragraphs):
        return None
    p = paras[k_fig]
    text = "".join(t.text or "" for t in p.iter(q("a:t")))
    num, rest = m.group(1).strip(), text[m.end():].lstrip("  ,—–-")
    runs = p.findall(q("a:r"))
    if not runs:
        return None
    rpr0 = runs[0].find(q("a:rPr"))
    fig_now = float(det.get("figure_pt") or 0) or (e.paragraphs[k_fig].runs[0].size_pt if e.paragraphs[k_fig].runs else 14.0)

    def measure(lab: float, fig: float, others: Optional[float], room_h: Optional[int] = None) -> bool:
        """Whether the element holds the number at `fig` on a line of its own, the words under it, the other
        paragraphs at `others` (None: as they are)."""
        from verstka.schemas.deck_ir import IRParagraph, IRRun

        ps = []
        for j, pp in enumerate(e.paragraphs):
            if j == k_fig:
                r0 = pp.runs[0] if pp.runs else IRRun(text="")
                ps.append(pp.model_copy(update={"text": num, "runs": [r0.model_copy(update={"text": num, "size_pt": fig, "bold": True})]}))
                if rest:
                    ps.append(pp.model_copy(update={"text": rest, "runs": [r0.model_copy(update={"text": rest, "size_pt": fig_now if others is None else min(fig_now, others)})], "space_before_pt": 0.0}))
            else:
                ps.append(pp if others is None else pp.model_copy(update={"runs": [r.model_copy(update={"size_pt": others}) for r in pp.runs]}))
        bb = e.bbox if room_h is None else e.bbox.model_copy(update={"h": room_h})
        e2 = e.model_copy(update={"paragraphs": ps, "bbox": bb})
        return text_height_needed_pt(e2)[0] <= usable_height_pt(e2) * 1.03

    fig = big_for(label_pt)
    plan = None
    if measure(label_pt, fig, None):
        plan = (fig, None, None)
    else:
        lab2 = max(body, least)
        if lab2 < label_pt:
            fig2 = big_for(lab2)
            if measure(lab2, fig2, lab2):
                plan = (fig2, lab2, None)
        if plan is None:
            card = _holder(e, sl, float(ir.slide_w) * ir.slide_h)
            if card is not None:
                room = card.bbox.y2 - max(0, e.bbox.x - card.bbox.x) - e.bbox.y
                lab2 = min(label_pt, max(body, least))
                fig2 = big_for(lab2)
                if room > e.bbox.h and measure(lab2, fig2, lab2 if lab2 < label_pt else None, room):
                    plan = (fig2, lab2 if lab2 < label_pt else None, room)
    if plan is None:
        return None
    fig, others, room = plan
    # the paragraph again: the number (bold, large), a line break, the words at their size
    for r in runs:
        p.remove(r)
    for br in p.findall(q("a:br")):
        p.remove(br)
    end = p.find(q("a:endParaRPr"))

    def run_of(txt: str, size: float, bold: Optional[bool]) -> Any:
        r = etree.Element(q("a:r"))
        rp = copy.deepcopy(rpr0) if rpr0 is not None else etree.Element(q("a:rPr"))
        rp.tag = q("a:rPr")
        rp.set("sz", str(int(round(size * 100))))
        if bold:
            rp.set("b", "1")
        r.append(rp)
        t = etree.SubElement(r, q("a:t"))
        t.text = txt
        return r

    pieces = [run_of(num, fig, True)]
    if rest:
        br = etree.Element(q("a:br"))
        br.append(copy.deepcopy(pieces[0].find(q("a:rPr"))))
        pieces += [br, run_of(rest, fig_now if others is None else min(fig_now, others), None)]
    for x in pieces:
        if end is not None:
            end.addprevious(x)
        else:
            p.append(x)
    if others is not None:
        for j, pp in enumerate(paras):
            if j == k_fig:
                continue
            for rp in pp.iter(q("a:rPr")):
                rp.set("sz", str(int(round(others * 100))))
    if room is not None:
        set_element_pos(el, h=int(room))
    prs.save(str(pptx))
    said = f"Цифра «{num}» вынесена отдельной строкой кеглем {fig:g} пт — крупнее подписи"
    if others is not None:
        said += f"; остальной текст карточки — {others:g} пт"
    if room is not None:
        said += "; блок текста растянут по карточке"
    return {"slide": n, "kind": "figure_size", "element_id": str(ids[0]), "result": said, "role": "text"}
