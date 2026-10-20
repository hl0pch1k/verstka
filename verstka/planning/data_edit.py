"""Правка слайда с данными по просьбе человека — по правилам, без модели (жюри 5, UI1: «итог Q3 к Q2 в процентах, выдели
падение» дал «Объектное хранилище — 64% выручки Q3», процентов и падения нет; «сделай слайд 3 короче» вернул прежнюю
подпись).

Что умеет:
- другая мера: изменение в % (к прошлому периоду, Q3 к Q2 — две колонки-среза одной величины), выполнение плана в %
  (колонки «План» и «Факт»), доли от итога; меру пересчитывает из значений слайда (`OutlineSlide.data` — данные файла);
- выделение: падение / рост / лидер / наименьшее / названная категория — подсветка категории на диаграмме;
- вид графика: столбцы ↔ полосы, круговая для долей одной величины (значения те же);
- заголовок-вывод и подпись под новую меру, со всеми числами — фактами слайда (`headline_facts`, их «откуда»);
- «короче»: подпись, которая повторяет заголовок и диаграмму, уходит; заголовок и строки — до первой мысли, без потери
  чисел, которых больше нигде на слайде нет.

Каждое новое число записано фактом слайда с объяснением, как посчитано: проверки данных (`data_text_ok`, аудит) видят
его как число данных, «Почему так» — откуда оно."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from verstka.schemas.outline import OutlineSlide

# ── что просит человек
_PCT_RE = re.compile(r"в\s+процент|процент|в\s*%|%", re.I)
_CHANGE_RE = re.compile(
    r"изменени|прирост|динамик|к\s+прошл|к\s+предыдущ|по\s+сравнению|относительно|против|"
    r"(?<![а-яё])к\s+(?:q\d|кв|[ivx]+\s+кв|\d\s*кв|январ|феврал|март|апрел|ма[ейя]|июн|июл|август|сентябр|октябр|ноябр|декабр|20\d\d)|"
    r"насколько\s+(?:вырос|упал|снизил|измени)|рост\w*\s+и\s+(?:паден|снижен)",
    re.I,
)
_PLAN_RE = re.compile(r"(?<![а-яё])к\s+план|от\s+плана|выполнени\w*\s+план|план\s+и\s+факт|факт\w*\s+(?:к|против|и)\s+план", re.I)
_SHARE_RE = re.compile(r"(?<![а-яё])(?:дол[яиюе]|долях|структур)", re.I)
_EMPH_RE = re.compile(r"(?<![а-яё])(?:выдели\w*|выделить|подсвет\w*|акцент\w*|отметь|покрась|сделай\s+заметн\w*)", re.I)
_FALL_RE = re.compile(r"паден|упал|упавш|просел|просад|снижени|снизил|сократил|минус|отстающ|хуже|не\s+выполн", re.I)
_RISE_RE = re.compile(r"(?<![а-яё])(?:рост\b|вырос|растущ|лидер|быстрее|лучш|больше\s+всех)", re.I)
_MIN_RE = re.compile(r"наименьш|меньше\s+всего|самый\s+маленьк|самое\s+маленьк|минимальн", re.I)
_MAX_RE = re.compile(r"наибольш|больше\s+всего|самый\s+больш|самое\s+больш|максимальн", re.I)
_WORDS_ONLY_RE = re.compile(r"заголов|подпис|вывод", re.I)
_COLUMN_RE = re.compile(r"вертикальн|столбц|столбик|столбч", re.I)
_BAR_RE = re.compile(r"горизонтальн|полос", re.I)
_PIE_RE = re.compile(r"кругов|пирог", re.I)
_SHORTER_RE = re.compile(r"короч|сократи|меньше\s+текст|покороче|лаконичн|сжат", re.I)
_TIME_CAT_RE = re.compile(
    r"^(?:q\d|[ivx]+\s*кв|\d\s*кв|кв|январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|(?:19|20)\d\d|\d{1,2}[./]\d{2,4}|недел|н\d)",
    re.I,
)
_PLAN_NAME_RE = re.compile(r"(?<![а-яё])(?:план|цел[ьи]|target|plan)", re.I)
_FACT_NAME_RE = re.compile(r"(?<![а-яё])(?:факт|actual)", re.I)
# величины, которые не складываются (среднее, доля, время, оценка): итог по ним не считается
_NOT_ADDITIVE_RE = re.compile(r"средн|медиан|дол[яи]|ставк|конверс|nps|sla|csat|балл|рейтинг|цен[аы]|время|мин\b|минут|час|дн[ейя]|%", re.I)


@dataclass
class Wish:
    """Что из просьбы — дело правил данных."""

    measure: Optional[str] = None  # "change" | "plan" | "share"
    highlight: Optional[str] = None  # "fall" | "rise" | "min" | "max" | "named"
    named: Optional[int] = None  # категория, названная в просьбе
    chart: Optional[str] = None  # "column" | "bar" | "pie"
    show: bool = False  # мера — на диаграмме (иначе — в заголовке и подписи, диаграмма прежняя)
    shorter: bool = False

    @property
    def any(self) -> bool:
        return bool(self.measure or self.highlight or self.chart or self.shorter)


def read_wish(request: str, s: OutlineSlide) -> Wish:
    """Просьба к слайду с данными, прочитанная правилами; пустая Wish — правилам здесь делать нечего."""
    from verstka.planning.slide_edit import emphasis_index

    t = " ".join((request or "").split())
    w = Wish()
    if not t or s.data is None:
        return w
    pct = bool(_PCT_RE.search(t))
    if _PLAN_RE.search(t):
        w.measure = "plan"
    elif _CHANGE_RE.search(t) or (pct and re.search(r"итог|вырос|упал|рост|паден|сниз", t, re.I)):
        w.measure = "change"
    elif _SHARE_RE.search(t) and pct or (_SHARE_RE.search(t) and re.search(r"покажи|доли", t, re.I)):
        w.measure = "share"
    elif pct:
        w.measure = "change"  # «в процентах» у двух срезов одной величины — изменение; без пары `apply` уточнит
    if _EMPH_RE.search(t):
        _, k, _ = emphasis_index(t, s)
        if k is not None:
            w.highlight, w.named = "named", k
        elif _FALL_RE.search(t):
            w.highlight = "fall"
        elif _MIN_RE.search(t):
            w.highlight = "min"
        elif _MAX_RE.search(t):
            w.highlight = "max"
        elif _RISE_RE.search(t):
            w.highlight = "rise"
    if w.highlight in ("fall", "rise") and w.measure is None:
        w.measure = "change"  # «выдели падение» — падение чего-то к чему-то: та же пара срезов
    if _PIE_RE.search(t):
        w.chart = "pie"
    elif _BAR_RE.search(t):
        w.chart = "bar"
    elif _COLUMN_RE.search(t):
        w.chart = "column"
    # the measure goes onto the chart when asked in it («в процентах», «покажи…»), unless only the words are asked
    # («заголовок — вывод: …»); «выдели падение» alone keeps the chart and its values, the fall highlighted
    explicit = bool(re.search(r"покажи|отобрази|на\s+(?:график|диаграмм)|пересчитай", t, re.I))
    w.show = bool(w.measure) and (pct or explicit or w.measure == "share") and (not _WORDS_ONLY_RE.search(t) or explicit)
    w.shorter = bool(_SHORTER_RE.search(t))
    return w


# ── числа и слова
def _num(x: float) -> str:
    from verstka.data.words import fmt_num

    return fmt_num(x)


def _pct(x: float) -> float:
    from verstka.data.words import round_pct

    return round_pct(x)


def _signed(x: float) -> str:
    from verstka.data.words import fmt_signed

    return fmt_signed(_pct(x), "%")


def _value(x: float, unit: Optional[str]) -> str:
    from verstka.data.words import fmt_value

    return fmt_value(x, unit)


def _low(name: str) -> str:
    from verstka.data.words import lower_first

    return lower_first(name)


def _common(names: list[str]) -> tuple[str, list[str]]:
    """(общая часть названий рядов, их различающиеся хвосты): «Выручка Q2», «Выручка Q3» → («Выручка», [«Q2», «Q3»])."""
    if len(names) < 2:
        return (names[0] if names else ""), names
    toks = [n.split() for n in names]
    k = 0
    while all(len(t) > k + 1 for t in toks) and len({t[k].lower() for t in toks}) == 1:
        k += 1
    if k == 0:
        return "", names
    return " ".join(toks[0][:k]), [" ".join(t[k:]) for t in toks]


def _verb(name: str, up: bool) -> str:
    from verstka.data.words import phrase, verb

    p = phrase(name)
    g = p.gender if p is not None else "m"
    return verb("grow" if up else "fall", g)


@dataclass
class Edited:
    slide: OutlineSlide
    did: list[str] = field(default_factory=list)  # что сделано, словами для ответа


@dataclass
class _Pair:
    """Два ряда одной величины по категориям: база (раньше / план) и текущий (позже / факт)."""

    base: int
    cur: int
    base_label: str
    cur_label: str
    metric: str
    unit: Optional[str]
    additive: bool


def _pair(s: OutlineSlide, plan: bool) -> Optional[_Pair]:
    ch = s.content.chart
    if ch is None or len(ch.series) < 2 or ch.type in ("scatter", "histogram", "pie", "doughnut") or ch.xy:
        return None
    names = [x.name or f"Ряд {k + 1}" for k, x in enumerate(ch.series)]
    units = {(x.unit or ch.unit or "").strip() for x in ch.series}
    if len(units) > 1:
        return None
    unit = (ch.series[0].unit or ch.unit or None)
    base, cur = 0, len(names) - 1
    if plan:
        pl = [k for k, n in enumerate(names) if _PLAN_NAME_RE.search(n)]
        if not pl:
            return None
        base = pl[0]
        fact = [k for k, n in enumerate(names) if _FACT_NAME_RE.search(n) and k != base]
        others = [k for k in range(len(names)) if k != base]
        if not others:
            return None
        cur = fact[0] if fact else others[-1]
    metric, tails = _common([names[base], names[cur]])
    base_label, cur_label = tails[0], tails[1]
    additive = not _NOT_ADDITIVE_RE.search(f"{metric} {names[cur]} {unit or ''}")
    return _Pair(base, cur, base_label, cur_label, metric or names[cur], unit, additive)


def _time_series(s: OutlineSlide) -> bool:
    ch = s.content.chart
    if ch is None or len(ch.series) != 1 or len(ch.categories) < 2:
        return False
    if s.data is not None and s.data.time_axis is not None:
        return True
    return ch.type in ("line", "area") or sum(1 for c in ch.categories if _TIME_CAT_RE.search(str(c).strip())) >= len(ch.categories) - 1


def _fact(fid: str, text: str, value: float, unit: Optional[str], kind: str, explain: str):
    from verstka.schemas.data import HeadlineFact

    return HeadlineFact(id=fid, text=text, value=float(value), unit=unit, kind=kind, explain=explain)


def _add_facts(s: OutlineSlide, facts: list) -> None:
    ids = {x.id for x in facts}
    s.data.headline_facts = [f for f in s.data.headline_facts if f.id not in ids] + facts


def _with_prepared(s: OutlineSlide, cats: list[str], name: str, values: list[Optional[float]], texts: list[str]) -> None:
    """Подготовленные значения слайда — новая мера, посчитанная из значений файла (аудит сверяет диаграмму с ними)."""
    from verstka.schemas.data import PreparedValues

    p = s.data.prepared
    keep = list(p.texts) if p is not None else []
    s.data.prepared = PreparedValues(categories=list(cats), series=[(name, list(values))], texts=keep + texts)


def _highlight_of(w: Wish, vals: list[Optional[float]], raw: Optional[list[Optional[float]]] = None) -> Optional[int]:
    idx = [k for k, v in enumerate(vals) if v is not None]
    if not idx:
        return None
    if w.highlight == "named":
        return w.named
    if w.highlight == "fall":
        k = min(idx, key=lambda j: vals[j])
        return k
    if w.highlight == "rise":
        return max(idx, key=lambda j: vals[j])
    src = raw if raw is not None else vals
    sidx = [k for k in idx if k < len(src) and src[k] is not None]
    if w.highlight == "min" and sidx:
        return min(sidx, key=lambda j: src[j])
    if w.highlight == "max" and sidx:
        return max(sidx, key=lambda j: src[j])
    return None


def _change_by_category(s: OutlineSlide, w: Wish, pr: _Pair, plan: bool) -> Optional[Edited]:
    ch = s.content.chart
    cats = [str(c) for c in ch.categories]
    a = list(ch.series[pr.base].values)[: len(cats)]
    b = list(ch.series[pr.cur].values)[: len(cats)]
    pcts: list[Optional[float]] = []
    for x, y in zip(a, b):
        if x is None or y is None or x == 0:
            pcts.append(None)
        elif plan:
            pcts.append(round(y / x * 100, 1))
        else:
            pcts.append(round((y - x) / abs(x) * 100, 1))
    if not any(p is not None for p in pcts):
        return None
    new = s.model_copy(deep=True)
    unit = pr.unit
    cols = f"«{ch.series[pr.base].name}» и «{ch.series[pr.cur].name}»"
    facts = []
    did: list[str] = []
    vs = f"к {pr.base_label}" if not plan else "плана"
    for k, (c, p) in enumerate(zip(cats, pcts)):
        if p is None:
            continue
        if plan:
            text = f"{c} — {_num(_pct(p))}% плана"
            explain = f"{c}: {_value(b[k], unit)} при плане {_value(a[k], unit)} — {_num(_pct(p))}% плана. Посчитано по колонкам {cols}."
        else:
            text = f"{c}: {_signed(p)} {vs}"
            word = "больше" if p > 0 else "меньше"
            explain = f"{c}: {_value(b[k], unit)} в {pr.cur_label} против {_value(a[k], unit)} в {pr.base_label} — на {_num(abs(_pct(p)))}% {word}. Посчитано по колонкам {cols}."
        facts.append(_fact(f"edit_{'plan' if plan else 'change'}_{k}", text, abs(_pct(p)), "%", "change", explain))
    total_a = sum(x for x, y in zip(a, b) if x is not None and y is not None)
    total_b = sum(y for x, y in zip(a, b) if x is not None and y is not None)
    total_p: Optional[float] = None
    if pr.additive and total_a:
        total_p = (total_b / total_a * 100) if plan else (total_b - total_a) / abs(total_a) * 100
        if plan:
            explain = f"Всего: {_value(total_b, unit)} при плане {_value(total_a, unit)} — {_num(_pct(total_p))}% плана. Посчитано по колонкам {cols}."
            facts.append(_fact("edit_total_plan", f"Всего — {_num(_pct(total_p))}% плана", abs(_pct(total_p)), "%", "change", explain))
        else:
            word = "больше" if total_p > 0 else "меньше"
            explain = f"Всего: {_value(total_b, unit)} в {pr.cur_label} против {_value(total_a, unit)} в {pr.base_label} — на {_num(abs(_pct(total_p)))}% {word}. Посчитано по колонкам {cols}."
            facts.append(_fact("edit_total_change", f"Всего {_signed(total_p)} к {pr.base_label}", abs(_pct(total_p)), "%", "change", explain))
        facts.append(_fact("edit_total_cur", f"Всего — {_value(total_b, unit)}", total_b, unit, "total", f"Сумма по колонке «{ch.series[pr.cur].name}»."))
        facts.append(_fact("edit_total_base", f"Всего — {_value(total_a, unit)}", total_a, unit, "total", f"Сумма по колонке «{ch.series[pr.base].name}»."))
    hi = _highlight_of(w, pcts, b)
    if w.highlight == "fall" and hi is not None and not plan and (pcts[hi] or 0) >= 0:
        did.append("падения нет — все категории выросли; выделена та, что выросла меньше всех")
    # заголовок-вывод: итог в новой мере, затем выделенная категория (падение / лидер / названная)
    metric = pr.metric
    if plan:
        head = f"{metric}: {_num(_pct(total_p))}% плана" if total_p is not None else f"{metric} — выполнение плана"
    elif total_p is not None:
        head = f"{metric} {pr.cur_label} — {_value(total_b, unit)}, {_signed(total_p)} к {pr.base_label}".strip()
    else:
        head = f"{metric}: {pr.cur_label} к {pr.base_label}"
    if hi is not None and pcts[hi] is not None:
        c = cats[hi]
        if plan:
            tail = f"{_low(c)} — {_num(_pct(pcts[hi]))}% плана"
        else:
            up = pcts[hi] >= 0
            tail = f"{_low(c)} {_verb(c, up)} на {_num(abs(_pct(pcts[hi])))}%"
        head = f"{head}; {tail}"
    elif total_p is None:
        lead = max((k for k, p in enumerate(pcts) if p is not None), key=lambda j: pcts[j])
        head = f"{head}: {_low(cats[lead])} {_signed(pcts[lead])}" if not plan else f"{head}: {_low(cats[lead])} — {_num(_pct(pcts[lead]))}%"
    new.headline = head[0].upper() + head[1:]
    # подпись: по каждой категории — новая мера и значения, из которых она посчитана
    parts = []
    for k, (c, p) in enumerate(zip(cats, pcts)):
        if p is None:
            continue
        if plan:
            parts.append(f"{c} — {_num(_pct(p))}%")
        else:
            parts.append(f"{c} {_signed(p)} ({_num(a[k])} → {_value(b[k], unit)})")
    new.takeaway = "; ".join(parts)
    if len(new.takeaway) > 160:
        new.takeaway = "; ".join(p.split(" (")[0] for p in parts)
    _add_facts(new, facts)
    # a fall drawn as a bar of its own is no bar the previews draw right (LibreOffice draws −8,6 as a bar of 8,6 to the right):
    # with a fall the chart keeps both periods side by side, the fall highlighted, and the words say the percentages
    show = w.show and all(p is None or p >= 0 for p in pcts)
    if w.show and not show:
        did.append(f"на диаграмме — {pr.base_label} и {pr.cur_label} рядом, проценты — в заголовке и подписи")
    if show:
        name = "Выполнение плана, %" if plan else f"Изменение {pr.cur_label} к {pr.base_label}, %".replace("  ", " ")
        horizontal = ch.type in ("bar", "grouped_bar", "stacked_bar") or w.chart == "bar"
        kind = "column" if w.chart == "column" else "bar" if horizontal else "column"
        from verstka.schemas.outline import InlineSeries

        nc = new.content.chart
        nc.type = kind
        nc.series = [InlineSeries(name=name, values=pcts, unit="%")]
        nc.series_ids = []
        nc.unit = "%"
        nc.y_title = "%"
        nc.legend_title = None
        nc.highlight_index = hi
        nc.split = False
        _with_prepared(new, cats, name, pcts, [f.explain for f in facts])
        new.data.aggregation = (f"{'выполнение плана' if plan else 'изменение ' + pr.cur_label + ' к ' + pr.base_label} в процентах — "
                                f"посчитано по колонкам {cols}")
        did.append(("диаграмма показывает выполнение плана в процентах" if plan else f"диаграмма показывает изменение {pr.cur_label} к {pr.base_label} в процентах"))
    elif hi is not None:
        new.content.chart.highlight_index = hi
    if hi is not None:
        did.append(f"выделено «{cats[hi]}» ({_signed(pcts[hi]) if not plan else _num(_pct(pcts[hi])) + '% плана'})")
    did.insert(0, f"заголовок «{new.headline}»")
    new.notes = "\n".join(x for x in [(s.notes or "").strip(), *[f.explain for f in facts]] if x)
    return Edited(new, did)


def _change_over_time(s: OutlineSlide, w: Wish) -> Optional[Edited]:
    ch = s.content.chart
    cats = [str(c) for c in ch.categories]
    vals = list(ch.series[0].values)[: len(cats)]
    real = [k for k, v in enumerate(vals) if v is not None]
    if len(real) < 2:
        return None
    unit = ch.series[0].unit or ch.unit
    name = ch.series[0].name or (s.data.metrics[0] if s.data and s.data.metrics else "Значение")
    last, prev = real[-1], real[-2]
    if vals[prev] == 0:
        return None
    p = (vals[last] - vals[prev]) / abs(vals[prev]) * 100
    steps: list[Optional[float]] = [None]
    for k in range(1, len(vals)):
        a, b = vals[k - 1], vals[k]
        steps.append(None if a in (None, 0) or b is None else round((b - a) / abs(a) * 100, 1))
    new = s.model_copy(deep=True)
    col = f"«{name}»"
    facts = [_fact("edit_change_last", f"{cats[last]}: {_signed(p)} к {cats[prev]}", abs(_pct(p)), "%", "change",
                   f"{cats[last]}: {_value(vals[last], unit)} против {_value(vals[prev], unit)} в {cats[prev]} — на {_num(abs(_pct(p)))}% "
                   f"{'больше' if p > 0 else 'меньше'}. Посчитано по колонке {col}.")]
    for k, st in enumerate(steps):
        if st is not None and k != last:
            facts.append(_fact(f"edit_step_{k}", f"{cats[k]}: {_signed(st)}", abs(_pct(st)), "%", "change",
                               f"{cats[k]} к {cats[k - 1]}: {_signed(st)}. Посчитано по колонке {col}."))
    hi = _highlight_of(w, steps, vals) if w.highlight else (last if w.show else None)
    head = f"{name} {cats[last]} — {_value(vals[last], unit)}, {_signed(p)} к {cats[prev]}"
    if hi is not None and hi != last and steps[hi] is not None:
        head += f"; {'сильнее всего упал' if steps[hi] < 0 else 'сильнее всего вырос'} {cats[hi]}: {_signed(steps[hi])}"
    new.headline = head[0].upper() + head[1:]
    new.takeaway = f"{cats[prev]} — {_value(vals[prev], unit)}, {cats[last]} — {_value(vals[last], unit)}"
    _add_facts(new, facts)
    did = [f"заголовок «{new.headline}»"]
    if w.show and all(st is None or st >= 0 for st in steps):
        from verstka.schemas.outline import InlineSeries

        sname = "Изменение к прошлому периоду, %"
        nc = new.content.chart
        nc.type = "column"
        nc.categories = cats[1:]
        nc.series = [InlineSeries(name=sname, values=steps[1:], unit="%")]
        nc.series_ids, nc.unit, nc.y_title, nc.split = [], "%", "%", False
        nc.highlight_index = (hi - 1) if hi is not None and hi >= 1 else None
        _with_prepared(new, cats[1:], sname, steps[1:], [f.explain for f in facts])
        new.data.aggregation = f"изменение к прошлому периоду в процентах — посчитано по колонке {col}"
        did.append("диаграмма показывает изменение к прошлому периоду в процентах")
    elif hi is not None:
        new.content.chart.highlight_index = hi
    new.notes = "\n".join(x for x in [(s.notes or "").strip(), *[f.explain for f in facts]] if x)
    return Edited(new, did)


def _shares(s: OutlineSlide, w: Wish) -> Optional[Edited]:
    ch = s.content.chart
    if ch is None or not ch.series or ch.xy:
        return None
    sr = ch.series[-1]
    cats = [str(c) for c in ch.categories]
    vals = list(sr.values)[: len(cats)]
    unit = sr.unit or ch.unit
    if any(v is not None and v < 0 for v in vals) or _NOT_ADDITIVE_RE.search(f"{sr.name} {unit or ''}"):
        return None
    total = sum(v for v in vals if v is not None)
    if not total:
        return None
    shares = [None if v is None else round(v / total * 100, 1) for v in vals]
    new = s.model_copy(deep=True)
    col = f"«{sr.name}»" if sr.name else "значений"
    facts = [_fact(f"edit_share_{k}", f"{c} — {_num(_pct(p))}%", _pct(p), "%", "share",
                   f"{c}: {_value(vals[k], unit)} из {_value(total, unit)} — {_num(_pct(p))}%. Посчитано по колонке {col}.")
             for k, (c, p) in enumerate(zip(cats, shares)) if p is not None]
    facts.append(_fact("edit_share_total", f"Всего — {_value(total, unit)}", total, unit, "total", f"Сумма по колонке {col}."))
    hi = _highlight_of(w, shares) if w.highlight else max((k for k, p in enumerate(shares) if p is not None), key=lambda j: shares[j])
    lead = hi if hi is not None else 0
    new.headline = f"{cats[lead]} — {_num(_pct(shares[lead]))}% из {_value(total, unit)}"
    new.takeaway = "; ".join(f"{c} — {_num(_pct(p))}%" for c, p in zip(cats, shares) if p is not None)
    _add_facts(new, facts)
    did = [f"заголовок «{new.headline}»"]
    if w.show or w.chart == "pie":
        from verstka.schemas.outline import InlineSeries

        nc = new.content.chart
        nc.type = "pie" if (w.chart == "pie" and len(cats) <= 6) else ("bar" if ch.type in ("bar", "grouped_bar", "stacked_bar") else "column")
        nc.series = [InlineSeries(name="Доля, %", values=shares, unit="%")]
        nc.series_ids, nc.unit, nc.split = [], "%", False
        nc.y_title = "Доля, %"
        nc.highlight_index = hi
        _with_prepared(new, cats, "Доля, %", shares, [f.explain for f in facts])
        new.data.aggregation = f"доли от итога в процентах — посчитано по колонке {col}"
        did.append("диаграмма показывает доли в процентах")
    elif hi is not None:
        new.content.chart.highlight_index = hi
    return Edited(new, did)


def _chart_kind(s: OutlineSlide, w: Wish) -> Optional[Edited]:
    """«покажи столбцами / полосами»: та же диаграмма в другой ориентации (значения те же)."""
    ch = s.content.chart
    if ch is None or w.chart not in ("column", "bar"):
        return None
    swap = {"bar": "column", "column": "bar", "grouped_bar": "grouped_column", "grouped_column": "grouped_bar",
            "stacked_bar": "stacked_column", "stacked_column": "stacked_bar"}
    horizontal = ch.type in ("bar", "grouped_bar", "stacked_bar")
    if (w.chart == "bar") == horizontal or ch.type not in swap:
        return None
    new = s.model_copy(deep=True)
    new.content.chart.type = swap[ch.type]
    return Edited(new, ["диаграмма — " + ("горизонтальными полосами" if w.chart == "bar" else "вертикальными столбцами")])


def apply_wish(s: OutlineSlide, w: Wish) -> Optional[Edited]:
    """Слайд с данными после просьбы `w`; None — правилам здесь делать нечего (слово за дизайнером)."""
    if s.data is None or s.content.chart is None:
        return None
    out: Optional[Edited] = None
    if w.measure in ("change", "plan"):
        pr = _pair(s, w.measure == "plan")
        if pr is not None:
            out = _change_by_category(s, w, pr, w.measure == "plan")
        elif w.measure == "change" and _time_series(s):
            out = _change_over_time(s, w)
    elif w.measure == "share":
        out = _shares(s, w)
    elif w.highlight is not None:
        ch = s.content.chart
        vals = list(ch.series[-1].values) if ch.series else []
        hi = _highlight_of(w, vals)
        if hi is not None and hi != ch.highlight_index:
            new = s.model_copy(deep=True)
            new.content.chart.highlight_index = hi
            out = Edited(new, [f"выделено «{ch.categories[hi]}» на диаграмме"])
    if w.chart in ("column", "bar"):
        base = out.slide if out is not None else s
        k = _chart_kind(base, w)
        if k is not None:
            out = Edited(k.slide, (out.did if out is not None else []) + k.did)
    return out


# ── «короче» для слайда с данными
def _shown_numbers(s: OutlineSlide, skip: str = "") -> set[float]:
    """Числа, которые слайд показывает помимо текста `skip`: значения диаграммы и таблицы, карточки и прочие слова."""
    from verstka.data.headline import numbers_in

    out: set[float] = set()
    c = s.content
    for ch in (c.chart, c.chart2):
        if ch is None:
            continue
        for sr in ch.series:
            out |= {round(abs(float(v)), 2) for v in sr.values if v is not None}
    if c.table is not None:
        for r in c.table.rows:
            for cell in r:
                out |= {round(x, 2) for x in numbers_in(str(cell))}
    texts = [s.headline, s.subtitle, s.takeaway, *c.bullets, *c.paragraphs, *[f"{n.value} {n.label}" for n in c.numbers],
             *[f"{it.title} {it.text}" for it in c.items]]
    for t in texts:
        if t and t != skip:
            out |= {round(x, 2) for x in numbers_in(t)}
    return out


def _kept(dropped: str, s: OutlineSlide, skip: str) -> bool:
    """Каждое число выброшенной части `dropped` слайд показывает где-то ещё (кроме текста `skip`)."""
    from verstka.data.headline import _matches, numbers_in

    shown = _shown_numbers(s, skip)
    return all(any(_matches(n, v) or _matches(v, n) for v in shown) for n in numbers_in(dropped))


def _cut(t: str, s: OutlineSlide, field_text: str) -> str:
    """Текст до первой мысли («…, наименьшая категория» → без хвоста), когда числа хвоста есть на слайде и так."""
    t = (t or "").strip()
    for sep in ("; ", ". ", ", ", ": "):
        head, _, tail = t.partition(sep)
        if tail and len(head) >= 12 and re.search(r"[а-яёa-z]{3,}", head, re.I) and _kept(tail, s, field_text):
            return head.rstrip(".;:,")
    return t


def _length(s: OutlineSlide) -> int:
    c = s.content
    return sum(len(x or "") for x in [s.headline, s.subtitle, s.takeaway, *c.bullets, *c.paragraphs, *[f"{it.title} {it.text}" for it in c.items]])


def shorter(s: OutlineSlide) -> Optional[Edited]:
    """«короче» на слайде с данными: подпись, что повторяет заголовок и диаграмму, уходит; заголовок, подзаголовок, подпись
    и строки — до первой мысли, если числа отрезанного слайд показывает и так. None — короче без потери чисел не выйдет."""
    from verstka.data.headline import _matches, numbers_in

    new = s.model_copy(deep=True)
    did: list[str] = []
    tk = (new.takeaway or "").strip()
    if tk:
        shown = _shown_numbers(new, tk)
        tnums = numbers_in(tk)
        if tnums and all(any(_matches(n, v) or _matches(v, n) for v in shown) for n in tnums):
            new.takeaway = None
            did.append("подпись под диаграммой убрана — её числа уже в заголовке и на диаграмме")
        else:
            cut = _cut(tk, new, tk)
            if cut != tk:
                new.takeaway = cut
                did.append(f"подпись «{cut}»")
    h = new.headline or ""
    if len(h) > 50:
        cut = _cut(h, new, h)
        if cut != h:
            new.headline = cut
            did.insert(0, f"заголовок «{cut}»")
    if new.subtitle:
        cut = _cut(new.subtitle, new, new.subtitle)
        if cut != new.subtitle:
            new.subtitle = cut
            did.append("подзаголовок короче")
    c = new.content
    lines = [_cut(b, new, b) for b in c.bullets]
    if lines != list(c.bullets):
        c.bullets = lines
        did.append("строки сокращены до главного")
    if _length(new) >= _length(s):
        return None
    return Edited(new, did)
