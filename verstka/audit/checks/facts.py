"""Figures on the slides against the brief (criterion Q4 of the ТЗ: every figure and fact comes from the source).

The planner grounds the plan's figures before rendering (planning/grounding.py); this check reads the finished deck —
text boxes, table cells, chart values — so what the renderer computed on its own (a pie legend's shares, a doughnut's
total, a before/after delta) is checked too, and the report can say how many figures were compared. A figure passes
when the brief writes it (units compatible, rounded as a person rounds), when it follows from two of the brief's
figures of one measure (difference, percent change, ratio — the analyst's before/after pairs included), when its table
row gives it (a count its label spells in words, a price per unit of two of the row's figures), or when it is a
share, a total, a ratio, a percent change or a difference of a chart's own values on the same slide (the renderer's
growth label «×2,1» beside a chart of 120 000 → 254 795). Step badges («01», «3»), page numbers and a cover's date
are not facts and are skipped."""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterable, Iterator, Optional

from verstka.audit.checks.common import is_chrome_like
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.deck_ir import IRElement, IRSlide

FIGURE_NOT_IN_BRIEF = CheckSpec(
    id="figure_not_in_brief",
    title="Число на слайде не найдено в тексте",
    severity="warn",
    category="content",
    description=(
        "Каждое число в тексте, таблицах и диаграммах слайда ищется среди чисел исходного текста (с единицами измерения) "
        "и того, что из них прямо следует: разность, процент изменения, во сколько раз, доли и сумма частей диаграммы, "
        "а также разность, процент изменения и отношение двух значений диаграммы на том же слайде («×2,1» рядом "
        "с ростом со 120 000 до 254 795). В строке таблицы своими считаются число, которое подпись строки пишет словами "
        "(«Четыре занятия» — 4), и цена за единицу из двух чисел той же строки (3 200 ₽ / 4 = 800 ₽). "
        "Номера шагов, страниц и дата на обложке не проверяются."
    ),
)

_BADGE_RE = re.compile(r"^\s*0?\d{1,2}[.)]?\s*$")
# a step's number, not a quantity: «Месяц 2», «Этап 1», «Шаг 3:», «Модуль 2», «Урок 4», «3‑й мес.» (a label shortened
# on a chart axis)
_STEP_BEFORE_RE = re.compile(
    r"(?:месяц|мес\.|этап|шаг|недел[яию]|квартал|день|дн[яи]|пункт|слайд|раздел|волна|спринт|модул[ьяи]|урок|"
    r"заняти[еяй]|блок|семестр|глав[аы]|част[ьи]|№|Q)\s*$",
    re.I,
)
_ORDINAL_AFTER_RE = re.compile(r"^[-‑\u2060]*(?:й|я|е|го|м|ом|ый|ой|ая|ую)\b", re.I)


def _step_number(text: str, f) -> bool:
    if f.unit is not None or f.dec or f.value > 99:
        return False
    return bool(_STEP_BEFORE_RE.search(text[: f.start]) or _ORDINAL_AFTER_RE.match(text[f.end :]))
_SKIP_PH = {"sldNum", "dt", "ftr", "SLIDE_NUMBER", "DATE", "FOOTER"}


def _texts(e: IRElement) -> list[str]:
    if e.table is not None:
        return [c for row in e.table.rows for c in row if c and c.strip()]
    if e.chart is not None:
        return []  # a chart's values are checked as numbers (below), its categories are labels
    if not e.has_text or _BADGE_RE.match(e.text):
        return []
    # (a paragraph that is only an item's badge — «1» over «Основы SQL» in one box — is a number of the list, not a
    # figure: qa3 N-L6, o03's «1», «2» warnings)
    return [p.text for p in e.paragraphs if p.text.strip() and not _BADGE_RE.match(p.text)]


def _chart_parts(slide: IRSlide) -> tuple[list[float], list[float]]:
    """Shares (in %) and totals the slide's charts imply: a legend beside a pie says «40%» of 315 000 in 780 000."""
    shares: list[float] = []
    totals: list[float] = []
    for e in slide.elements:
        if e.chart is None or (e.chart.type == "doughnut" and [str(c).strip().lower() for c in e.chart.categories] == ["value", "rest"]):
            continue  # (a progress ring's track is drawing, not a part of a whole)
        for s in e.chart.series:
            vals = [v for v in s.values if v is not None and v >= 0]
            total = sum(vals)
            if total <= 0 or len(vals) < 2:
                continue
            totals.append(total)
            shares.extend(v / total * 100 for v in vals)
    return shares, totals


