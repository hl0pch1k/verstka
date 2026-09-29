"""The agent's compiler (Agent v2, step 4): the slide designer's slides become one deck the renderer lays out.

The designer writes each slide on its own (planning/agent.py, skills/slide_designer): a chart with its data inline
(`ChartSpec.categories` + `series`), a second chart, a formula, a takeaway, a footnote, the number of the slide the
user asked for (`spec_ref`) and two other forms of the slide (`alternatives`). The compiler, deterministically and
without a model:

- keeps the user's slides in the user's order and number when the brief describes them («Слайд 1…10»): a slide the
  designer did not send is built from the brief's own text (`fallback_slide`), a repeated one goes, a slide nobody
  asked for goes; a cover is added when no slide is one and the user's count leaves room for it;
- gives every slide what the user asked for on it and the designer left out: the formula («Покажи формулу: …»), the
  footnote («Укажи, что …»), the takeaway («Вывод: …»), the chart and its type («Нужна круговая диаграмма …») with the
  brief's data (BriefStructure.series), the table («Сделай сравнительную таблицу …»);
- varies the forms: more than two slides of one kind in a row → a slide takes one of its alternatives that fits
  (`apply_alternative`), never a slide whose chart or table the user asked for;
- turns the data written into charts into registry series (ids `s_<slide id>_<n>`, the chart's `series_ids`), so the
  renderer, the audit and grounding see one set of data;
- sets the deck's title and subtitle from the brief («Название: …», «Подзаголовок: …»), puts the goal line of the cover
  the brief describes («Главная цель: увеличить …») under the subtitle as «Цель: увеличить …» (content.paragraphs[0],
  the renderer's line under the subtitle) and the brief's disclaimer («Все исходные данные и прогнозы условные») on the
  cover as a footnote;
- keeps the user's formula's figures and operators, its factors named as the slide's text names them («100 покупок
  в день × 300 ₽ × 30 рабочих дней = 900 000 ₽» of «100 × 300 × 30 = 900 000 рублей»);
- then grounds the deck in the brief (grounding.ground_outline with the structure: chart values rounded as the brief
  allows, the user's slides never dropped) and fills a slide of the user's that grounding left empty from the
  brief's text.

What it did goes to `DeckOutline.agent_log` in plain Russian (and to `progress` as agent events of the «compile»
step); the warning lines it returns are for the run's manifest.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Union

from verstka.planning import heuristics as H
from verstka.planning.grounding import BriefIndex, PAST_CHANGE_RE, figures, ground_outline, inline_ok, rounding_step, to_future, unit_scale, unquote
from verstka.planning.outline import MAX_BULLETS, MAX_ITEMS, MAX_NUMBERS
from verstka.planning.plan_json import ALLOWED_KINDS, FRAME_KINDS, has_body
from verstka.ru import ru_count
from verstka.schemas.brief_structure import BriefStructure, ChartRequest, SlideSpec
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import (
    Brief,
    ChartSpec,
    DeckOutline,
    InlineSeries,
    NumberCallout,
    OutlineSlide,
    Series,
    SlideAlternative,
    SlideContent,
    SlideItem,
)

Progress = Callable[[dict], None]

_FRAMES = {K(k) for k in FRAME_KINDS}
_ITEM_KINDS = {K.cards, K.process, K.timeline, K.team}
_COLUMN_KINDS = {K.two_column, K.comparison}
_LINE_KINDS = {K.bullets, K.image_text}
# the fields that make a slide's form: they go with the form when the slide takes another one
_PRIMARY: dict[K, tuple[str, ...]] = {
    K.chart: ("chart", "chart2"),
    K.table: ("table",),
    K.stat_row: ("numbers",),
    K.big_number: ("numbers",),
    K.cards: ("items",),
    K.process: ("items",),
    K.timeline: ("items",),
    K.team: ("items",),
    K.two_column: ("columns",),
    K.comparison: ("columns",),
    K.bullets: ("bullets", "paragraphs"),
    K.image_text: ("bullets", "paragraphs"),
    K.quote: ("quote", "quote_author"),
}
_CHART_FAMILY = {"pie": "pie", "doughnut": "pie", "column": "column", "bar": "column", "line": "line", "area": "line"}
_KIND_RU = {
    K.bullets: "короткий список", K.cards: "карточки", K.two_column: "две колонки", K.big_number: "крупная цифра",
    K.stat_row: "ряд крупных цифр", K.comparison: "сравнение", K.timeline: "шкала времени", K.process: "шаги",
    K.table: "таблица", K.chart: "диаграмма", K.image_text: "текст с картинкой", K.team: "команда", K.quote: "цитата",
}
_CHART_RU = {"pie": "круговая диаграмма", "doughnut": "кольцевая диаграмма", "column": "столбчатая диаграмма", "bar": "горизонтальная столбчатая диаграмма", "line": "линейный график", "area": "график с областями"}
# a line of a slide's description in the brief that tells what to do rather than what to say
_INSTRUCTION_RE = re.compile(
    r"^(?:покажи|сделай|нужн[аоыи]?|укажи|используй|выдели|добавь|предложи|отметь|вынеси|не\s|разовые\s+вложения\s+показывай"
    r"|название\s*:|подзаголовок\s*:|финальный\s+вывод\s*:|вывод\s*:)",
    re.I,
)
_COVER_RE = re.compile(r"титул|обложк|cover|title", re.I)


# ------------------------------------------------------------------ helpers


def _kind(value: Any) -> Optional[K]:
    k = str(getattr(value, "value", value) or "").strip().lower().replace(" ", "_").replace("-", "_")
    return K(k) if k in ALLOWED_KINDS else None


def _lines(c: SlideContent) -> list[str]:
    return [x for x in c.bullets + c.paragraphs if x.strip()]


def _num(v: float) -> str:
    """27000 → «27 000», 13.3 → «13,3»: a chart's value as a person writes it."""
    v = round(float(v), 6)
    if v.is_integer():
        return f"{int(v):,}".replace(",", " ")
    return f"{v:.6f}".rstrip("0").rstrip(".").replace(".", ",")


def _with_unit(v: float, unit: Optional[str]) -> str:
    u = (unit or "").strip()
    if not u:
        return _num(v)
    return f"{_num(v)}{u}" if u == "%" else f"{_num(v)} {u}"


