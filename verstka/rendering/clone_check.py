"""The gate of a content slide set on a template sample: a clone that loses content, sets type below a readable size
or leaves the sample's own words on the slide is not shown — the renderer tries the next sample, then composes.

A template slide filled with new content is the most faithful way to show the template, and the worst when it
reads badly: a card that lost its text, a figure without its ring, «Безопасность» left in a card. The checks here are
measured on the slide as rendered, so they hold for any template."""

from __future__ import annotations

import re
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import q
from verstka.schemas.common import EMU_PER_PT
from verstka.schemas.outline import OutlineSlide
from verstka.schemas.common import PatternKind, SlotRole
from verstka.schemas.template import Pattern, TemplateManifest

# warnings of the clone renderer that mean the slide lost a part of its content
LOSS_MARKERS = (
    "items dropped",
    "had no slot",
    "text may overflow",
    "no slot for",
    "pattern has no title slot",
    "native object failed",
    "removed: it cannot show this figure",
    "items merged",
)


# the largest empty rectangle a slide may have gained over its sample (shares of the slide)
HOLE_MIN = 0.15
HOLE_GROWTH = 0.08


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ").replace("⁠", "")).strip().lower()


def _content_strings(oslide: OutlineSlide) -> set[str]:
    c = oslide.content
    out = [oslide.headline, oslide.subtitle or "", oslide.section or "", oslide.takeaway or "", oslide.footnote or ""]
    out += list(c.bullets) + list(c.paragraphs) + [c.quote or "", c.quote_author or ""]
    for it in list(c.items) + list(c.columns):
        out += [it.title, it.text or "", it.number or ""] + list(it.bullets)
    for n in c.numbers:
        out += [n.value, n.label]
    return {_norm(s) for s in out if s}


def _shape_text(el) -> str:
    paras = []
    for p in el.iter(q("a:p")):
        paras.append("".join(t.text or "" for t in p.iter(q("a:t"))))
    return "\n".join(paras)


def _is_code_para(p) -> bool:
    """A paragraph of the user's code: its runs set in a monospace face."""
    from verstka.rendering.compose import MONO_RE

    faces = [lat.get("typeface") or "" for lat in p.iter(q("a:latin"))]
    return bool(faces) and all(MONO_RE.search(f) for f in faces)


# ---- the typographic floor of every slide (qa4 L3 / NEW-L2): one rule for the composer, the clone gate and the audit

FIG_RATIO = 1.6  # a key figure stands at least this much larger than its label
SMALL_SHARE = 0.017  # small print (a source line, a caption) never under this share of the slide's height (the composer's dense floor)


def body_floor(manifest: TemplateManifest) -> float:
    """The template's body size: running text (a card's text, a step, a bullet, a figure's label) is never set
    smaller. A template whose scale names no body size takes 14 pt, at most 3.1 % of the slide's height (the
    composer's body there).

    The declared size is capped where it is a placeholder's size rather than the size of the template's running text
    (final review C1): a LibreOffice template declares 24–32 pt on a 6.2″ slide, synth_huge 64 pt — as a floor they
    lifted every sample's text into overflow and broken words and flagged 20 pt bullets. The cap is the composer's own
    reading of the template's body (`Kit`): 3.1 % of the slide's height on a template whose scale is a derived ladder
    (a sparse one), 3.7 % otherwise, never under 14 pt; VK Tech's 9, ЛЦТ's 14, Классика's 18 pt stay as declared."""
    typo = manifest.tokens.typography
    hpt = manifest.slide_size.h / EMU_PER_PT
    got = typo.size_for("body", 0.0)
    if got > 0:
        share = 0.031 if getattr(typo, "derived_sizes", None) else 0.037
        return float(min(got, max(14.0, round(share * hpt * 2) / 2)))
    return min(14.0, round(0.031 * hpt * 2) / 2)


def small_floor(manifest: TemplateManifest) -> float:
    """The least size of any text of a content slide — small print included: 1.7 % of the slide's height (9.2 pt on a
    7.5″ slide, 7 pt on VK Tech's 5.6″), the composer's own dense floor: text under it reads as specks (qa4: 6–8 pt)."""
    return SMALL_SHARE * manifest.slide_size.h / EMU_PER_PT


def _sq(text: str) -> str:
    """A text for comparing: no spaces of any kind, no word joiners, lower case."""
    return re.sub(r"[\s   ⁠​]+", "", text or "").lower()


_LEAD_FIG_RE = re.compile(r"^\s*([+\-−–~≈]?\d[\d\s  ]*(?:[.,]\d+)?\s?(?:%|‰|×|₽|\$|€|раз[а]?\b|тыс\.?|млн|млрд)?)")
_YEAR_RE = re.compile(r"^(?:19|20)\d\d$")


def is_index_number(num: str, i: int) -> bool:
    """An item's number that only counts the items (its place «1», «02», a step's «III») or names a year: never a key
    figure set larger than its words."""
    t = _sq(num).strip(".)")
    return t in (str(i + 1), f"{i + 1:02d}") or bool(re.fullmatch(r"[ivxlc]+", t)) or bool(_YEAR_RE.match(t)) or (t.isdigit() and len(t) <= 2 and int(t) <= 12)


def figure_pairs(oslide: OutlineSlide, headline: Optional[str] = None) -> list[tuple[str, list[str], bool]]:
    """The slide's key figures with their labels: (figure, the label's possible texts, lead) — `lead`: the figure starts
    its own sentence under a short label («Было» over «31% срывов дедлайнов»), where the figure must lead, not the label.
    The labels a composer may show for a figure (`distinct_label`) are among the texts."""
    from verstka.rendering.compose import distinct_label

    c = oslide.content
    head = headline if headline is not None else (oslide.headline or "")
    out: list[tuple[str, list[str], bool]] = []
    for n in c.numbers:
        if (n.value or "").strip() and (n.label or "").strip():
            out.append((n.value, list(dict.fromkeys([n.label, distinct_label(n.value, n.label, head)])), False))
    for i, it in enumerate(list(c.items) + list(c.columns)):
        num = (it.number or "").strip()
        title = (it.title or "").strip()
        if num and any(ch.isdigit() for ch in num) and not is_index_number(num, i):
            lab = title if title and _sq(title) != _sq(num) else (it.text or "").strip()
            if lab:
                out.append((num, [lab], False))
        elif not num and title and (it.text or "").strip() and len(title.split()) <= 3 and not any(ch.isdigit() for ch in title):
            m = _LEAD_FIG_RE.match(it.text or "")
            if m and any(ch.isdigit() for ch in m.group(1)):
                out.append((m.group(1).strip(), [title], True))
    return out


def match_figures(pairs: list[tuple[str, list[str], bool]], records: list[tuple]) -> list[tuple]:
    """(figure, label, figure size, label size, figure record, label record) of the pairs found on a slide. `records`:
    one per paragraph — (text, size of its runs that hold digits, its largest size, x, y, …); a figure and its label
    are the nearest matching paragraphs of two different texts or of one text's two paragraphs."""
    out = []
    for fig, labels, lead in pairs:
        f = _sq(fig)
        if not f:
            continue
        figs = [r for r in records if r[1] and ((not lead and _sq(r[0]) == f) or (lead and _sq(r[0]).startswith(f) and len(_sq(r[0])) > len(f)))]
        if not figs:
            continue
        labs_sq = [_sq(x) for x in labels if _sq(x)]
        labs = [r for r in records if r[2] and any(_sq(r[0]) == x or (len(x) >= 12 and _sq(r[0])[:12] == x[:12]) for x in labs_sq)]
        best = None
        for fr in figs:
            for lr in labs:
                if lr is fr:
                    continue
                d = abs(fr[3] - lr[3]) + abs(fr[4] - lr[4])
                if best is None or d < best[0]:
                    best = (d, fr, lr)
        if best is not None:
            _, fr, lr = best
            out.append((fr[0], lr[0], fr[1], lr[2], fr, lr))
    return out