_TIMES_BEFORE_RE = re.compile(r"[×xх]\s?$", re.I)  # «×2,1»: a multiple written before its number
_PAIRS_ALL = 12  # a series this long or shorter: every two of its values are compared; longer: neighbours and ends


def _series_pairs(vals: list[float]) -> list[tuple[float, float]]:
    """(earlier, later) pairs of one series a reader compares: any two of a short series, else neighbours and the
    first and last value."""
    n = len(vals)
    if n <= _PAIRS_ALL:
        return [(vals[i], vals[j]) for i in range(n) for j in range(i + 1, n)]
    return [(vals[i], vals[i + 1]) for i in range(n - 1)] + [(vals[0], vals[-1])]


def _chart_changes(slide: IRSlide) -> tuple[list[float], list[float], list[float]]:
    """(ratios, percent changes, differences) of two values of a chart on the slide: two values of one series (the
    renderer's growth label «×2,1» beside a chart of 120 000 → 254 795, «−53%», «+134 795 ₽»), or two series at one
    category. What a person reads off the chart beside it is derived from its values, not a new figure."""
    ratios: list[float] = []
    pcts: list[float] = []
    diffs: list[float] = []
    for e in slide.elements:
        if e.chart is None:
            continue
        rows = [[v for v in s.values] for s in e.chart.series]
        pairs: list[tuple[float, float]] = []
        for r in rows:
            vals = [v for v in r if v is not None]
            if len(vals) >= 2:
                pairs.extend(_series_pairs(vals))
        for a_row, b_row in zip(rows, rows[1:]):
            pairs.extend((a, b) for a, b in zip(a_row, b_row) if a is not None and b is not None)
        for a, b in pairs:
            if a == b:
                continue
            diffs.append(abs(b - a))
            if a > 0 and b > 0:
                ratios.append(max(a, b) / min(a, b))
                pcts.append(abs(b - a) / a * 100.0)
    return ratios, pcts, diffs


def _chart_derived(text: str, f, changes: tuple[list[float], list[float], list[float]]) -> bool:
    """The figure is a ratio, a percent change or a difference of two values of a chart on the same slide."""
    ratios, pcts, diffs = changes
    if not (ratios or diffs):
        return False
    if f.unit == "times" or (f.unit is None and _TIMES_BEFORE_RE.search(text[: f.start])):
        return _near(f.value, f.dec, ratios)
    if f.unit == "pct":
        return _near(f.value, f.dec, pcts)
    if f.unit in ("pp", "pts") or f.date is not None:
        return False
    return _near(f.value, f.dec, [d / (f.scale or 1.0) for d in diffs])


def _line_change(text: str, f) -> bool:
    """A percent the line computes from two of its own figures: the change («1 840 против 1 750 (+5%)») or the share."""
    from verstka.planning.grounding import figures

    vals = [g.value for g in figures(text) if g.start != f.start and g.unit != "pct" and g.value and g.date is None]
    cands = [x for a in vals for b in vals if a != b for x in ((a - b) / b * 100, abs(a - b) / b * 100, a / b * 100)]
    return _near(abs(f.value), f.dec, cands)


def _plain(text: str) -> str:
    """A line as words: no-break spaces and word joiners as spaces, no closing period, lower case."""
    return " ".join(re.sub(r"[\u00a0\u202f\u2009\u2060\u200b]", " ", text or "").split()).rstrip(".").lower()


def _near(value: float, dec: int, candidates: list[float]) -> bool:
    step = 10 ** -dec
    return any(abs(value - c) <= step * 0.51 + 1e-9 for c in candidates)


class FigureStats:
    """What the check compared, for the report's summary («72 числа сверены с текстом, 4 посчитаны из его чисел»)."""

    def __init__(self) -> None:
        self.checked = 0
        self.derived = 0
        self.unverified = 0

    def as_dict(self) -> dict:
        return {"checked": self.checked, "derived": self.derived, "unverified": self.unverified}


# the texts besides the brief the deck's figures come from (a data deck's knowledge base: its documents and the part the
# writer wrote of them — «150 клиентов к 31 декабря 2026 года» is the base's, not a figure made up): the API sets them
# around an edit or a fix of a generation (api/app.py `_figure_sourced`); this check and the edit's grounding read them
_SOURCES: ContextVar[tuple[str, ...]] = ContextVar("verstka_figure_sources", default=())