def _has_data(ch: Optional[ChartSpec], registry: dict[str, Series]) -> bool:
    return ch is not None and (any(ser.values for ser in ch.series) or any(i in registry for i in ch.series_ids))


def _guess_type(series: list[Series]) -> str:
    """A chart type for data the user did not name a chart for: shares of a whole → pie, a run over time → line,
    anything else → columns."""
    s = series[0]
    n = len(s.values)
    unit = (s.unit or "").strip()
    if len(series) == 1 and 2 <= n <= 7 and all(v >= 0 for v in s.values) and (unit == "%" and 95 <= sum(s.values) <= 105):
        return "pie"
    if n >= 5:
        return "line"
    return "column"


def _is_cover(spec: SlideSpec) -> bool:
    return bool(_COVER_RE.search(spec.title or ""))


def _spec_lines(text: str) -> list[str]:
    """What a slide's description in the brief says, line by line (sentence by sentence in a paragraph), without the
    instructions («Покажи …», «Нужна круговая диаграмма …») and the lead-ins («Ежемесячные расходы:»)."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("—–-•*·").strip()
        for sn in H.split_sentences(line) or [line]:
            t = sn.strip().rstrip(";.").strip()
            if not t or t.endswith(":") or _INSTRUCTION_RE.match(t):
                continue
            out.append(t[:1].upper() + t[1:])
    return out


_FORMULA_OP_RE = re.compile(r"[×x*хX·+\-−–÷/=]")


def formula_terms(text: Optional[str]) -> tuple[tuple[float, ...], tuple[str, ...]]:
    """The figures of a formula and the operators between them, whatever words label them: «100 покупок в день ×
    300 ₽ × 30 дней = 900 000 ₽» and «100 × 300 × 30 = 900 000 рублей» are the same calculation."""
    t = " ".join((text or "").split())
    figs = [f for f in figures(t) if f.date is None]
    vals = tuple(round(f.mag if f.scale != 1.0 else f.value, 6) for f in figs)
    ops = []
    for a, b in zip(figs, figs[1:]):
        found = _FORMULA_OP_RE.findall(t[a.end : b.start])
        ops.append("=" if "=" in found else (found[-1] if found else ""))
    norm = {"x": "×", "х": "×", "X": "×", "*": "×", "·": "×", "−": "-", "–": "-", "÷": "/"}
    return vals, tuple(norm.get(o, o) for o in ops)


def same_formula(a: Optional[str], b: Optional[str]) -> bool:
    ta, tb = formula_terms(a), formula_terms(b)
    return bool(ta[0]) and ta == tb


_RUB_RE = re.compile(r"(?<![\wё])(?:рубл(?:ей|я|ь)|руб\.?)(?![\wё])", re.I)


def label_formula(formula: Optional[str], source: str) -> Optional[str]:
    """The user's formula with its factors named as the slide's source names them: «100 × 300 × 30 = 900 000 рублей»
    over «— 100 покупок в день; — средний чек — 300 рублей; — 30 рабочих дней в расчетном месяце» → «100 покупок в
    день × 300 ₽ × 30 рабочих дней = 900 000 ₽». A factor keeps what the formula writes when the source gives it no
    words of its own; the formula is returned as it is when no factor gets a name."""
    t = " ".join((formula or "").split()).rstrip(".")
    if not t or "=" not in t:
        return formula
    figs = [f for f in figures(t) if f.date is None]
    lines = [H.strip_end(ln.strip().lstrip("—–-•*·").strip()) for ln in (source or "").splitlines() if ln.strip()]
    lines = [x for ln in lines for x in re.split(r";\s+", ln)]
    out, pos, named = [], 0, 0
    eq = t.index("=")
    for f in figs:
        out.append(t[pos : f.start])
        times = f.unit == "times"  # «100 ×» reads as a multiple: the operator after it is not its unit
        end = f.end if times else f.uend
        word = t[f.start : end]
        pos = end
        if f.start > eq or (f.unit is not None and not times) or (not times and t[f.end : f.uend].strip()):
            out.append(word)
            continue
        label = None
        for ln in lines:
            for g in figures(ln):
                if g.date is not None or abs(g.value - f.value) > 1e-9 or g.scale != f.scale:
                    continue
                tail = ln[g.uend :]
                words = re.match(r"\s+((?:[а-яё]+\s+){0,3}?[а-яё]{3,})(?=\s*(?:$|[,;.(]|\s(?:в|на)\s+(?:расч|месяц|среднем)))", tail, re.I)
                if g.unit is None and words and not re.match(r"\s*(?:—|–|-|:)", tail):
                    label = f"{ln[g.start : g.uend].strip()} {words.group(1).strip()}"
                elif g.unit is not None:
                    label = ln[g.start : g.uend].strip()
                if label:
                    break
            if label:
                break
        if label:
            named += 1
            out.append(label)
        else:
            out.append(word)
    out.append(t[pos:])
    if not named:
        return formula
    return _RUB_RE.sub("₽", "".join(out)).replace(" ₽", " ₽")


def _item_of(line: str) -> SlideItem:
    """«Витрина для десертов — 70 000 рублей» → a card «Витрина для десертов» with «70 000 рублей»."""
    m = re.match(r"^(?P<t>[^:—–]{2,60}?)\s*(?::|\s[—–]\s)\s*(?P<x>.+)$", line)
    if m:
        return SlideItem(title=m.group("t").strip(), text=m.group("x").strip())
    return SlideItem(title=line.strip())


def _line_of(it: SlideItem) -> str:
    head = it.title.strip()
    body = (it.text or "").strip() or "; ".join(it.bullets)
    if it.number and it.number not in f"{head} {body}":
        body = f"{it.number} {body}".strip()
    return f"{head} — {body}" if head and body else head or body


# ------------------------------------------------------------------ alternatives


def _convert(c: SlideContent, old: K, new: K) -> Optional[SlideContent]:
    """The slide's own content in another form, when it can be shown so without a model; None when it cannot."""
    c = c.model_copy(deep=True)
    lines = _lines(c)
    if new in _ITEM_KINDS:
        if old in _ITEM_KINDS:
            return c
        if old in _COLUMN_KINDS and len(c.columns) >= 2:
            c.items, c.columns = c.columns, []
            return c
        if 2 <= len(lines) <= MAX_ITEMS:
            c.items, c.bullets, c.paragraphs = [_item_of(x) for x in lines], [], []
            if old == K.chart:
                c.chart = c.chart2 = None
            return c
        return None
    if new in _LINE_KINDS:
        if old in _ITEM_KINDS and c.items:
            c.bullets, c.items = [_line_of(it) for it in c.items][:MAX_BULLETS], []
            return c
        if old in _COLUMN_KINDS and c.columns:
            c.bullets = [f"{col.title}: {'; '.join(col.bullets) or col.text}".strip(": ") for col in c.columns][:MAX_BULLETS]
            c.columns = []
            return c
        if old in (K.stat_row, K.big_number) and c.numbers:
            c.bullets = [f"{n.value} — {n.label}" if n.label else n.value for n in c.numbers] + lines
            c.numbers, c.paragraphs = [], []
            return c
        if lines:
            if old == K.chart:
                c.chart = c.chart2 = None
            return c
        return None
    if new in (K.stat_row, K.big_number):
        if c.numbers:
            return c
        ch = c.chart
        if old == K.chart and ch is not None and c.chart2 is None and len(ch.series) == 1 and ch.categories:
            vals = ch.series[0].values
            name = ch.series[0].name or ch.title or ""
            if len(vals) == 2 and new == K.big_number:
                c.numbers = [NumberCallout(value=f"{_num(vals[0])} → {_with_unit(vals[1], ch.unit)}", label=name)]
            elif 2 <= len(vals) <= min(4, MAX_NUMBERS) and new == K.stat_row:
                c.numbers = [NumberCallout(value=_with_unit(v, ch.unit), label=str(cat)) for cat, v in zip(ch.categories, vals)]
            else:
                return None
            c.chart = None
            return c
        return None
    if new in _COLUMN_KINDS:
        if old in _COLUMN_KINDS:
            return c
        if old in _ITEM_KINDS and 2 <= len(c.items) <= 3 and all(it.text or it.bullets for it in c.items):
            c.columns, c.items = c.items, []
            return c
        return None
    if new == K.chart:
        return c if c.chart is not None else None
    if new == K.table:
        return c if c.table is not None else None
    return None


