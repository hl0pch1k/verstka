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
from typing import Optional

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
# a step's number, not a quantity: «Месяц 2», «Этап 1», «Шаг 3:», «3‑й мес.» (a label shortened on a chart axis)
_STEP_BEFORE_RE = re.compile(r"(?:месяц|мес\.|этап|шаг|недел[яи]|квартал|день|пункт|слайд|раздел|волна|спринт|№|Q)\s*$", re.I)
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
    return [p.text for p in e.paragraphs if p.text.strip()]


def _chart_parts(slide: IRSlide) -> tuple[list[float], list[float]]:
    """Shares (in %) and totals the slide's charts imply: a legend beside a pie says «40%» of 315 000 in 780 000."""
    shares: list[float] = []
    totals: list[float] = []
    for e in slide.elements:
        if e.chart is None:
            continue
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


def _index(ctx: AuditContext):
    from verstka.planning.brief_structure import read_structure
    from verstka.planning.grounding import BriefIndex

    idx = BriefIndex(ctx.brief_text or "", ctx.outline.title if ctx.outline is not None else None)
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
    for s in ctx.ir.slides:
        shares, totals = _chart_parts(s)
        changes = _chart_changes(s)
        cover = _cover(s, ctx)
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
                    elif v == "ok" and not idx._same(f):
                        v = "derived"  # a difference, a percent change or a ratio of the brief's figures
                    if v != "ok" and t in row_given:
                        v = "derived"  # 3 200 ₽ / 4 занятия = 800 ₽ за занятие, in the same row of the table
                    found.append((written, v))
            if e.chart is not None:
                for ser in e.chart.series:
                    for val in ser.values:
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