@contextmanager
def figure_sources(texts: Iterable[str]) -> Iterator[None]:
    """Within the block the figures check also takes the figures of `texts` (the knowledge base's documents) as given."""
    token = _SOURCES.set(tuple(t for t in texts if t and t.strip()))
    try:
        yield
    finally:
        _SOURCES.reset(token)


def figure_texts() -> tuple[str, ...]:
    """The texts `figure_sources` set for this job (planning/grounding asks them too); empty outside it."""
    return _SOURCES.get()


def _index(ctx: AuditContext):
    from verstka.planning.brief_structure import read_structure
    from verstka.planning.grounding import BriefIndex

    text = "\n\n".join([ctx.brief_text or "", *_SOURCES.get()])
    idx = BriefIndex(text, ctx.outline.title if ctx.outline is not None else None)
    try:
        idx.use_structure(read_structure(ctx.brief_text or ""))
    except Exception:  # noqa: BLE001  (the rules' reading only adds derived pairs; the brief's figures stand without it)
        pass
    return idx


def _cover(slide: IRSlide, ctx: AuditContext) -> bool:
    if slide.index == 1:
        return True
    if ctx.outline is not None and slide.outline_id:
        o = next((s for s in ctx.outline.slides if s.id == slide.outline_id), None)
        return o is not None and o.kind.value in ("title", "thanks")
    return False