def _fits(s: OutlineSlide) -> bool:
    c, k = s.content, s.kind
    if k == K.chart:
        return c.chart is not None and (bool(c.chart.series) or bool(c.chart.series_ids))
    if k == K.table:
        return c.table is not None and bool(c.table.rows)
    if k == K.stat_row:
        return 2 <= len(c.numbers) <= MAX_NUMBERS
    if k == K.big_number:
        return len(c.numbers) == 1 or (not c.numbers and bool((c.formula or "").strip()))
    if k in _ITEM_KINDS:
        return 2 <= len(c.items) <= MAX_ITEMS
    if k in _COLUMN_KINDS:
        return len(c.columns) >= 2
    if k in _LINE_KINDS:
        return bool(_lines(c))
    if k == K.quote:
        return bool(c.quote)
    return False


def _pinned(spec: Optional[SlideSpec]) -> bool:
    """A slide whose chart or table the user asked for keeps its form."""
    return spec is not None and bool(spec.charts or spec.table)


def _keeps_requests(s: OutlineSlide, spec: Optional[SlideSpec]) -> bool:
    if spec is None:
        return True
    if spec.charts and (s.kind != K.chart or s.content.chart is None):
        return False
    if spec.table and s.content.table is None:
        return False
    return not (spec.formula and not (s.content.formula or "").strip())


def apply_alternative(slide: OutlineSlide, alt: Union[SlideAlternative, dict], spec: Optional[SlideSpec] = None) -> Optional[OutlineSlide]:
    """The slide in one of the other forms its designer proposed (a copy), or None when that form does not fit: the
    kind is unknown or a frame, the alternative brings no content and the slide's own cannot be shown so (a list as
    cards, a before/after chart as «A → B», cards as a list …), the result is not a full slide of that kind, or it
    loses what the user asked for on it (`spec`). The form it had becomes one of its alternatives. The orchestrator may
    use it for the variants (the visual one prefers forms that show more)."""
    a = alt if isinstance(alt, SlideAlternative) else SlideAlternative.model_validate(alt)
    new_kind = _kind(a.kind)
    if new_kind is None or new_kind in _FRAMES or new_kind == slide.kind:
        return None
    new = slide.model_copy(deep=True)
    if a.content is not None and a.content.model_fields_set:
        given = a.content.model_fields_set
        data = new.content.model_dump()
        for f in given:
            data[f] = getattr(a.content, f).model_dump() if hasattr(getattr(a.content, f), "model_dump") else getattr(a.content, f)
        for f in _PRIMARY.get(slide.kind, ()):
            if f not in given and f not in _PRIMARY.get(new_kind, ()):
                data[f] = SlideContent.model_fields[f].get_default(call_default_factory=True)
        new.content = SlideContent.model_validate(data)
    else:
        content = _convert(new.content, slide.kind, new_kind)
        if content is None:
            return None
        new.content = content
    new.kind = new_kind
    if not _fits(new) or not _keeps_requests(new, spec):
        return None
    if a.change.strip():
        new.rationale = a.change.strip()
    was = SlideAlternative(kind=slide.kind.value, change=slide.rationale or "")
    new.alternatives = [x for x in slide.alternatives if x is not alt and _kind(x.kind) != new_kind] + [was]
    return new


def _run_len(kinds: list[Optional[K]], j: int, k: K) -> int:
    """The length of the run of kind `k` through position j, with slide j of kind k."""
    n, i = 1, j - 1
    while i >= 0 and kinds[i] == k:
        n, i = n + 1, i - 1
    i = j + 1
    while i < len(kinds) and kinds[i] == k:
        n, i = n + 1, i + 1
    return n


# ------------------------------------------------------------------ fallback