def slide_records(slide, skip: Optional[set] = None) -> list[tuple]:
    """The paragraphs of a slide's text boxes as `match_figures` records (the slide's own shapes, groups included)."""
    from verstka.rendering.deck import abs_bbox

    out = []
    tree = slide._element.cSld.find(q("p:spTree"))
    for sp in tree.iter(q("p:sp")):
        nv = sp.find(".//" + q("p:cNvPr"))
        if skip and nv is not None and nv.get("id") in skip:
            continue
        b = abs_bbox(sp)
        if not b:
            continue
        paras = list(sp.iter(q("a:p")))
        for j, p in enumerate(paras):
            runs = [(("".join(t.text or "" for t in r.iter(q("a:t")))), r.find(q("a:rPr"))) for r in p.iter(q("a:r"))]
            text = "".join(t for t, _ in runs)
            if not text.strip():
                continue
            sizes = [(t, int(rp.get("sz")) / 100) for t, rp in runs if rp is not None and (rp.get("sz") or "").isdigit() and t.strip()]
            if not sizes:
                continue
            dig = [s for t, s in sizes if any(ch.isdigit() for ch in t)]
            out.append((text, max(dig) if dig else 0.0, max(s for _, s in sizes), b[0] + b[2] / 2, b[1] + (j + 0.5) * b[3] / max(len(paras), 1), sp, p, b))
    return out


def box_gap(a: tuple, b: tuple) -> tuple[float, float]:
    """(horizontal, vertical) gap between two (x, y, w, h) boxes, 0 where they overlap along that axis."""
    gx = max(0.0, max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2]))
    gy = max(0.0, max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3]))
    return gx, gy


def figure_trouble(slide, oslide: OutlineSlide, skip: Optional[set] = None) -> Optional[str]:
    """A key figure of the slide set hardly larger than its label (qa4 L3 / NEW-L2: Marketing 43 over 30.5 pt,
    Forestbird 16 over 14 pt; «Было» large over a small «31%»), or apart from it (qa4 NEW-L3: «до 5 часов» alone at the
    slide's top-right edge, its words in a list at the left; a ring's «18%» with its words elsewhere): why, or None."""
    W = slide.part.package.presentation_part.presentation.slide_width
    H = slide.part.package.presentation_part.presentation.slide_height
    pairs = figure_pairs(oslide)
    recs = slide_records(slide, skip)
    found = match_figures(pairs, recs)
    for fig, lab, fs, ls, fr, lr in found:
        if fs < FIG_RATIO * ls - 0.3:
            return f"цифра «{fig.strip()[:14]}» в {fs:g} pt почти не крупнее подписи «{lab.strip()[:18]}» в {ls:g} pt"
        gx, gy = box_gap(fr[7], lr[7])
        if gx > 0.1 * W or gy > 0.12 * H:
            return f"цифра «{fig.strip()[:14]}» стоит отдельно от своей подписи «{lab.strip()[:18]}»"
    if oslide.kind in (PatternKind.stat_row, PatternKind.big_number):
        shown = {_sq(f[0]) for f in found}
        for fig, labels, lead in pairs:
            if lead or _sq(fig) in shown:
                continue
            if any(r[1] and _sq(r[0]) == _sq(fig) for r in recs):
                return f"у цифры «{fig.strip()[:14]}» нет подписи рядом"
    return None


def _panel_left_empty(slide, oslide: OutlineSlide, chrome: set, manifest: TemplateManifest) -> Optional[str]:
    """A sample's big panel (a plate of a fifth of the slide and more) that the slide's text leaves nearly empty — one
    paragraph at the top of ЛЦТ's white half-slide panel, the rest a white field (qa4 NEW-L5: slides 6–8 % filled):
    the composer sets the same words at the size the area gives them. Why, or None."""
    from verstka.rendering.clone_notes import _paints
    from verstka.rendering.deck import element_bbox
    from verstka.schemas.common import Bbox

    if oslide.kind in (PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.quote, PatternKind.big_number):
        return None
    c = oslide.content
    if c.chart is not None or c.table is not None or c.chart2 is not None or (c.code is not None) or (c.formula or "").strip():
        return None
    W, H = manifest.slide_size.w, manifest.slide_size.h
    fam = manifest.tokens.typography.primary_family
    tree = slide._element.cSld.find(q("p:spTree"))
    panels, inks = [], []
    for sp in tree.iter(q("p:sp")):
        nv = sp.find(".//" + q("p:cNvPr"))
        if nv is not None and nv.get("id") in chrome:
            continue
        b = element_bbox(sp)
        if b and _paints(sp) and b[2] * b[3] >= 0.2 * W * H and b[2] * b[3] < 0.9 * W * H:
            panels.append(Bbox(x=b[0], y=b[1], w=b[2], h=b[3]))
        if _shape_text(sp).strip():
            ib = ink_box(sp, fam)
            if ib is not None and ib.area > 0:
                inks.append(ib)
    for pnl in panels:
        inside = [ib for ib in inks if pnl.contains_point(ib.x + ib.w / 2, ib.y + ib.h / 2)]
        if not inside:
            continue
        top, bottom = min(ib.y for ib in inside), max(ib.y2 for ib in inside)
        area = sum(ib.area for ib in inside)
        if bottom - top < 0.3 * pnl.h and area < 0.2 * pnl.area:
            return f"панель образца осталась бы почти пустой: текст занимает {(bottom - top) / pnl.h:.0%} её высоты"
    return None


def _marks_trouble(slide, oslide: OutlineSlide, marks: list, chrome: set, manifest: TemplateManifest) -> Optional[str]:
    """The marks the ground picture draws in the sample's cells (`clone._render_clone`: (cell, mark) boxes) — VK Tech's
    «01»…«04» watermarks, its numerals over the cards (qa4 NEW-L3): no text of the slide over a mark, no cell with a
    mark left empty (the picture would show a numbered card with nothing in it), and no numbers of the slide's own
    beside the picture's (the numbering doubled: «1» over «01»). Why, or None."""
    fam = manifest.tokens.typography.primary_family
    tree = slide._element.cSld.find(q("p:spTree"))
    texts = []
    for sp in tree.iter(q("p:sp")):
        nv = sp.find(".//" + q("p:cNvPr"))
        if nv is not None and nv.get("id") in chrome:
            continue
        t = _shape_text(sp).strip()
        if not t:
            continue
        lines = ink_lines(sp, fam)
        if lines:
            texts.append((t, lines, sp))
    for t, lines, _ in texts:
        for _, m in marks:
            for ln in lines:
                if ln.area > 0 and ln.intersection(m) > 0.12 * min(ln.area, m.area):
                    return f"текст «{t[:24]}» лёг на рисунок в карточке шаблона"
    for cell, _ in marks:
        if not any(any(cell.intersection(ln) > 0.5 * ln.area for ln in lines) for _, lines, _ in texts):
            return "карточка рисунка шаблона осталась пустой"
    items = list(oslide.content.items) + list(oslide.content.columns)
    if any(is_index_number(it.number or "", i) and not _YEAR_RE.match(_sq(it.number or "")) for i, it in enumerate(items) if it.number):
        idx = {_sq(it.number) for it in items if it.number} | {str(i + 1) for i in range(len(items))} | {f"{i + 1:02d}" for i in range(len(items))}
        for t, _, sp in texts:
            for p in sp.iter(q("a:p")):
                if _sq("".join(x.text or "" for x in p.iter(q("a:t")))).strip(".)") in idx:
                    return "образец сам нумерует карточки рисунком: номера удвоились бы"
    return None


def readable_floor(manifest: TemplateManifest) -> float:
    """The least size of running text on a slide set on a template sample: the template's body size (`body_floor`).
    VK Tech's 9 pt is its own body — the size of the running text on 7 of its 12 slides with running text (its card
    samples), the most frequent size of its scale — so its 9 pt cards stay, though the composer sets 11 pt there (its
    body is never under 2.7 % of the slide height); a floor of 2.7 % for every template would turn down ЛЦТ's own
    14 pt cards as well."""
    # (qa4 L3: the template's body size itself — a step under it set the cards of VK Tech at 7 pt and ЛЦТ's at 12 pt
    # beside 14 pt composed slides; the floor is the same for the composer and the audit, `body_floor`)
    return body_floor(manifest)