@check(FIGURE_NOT_IN_BRIEF)
def figure_not_in_brief(ctx: AuditContext) -> list[Issue]:
    if not (ctx.brief_text or "").strip():
        return []
    from verstka.planning.grounding import figures

    idx = _index(ctx)
    stats = FigureStats()
    out: list[Issue] = []
    # a slide made from a data file (OutlineSlide.data) takes its figures from the file, not from the brief: they are
    # checked against the dataset's facts and values (audit/checks/data.py)
    data_slides = [s for s in (ctx.outline.slides if ctx.outline is not None else []) if getattr(s, "data", None) is not None]
    from_data = {s.id for s in data_slides}
    # the facts the analysis counted from those files: the summary of a data deck («Выручка выросла на 23%») says them
    data_facts = [float(f.value) for s in data_slides for f in s.data.headline_facts]
    # …and every value the data layer put on those slides (their charts, tables, cards, captions and the numbers in
    # their names — the bins «больше 120» of a histogram): a data deck's summary and next steps carry the data story's
    # figures, re-set by «Исправить слайд» («20% — больше 120 мин · 3 — больше 10 часов»), never the one-line brief's
    if data_slides:
        from verstka.data.headline import numbers_in
        from verstka.data.story import data_slide_labels, slide_values

        for s0 in data_slides:
            try:
                data_facts += slide_values(s0)
                data_facts += [v for lab in data_slide_labels(s0) for v in numbers_in(str(lab))]
                prep = s0.data.prepared
                if prep is not None:
                    data_facts += [v for c in list(prep.categories) + list(prep.columns) for v in numbers_in(str(c))]
            except Exception:  # noqa: BLE001 - a slide the data layer cannot read: its headline facts only
                continue
    # …and the data slides' conclusions repeated whole (a summary card: «Прямые продажи приносят почти половину выручки»)
    data_heads = {_plain(s.headline) for s in data_slides}
    for s in ctx.ir.slides:
        if s.outline_id in from_data:
            continue
        shares, totals = _chart_parts(s)
        changes = _chart_changes(s)
        cover = _cover(s, ctx)
        # the shares of two given figures of the slide: «131» (the data) of «150» (the base's goal) is «87 % цели» on a
        # card of its own — computed from what the slide shows, not a new figure
        given = [g.value for e in s.elements for t in _texts(e) for g in figures(t)
                 if g.unit != "pct" and g.date is None and g.value > 0
                 and (idx.verdict(g) == "ok" or (data_facts and _near(g.value, g.dec, data_facts)))]
        shares_of = [a / b * 100.0 for a in given for b in given if a < b]
        for e in s.elements:
            if (e.ph_type or "") in _SKIP_PH or is_chrome_like(e, ctx.ir, ctx.manifest):
                continue
            found: list[tuple[str, str]] = []  # (as written, verdict)
            # a table row gives its own counts spelled in its label and a per-unit value of two of its figures
            # («Четыре занятия» | 4 | 3 200 | 800) — as the planner's grounding lets them stand
            row_given: set[str] = set()
            if e.table is not None:
                from verstka.planning.grounding import _row_given

                for row in e.table.rows:
                    try:
                        row_given.update(row[j] for j in _row_given(idx, [c or "" for c in row]))
                    except Exception:  # noqa: BLE001 - the plain verdict then
                        pass
            for t in _texts(e):
                pt = _plain(t)
                if data_heads and (pt in data_heads or (len(pt) >= 20 and any(pt in h for h in data_heads))):
                    # a data slide's conclusion said again, whole or without its figure (the summary redone with
                    # «цифры крупнее»: «46%» over «Прямые продажи приносят почти половину выручки» — qa4 live checks)
                    continue
                for f in figures(t):
                    if cover and (f.date is not None or (f.plain and 1900 <= f.value <= 2100)):
                        continue  # the cover's date is the deck's, not a fact of the brief
                    if _step_number(t, f):
                        continue
                    written = t[f.start : f.uend].strip()
                    v = idx.verdict(f)
                    if v != "ok" and f.unit == "pct" and _near(f.value, f.dec, shares):
                        v = "derived"
                    elif v != "ok" and _near(f.mag, 0, totals):
                        v = "derived"
                    elif v != "ok" and _chart_derived(t, f, changes):
                        v = "derived"  # «×2,1» beside a chart of 120 000 → 254 795: read off the chart's own values
                    elif v != "ok" and f.unit == "pct" and _line_change(t, f):
                        v = "derived"  # «1 840 млн ₽ против 1 750 (+5%)»: the change of the line's own two figures (qa6)
                    elif v != "ok" and f.unit == "pct" and _near(f.value, f.dec, shares_of):
                        v = "derived"  # «87 % цели» beside «131» and «150» on the same slide
                    elif v == "ok" and not idx._same(f):
                        v = "derived"  # a difference, a percent change or a ratio of the brief's figures
                    if v != "ok" and t in row_given:
                        v = "derived"  # 3 200 ₽ / 4 занятия = 800 ₽ за занятие, in the same row of the table
                    elif v != "ok" and data_facts and _near(f.value, f.dec, data_facts):
                        v = "derived"  # a fact of the deck's data files (the summary's conclusions, the key figures)
                    found.append((written, v))
            if e.chart is not None:
                for ser in e.chart.series:
                    # (a progress ring — «18%» drawn as a doughnut of «value» and its hidden «rest» track — says one
                    # figure: the track's 82 is drawing, not a figure of the slide — qa3 N-L7)
                    ring = e.chart.type == "doughnut" and [str(c).strip().lower() for c in e.chart.categories] == ["value", "rest"]
                    for val in (ser.values[:1] if ring else ser.values):
                        if val is None:
                            continue
                        written = f"{val:.12g}".replace(".", ",")  # 1138500, not 1.1385e+06
                        f = next(iter(figures(written)), None)
                        if f is None:
                            continue
                        v = idx.verdict(f)
                        found.append((written, "derived" if v != "ok" and _near(val, 0, totals) else v))
            bad = []
            for written, v in found:
                stats.checked += 1
                if v == "derived":
                    stats.derived += 1
                elif v != "ok":
                    stats.unverified += 1
                    bad.append(written)
            if bad:
                shown = ", ".join(f"«{b}»" for b in dict.fromkeys(bad))
                out.append(ctx.new_issue(
                    FIGURE_NOT_IN_BRIEF, s.index,
                    f"{shown}: такого числа нет в исходном тексте и оно не следует из его чисел",
                    bboxes=[e.bbox_frac], element_ids=[e.id],
                    suggestion="Проверьте число по исходному тексту или уберите его со слайда.",
                ))
    ctx.figure_stats = stats.as_dict()
    return out


def figure_summary(stats: Optional[dict]) -> Optional[str]:
    """«Сверил с исходным текстом 72 числа на слайдах — лишних нет: 60 взяты из текста, 12 посчитаны из его чисел» —
    for the result screen and the chat."""
    if not stats or not stats.get("checked"):
        return None
    from verstka.ru import ru_count

    n, d, u = stats["checked"], stats.get("derived", 0), stats.get("unverified", 0)
    head = f"Сверил с исходным текстом {ru_count(n, 'число', 'числа', 'чисел')} на слайдах"
    if u:
        return f"{head}: {ru_count(u, 'число', 'числа', 'чисел')} в нём нет — посмотрите замечания."
    if not d:
        return f"{head} — все взяты из него."
    return f"{head} — лишних нет: {n - d} взяты из текста, {d} посчитаны из его чисел (доли, изменения, суммы)."