def fallback_slide(spec: SlideSpec, structure: BriefStructure, slide_id: Optional[str] = None) -> OutlineSlide:
    """A slide the user asked for, built from the brief without a model: the charts and the table it asks for with the
    brief's data, its formula, footnote and takeaway, and the lines of its description (not the instructions) as a
    short list. Used when the designer sent nothing for it, and to fill a slide grounding left empty."""
    sid = slide_id or f"sl{spec.number}"
    title = unquote(spec.title) or f"Слайд {spec.number}"
    if _is_cover(spec):
        return OutlineSlide(
            id=sid, kind=K.title, headline=unquote(structure.title) or title, subtitle=unquote(structure.subtitle) or None,
            spec_ref=spec.number, rationale="Титульный слайд, как в брифе.",
        )
    reg = {x.id: x for x in structure.series}
    charts: list[ChartSpec] = []
    used: set[str] = set()
    for req in spec.charts[:2]:
        ids = [i for i in req.series_ids if i in reg] or [i for i in spec.series_ids if i in reg and i not in used][:1]
        if not ids:
            continue
        used.update(ids)
        first = reg[ids[0]]
        charts.append(ChartSpec(type=req.type or _guess_type([reg[i] for i in ids]), series_ids=ids, unit=first.unit, title=(req.what or first.name or None)))
    c = SlideContent()
    if charts:
        c.chart = charts[0]
        c.chart2 = charts[1] if len(charts) > 1 else None
    if spec.table and spec.table_ids and 0 <= spec.table_ids[0] < len(structure.tables):
        c.table = structure.tables[spec.table_ids[0]].model_copy(deep=True)
    if spec.formula:
        c.formula = (label_formula(spec.formula, spec.text) or spec.formula).strip().rstrip(".")
    lines = _spec_lines(spec.text)
    if c.chart is not None or c.table is not None:
        c.bullets = [x for x in lines if len(x.split()) <= 16][:3]  # the chart shows the figures; a few short lines
        kind = K.chart if c.chart is not None else K.table
    elif lines:
        c.bullets = [H.short(x, 18) for x in lines[:MAX_BULLETS]]
        kind = K.bullets
    else:
        kind = K.big_number if c.formula else K.bullets
    return OutlineSlide(
        id=sid, kind=kind, headline=title, content=c, takeaway=unquote(spec.takeaway) or None, footnote=spec.footnote or None,
        spec_ref=spec.number, rationale="Слайд собран по тексту брифа без модели.",
    )


# ------------------------------------------------------------------ the compiler


class _Run:
    """The compiler's report: warning lines (English, for the manifest) and what the agent did (Russian, for the
    user) — both to the outline's agent_log and to `progress`."""

    def __init__(self, o: DeckOutline, progress: Optional[Progress]) -> None:
        self.o, self.progress = o, progress
        self.warnings: list[str] = []

    def warn(self, line: str) -> None:
        self.warnings.append(f"compile: {line}")

    def say(self, message: str, slide: Optional[OutlineSlide] = None) -> None:
        # the log line names its step («Сборка: …», like «Аналитик: …» of the agent); the event does not: the
        # timeline shows it under its step
        self.o.agent_log.append(f"Сборка: {message[:1].lower() + message[1:] if message[1:2].islower() else message}")
        if self.progress is not None:
            pos = next((i + 1 for i, s in enumerate(self.o.slides) if s is slide), None) if slide is not None else None
            try:
                self.progress({"type": "agent", "step": "compile", "message": message, "slide": pos, "variant": self.o.strategy or None})
            except Exception:  # a broken progress sink never stops the deck
                pass


def _name(s: OutlineSlide) -> str:
    h = " ".join((s.headline or "").split())
    return f"«{h if len(h) <= 60 else h[:59] + '…'}»"


def _registry(o: DeckOutline, structure: BriefStructure) -> None:
    """The brief's data (the analyst's series and tables) joins the deck's registry."""
    have = {x.id for x in o.series}
    o.series.extend(x.model_copy(deep=True) for x in structure.series if x.id not in have)
    for t in structure.tables:
        if not any(t.columns == u.columns and t.rows == u.rows for u in o.tables):
            o.tables.append(t.model_copy(deep=True))


def _unique_ids(slides: list[OutlineSlide]) -> None:
    seen: set[str] = set()
    for i, s in enumerate(slides, 1):
        sid = re.sub(r"[^\w\-]+", "_", (s.id or "").strip()) or f"sl{s.spec_ref or i}"
        base, n = sid, 2
        while sid in seen:
            sid, n = f"{base}_{n}", n + 1
        s.id = sid
        seen.add(sid)


def _order(o: DeckOutline, structure: BriefStructure, run: _Run, count: Optional[int] = None) -> None:
    """The user's slides in the user's order and number; a cover when none is one and the count leaves room (a deck
    the architect planned gets its cover here too, so the disclaimer has its place)."""
    specs = {sp.number: sp for sp in structure.specs}
    if not specs:
        if o.slides and o.slides[0].kind != K.title:
            o.slides.insert(0, OutlineSlide(id="cover", kind=K.title, headline=o.title, subtitle=o.subtitle))
            _unique_ids(o.slides)
        return
    by_spec: dict[int, OutlineSlide] = {}
    cover: Optional[OutlineSlide] = None
    closing: Optional[OutlineSlide] = None
    extra: list[OutlineSlide] = []
    for s in o.slides:
        if s.spec_ref in specs:
            if s.spec_ref in by_spec:
                run.warn(f"slide {s.id}: a second slide for the brief's slide {s.spec_ref} dropped")
                continue
            by_spec[s.spec_ref] = s
        elif s.kind == K.title and cover is None and s.spec_ref is None:
            cover = s
        elif s.kind == K.thanks and s.spec_ref is None:
            closing = s
        else:
            extra.append(s)
    slides: list[OutlineSlide] = []
    missing: list[OutlineSlide] = []
    for n in sorted(specs):
        s = by_spec.get(n)
        if s is None:
            s = fallback_slide(specs[n], structure)
            missing.append(s)
            run.warn(f"the brief's slide {n} had no designed slide: built from the brief's text")
        elif _is_cover(specs[n]) and s.kind != K.title:
            s.kind = K.title
        slides.append(s)
    # the brief's own «на 10 слайдов» is a hard count: no cover beyond it. The request's count (the form always sends
    # one, 5 at least) only keeps a closing slide out: a brief that describes five slides and none of them a cover
    # gets its title slide, a brief of ten slides with its own cover gets no «Спасибо» as an eleventh
    hard = structure.slide_count
    limit = hard or count
    n_specs = len(slides)
    added_cover = slides[0].kind != K.title and (hard is None or len(slides) < hard)
    if added_cover:
        slides.insert(0, cover or OutlineSlide(id="cover", kind=K.title, headline=o.title, subtitle=o.subtitle))
    if closing is not None and (limit is None or len(slides) < limit):
        slides.append(closing)
    for s in extra:
        run.warn(f"slide {s.id} «{s.headline[:60]}» dropped: the brief describes its slides and this is not one of them")
    o.slides = slides
    _unique_ids(o.slides)
    in_order = f"{ru_count(n_specs, 'слайд', 'слайда', 'слайдов')} в том порядке, который задан в брифе"
    if added_cover:
        # the user's «Слайд 1» is the deck's second: say so, and how many slides the deck has
        run.say(f"Собрал {in_order}, и добавил перед ними титульный слайд с названием: всего {ru_count(len(slides), 'слайд', 'слайда', 'слайдов')}.")
    else:
        run.say(f"Собрал {in_order}.")
    for s in missing:
        run.say(f"Слайд {_name(s)} модель не прислала — собрал его из текста брифа.", s)