def para_indent(p, body=None) -> int:
    """Where a paragraph's lines start inside its box, in EMU: its left margin (and a first line indented further),
    read from the paragraph or the box's list style for its level. The lines wrap that much narrower than the box
    (VK Education's cards indent their text 14 pt: measured at the full width, 6 lines read as 5)."""
    ppr = p.find(q("a:pPr"))
    marl = indent = None
    if ppr is not None:
        marl, indent = ppr.get("marL"), ppr.get("indent")
    lst = body.find(q("a:lstStyle")) if body is not None else None
    if lst is not None and (marl is None or indent is None):
        try:
            lvl = int(ppr.get("lvl") or 0) if ppr is not None else 0
        except ValueError:
            lvl = 0
        node = lst.find(q(f"a:lvl{lvl + 1}pPr"))
        if node is not None:
            marl = marl if marl is not None else node.get("marL")
            indent = indent if indent is not None else node.get("indent")
    try:
        m, i = int(marl or 0), int(indent or 0)
    except ValueError:
        return 0
    return max(0, m + max(i, 0))


def ink_lines(sp, default_family: Optional[str]) -> list:
    """Where each line of a box's text stands (Bboxes in EMU, by its anchor and its paragraph's alignment): a short
    second line under a long first one covers only its own width."""
    from verstka.rendering.deck import element_bbox
    from verstka.rendering.fonts import text_width_pt, wrap_lines
    from verstka.schemas.common import Bbox

    b = element_bbox(sp)
    body = sp.find(q("p:txBody"))
    if not b or b[2] <= 0 or b[3] <= 0 or body is None:
        return []
    bp = body.find(q("a:bodyPr"))

    def ins(name: str, default: int) -> int:
        try:
            return int(bp.get(name)) if bp is not None and bp.get(name) is not None else default
        except ValueError:
            return default

    l, tp, r, bt = ins("lIns", 91440), ins("tIns", 45720), ins("rIns", 91440), ins("bIns", 45720)
    width = max((b[2] - l - r) / EMU_PER_PT, 1.0)
    rows = []  # (width pt, height pt, align)
    for p in body.findall(q("a:p")):
        text = "".join(x.text or "" for x in p.iter(q("a:t")))
        rpr = next((x for x in p.iter(q("a:rPr")) if x.get("sz")), None)
        size = int(rpr.get("sz")) / 100 if rpr is not None else 12.0
        lat = rpr.find(q("a:latin")) if rpr is not None else None
        fam = lat.get("typeface") if lat is not None and lat.get("typeface") else default_family
        bold = bool(rpr is not None and rpr.get("b") == "1")
        pct = p.find(q("a:pPr") + "/" + q("a:lnSpc") + "/" + q("a:spcPct"))
        ls = 1.2 * (int(pct.get("val")) / 100000 if pct is not None and pct.get("val") else 1.0)
        ppr = p.find(q("a:pPr"))
        algn = ppr.get("algn") if ppr is not None and ppr.get("algn") else "l"
        ind = para_indent(p, body)
        w_para = max(width - ind / EMU_PER_PT, 1.0)
        for line in (wrap_lines(text, fam, size, bold, w_para) if text.strip() else [""]):
            rows.append((text_width_pt(line, fam, size, bold) if line.strip() else 0.0, size * ls, algn, ind))
    total = sum(r[1] for r in rows) * EMU_PER_PT
    anchor = (bp.get("anchor") if bp is not None else None) or "t"
    inner_h = b[3] - tp - bt
    y = b[1] + tp + (max(inner_h - total, 0) // 2 if anchor == "ctr" else (max(inner_h - total, 0) if anchor == "b" else 0))
    out = []
    for w_pt, h_pt, algn, ind in rows:
        w = min(int(w_pt * EMU_PER_PT), max(b[2] - l - r - ind, 1))
        h = int(h_pt * EMU_PER_PT)
        if w > 0:
            x = b[0] + l + ind + ((b[2] - l - r - ind - w) // 2 if algn == "ctr" else (b[2] - l - r - ind - w if algn == "r" else 0))
            out.append(Bbox(x=int(x), y=int(y), w=w, h=h))
        y += h
    return out


def ink_box(sp, default_family: Optional[str]):
    """Where the text of a box really stands (its lines wrapped at its own size, by its anchor), in EMU; None when it
    has no text or no geometry."""
    from verstka.rendering.deck import element_bbox
    from verstka.rendering.fonts import wrap_lines
    from verstka.schemas.common import Bbox

    b = element_bbox(sp)
    if not b or b[2] <= 0 or b[3] <= 0:
        return None
    body = sp.find(q("p:txBody"))
    if body is None:
        return None
    bp = body.find(q("a:bodyPr"))

    def ins(name: str, default: int) -> int:
        try:
            return int(bp.get(name)) if bp is not None and bp.get(name) is not None else default
        except ValueError:
            return default

    l, tp, r, bt = ins("lIns", 91440), ins("tIns", 45720), ins("rIns", 91440), ins("bIns", 45720)
    width = max((b[2] - l - r) / EMU_PER_PT, 1.0)
    height = 0.0
    widest = 0.0
    lst = body.find(q("a:lstStyle") + "/" + q("a:lvl1pPr"))

    def space(ppr, tag: str, size: float) -> float:
        # the space a paragraph sets before or after itself (or its box's list style sets): it pushes the lines under
        # it down (a WorkSpace card's text 6 pt under its heading)
        for src in (ppr, lst):
            node = src.find(q(tag)) if src is not None else None
            if node is None:
                continue
            pts, pct = node.find(q("a:spcPts")), node.find(q("a:spcPct"))
            try:
                if pts is not None and pts.get("val"):
                    return max(int(pts.get("val")) / 100.0, 0.0)
                if pct is not None and pct.get("val"):
                    return max(int(pct.get("val")) / 100000.0 * size * 1.2, 0.0)
            except ValueError:
                pass
            return 0.0
        return 0.0

    paras = body.findall(q("a:p"))
    for k, p in enumerate(paras):
        text = "".join(x.text or "" for x in p.iter(q("a:t")))
        rpr = next((x for x in p.iter(q("a:rPr")) if x.get("sz")), None)
        size = int(rpr.get("sz")) / 100 if rpr is not None else 12.0
        lat = rpr.find(q("a:latin")) if rpr is not None else None
        fam = lat.get("typeface") if lat is not None and lat.get("typeface") else default_family
        ppr = p.find(q("a:pPr"))
        pct = p.find(q("a:pPr") + "/" + q("a:lnSpc") + "/" + q("a:spcPct"))
        ls = 1.2 * (int(pct.get("val")) / 100000 if pct is not None and pct.get("val") else 1.0)
        if rpr is not None and rpr.get("cap") == "all":
            text = text.upper()  # shown in capitals: measured so
        lines = wrap_lines(text, fam, size, bool(rpr is not None and rpr.get("b") == "1"), max(width - para_indent(p, body) / EMU_PER_PT, 1.0)) if text.strip() else [""]
        height += max(len(lines), 1) * size * ls
        if k:
            height += space(ppr, "a:spcBef", size)
        if k < len(paras) - 1:
            height += space(ppr, "a:spcAft", size)
        if text.strip():
            from verstka.rendering.fonts import text_width_pt

            widest = max(widest, max(text_width_pt(x, fam, size) for x in lines))
    if widest <= 0:
        return None
    h = int(height * EMU_PER_PT)
    anchor = (bp.get("anchor") if bp is not None else None) or "t"
    inner_h = b[3] - tp - bt
    y = b[1] + tp + (max(inner_h - h, 0) // 2 if anchor == "ctr" else (max(inner_h - h, 0) if anchor == "b" else 0))
    return Bbox(x=b[0] + l, y=y, w=min(int(widest * EMU_PER_PT), b[2] - l - r), h=min(h, max(b[3], h)))


def _aligned_ink(sp, family: Optional[str]):
    """`ink_box` set where its alignment puts it: a centred or right-aligned line stands in the middle or at the
    right of its frame, not at its left edge."""
    from verstka.rendering.deck import element_bbox
    from verstka.schemas.common import Bbox

    ib = ink_box(sp, family)
    if ib is None:
        return None
    b = element_bbox(sp)
    ppr = sp.find(".//" + q("a:pPr"))
    algn = ppr.get("algn") if ppr is not None else None
    if b and algn in ("ctr", "r"):
        bp = sp.find(q("p:txBody") + "/" + q("a:bodyPr"))
        l = int(bp.get("lIns")) if bp is not None and (bp.get("lIns") or "").isdigit() else 91440
        r = int(bp.get("rIns")) if bp is not None and (bp.get("rIns") or "").isdigit() else 91440
        inner = b[2] - l - r
        x = b[0] + l + ((inner - ib.w) // 2 if algn == "ctr" else inner - ib.w)
        return Bbox(x=x, y=ib.y, w=ib.w, h=ib.h)
    return ib


def _texts_over_each_other(slide, tree, skip_ids: set, family: Optional[str], native: Optional[set] = None) -> Optional[str]:
    """Two texts of the slide whose lines lie over each other (more than 30 % of the smaller), or None. Texts the
    sample itself laid over each other as much (a figure on its label) are its design; a text inside a filled or
    outlined box that carries text of its own (a pill and its caption) is that box's. `native`: the texts the design
    system set with a chart or a table (its caption, its legend) — checked against the sample's texts, not against
    each other."""
    native = native or set()
    from verstka.rendering.deck import element_bbox, is_nested
    from verstka.rendering.textfill import has_visible_style

    designed = slide.__dict__.get("_verstka_designed_ink") or {}
    origin = slide.__dict__.get("_verstka_origin") or {}
    inks = []
    for sp in tree.iter(q("p:sp")):
        nv = sp.find(".//" + q("p:cNvPr"))
        sid = nv.get("id") if nv is not None else None
        if sid is None or sid in skip_ids or is_nested(sp) or not _shape_text(sp).strip():
            continue
        ib = _aligned_ink(sp, family)
        if ib is not None and ib.w > 0 and ib.h > 0:
            inks.append((sid, sp, ib))
    for i, (ida, a, ia) in enumerate(inks):
        for idb, b, ib in inks[i + 1:]:
            if ida in native and idb in native:
                continue
            inter = ia.intersection(ib)
            small = min(ia.area, ib.area)
            if small <= 0 or inter <= 0.3 * small:
                continue
            da, db = designed.get(origin.get(ida, ida)), designed.get(origin.get(idb, idb))
            if da is not None and db is not None and da.intersection(db) >= 0.3 * min(da.area, db.area):
                continue
            ba, bb = element_bbox(a), element_bbox(b)
            if ba and bb:
                a_holds = has_visible_style(a) and ba[0] <= bb[0] and ba[1] <= bb[1] and ba[0] + ba[2] >= bb[0] + bb[2] and ba[1] + ba[3] >= bb[1] + bb[3]
                b_holds = has_visible_style(b) and bb[0] <= ba[0] and bb[1] <= ba[1] and bb[0] + bb[2] >= ba[0] + ba[2] and bb[1] + bb[3] >= ba[1] + ba[3]
                if a_holds or b_holds:
                    continue
            return f"texts «{_shape_text(a).strip()[:20]}» and «{_shape_text(b).strip()[:20]}» lie over each other"
    return None


_GRID_C, _GRID_R = 48, 27


def _covered(slide, pattern: Pattern, manifest: TemplateManifest):
    """The cells of a 48 × 27 grid over the slide that its content covers: painted shapes, pictures, charts and
    tables by their boxes, text by the lines it really takes (the box's width, the height its lines fill). Hairlines
    and full-slide grounds cover nothing. Returns (grid, the content area as cell bounds)."""
    import numpy as np

    from verstka.rendering.clone_notes import _paints
    from verstka.rendering.deck import element_bbox

    W, H = manifest.slide_size.w, manifest.slide_size.h
    grid = np.zeros((_GRID_R, _GRID_C), dtype=bool)
    fam = manifest.tokens.typography.primary_family
    tree = slide._element.cSld.find(q("p:spTree"))

    def mark(x: float, y: float, w: float, h: float) -> None:
        if w <= 0 or h <= 0:
            return
        c0, c1 = int(max(x, 0) / W * _GRID_C), int(min(x + w, W) / W * _GRID_C - 1e-9)
        r0, r1 = int(max(y, 0) / H * _GRID_R), int(min(y + h, H) / H * _GRID_R - 1e-9)
        if c1 >= c0 and r1 >= r0:
            grid[max(r0, 0) : min(r1, _GRID_R - 1) + 1, max(c0, 0) : min(c1, _GRID_C - 1) + 1] = True

    for el in tree:
        tag = etree.QName(el).localname
        if tag not in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp"):
            continue
        b = element_bbox(el)
        if not b or b[2] <= 0 or b[3] <= 0 or b[2] * b[3] >= 0.9 * W * H:
            continue
        if tag == "cxnSp" or min(b[2] / W, b[3] / H) < 0.01:
            continue  # a rule or a connector divides the room, it does not fill it
        if tag == "sp" and not _paints(el):
            continue
        if tag == "sp" and _shape_text(el).strip() and not _fills_box(el):
            ib = ink_box(el, fam)
            if ib is not None:
                mark(b[0], ib.y, b[2], ib.h)
            continue
        mark(*b)
    safe = manifest.tokens.spacing.safe_area
    top = max((s.bbox.y2 for s in pattern.slots if s.role == SlotRole.title), default=safe.y)
    area = (int(safe.x * _GRID_C), int(min(top + 0.02, 0.5) * _GRID_R), int(safe.x2 * _GRID_C), int(safe.y2 * _GRID_R))
    return grid, area


def _fills_box(el) -> bool:
    """A text shape whose own fill or outline draws its box (a card, a pill): it covers the box, not only its lines."""
    spPr = el.find(q("p:spPr"))
    if spPr is None:
        return False
    if spPr.find(q("a:noFill")) is None and any(spPr.find(q(x)) is not None for x in ("a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill")):
        return True
    ln = spPr.find(q("a:ln"))
    return ln is not None and ln.find(q("a:noFill")) is None and any(ln.find(q(x)) is not None for x in ("a:solidFill", "a:gradFill"))


def largest_hole(grid, area) -> float:
    """The largest empty rectangle of the content area, as a share of the slide."""
    c0, r0, c1, r1 = area
    heights = [0] * _GRID_C
    best = 0
    for r in range(max(r0, 0), min(r1, _GRID_R)):
        for c in range(_GRID_C):
            heights[c] = heights[c] + 1 if (c0 <= c < c1 and not grid[r, c]) else 0
        stack: list[int] = []
        for c in range(_GRID_C + 1):
            h = heights[c] if c < _GRID_C else 0
            while stack and heights[stack[-1]] >= h:
                top = stack.pop()
                width = c if not stack else c - stack[-1] - 1
                best = max(best, heights[top] * width)
            stack.append(c)
    return best / float(_GRID_C * _GRID_R)


def free_rect(slide, pattern: Pattern, manifest: TemplateManifest, min_w: float, min_h: float, y_from: float, floor_emu: int):
    """The largest empty rectangle of the slide below `y_from` (a share of the height) and above `floor_emu`, at
    least `min_w` × `min_h` (shares of the slide): (x, y, w, h) in EMU, or None. Where a conclusion can stand when
    the sample's content runs down to the foot on one side (a chart and its legend beside a short text column)."""
    import numpy as np  # noqa: F401

    W, H = manifest.slide_size.w, manifest.slide_size.h
    grid, area = _covered(slide, pattern, manifest)
    c0, _, c1, _ = area
    r0 = int(y_from * _GRID_R + 0.999)
    r1 = min(int(floor_emu / H * _GRID_R), _GRID_R)
    best = None
    heights = [0] * _GRID_C
    for r in range(max(r0, 0), r1):
        for c in range(_GRID_C):
            heights[c] = heights[c] + 1 if (c0 <= c < c1 and not grid[r, c]) else 0
        stack: list[int] = []
        for c in range(_GRID_C + 1):
            h = heights[c] if c < _GRID_C else 0
            while stack and heights[stack[-1]] >= h:
                top = stack.pop()
                left = stack[-1] + 1 if stack else 0
                width = c - left
                hh = heights[top]
                if width / _GRID_C >= min_w and hh / _GRID_R >= min_h and (best is None or width * hh > best[2] * best[3]):
                    best = (left, r - hh + 1, width, hh)
            stack.append(c)
    if best is None:
        return None
    cx, ry, cw, rh = best
    return (int(cx / _GRID_C * W), int(ry / _GRID_R * H), int(cw / _GRID_C * W), int(rh / _GRID_R * H))


def sample_hole(slide, pattern: Pattern, manifest: TemplateManifest) -> Optional[float]:
    """The largest empty rectangle of the sample as the template draws it (measured on the fresh copy)."""
    try:
        grid, area = _covered(slide, pattern, manifest)
        return largest_hole(grid, area)
    except Exception:  # noqa: BLE001
        return None


def _layout_plates_left_empty(slide, manifest: TemplateManifest) -> int:
    """How many plates the slide's layout draws as filled placeholders (LCT p23's layout: four faint cards that are
    body placeholders of the layout with a fill of their own) in the content area while the slide writes nothing in
    them — a viewer that draws a layout's placeholders (LibreOffice, the previews and the PDF) shows them as empty
    cards beside the slide's text. 0 when the layout has fewer than two such plates or the slide writes in them."""
    try:
        layout = slide.slide_layout
    except Exception:  # noqa: BLE001
        return 0
    W, H = manifest.slide_size.w, manifest.slide_size.h
    texts = {}
    for sp in slide._element.cSld.find(q("p:spTree")).iter(q("p:sp")):
        ph = sp.find(".//" + q("p:ph"))
        if ph is not None and ph.get("idx"):
            texts[ph.get("idx")] = bool(_shape_text(sp).strip())
    plates = []
    for sp in layout._element.cSld.find(q("p:spTree")).iter(q("p:sp")):
        ph = sp.find(".//" + q("p:ph"))
        if ph is None or (ph.get("type") or "body") in ("title", "ctrTitle", "dt", "ftr", "sldNum", "pic"):
            continue
        sppr = sp.find(q("p:spPr"))
        if sppr is None or not any(sppr.find(q(t)) is not None for t in ("a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill")):
            continue
        xf = sppr.find(q("a:xfrm"))
        off = xf.find(q("a:off")) if xf is not None else None
        ext = xf.find(q("a:ext")) if xf is not None else None
        if off is None or ext is None:
            continue
        y = int(off.get("y") or 0) / H
        area = int(ext.get("cx") or 0) * int(ext.get("cy") or 0) / float(W * H)
        if y < 0.12 or area < 0.02:
            continue
        plates.append(ph.get("idx"))
    if len(plates) < 2:
        return 0
    empty = [i for i in plates if not texts.get(i)]
    return len(empty) if len(empty) >= 2 else 0


def closing_trouble(slide, body: float, headline: Optional[str] = None) -> Optional[str]:
    """A data deck's closing slides (the clone marks their items, `_verstka_closing`) are the slide's whole content and
    read as a deliberate end, not as a footnote: their text at the template's body size or larger (ЛЦТ p4: the summary
    at 13 pt under its 14 pt body, squeezed further by its box), and the summary's cards led by their figures — a
    figure set little above its card's text (ЛЦТ p17: 24 pt over the cards' 18 pt bold) leads nothing; under 1.5× the
    text (the composer's rule for a figure over its label) the sample is no place for them. Why, or None (qa3
    leftovers)."""
    marks = slide.__dict__.get("_verstka_closing")
    if not marks:
        return None

    def norm(t: str) -> str:
        return re.sub(r"\s+", "", t or "")

    nums = {norm(n) for n, _, _ in marks if norm(n)}
    words = [norm(x) for _, a, b in marks for x in (a, b) if len(norm(x)) >= 4]
    figs: list[float] = []
    texts: list[float] = []
    # the cards are compared with the cards only: the slide's heading — an answer-first summary's headline made of its
    # two strongest conclusions starts with a card's words (story 9057be0) — is no card text
    head = norm(headline or "")
    titles = set()
    for sp in slide._element.iter(q("p:sp")):
        ph = sp.find(".//" + q("p:ph"))
        if ph is not None and (ph.get("type") or "") in ("title", "ctrTitle"):
            titles.add(sp)
    for para in slide._element.iter(q("a:p")):
        t = norm("".join(x.text or "" for x in para.iter(q("a:t"))))
        if not t:
            continue
        owner = para.getparent()
        while owner is not None and etree.QName(owner).localname != "sp":
            owner = owner.getparent()
        if owner in titles or (head and (t == head or (len(t) >= 16 and head.startswith(t)) or (len(head) >= 16 and t.startswith(head)))):
            continue
        sizes = [int(rp.get("sz")) / 100 for rp in (r.find(q("a:rPr")) for r in para.iter(q("a:r"))) if rp is not None and (rp.get("sz") or "").isdigit()]
        if not sizes:
            continue
        if t in nums:
            figs.append(max(sizes))
        elif any(t[:16] == w[:16] for w in words):
            texts.append(min(sizes))
    if texts and body and min(texts) < body - 0.5:
        return f"текст итоговых карточек мельче основного текста шаблона: {min(texts):g} pt при {body:g} pt"
    if figs and texts and min(figs) < FIG_RATIO * max(texts) - 0.5:
        return f"цифры карточек не ведут их: {min(figs):g} pt над текстом в {max(texts):g} pt"
    return None


def heading_off_its_ground(slide, pattern: Pattern, manifest: TemplateManifest) -> Optional[str]:
    """The sample's heading, filled with the slide's headline, runs off the ground it is coloured for: a part of its
    letters reads (3:1) and a part does not (under 2:1) — a white headline longer than the sample's on a teal band cut
    on the diagonal ran onto the white page, «38% выручки» white on white. Measured along each line of its letters on
    what the layout and the master really paint there (their shapes' outlines), else the sample's ground."""
    from verstka.rendering.layers import ground_under
    from verstka.rendering.textfill import inherited_color
    from verstka.schemas.common import Bbox, contrast_ratio

    t = next((s_ for s_ in pattern.slots if s_.role == SlotRole.title), None)
    if t is None:
        return None
    shape = next((sh for sh in slide.shapes if str(sh.shape_id) == str(t.shape_id)), None)
    if shape is None or not shape.has_text_frame or not shape.text_frame.text.strip():
        return None
    try:
        if abs(((float(shape.rotation or 0.0) + 180.0) % 360.0) - 180.0) > 1.5:
            return None  # a turned heading: its band is turned with it (`synth._keep_turned_heading`)
        col = inherited_color(shape)
    except Exception:  # noqa: BLE001
        return None
    if not col:
        return None
    W = manifest.slide_size.w
    bg = next((b.hex for b in manifest.tokens.backgrounds if pattern.source_slide in b.slides and b.hex), None)
    bg = bg or manifest.tokens.color_for("background.dark" if pattern.family.value == "dark" else "background.light")
    reads, fails = 0, 0
    for ln in ink_lines(shape._element, manifest.tokens.typography.primary_family):
        for i in range(10):
            px = ln.x + (i + 0.5) * ln.w / 10
            probe = Bbox(x=int(px - 0.004 * W), y=ln.y + ln.h // 4, w=max(int(0.008 * W), 1), h=max(ln.h // 2, 1))
            try:
                got = ground_under(slide, probe, min_share=0.5)
            except Exception:  # noqa: BLE001
                return None
            g = got[0] if got is not None else bg
            if not g:
                continue
            cr = contrast_ratio(col, g)
            reads += cr >= 3.0
            fails += cr < 2.0
    if reads and fails >= 2:
        return "the headline runs off the ground its colour is set for: a part of its letters does not read"
    return None


def content_trouble(slide, oslide: OutlineSlide, pattern: Pattern, manifest: TemplateManifest, warnings: list[str]) -> Optional[str]:
    """Why a content slide set on `pattern` must not be shown, or None."""
    for w in warnings:
        for m in LOSS_MARKERS:
            if m in w:
                return w
    c = oslide.content
    if (c.formula or "").strip():
        return "a formula: the composer sets it"
    if c.photo_slot:
        from verstka.schemas.outline import PHOTO_PLACE_NAME

        if not any((nv.get("name") or "") == PHOTO_PLACE_NAME for nv in slide._element.iter(q("p:cNvPr"))):
            return "no place for the user's photo on the sample"

    if c.chart is not None and c.table is not None:
        return "a chart and a table on one slide"
    ghosts = _layout_plates_left_empty(slide, manifest)
    if ghosts:
        return f"{ghosts} plates of the layout's placeholders stay empty on the slide"
    try:
        off = heading_off_its_ground(slide, pattern, manifest)
    except Exception:  # noqa: BLE001 - a measure never refuses a sample by failing
        off = None
    if off:
        return off
    H = manifest.slide_size.h
    hpt = H / EMU_PER_PT
    typo = manifest.tokens.typography
    body = typo.size_for("body", 14.0)
    small = typo.size_for("small", body * 0.8)
    run_floor = readable_floor(manifest)
    # (a short label — a card's title, a figure's unit — may be small print, never under the floor of small print)
    label_floor = max(small_floor(manifest), min(small * 0.9, run_floor))
    samples = {_norm(s.sample_text) for s in pattern.slots if s.sample_text and len(_norm(s.sample_text)) >= 3}
    ours = _content_strings(oslide)
    tree = slide._element.cSld.find(q("p:spTree"))
    chrome = set(pattern.chrome_shape_ids)
    # text written over the template's art (a 3D render in a card): the art stays, so the text must stand clear of it
    arts = slide.__dict__.get("_verstka_art_boxes") or []
    designed = slide.__dict__.get("_verstka_designed") or {}
    front = slide.__dict__.get("_verstka_art_front") or []
    if front:
        # the template's art drawn over a text (VK Tech p7: the 3D spiral in front of the heading's third line) hides
        # its letters: no text runs under it, whatever the sample's own text did
        fam_f = manifest.tokens.typography.primary_family
        order = {el: i for i, el in enumerate(tree)}
        for sp in tree.iter(q("p:sp")):
            nv = sp.find(".//" + q("p:cNvPr"))
            if nv is not None and nv.get("id") in chrome or sp.getparent() is not tree:
                continue
            ib = ink_box(sp, fam_f)
            if ib is None or ib.area <= 0:
                continue
            for b, el in front:
                if el.getparent() is tree and order.get(el, -1) > order.get(sp, 10**6) and ib.intersection(b) > 0.005 * ib.area:
                    # (by its painted pixels: a round render's transparent corner over a line covers nothing)
                    from verstka.rendering.deck import element_bbox as _eb
                    from verstka.rendering.layers import opaque_share
                    from verstka.schemas.common import Bbox as _BB

                    eb = _eb(el)
                    if eb:
                        ebox = _BB(x=eb[0], y=eb[1], w=eb[2], h=eb[3])
                        if all(opaque_share(slide.part, el, ebox, ln) <= 0.02 for ln in ink_lines(sp, fam_f)):
                            continue
                    return f"the template's art stands over the text «{_shape_text(sp).strip()[:24]}»"
    if arts:
        fam = manifest.tokens.typography.primary_family
        for sp in tree.iter(q("p:sp")):
            nv = sp.find(".//" + q("p:cNvPr"))
            sid = nv.get("id") if nv is not None else None
            if sid in chrome:
                continue
            if nv is not None and (nv.get("name") or "").startswith("Photo caption"):
                continue  # the user's picture place says what goes there — inside the place, on a screen of the art too
            ib = ink_box(sp, fam)
            if ib is None or ib.area <= 0:
                continue
            own = designed.get(sid)
            own_ink = (slide.__dict__.get("_verstka_designed_ink") or {}).get(sid)
            lines = ink_lines(sp, fam) or [ib]
            lines_area = sum(ln.area for ln in lines) or ib.area
            for a in arts:
                # (line by line: a short last line under a long first one leaves the corner beside it free)
                ov = sum(ln.intersection(a) for ln in lines)
                if ov <= 0.03 * lines_area:
                    continue
                if own_ink is not None:
                    # the sample sets its own words over the art: ours may cover as much of it as they did, a little more
                    if ov <= 1.25 * own_ink.intersection(a) + 0.03 * ib.area:
                        continue
                elif own is not None and own.intersection(a) > 0.1 * max(own.area, 1):
                    continue  # the sample sets this text over the art itself
                return f"text «{_shape_text(sp).strip()[:24]}» runs over the template's art"

    # a heading squeezed far below the deck's heading size (a long headline in a sample's short title bar): the deck's
    # headings would jump from slide to slide
    heads = [s for s in pattern.slots if s.role == SlotRole.title]
    if heads and (oslide.headline or "").strip():
        h1 = slide.__dict__.get("_verstka_head_size") or typo.size_for("h1", 0.0)
        ref = min(x for x in (heads[0].style.size_pt or 0.0, h1) if x > 0) if (heads[0].style.size_pt or h1) else 0.0
        el = next((x for x in tree.iter(q("p:sp")) if (x.find(".//" + q("p:cNvPr")) is not None and x.find(".//" + q("p:cNvPr")).get("id") == heads[0].shape_id)), None)
        sizes = [int(r.get("sz")) / 100 for r in el.iter(q("a:rPr")) if r.get("sz")] if el is not None else []
        if ref and sizes and min(sizes) < 0.75 * ref - 0.05:
            return f"the heading had to shrink to {min(sizes):g} pt (the deck sets {ref:g} pt)"
    closing = closing_trouble(slide, body, oslide.headline)
    if closing:
        return closing
    sparse = _panel_left_empty(slide, oslide, chrome, manifest)
    if sparse:
        return sparse
    marks = slide.__dict__.get("_verstka_cell_marks") or []
    if marks:
        why = _marks_trouble(slide, oslide, marks, chrome, manifest)
        if why:
            return why
    # figures squeezed far below the sample's own (VK Tech p42: two display figures, three of ours set at a label's
    # size in narrowed cells): the sample's point — the big number — is lost
    nums = {s.shape_id: (s.style.size_pt or 0.0) for s in pattern.slots if s.role == SlotRole.number and (s.style.size_pt or 0.0) >= 20}
    if nums:
        origin = slide.__dict__.get("_verstka_origin") or {}
        for sp in tree.iter(q("p:sp")):
            nv = sp.find(".//" + q("p:cNvPr"))
            sid = nv.get("id") if nv is not None else None
            own = nums.get(origin.get(sid, sid)) if sid else None
            if not own or not _shape_text(sp).strip():
                continue
            sizes = [int(r.get("sz")) / 100 for r in sp.iter(q("a:rPr")) if r.get("sz")]
            if sizes and max(sizes) < 0.5 * own:
                return f"figure «{_shape_text(sp).strip()[:12]}» set at {max(sizes):g} pt where the sample sets {own:g} pt"
    # the heading's lines run into the content under them (a headline of two lines over a sample made for one)
    if heads:
        t_el = next((x for x in tree.iter(q("p:sp")) if (x.find(".//" + q("p:cNvPr")) is not None and x.find(".//" + q("p:cNvPr")).get("id") == heads[0].shape_id)), None)
        tib = ink_box(t_el, manifest.tokens.typography.primary_family) if t_el is not None else None
        if tib is not None and tib.area > 0:
            from verstka.rendering.deck import element_bbox
            from verstka.schemas.common import Bbox

            for el in tree:
                if el is t_el or etree.QName(el).localname not in ("sp", "pic", "graphicFrame", "grpSp"):
                    continue
                nv = el.find(".//" + q("p:cNvPr"))
                if nv is not None and nv.get("id") in chrome:
                    continue
                b = element_bbox(el)
                if not b or b[2] <= 0 or b[3] <= 0 or b[2] * b[3] >= 0.5 * manifest.slide_size.w * H:
                    continue
                ob = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
                if ob.contains_point(tib.x + tib.w / 2, tib.y + tib.h / 2):
                    continue  # the heading's own pill or band
                if etree.QName(el).localname == "pic":
                    try:
                        from verstka.rendering.layers import opaque_box

                        ob = opaque_box(slide.part, el, ob)  # a render's transparent margin is no obstacle
                    except Exception:  # noqa: BLE001
                        pass
                    if ob.w <= 0 or ob.h <= 0:
                        continue
                if etree.QName(el).localname == "sp":
                    if _shape_text(el).strip():
                        ob = ink_box(el, manifest.tokens.typography.primary_family) or ob
                    else:
                        from verstka.rendering.clone_notes import _paints

                        if not _paints(el):
                            continue
                if ob.y > tib.y and tib.intersection(ob) > 0.04 * tib.area:
                    return f"the heading runs into «{_shape_text(el).strip()[:20] or etree.QName(el).localname}» under it"
            # a rule of the sample's grid between the heading's lines (Классика p11: a two-line heading in a band made for
            # one, the band's rule through its second line; the grid drawn on the layout) — a hairline has no area to
            # overlap, so it is crossed or not
            Wd = manifest.slide_size.w
            pad = max(int(0.12 * tib.h), int(0.006 * H))
            lines = list(tree)
            try:
                for holder in (slide.slide_layout, slide.slide_layout.slide_master):
                    lines += [x for x in holder._element.cSld.find(q("p:spTree")) if x.find(".//" + q("p:ph")) is None]
            except Exception:  # noqa: BLE001 - the slide's own rules then
                pass
            for el in lines:
                tag = etree.QName(el).localname
                if tag not in ("cxnSp", "sp") or el is t_el:
                    continue
                if tag == "sp" and _shape_text(el).strip():
                    continue
                b = element_bbox(el)
                if not b:
                    continue
                x, y, w, h = b
                if h <= 0.006 * H and w >= 0.05 * Wd and tib.y + pad < y + h / 2 < tib.y2 - pad and min(tib.x2, x + w) - max(tib.x, x) > 0.2 * tib.w:
                    return "the heading's lines cross a rule of the sample"
                if w <= 0.006 * Wd and h >= 0.05 * H and tib.x + pad < x + w / 2 < tib.x2 - pad and min(tib.y2, y + h) - max(tib.y, y) > 0.5 * tib.h:
                    return "a rule of the sample runs through the heading"
    # two of the slide's own texts over each other (Классика p11: three stages in a column made for two, the first
    # stage's heading over its own text)
    fam_o = manifest.tokens.typography.primary_family

    def ours_text(t: str) -> bool:
        n = _norm(t)[:30]
        return bool(n) and any(o.startswith(n) or n.startswith(o[:30]) for o in ours if o)

    placed = []
    for sp in tree.iter(q("p:sp")):
        nv = sp.find(".//" + q("p:cNvPr"))
        if sp.getparent() is not tree or (nv is not None and nv.get("id") in chrome):
            continue
        t = _shape_text(sp).strip()
        if not t or not ours_text(t):
            continue
        ib = ink_box(sp, fam_o)
        if ib is not None and ib.area > 0:
            placed.append((t, ib))
    for i, (ta, a) in enumerate(placed):
        for tb_, b in placed[i + 1 :]:
            if a.intersection(b) > 0.15 * min(a.area, b.area):
                return f"text «{ta[:20]}» runs into «{tb_[:20]}»"
    # a hairline of the sample's rows through one of our texts (LCT: rows of a list set at their own rhythm, the
    # sample's rules left where its own rows were — «Разместить десерты рядом с кассой» struck through)
    from verstka.rendering.deck import element_bbox as _eb

    Wd2 = manifest.slide_size.w
    for el in tree:
        tag = etree.QName(el).localname
        if tag not in ("cxnSp", "sp") or (tag == "sp" and _shape_text(el).strip()):
            continue
        nv = el.find(".//" + q("p:cNvPr"))
        if nv is not None and nv.get("id") in chrome:
            continue
        lb = _eb(el)
        if not lb or lb[3] > 0.006 * H or lb[2] < 0.05 * Wd2:
            continue
        ly = lb[1] + lb[3] / 2
        for t, ib in placed:
            pad = max(int(0.2 * min(ib.h, 0.05 * H)), int(0.004 * H))
            if ib.y + pad < ly < ib.y2 - pad and min(ib.x2, lb[0] + lb[2]) - max(ib.x, lb[0]) > 0.3 * ib.w:
                return f"a rule of the sample runs through «{t[:20]}»"
    # text running out of the card it starts in (a third line of a card's text under the card's foot)
    native = slide.__dict__.get("_verstka_native") or set()
    cards = []
    from verstka.rendering.clone_notes import _paints as _paints_c
    from verstka.rendering.deck import element_bbox as _ebox
    from verstka.schemas.common import Bbox as _Bbox

    for el in tree:
        if etree.QName(el).localname != "sp" or _shape_text(el).strip() or not _paints_c(el):
            continue
        b = _ebox(el)
        if b and b[2] > 0 and b[3] > 0 and b[2] * b[3] < 0.5 * manifest.slide_size.w * H:
            cards.append(_Bbox(x=b[0], y=b[1], w=b[2], h=b[3]))
    # text running out of its own plate (VK WorkSpace p6: a card heading written in the grey card itself, its frame cut
    # to one line while the heading took two — the second line hangs under the card)
    for sp in tree.iter(q("p:sp")):
        nv = sp.find(".//" + q("p:cNvPr"))
        if nv is not None and (nv.get("id") in chrome or nv.get("id") in native):
            continue
        if not _shape_text(sp).strip() or not _paints_c(sp):
            continue
        bp = sp.find(q("p:txBody") + "/" + q("a:bodyPr"))
        if bp is not None and bp.find(q("a:spAutoFit")) is not None:
            continue  # the plate grows with its text where it is opened
        b = _ebox(sp)
        ib = ink_box(sp, manifest.tokens.typography.primary_family)
        if not b or ib is None or b[3] <= 0:
            continue
        # (its last line's leading under the letters is no ink: half a percent of the slide is let through)
        if ib.y + ib.h > b[1] + b[3] + 0.005 * H or ib.y < b[1] - 0.01 * H:
            return f"text «{_shape_text(sp).strip()[:24]}» runs out of its plate"
    if cards:
        fam_c = manifest.tokens.typography.primary_family
        W = manifest.slide_size.w
        from verstka.rendering.textfill import has_visible_style as _boxed

        for sp in tree.iter(q("p:sp")):
            nv = sp.find(".//" + q("p:cNvPr"))
            if nv is not None and (nv.get("id") in chrome or nv.get("id") in native):
                continue
            if not _shape_text(sp).strip():
                continue
            ib = ink_box(sp, fam_c)
            if ib is None:
                continue
            home = [c for c in cards if c.contains_point(ib.x + min(ib.w, c.w) / 2, ib.y + 1) and c.area >= 1.3 * ib.w * min(ib.h, c.h)]
            if home:
                card = min(home, key=lambda c: c.area)
                if ib.y + ib.h > card.y2 + 0.01 * H:
                    return f"text «{_shape_text(sp).strip()[:24]}» runs out of its card"
            # its frame running past the right edge of the label or card its first line starts on (a two-line heading
            # set over a pill widened short of it: LCT p11) — the audit's own measure (`text_outside_card`)
            b_sp = _ebox(sp)
            if not b_sp or _boxed(sp):
                continue  # a text on its own plate is its own card
            occ = _Bbox(x=b_sp[0], y=ib.y, w=b_sp[2], h=ib.h)
            x0, y0 = occ.x + min(occ.w // 20, int(0.01 * W)), occ.y + min(occ.h // 20, int(0.01 * H))
            hosts = [c for c in cards if c.x <= x0 <= c.x2 and c.y <= y0 <= c.y2 and c.area > 0.3 * occ.area]
            if hosts:
                host = min(hosts, key=lambda c: c.area)
                sid0 = (slide.__dict__.get("_verstka_origin") or {}).get(nv.get("id") if nv is not None else "", nv.get("id") if nv is not None else "")
                own = next((x.bbox for x in pattern.slots if x.shape_id == sid0), None)
                as_designed = own is not None and abs(own.x2 * W - occ.x2) <= 0.005 * W
                if occ.x2 - host.x2 > 0.015 * W and not as_designed:
                    return f"text «{_shape_text(sp).strip()[:24]}» runs past the right edge of its card"
    # a hole where the sample had its content: cells, a band, a card or a picture taken off and nothing in their
    # place (WorkSpace p15 without its note band, LCT p20 without its big card) — the composer sets such content better
    if slide.__dict__.get("_verstka_rows_off_rules"):
        return "the rows moved off the sample's rules: two rows between two rules"
    hole0 = slide.__dict__.get("_verstka_hole0")
    if hole0 is not None:
        try:
            grid, area = _covered(slide, pattern, manifest)
            hole = largest_hole(grid, area)
            slide.__dict__["_verstka_hole"] = hole
            if hole >= HOLE_MIN and hole - hole0 >= HOLE_GROWTH:
                return f"a hole of {hole:.0%} of the slide where the sample had {hole0:.0%} free"
        except Exception:  # noqa: BLE001
            pass
    # the figures of a stat slide set at a caption's size (VK Tech p20: «87» at 10 pt in a list made for «Пункт»): the
    # slide's point is its figures — they read as figures or the slide is composed
    if c.numbers and oslide.kind in (PatternKind.stat_row, PatternKind.big_number):
        vals = {re.sub(r"\s+", "", (n.value or "")) for n in c.numbers if (n.value or "").strip()}
        fig_sizes = []
        for sp in tree.iter(q("p:sp")):
            nv = sp.find(".//" + q("p:cNvPr"))
            if nv is not None and (nv.get("id") in chrome or nv.get("id") in native):
                continue
            for para in sp.iter(q("a:p")):
                ptxt = re.sub(r"[\s\u2060]+", "", "".join(t.text or "" for t in para.iter(q("a:t"))))
                if ptxt and ptxt in vals:
                    szs = [int(r.get("sz")) / 100 for r in para.iter(q("a:rPr")) if r.get("sz")]
                    if szs:
                        fig_sizes.append(max(szs))
        want = max(1.6 * body, 0.7 * typo.size_for("h1", body * 2))
        if fig_sizes and max(fig_sizes) < want - 0.05:
            return f"figures set at {max(fig_sizes):g} pt — a figure reads at {want:.0f} pt and more"
    # a key figure leads its label (qa4 L3 / NEW-L2: 1.6 times its size at the least) and stands with it — the clone
    # has set the pair as large as the sample's frames allow (`clone._figure_floor`): a sample that cannot is no place
    # for the figures
    fig_trouble = figure_trouble(slide, oslide, skip=chrome)
    if fig_trouble:
        return fig_trouble
    # two texts laid over each other: a card title that took a second line runs into the text under it (LCT p11
    # with a third card: «На входе — шаблон и текст» over «Verstka использует…») — unless the sample set them so
    clash = _texts_over_each_other(slide, tree, chrome, typo.primary_family, native=set(native))
    if clash:
        return clash
    # the chart or the table the slide carries must be on it (drawn, and not taken off by a later step)
    if c.chart is not None or c.table is not None:
        frames = [el for el in tree if etree.QName(el).localname == "graphicFrame" and el.find(".//" + q("p:cNvPr")) is not None and el.find(".//" + q("p:cNvPr")).get("id") in native]
        if not frames:
            return "the slide's chart or table is not on the slide"
    # the design system's table or chart squeezed into a sample's small area: its type below the deck's own data size
    if native:
        data_floor = 0.85 * min(manifest.components.table_style.font_size_pt, manifest.components.chart_style.font_size_pt)
        for el in tree:
            nv = el.find(".//" + q("p:cNvPr"))
            if nv is None or nv.get("id") not in native or etree.QName(el).localname != "graphicFrame":
                continue
            sizes = [int(r.get("sz")) / 100 for r in el.iter(q("a:rPr")) if r.get("sz")]
            if sizes and min(sizes) < data_floor - 0.05:
                return f"the table or chart set at {min(sizes):g} pt, below the deck's {data_floor / 0.85:g} pt for data"
    for sp in tree.iter(q("p:sp")):
        nv = sp.find(".//" + q("p:cNvPr"))
        if nv is not None and nv.get("id") in chrome:
            continue
        # the design system's own texts drawn with a chart or a table (its side text, its legend) set their own sizes
        # (the data floor above), but a word of theirs broken across lines reads as badly as any («рентабельно / сть»)
        drawn = nv is not None and nv.get("id") in native
        text = _shape_text(sp)
        if not text.strip():
            continue
        n = _norm(text)
        if not drawn and n in samples and n not in ours and not any(n in o for o in ours):
            return f"sample text «{text.strip()[:30]}» left on the slide"
        from verstka.rendering.deck import abs_bbox, element_bbox, is_nested
        from verstka.rendering.fonts import text_width_pt

        # (in slide units: a text in a scaled group keeps its size while its box scales with the group)
        b_sp = abs_bbox(sp) if is_nested(sp) else element_bbox(sp)
        bp_sp = sp.find(q("p:txBody") + "/" + q("a:bodyPr"))

        def _ins(name: str, default: int) -> int:
            try:
                return int(bp_sp.get(name)) if bp_sp is not None and bp_sp.get(name) is not None else default
            except ValueError:
                return default

        usable = (b_sp[2] - _ins("lIns", 91440) - _ins("rIns", 91440)) / EMU_PER_PT if b_sp else 0.0
        wrap_on = bp_sp is None or bp_sp.get("wrap") != "none"
        for p in sp.iter(q("a:p")):
            ptxt = "".join(t.text or "" for t in p.iter(q("a:t")))
            if not ptxt.strip():
                continue
            sizes = [int(r.get("sz")) / 100 for r in p.iter(q("a:rPr")) if r.get("sz")]
            if not sizes:
                continue
            if _is_code_para(p):
                continue  # the user's code: set unbroken at the size its longest line allows, never typeset as prose
            if usable > 0 and wrap_on and nv is not None:
                # a word (or words bound by no-break spaces) wider than its box is broken across lines by the renderer
                rpr = next((r for r in p.iter(q("a:rPr")) if r.get("sz")), None)
                lat = rpr.find(q("a:latin")) if rpr is not None else None
                fam_p = lat.get("typeface") if lat is not None and lat.get("typeface") else typo.primary_family
                bold_p = bool(rpr is not None and rpr.get("b") == "1")
                # split as the renderer breaks lines: at ordinary spaces only (`wrap_lines`), at the width the
                # paragraph's lines really have (its left margin off)
                room = usable - para_indent(p, sp.find(q("p:txBody"))) / EMU_PER_PT
                for chunk in re.split(r"[ \t\r\n]+", ptxt):
                    if len(chunk) >= 4 and text_width_pt(chunk, fam_p, max(sizes), bold_p) > room * 1.01:
                        return f"«{chunk.replace(chr(160), ' ')[:24]}» is wider than its box and breaks mid-word"
            if drawn:
                continue
            size = min(sizes)
            floor = run_floor if len(ptxt.strip()) >= 25 else label_floor
            if nv is not None and re.fullmatch(r"Footnote( \d+)?", nv.get("name") or ""):
                # the slide's footnote is small print by design, set at the composer's footnote size (about 2 % of
                # the slide height, `Composer._footnote_size`) — the size a composed slide gives it
                floor = min(floor, 0.019 * manifest.slide_size.h / EMU_PER_PT)
            if size < floor - 0.05:
                return f"text «{ptxt.strip()[:24]}» set at {size:g} pt, below {floor:.1f} pt"
    return None