def _match(charts: list[ChartSpec], reqs: list[ChartRequest]) -> tuple[list[tuple[ChartSpec, ChartRequest]], list[ChartRequest]]:
    """Pairs of the slide's charts and the charts the user asked for: the same kind first, then in order."""
    left = list(reqs)
    pairs: list[tuple[ChartSpec, ChartRequest]] = []
    free: list[ChartSpec] = []
    for ch in charts:
        r = next((r for r in left if r.type and _CHART_FAMILY.get(r.type) == _CHART_FAMILY.get(ch.type)), None)
        if r is not None:
            left.remove(r)
            pairs.append((ch, r))
        else:
            free.append(ch)
    for ch in free:
        if left:
            pairs.append((ch, left.pop(0)))
    return pairs, left


def _requests(o: DeckOutline, structure: BriefStructure, idx: BriefIndex, run: _Run) -> None:
    """What the user asked for on a slide and the designer left out: formula, footnote, takeaway, the charts (their
    type and the brief's data — also instead of data the designer wrote that is not the brief's) and the table."""
    specs = {sp.number: sp for sp in structure.specs}
    reg = {x.id: x for x in o.series}
    step = rounding_step(structure.rounding)
    for s in o.slides:
        spec = specs.get(s.spec_ref) if s.spec_ref is not None else None
        if spec is None or s.kind in _FRAMES:
            continue
        c = s.content
        if spec.formula and not same_formula(c.formula, spec.formula):
            # the user's calculation; its factors named as the slide's text names them (the words may differ, the
            # figures and the operators never)
            had = bool((c.formula or "").strip())
            c.formula = (label_formula(spec.formula, spec.text) or spec.formula).strip().rstrip(".")
            run.say(f"Слайд {_name(s)}: " + ("формула — как в брифе." if had else "добавил формулу из брифа."), s)
        if spec.footnote and not (s.footnote or "").strip():
            s.footnote = spec.footnote.strip()
        if spec.takeaway and not (s.takeaway or "").strip():
            s.takeaway = unquote(spec.takeaway)
        if spec.charts:
            charts = [x for x in (c.chart, c.chart2) if x is not None]
            pairs, left = _match(charts, spec.charts[:2])
            # the brief's series of this slide no chart shows yet (a chart with its data written in shows its own)
            shown = [list(ser.values) for ch in charts for ser in ch.series]
            spare = [i for i in spec.series_ids if i in reg and list(reg[i].values) not in shown]
            for ch, req in pairs:
                if req.type and _CHART_FAMILY.get(req.type) != _CHART_FAMILY.get(ch.type):
                    run.warn(f"slide {s.id}: chart type {ch.type} → {req.type} (the brief asks for it)")
                    ch.type = req.type
                    run.say(f"Слайд {_name(s)}: {_CHART_RU.get(req.type, 'диаграмма')}, как просили в брифе.", s)
                invented = bool(ch.series) and (not inline_ok(ch, idx, step) or _swapped(ch, structure))
                if invented or not _has_data(ch, reg):
                    ids = [i for i in req.series_ids if i in reg] or spare[:1]
                    if ids:
                        ch.series_ids, ch.categories, ch.series = ids, [], []
                        # the brief's values in full: a unit that counts in thousands would misread them
                        ch.unit = reg[ids[0]].unit or (ch.unit if unit_scale(ch.unit) == 1.0 else None)
                        why = "numbers not in the brief" if invented else "no data"
                        run.warn(f"slide {s.id}: chart with {why} takes the brief's series {', '.join(ids)}")
                        run.say(f"Слайд {_name(s)}: " + ("в диаграмме были числа не из брифа" if invented else "у диаграммы не было данных") + " — взял данные из брифа.", s)
                for i in ch.series_ids:
                    if i in spare:
                        spare.remove(i)
            for req in left:
                ids = [i for i in req.series_ids if i in reg] or spare[:1]
                if not ids:
                    run.warn(f"slide {s.id}: the chart the brief asks for («{req.what[:60]}») has no data in the brief")
                    continue
                for i in ids:
                    if i in spare:
                        spare.remove(i)
                ch = ChartSpec(type=req.type or _guess_type([reg[i] for i in ids]), series_ids=ids, unit=reg[ids[0]].unit, title=req.what or reg[ids[0]].name or None)
                if c.chart is None:
                    c.chart = ch
                elif c.chart2 is None:
                    c.chart2 = ch
                else:
                    continue
                run.warn(f"slide {s.id}: the chart the brief asks for added ({ch.type}, series {', '.join(ids)})")
                run.say(f"Слайд {_name(s)}: добавил {_CHART_RU.get(ch.type, 'диаграмму')}, которую просили в брифе.", s)
            if c.chart is not None and s.kind != K.chart:
                s.kind = K.chart
        if spec.table and c.table is None and spec.table_ids and 0 <= spec.table_ids[0] < len(structure.tables):
            c.table = structure.tables[spec.table_ids[0]].model_copy(deep=True)
            if s.kind != K.chart:
                s.kind = K.table
            run.say(f"Слайд {_name(s)}: добавил таблицу из брифа.", s)


def _swapped(ch: ChartSpec, structure: BriefStructure) -> bool:
    """The chart draws the brief's figures under other labels than the brief's («Продукты» at 270 000 when the brief's
    «Продукты» is 315 000): as wrong as invented figures."""
    try:
        from verstka.planning.agent import _similar_data, chart_of, label_conflicts
    except Exception:  # noqa: BLE001
        return False
    for s in structure.series:
        want = chart_of([s])
        if want is not None and ch.series and _similar_data(want, ch) and label_conflicts(want, ch):
            return True
    return False


# a forecast or a target told as done: «Операционная прибыль выросла почти в 2,1 раза» over a «Цель» column
def _tense_guard(o: DeckOutline, structure: BriefStructure, idx: BriefIndex, run: _Run) -> None:
    """A plan, a target or a forecast is never told as done, and a hedge is on the true value's side: every line of a
    content slide whose figure the brief gives as a plan (a «Цель» / «Прогноз» value, a sentence with «составит»,
    «вырастет», «к шестому месяцу», or a change of such a value) says it in the future tense («выросла» → «вырастет»);
    on a slide whose source speaks only of the plan, so does a line without a figure. «почти в 2,1 раза» of 2,12 →
    «более чем в 2,1 раза». The brief's own rule «Не представляй прогноз как гарантию» makes this stricter, never
    looser."""
    specs = {sp.number: sp for sp in structure.specs}
    changed: list[str] = []
    for s in o.slides:
        if s.kind in _FRAMES:
            continue
        spec = specs.get(s.spec_ref) if s.spec_ref is not None else None
        src = (spec.text if spec else "") or ""
        plan_only = bool(re.search(r"цел[ьи]|прогноз|план|к\s+\S+\s+месяцу|планир|составит|вырастет|достигнет", f"{spec.title if spec else ''} {src}", re.I)) and not re.search(
            r"(?<![\wё])(?:сейчас|текущ|нынешн|исходн)\w*\s+(?:показател|выручк|прибыл|расход)", src, re.I
        )

        def fix(text: Optional[str], lenient_plan: bool = True) -> Optional[str]:
            if not text:
                return text
            new = idx.fix_hedges(text)
            if PAST_CHANGE_RE.search(new) and (idx.forecast_line(new) or (lenient_plan and plan_only and not figures(new))):
                new = to_future(new)
            if new != text:
                changed.append(f"«{text[:70]}» → «{new[:70]}»")
            return new

        s.headline = fix(s.headline) or s.headline
        s.subtitle = fix(s.subtitle)
        s.takeaway = fix(s.takeaway) if not (spec and spec.takeaway and s.takeaway and s.takeaway.strip() == unquote(spec.takeaway)) else s.takeaway
        c = s.content
        c.bullets = [fix(b) or b for b in c.bullets]
        c.paragraphs = [fix(b) or b for b in c.paragraphs]
        for it in [*c.items, *c.columns]:
            it.title = fix(it.title) or it.title
            it.text = fix(it.text) or it.text
            it.bullets = [fix(b) or b for b in it.bullets]
        for n in c.numbers:
            n.label = fix(n.label) or n.label
    if changed:
        run.warn("tense: forecasts told as done → future, hedges turned: " + "; ".join(changed[:6]))
        run.say(f"Прогнозы и цели — в будущем времени, как план, а не как достигнутый результат ({ru_count(len(changed), 'правка', 'правки', 'правок')}).")


def _undated_axis(s: OutlineSlide) -> bool:
    """A time axis whose steps are not all dates (writer.date_start): not one (gate 3 W3-6: «К месту прибыли военные…»
    as step 1 of 4)."""
    if s.kind not in (K.timeline,) or not s.content.items:
        return False
    from verstka.planning.writer import date_start

    return not all(date_start(it.title or "") for it in s.content.items)


def _variety(o: DeckOutline, structure: BriefStructure, run: _Run, written: bool = False) -> None:
    """More than two slides of one kind in a row: a slide of the run takes one of its alternatives that fits (the
    third first, then the second), never one whose chart or table the user asked for. `written` (writer mode): never a
    timeline of undated steps."""
    specs = {sp.number: sp for sp in structure.specs}
    slides = o.slides
    for i in range(2, len(slides)):
        k = slides[i].kind
        if k in _FRAMES or not (slides[i - 1].kind == k and slides[i - 2].kind == k):
            continue
        for j in (i, i - 1):
            s = slides[j]
            spec = specs.get(s.spec_ref) if s.spec_ref is not None else None
            if _pinned(spec):
                continue
            kinds: list[Optional[K]] = [x.kind for x in slides]
            done = False
            for alt in s.alternatives:
                new = apply_alternative(s, alt, spec)
                if new is None or _run_len(kinds, j, new.kind) > 2 or (written and _undated_axis(new)):
                    continue
                slides[j] = new
                run.warn(f"slide {s.id}: {k.value} → {new.kind.value} (three slides of one kind in a row)")
                run.say(f"Слайд {_name(new)}: чтобы не было трёх одинаковых слайдов подряд, выбрал для него другую форму — {_KIND_RU.get(new.kind, 'другой вид')}.", new)
                done = True
                break
            if done:
                break


def _compile_charts(o: DeckOutline, run: _Run) -> int:
    """The data written into charts → registry series `s_<slide id>_<n>` and the charts' series_ids."""
    reg: dict[str, Series] = {x.id: x for x in o.series}
    made = 0
    for s in o.slides:
        n = 0
        gone = False
        for which in ("chart", "chart2"):
            ch: Optional[ChartSpec] = getattr(s.content, which)
            if ch is None or not ch.series:
                continue
            cats = [" ".join(str(x).split()) for x in ch.categories]
            sers = [x for x in ch.series if x.values]
            if ch.type in ("pie", "doughnut") and len(sers) > 1:
                run.warn(f"slide {s.id}: a {ch.type} chart shows one series; {len(sers) - 1} more dropped")
                sers = sers[:1]
            # 1 for every category is the designer counting the slide's items (three cards → 1, 1, 1), not data,
            # unless the brief itself has such a series
            ones = [x for x in sers if len(cats) >= 2 and _all_ones(x.values[: len(cats)])
                    and not any(r.values and _all_ones(r.values) for r in reg.values())]
            if ones:
                run.warn(f"slide {s.id}: {which} series {', '.join(f'«{x.name}»' for x in ones)} is 1 for every category: a count of items, not data; dropped")
                sers = [x for x in sers if x not in ones]
                if not sers:
                    setattr(s.content, which, None)
                    gone = True
                    continue
            ids: list[str] = []
            kept: list[InlineSeries] = []
            for ser in sers:
                m = min(len(cats), len(ser.values))
                if m < 1:
                    run.warn(f"slide {s.id}: {which} series «{ser.name}» without categories dropped")
                    continue
                if len(ser.values) != len(cats):
                    run.warn(f"slide {s.id}: {which} series «{ser.name}» has {len(ser.values)} values for {len(cats)} categories; cut to {m}")
                n += 1
                sid = f"s_{s.id}_{n}"
                reg[sid] = Series(id=sid, name=(ser.name or ch.title or s.headline or "").strip(), categories=cats[:m], values=list(ser.values[:m]), unit=ch.unit)
                ids.append(sid)
                kept.append(InlineSeries(name=ser.name, values=list(ser.values[:m])))
            if ids:
                ch.series_ids = ids
                ch.categories = reg[ids[0]].categories
                ch.series = kept
                made += len(ids)
            else:
                ch.series = []
        if gone:
            _unchart(s)
    o.series = list(reg.values())
    return made


def _all_ones(values: list[float]) -> bool:
    return bool(values) and all(float(v) == 1.0 for v in values)


def _unchart(s: OutlineSlide) -> None:
    """A chart slide whose charts went: the second chart takes the first's place, else the slide's own table, items or
    lines are its form (none of them: grounding's repair fills it from the brief)."""
    c = s.content
    if c.chart is None and c.chart2 is not None:
        c.chart, c.chart2 = c.chart2, None
    if s.kind != K.chart or c.chart is not None:
        return
    if c.table is not None and c.table.rows:
        s.kind = K.table
    elif 2 <= len(c.items) <= MAX_ITEMS:
        s.kind = K.cards
    elif _lines(c):
        s.kind = K.bullets


def _cover(o: DeckOutline, structure: BriefStructure, run: _Run) -> None:
    """The deck's title and subtitle from the brief; the disclaimer as the cover's footnote."""
    title = unquote(structure.title) if structure.title else ""
    sub = unquote(structure.subtitle) if structure.subtitle else ""
    if title and title != o.title:
        o.title = title
    if sub:
        o.subtitle = sub
    cover = o.slides[0] if o.slides and o.slides[0].kind == K.title else None
    if cover is not None:
        if title:
            cover.headline = title
        if sub:
            cover.subtitle = sub
        elif not cover.subtitle and o.subtitle:
            cover.subtitle = o.subtitle
    if title:
        run.say(f"Название презентации — как в брифе: «{title}».", cover)
    goal = cover_goal(structure, cover.spec_ref if cover is not None else None)
    if cover is not None and goal and not any(" ".join(x.split()).lower() == goal.lower() for x in cover.content.paragraphs):
        # «Главная цель: увеличить …» of the cover's description: a line under the subtitle, in the brief's words
        cover.content.paragraphs = [goal, *cover.content.paragraphs]
        run.say(f"На титульный слайд под подзаголовком добавил цель из брифа: «{goal}».", cover)
    d = " ".join((structure.disclaimer or "").split()).strip()
    target = cover or (o.slides[0] if o.slides else None)
    if d and target is not None:
        have = (target.footnote or "").strip()
        if d.lower().rstrip(".") not in have.lower():
            target.footnote = f"{have.rstrip('.')}. {d}" if have else d
        run.say(f"На {'титульный' if cover is not None else 'первый'} слайд мелким текстом добавил: «{d.rstrip('.')}».", target)


_GOAL_LINE_RE = re.compile(
    r"^\s*(?:[—–\-•*]\s*)?(?:главная|основная|ключевая)?\s*(?:цель|задача)(?!\s+(?:презентаци|доклад|выступлени|слайд))\s*[:—–]\s*(?P<g>\S.+?)\s*[.;]?\s*$",
    re.I,
)


def cover_goal(structure: BriefStructure, spec_ref: Optional[int] = None) -> Optional[str]:
    """The goal line of the cover the brief describes («Главная цель: увеличить ежемесячную операционную прибыль со
    120 000 до 255 000 рублей») as the cover shows it: «Цель: увеличить … рублей». None when the cover's description
    has none (the deck's purpose, «Цель презентации — …», is not a goal to show)."""
    specs = [sp for sp in structure.specs if (spec_ref is not None and sp.number == spec_ref) or (spec_ref is None and _is_cover(sp))]
    for sp in specs[:1]:
        for line in (sp.text or "").splitlines():
            m = _GOAL_LINE_RE.match(line)
            if m:
                g = m.group("g").strip().rstrip(".;")
                return f"Цель: {g[:1].lower() + g[1:] if g[1:2].islower() else g}" if len(g.split()) >= 2 else None
    return None


def _takeaway_guard(o: DeckOutline, structure: BriefStructure, run: _Run) -> None:
    """The last word on a slide's conclusion, once the deck is final: a takeaway that says the headline again goes —
    or, when it is the user's own conclusion («Вывод: …»), the headline gives way to the user's heading."""
    try:
        from verstka.planning.agent import adds_nothing, same_text
    except Exception:  # noqa: BLE001
        return
    specs = {sp.number: sp for sp in structure.specs}
    for s in o.slides:
        if s.kind in _FRAMES or not s.takeaway:
            continue
        if not (same_text(s.takeaway, s.headline) or adds_nothing(s.takeaway, s.headline)):
            continue
        spec = specs.get(s.spec_ref) if s.spec_ref is not None else None
        if spec is not None and spec.takeaway and same_text(s.takeaway, unquote(spec.takeaway)) and spec.title and not same_text(spec.title, s.takeaway):
            run.warn(f"slide {s.id}: the headline repeated the user's conclusion → the user's heading «{unquote(spec.title)[:60]}»")
            s.headline = unquote(spec.title)
        else:
            run.warn(f"slide {s.id}: the takeaway «{s.takeaway[:60]}» repeated the headline, dropped")
            s.takeaway = None


def _sync_charts(o: DeckOutline) -> None:
    """After grounding, the data written into a chart is exactly its registry series (the renderer draws the inline
    data when the ids name nothing, so no value grounding removed may stay there)."""
    reg = {x.id: x for x in o.series}
    for s in o.slides:
        for ch in (s.content.chart, s.content.chart2):
            if ch is None:
                continue
            got = [reg[i] for i in ch.series_ids if i in reg]
            if got:
                same = [x for x in got if x.categories == got[0].categories]
                ch.series_ids = [x.id for x in same]
                ch.categories = list(same[0].categories)
                ch.series = [InlineSeries(name=x.name, values=list(x.values)) for x in same]
            n = len(ch.categories)
            if ch.highlight_index is not None and not 0 <= ch.highlight_index < n:
                ch.highlight_index = None


def _repair(o: DeckOutline, structure: BriefStructure, run: _Run) -> bool:
    """A slide the user asked for that grounding left empty (or took away) is filled from the brief's text."""
    specs = {sp.number: sp for sp in structure.specs}
    if not specs:
        return False
    changed = False
    present = {s.spec_ref: s for s in o.slides if s.spec_ref is not None}
    for n in sorted(specs):
        s = present.get(n)
        if s is None:
            new = fallback_slide(specs[n], structure)
            after = max((i for i, x in enumerate(o.slides) if x.spec_ref is not None and x.spec_ref < n), default=0 if o.slides and o.slides[0].kind == K.title else -1)
            o.slides.insert(after + 1, new)
            run.warn(f"the brief's slide {n} was lost in grounding: built from the brief's text")
            run.say(f"Слайд {_name(new)} собрал заново из текста брифа.", new)
            changed = True
            continue
        if s.kind in _FRAMES:
            continue
        c = s.content
        if has_body(c.model_dump()) or (c.formula or "").strip() or c.chart2 is not None:
            continue
        fb = fallback_slide(specs[n], structure, s.id)
        s.kind, s.content = fb.kind, fb.content
        s.takeaway = s.takeaway or fb.takeaway
        s.footnote = s.footnote or fb.footnote
        s.rationale = fb.rationale
        run.warn(f"slide {s.id}: nothing of the designed content was the brief's; filled from the brief's text")
        run.say(f"Слайд {_name(s)}: в нём не осталось того, что есть в брифе, — заполнил его текстом брифа.", s)
        changed = True
    if changed:
        _unique_ids(o.slides)
    return changed


def _grounding_say(run: _Run, lines: list[str], o: Optional[DeckOutline] = None, idx: Optional[BriefIndex] = None) -> None:
    figs = [x for x in lines if "not in the brief" in x or "changes the brief does not state" in x or "another subject" in x]
    if figs:
        run.say("Сверил цифры с брифом: убрал то, чего в брифе нет, и цифры, подписанные не тем, к чему они относятся в брифе.")
    else:
        run.say("Сверил цифры с брифом: все числа взяты из брифа или посчитаны из его чисел.")
    derived = _derived_on(o, idx) if o is not None and idx is not None else []
    if derived:
        run.say("Посчитано из чисел брифа (проверьте): " + ", ".join(f"«{x}»" for x in derived[:8]) + ("…" if len(derived) > 8 else "") + ".")


def _derived_on(o: DeckOutline, idx: BriefIndex) -> list[str]:
    """The figures the slides show that the brief does not write as they are but that are computed from its figures
    (a difference, a percent change, a ratio): listed for the user to review."""
    out: list[str] = []
    for s in o.slides:
        c = s.content
        texts = [s.headline, s.subtitle or "", s.takeaway or "", *c.bullets, *c.paragraphs, *(f"{n.value} {n.label}" for n in c.numbers)]
        texts += [f"{it.title} {it.text}" for it in [*c.items, *c.columns]] + [b for col in c.columns for b in col.bullets]
        for t in texts:
            for f in figures(t or ""):
                if f.date is not None or f.approx:
                    continue
                if not idx._same(f) and idx.verdict(f) == "ok":
                    w = (t[f.start : f.uend]).strip()
                    if w and w not in out:
                        out.append(w)
    return out


def compile_outline(
    outline: DeckOutline,
    structure: BriefStructure,
    brief: Brief,
    *,
    ground: bool = True,
    progress: Optional[Progress] = None,
) -> tuple[DeckOutline, list[str]]:
    """The designer's slides as one grounded deck (see the module docstring) and the warning lines of what changed.
    `ground=False` leaves grounding to the caller (then `_sync_charts` is the caller's too: charts keep their data as
    compiled). `progress` receives the compile step's agent events."""
    o = outline.model_copy(deep=True)
    run = _Run(o, progress)
    _registry(o, structure)
    _unique_ids(o.slides)
    _order(o, structure, run, brief.slide_count)
    idx = BriefIndex.of(brief)
    use = getattr(idx, "use_structure", None)
    if callable(use):
        use(structure)
    _requests(o, structure, idx, run)
    written = False
    try:
        from verstka.planning.writer import is_written_text

        written = is_written_text(brief.text or "")
    except Exception:  # noqa: BLE001 - the writer's check or none
        written = False
    _variety(o, structure, run, written)
    try:
        from verstka.planning.agent import polish_case

        for s in o.slides:
            polish_case(s, brief.text)  # the lines another form made («Партнёрства: с пятью ближайшими офисами»)
    except Exception:  # noqa: BLE001 - capitals are cosmetics: the deck stands without them
        pass
    made = _compile_charts(o, run)
    if made:
        n = sum(1 for s in o.slides for ch in (s.content.chart, s.content.chart2) if ch is not None and ch.series_ids)
        run.say(f"Подготовил данные для диаграмм: {ru_count(n, 'диаграмма', 'диаграммы', 'диаграмм')}.")
    _cover(o, structure, run)
    _tense_guard(o, structure, idx, run)
    if not ground:
        return o, run.warnings
    log = list(o.agent_log)
    o, lines = ground_outline(o, brief, idx, structure=structure)
    o.agent_log = log  # grounding copies the outline; the log stays the compiler's
    run.o = o
    run.warnings.extend(lines)
    if _repair(o, structure, run):
        o, more = ground_outline(o, brief, idx, structure=structure)
        o.agent_log = list(run.o.agent_log)
        run.o = o
        run.warnings.extend(x for x in more if x not in run.warnings)
    _sync_charts(o)
    _takeaway_guard(o, structure, run)
    _grounding_say(run, run.warnings, o, idx)
    return o, run.warnings
