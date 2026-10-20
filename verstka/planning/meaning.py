"""The meaning passes of a planned deck (final polish M): what the listener takes away, not only what the slides show.

`finish_deck(outline, brief_text)` runs after the planner, with and without a model:
- no ask to the designer is a slide's text (planning/directives.py: «Нужен столбчатый график: …», «Сделай воронку»);
- a table gets a conclusion counted from its cells (as the data decks of the second stage do): «Итого: 214 → 176 млн ₽
  (−38)», «Факт выше плана: 1 840 против 1 750 млн ₽ (+5%)», «Стоимость заявки: от 923 ₽ (таргет) до 2 000 ₽
  (блогеры)» — the heading when the slide's own one only names a topic, its conclusion line otherwise;
- without a model, a slide headed by its topic takes its own short stated result as its heading (a model's headings stay
  the model's);
- a figure says what it is: a key figure whose label is its own value or a word torn from its sentence takes its
  label from the sentence the brief says it in, or goes;
- the deck ends on its point: a bare «Спасибо за внимание» is never instead of it — after the ask it stays as a
  courtesy, with no ask or conclusion before it it carries the brief's ask (or its stated conclusion); a planner's deck
  (not the author's dictated order) has its ask / next steps slide last.

Every figure a pass writes is a cell of the table or a figure of the brief: nothing is estimated.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from verstka.planning import heuristics as H
from verstka.planning.directives import scrub_outline
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent, SlideItem, TableData

log = logging.getLogger(__name__)

MINUS = "−"
_FRAME = {PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.agenda}


# ------------------------------------------------------------------ numbers


_CELL_RE = re.compile(r"^\s*(?P<sign>[+\-−–]?)\s*(?P<num>\d{1,3}(?:[\s  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*(?P<pct>%)?\s*(?P<tail>[^\d]{0,12})$")


def cell_number(cell: str) -> Optional[float]:
    """«4 800» → 4800, «12,5%» → 12.5, «−5» → −5; None for a cell that is not one figure."""
    m = _CELL_RE.match(cell or "")
    if not m:
        return None
    if m.group("tail").strip() and not re.fullmatch(r"(?:₽|руб\.?|млн|млрд|тыс\.?|шт\.?|чел\.?|ч|дн\.?|п\.\s?п\.)", m.group("tail").strip(), re.I):
        return None
    v = float(re.sub(r"[\s  ]", "", m.group("num")).replace(",", "."))
    return -v if m.group("sign") in ("-", "−", "–") else v


def fmt(v: float) -> str:
    """1840 → «1 840», 2.25 → «2,25», −38 → «−38»."""
    a = abs(v)
    if abs(a - round(a)) < 1e-9:
        s = f"{int(round(a)):,}".replace(",", " ")
    else:
        s = f"{a:.2f}".rstrip("0").rstrip(".").replace(".", ",") if a < 10 else f"{a:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return (MINUS if v < 0 and round(a, 2) != 0 else "") + s


def signed(v: float) -> str:
    return ("+" if v > 0 else "") + fmt(v)


_UNIT_RE = re.compile(r",\s*(?P<u>[^,]{1,24})$")


def header_unit(header: str) -> tuple[str, Optional[str]]:
    """«План, млн ₽» → («План», «млн ₽»); «Расход, тыс. ₽» → («Расход», «тыс. ₽»); «2026» → («2026», None)."""
    h = " ".join((header or "").split())
    m = _UNIT_RE.search(h)
    if m and re.search(r"₽|руб|%|млн|млрд|тыс|шт|чел|дн|час|мин|\$|€|кг|т\b|м²", m.group("u"), re.I):
        return h[: m.start()].strip(), m.group("u").strip().replace("руб.", "₽").replace("рублей", "₽")
    return h, None


# ------------------------------------------------------------------ tables


@dataclass
class _Col:
    index: int
    name: str
    unit: Optional[str]
    values: list[Optional[float]]


_TOTAL_RE = re.compile(r"^(?:итого|всего|итог|в\s+сумме|сумма|total)\b", re.I)
# a column whose rows do not add up: a price, a share, a rate, a time, a score
_RATE_RE = re.compile(r"(?<![а-яё-])цен(?:а|ы|у|ой|е|ам|ами|ах|ник\w*|ов\w*)?(?![а-яё])|стоимост|средн|дол[яи]|%|процент|ставк|курс|срок|скорост|время|балл|рейтинг|конверси|маржин|рентабел|на\s+одн|за\s+одн|чек|cpl|cpa|ctr|cac|ltv", re.I)
_PLAN_RE = re.compile(r"\bплан|\bцел[ьи]\b|\bбюджет|\bпрогноз|\btarget|\bplan", re.I)
_FACT_RE = re.compile(r"\bфакт|\bисполн|\bитог\b|\bрезультат|\bactual", re.I)


def _columns(t: TableData) -> tuple[list[str], list[_Col], Optional[int]]:
    """(the labels of the rows, the numeric columns, the index of the total row or None)."""
    rows = [list(r) + [""] * (len(t.columns) - len(r)) for r in t.rows]
    labels = [r[0].strip() if r else "" for r in rows]
    total = next((i for i, lb in enumerate(labels) if _TOTAL_RE.match(lb)), None)
    cols: list[_Col] = []
    for j in range(1, len(t.columns)):
        vals = [cell_number(r[j]) for r in rows]
        body = [v for i, v in enumerate(vals) if i != total]
        if body and all(v is not None for v in body):
            name, unit = header_unit(t.columns[j])
            if unit is None and t.unit:
                unit = t.unit
            if unit is None:
                # «Статья, млн ₽ | 2026 | 2027»: the unit is the label column's
                _, unit = header_unit(t.columns[0])
            if unit is None and any("%" in (r[j] or "") for r in rows):
                unit = "%"
            cols.append(_Col(j, name, unit, vals))
    return labels, cols, total


def _with_unit(v: float, unit: Optional[str]) -> str:
    if not unit:
        return fmt(v)
    return f"{fmt(v)}{unit}" if unit == "%" else f"{fmt(v)} {unit}"


def _low(label: str) -> str:
    """A row label inside a sentence: its first letter lower unless it is a name («Онлайн-офис» → «онлайн-офис», «VK
    Cloud» stays)."""
    w = label.split()[0] if label.split() else ""
    if len(w) > 1 and (w[1:].lower() != w[1:] or re.search(r"[A-Z]{2}", w)):
        return label
    return label[:1].lower() + label[1:]


_PERIOD_LABEL_RE = re.compile(r"^(?:(?:19|20)\d{2}(?:\s*г\.?)?|[IV]{1,3}\s*кв\.?.*|Q[1-4].*|\d\s*кв.*|[1-4]-?й?\s*квартал.*|"
                              r"январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)$", re.I)


def _period_growth(labels: list[str], cols: list, body: list[int], subject: Optional[str]) -> Optional[tuple[str, Optional[str]]]:
    """A table of periods by rows and parts by columns («Год | Дата-центры | Разработка | Продажи»): the total from the
    first period to the last («Инвестиции: 240 → 480 млн ₽ за 2025–2027, ×2»), the part that grows fastest under it."""
    if len(body) < 2 or len(cols) < 2 or not all(_PERIOD_LABEL_RE.match((labels[i] or "").strip()) for i in body):
        return None
    if any(_RATE_RE.search(c.name + " " + (c.unit or "")) for c in cols):
        return None
    i0, i1 = body[0], body[-1]
    if any(c.values[i0] is None or c.values[i1] is None for c in cols):
        return None
    a, b = sum(c.values[i0] for c in cols), sum(c.values[i1] for c in cols)
    if a <= 0 or a == b:
        return None
    unit = next((c.unit for c in cols if c.unit), None)
    ratio = b / a
    change = f"×{fmt(round(ratio, 1))}" if ratio >= 1.5 else f"{signed(round((ratio - 1) * 100))}%"
    name = H.cap_first(re.sub(r"\s+по\s+(?:годам|кварталам|месяцам|периодам)\b.*$", "", H.strip_end(subject or ""), flags=re.I)) or "Всего"
    head = f"{name}: {fmt(a)} → {_with_unit(b, unit)} за {labels[i0]}–{labels[i1]} ({change})"
    fast = max(cols, key=lambda c: (c.values[i1] / c.values[i0]) if c.values[i0] else 0)
    detail = f"Быстрее всех растёт статья «{fast.name}»: {fmt(fast.values[i0])} → {fmt(fast.values[i1])}" if fast.values[i0] and fast.values[i1] / fast.values[i0] > ratio * 1.05 else None
    return head, detail


def table_conclusion(t: TableData, focus: Optional[list[list[float]]] = None, subject: Optional[str] = None) -> Optional[tuple[str, Optional[str]]]:
    """(the conclusion heading, a line of detail or None) counted from the table's cells; None when the table gives
    no clear one. `focus`: the values of each series a chart of the slide shows — the columns it draws are the ones
    concluded on."""
    if t is None or not t.rows or len(t.columns) < 2:
        return None
    labels, cols, total = _columns(t)
    if not cols or len(labels) < 2:
        return None
    body = [i for i in range(len(labels)) if i != total]
    if total is None and not focus and len(cols) >= 3:
        got = _period_growth(labels, cols, body, subject)
        if got is not None:
            return got
    if focus:
        fsets = [{round(v, 2) for v in f} for f in focus if f]
        hit = [c for c in cols if {round(c.values[i], 2) for i in body if c.values[i] is not None} in fsets]
        if 1 <= len(hit) <= 2:
            cols = hit
    if len(cols) == 2 and (cols[0].unit != cols[1].unit or bool(_COUNT_NAME_RE.search(cols[0].name)) != bool(_COUNT_NAME_RE.search(cols[1].name))):
        # «Квартал | Выручка, млн ₽ | Клиенты»: two measures, never added up — how each moved over the periods
        if len(body) >= 2 and all(_PERIOD_LABEL_RE.match((labels[i] or "").strip()) for i in body):
            i0, i1 = body[0], body[-1]
            moves = []
            for c in cols:
                a, b = c.values[i0], c.values[i1]
                if a is None or b is None or not a or a == b:
                    return None
                ch = f"×{fmt(round(b / a, 1))}" if b / a >= 1.5 else f"{signed(round((b / a - 1) * 100))}%"
                moves.append((c, a, b, ch))
            (c0, a0, b0, ch0), (c1, a1, b1, ch1) = moves
            return (f"{H.cap_first(c0.name)}: {fmt(a0)} → {_with_unit(b0, c0.unit)} за {labels[i0]}–{labels[i1]} ({ch0})",
                    f"{H.cap_first(c1.name)}: {fmt(a1)} → {_with_unit(b1, c1.unit)} ({ch1})")
        return None
    if len(cols) == 2:
        a, b = cols
        additive = not (_RATE_RE.search(a.name + " " + (a.unit or "")) or _RATE_RE.search(t.columns[0]))
        if total is not None:
            ta, tb = a.values[total], b.values[total]
        elif additive and len(body) >= 2:
            ta, tb = sum(a.values[i] for i in body), sum(b.values[i] for i in body)
        else:
            ta = tb = None
        unit = a.unit or b.unit
        if ta is not None and tb is not None and ta != tb:
            if _PLAN_RE.search(a.name) and _FACT_RE.search(b.name):
                pct = (tb - ta) / abs(ta) * 100 if ta else None
                word = "выше" if tb > ta else "ниже"
                head = f"Факт {word} плана: {_with_unit(tb, unit)} против {fmt(ta)}" + (f" ({signed(round(pct))}%)" if pct is not None and abs(pct) >= 1 else "")
                other = [i for i in body if (b.values[i] - a.values[i]) * (tb - ta) < 0]
                detail = None
                if other:
                    detail = ("Ниже плана: " if tb > ta else "Выше плана: ") + ", ".join(
                        f"{_low(labels[i])} ({fmt(b.values[i])} из {fmt(a.values[i])})" for i in other[:3])
                return head, detail
            tl = labels[total] if total is not None else "Итого"
            head = f"{tl}: {fmt(ta)} → {_with_unit(tb, unit)} ({signed(tb - ta)})"
            movers = sorted(body, key=lambda i: -abs(b.values[i] - a.values[i]))
            movers = [i for i in movers if b.values[i] != a.values[i]][:1]
            detail = None
            if movers:
                i = movers[0]
                detail = f"Сильнее всего: {_low(labels[i])} — {fmt(a.values[i])} → {fmt(b.values[i])}"
                if len(detail) > 70:
                    detail = None  # a short line or none: the heading has said the total
            return head, detail
    if len(cols) == 1 or focus:
        c = cols[-1] if len(cols) > 1 else cols[0]
        vals = [(c.values[i], i) for i in body if c.values[i] is not None]
        if len(vals) < 3:
            return None
        hi, ih = max(vals)
        lo, il = min(vals)
        if lo <= 0 or hi / lo < 1.3:
            return None
        name = c.name if not re.fullmatch(r"\d{4}", c.name) else ""
        head = (f"{H.cap_first(name)}: " if name else "") + f"от {_with_unit(lo, c.unit)} ({_low(labels[il])}) до {_with_unit(hi, c.unit)} ({_low(labels[ih])})"
        return head, None
    return None


def _topic(headline: str) -> bool:
    """The heading only names the slide's subject («Экономика», «По направлениям», «Статьи 2026 и 2027 годов»): short,
    no figure but a year, no verb form of a statement."""
    t = H.strip_end(headline or "")
    if not t or len(t.split()) > 6:
        return False
    if re.search(r"\d", re.sub(r"\b(?:19|20)\d{2}\b", "", t)):
        return False
    if re.match(r"^(?:сколько|как|что|где|когда|почему|зачем|кто|какой|какая|какие|каких|откуда|куда|чем)\b", t, re.I):
        return True  # «Сколько отгрузили», «Что случилось»: a question the slide answers
    return not re.search(r"\b\w+(?:ет|ют|ит|ат|ят|ил|ила|или|ло|ется|ются|ится|ался|алась|ались|ены|ена|ено|аны|ана|ано)\b", t.lower())


def _chart_values(s: OutlineSlide) -> list[list[float]]:
    ch = s.content.chart
    if ch is None or not ch.series:
        return []
    return [[float(v) for v in x.values if v is not None] for x in ch.series]


def keep_table_beside_chart(o: DeckOutline) -> list[str]:
    """A chart drawn from one column of the author's table (qa5 13: «стоимость заявки по каналам») never costs the rest
    of the table (расход, заявки): the table with its other columns goes on its own slide right after the chart."""
    said: list[str] = []
    out: list[OutlineSlide] = []
    for s in o.slides:
        out.append(s)
        c = s.content
        if c.chart is None or c.table is None or s.kind == PatternKind.table:
            continue
        drawn = {round(v, 2) for x in c.chart.series for v in x.values if v is not None}
        labels, cols, _ = _columns(c.table)
        extra = [col for col in cols if {round(v, 2) for v in col.values if v is not None} - drawn]
        if not extra:
            continue
        ids = {x.id for x in o.slides}
        nid = next(f"{s.id}-t{k}" for k in range(1, 9) if f"{s.id}-t{k}" not in ids)
        t = c.table
        c.table = None
        on_chart = table_conclusion(t, _chart_values(s) or None)
        if on_chart is not None and _topic(s.headline):
            s.section = s.section or s.headline
            s.headline = on_chart[0]
        got = table_conclusion(t)
        out.append(OutlineSlide(id=nid, kind=PatternKind.table, headline=got[0] if got else (s.section or s.headline),
                                section=s.section or s.headline, takeaway=got[1] if got else None,
                                content=SlideContent(table=t),
                                continues=s.id, notes=s.notes, rationale="Вся таблица автора — рядом с графиком одной её колонки."))
        said.append(f"slide {s.id}: the table's other columns ({', '.join(col.name for col in extra)}) on a slide of their own")
    o.slides = out
    return said


def keep_author_tables(o: DeckOutline, brief_text: str) -> list[str]:
    """A table the author wrote into the brief is on the deck: when most of its figures are on no slide (a model drew
    one of its columns — qa5 13: «расход / заявки по каналам» gone), the table goes on a slide of its own right after
    the slide that shows the most of it."""
    from verstka.planning.brief_structure import _markdown_tables, numbers_of

    said: list[str] = []
    try:
        tables = _markdown_tables(brief_text or "")
    except Exception:  # noqa: BLE001 - no table read
        return said
    for t in tables:
        cells = {round(v, 2) for row in t.rows for cell in row[1:] for v in numbers_of(cell)}
        if len(cells) < 4:
            continue

        def on(sl: OutlineSlide) -> set:
            c = sl.content
            vals = set()
            if c.chart is not None:
                vals |= {round(float(v), 2) for x in c.chart.series for v in x.values if v is not None}
            if c.table is not None:
                vals |= {round(v, 2) for row in c.table.rows for cell in row for v in numbers_of(cell)}
            vals |= {round(v, 2) for v in numbers_of(_slide_text(sl) + " " + " ".join(n.value for n in c.numbers))}
            return vals & cells

        shown = set().union(*(on(sl) for sl in o.slides)) if o.slides else set()
        if len(shown) * 2 > len(cells):
            continue
        host = max(o.slides, key=lambda sl: len(on(sl)))
        if not on(host):
            continue
        ids = {x.id for x in o.slides}
        nid = next(f"{host.id}-t{k}" for k in range(1, 9) if f"{host.id}-t{k}" not in ids)
        got = table_conclusion(t)
        new = OutlineSlide(id=nid, kind=PatternKind.table, headline=got[0] if got else (t.caption or host.section or host.headline),
                           section=host.section, takeaway=got[1] if got else None, content=SlideContent(table=t.model_copy(deep=True)),
                           continues=host.id, rationale="Таблица автора целиком: на графике — только её часть.")
        o.slides.insert(o.slides.index(host) + 1, new)
        said.append(f"slide {nid}: the author's table ({', '.join(t.columns[:4])}) on a slide of its own — the deck showed {len(shown)} of its {len(cells)} figures")
    return said


def keep_figures(o: DeckOutline) -> list[str]:
    """Without a model, a chart slide never loses the author's figures it does not draw (qa5 02: «аналитика — 41 день,
    продавца — 23 дня» under a chart of 54 against the market's 47): the sentence of the notes that states them stands
    beside the chart, as written (two at most, short)."""
    from verstka.planning.brief_structure import numbers_of
    from verstka.planning.directives import split_directive
    from verstka.planning.faithful import sentences

    said: list[str] = []
    for s in o.slides:
        c = s.content
        # (a chart, or one large figure standing for a whole item; a row of figures already shows the item's figures)
        figure_form = c.chart is not None or (s.kind == PatternKind.big_number and len(c.numbers) == 1)
        if s.kind in _FRAME or not figure_form or c.bullets or c.paragraphs or not s.notes:
            continue
        drawn = " ".join(str(v) for x in c.chart.series for v in x.values) if c.chart is not None else ""
        shown = {round(v, 2) for v in numbers_of(_slide_text(s) + " " + drawn + " " + " ".join(n.value for n in c.numbers))}
        add = []
        for sent in sentences(s.notes):
            ask, rest = split_directive(sent)
            line = rest if ask is not None else sent
            figs = {round(v, 2) for v in numbers_of(line or "")} - {v for v in numbers_of(line or "") if 1900 <= v <= 2100}
            if line and figs - shown and len(line.split()) <= 22:
                add.append(H.strip_end(line))
                shown |= figs
            if len(add) == 2:
                break
        if add:
            c.bullets = add
            said.append(f"slide {s.id}: the author's figures the chart does not draw stay beside it")
    return said


def table_conclusions(o: DeckOutline) -> list[str]:
    said: list[str] = []
    for s in o.slides:
        if s.kind in _FRAME or s.content.table is None:
            continue
        try:
            got = table_conclusion(s.content.table, _chart_values(s) or None, subject=s.headline if _topic(s.headline) else None)
        except Exception:  # noqa: BLE001 - the slide as planned
            log.warning("table conclusion failed on %s", s.id, exc_info=True)
            continue
        if got is None:
            continue
        head, detail = got
        if _topic(s.headline):
            if not s.section:
                s.section = s.headline
            said.append(f"slide {s.id}: the topic heading «{s.headline}» → the table's conclusion «{head}»")
            s.headline = head
            if detail and not (s.takeaway or "").strip():
                s.takeaway = detail
        elif not (s.takeaway or "").strip():
            s.takeaway = head
            said.append(f"slide {s.id}: the table's conclusion «{head}» as its conclusion line")
    return said


# ------------------------------------------------------------------ key figures


def _norm(t: str) -> str:
    return re.sub(r"[\s  ]", "", (t or "").lower())


def _weak_label(value: str, label: str) -> bool:
    lab = H.strip_end(label or "").strip()
    if not lab or _norm(lab) == _norm(value) or _norm(value) in _norm(lab) and len(lab.split()) <= 2:
        return True
    words = re.findall(r"[а-яёa-z]+", lab.lower())
    if not words:
        return True
    # a word torn from its sentence: «октября», «заказов», «не больше», «получили»
    return len(words) == 1 and len(lab) <= 12 and not lab[:1].isupper() or (len(words) <= 2 and words[0] in {"не", "до", "от", "на", "в", "с", "по", "из", "и"})


def _label_from(value: str, brief_text: str) -> Optional[str]:
    """The words the brief says right before the figure, up to the sentence's or clause's start («Текучесть — 15%» →
    «Текучесть»)."""
    num = re.match(r"[+\-−]?\d[\d\s ]*(?:[.,]\d+)?", (value or "").strip())
    if not num:
        return None
    core = re.escape(num.group(0).strip()).replace(r"\ ", r"[\s ]")
    for sent in H.split_sentences(" ".join((brief_text or "").split())) or []:
        m = re.search(rf"(?<![\d,.]){core}(?![\d])", sent)
        if not m:
            continue
        before = sent[: m.start()]
        clause = re.split(r"[,;:(]\s*|\.\s+", before)[-1]
        clause = re.sub(r"\s*[—–-]\s*$|\s+(?:составляет|составила|составил|составит|—|это|около|примерно|до|на|в)\s*$", "", clause.strip(), flags=re.I).strip(" —–-")
        ws = clause.split()
        if 1 <= len(ws) <= 6 and not re.search(r"\d", clause):
            return H.cap_first(clause)
    return None


_COUNT_VALUE_RE = re.compile(r"^\d{1,3}(?:[\s\u00a0\u202f]\d{3})*$")


_MONTH_RE = re.compile(r"^(?:январ|феврал|март|апрел|ма[йяе]|июн|июл|август|сентябр|октябр|ноябр|декабр|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[а-яёa-z]*$", re.I)


def _counted(value: str, label: str, brief_text: str) -> Optional[str]:
    """A bare count («40») whose label does not name what it counts («рост вызван наймом инженеров в облако»): the
    words the brief writes right after it («40 инженеров в облачное направление» → «Инженеров в облачное
    направление»)."""
    v = (value or "").strip()
    if not _COUNT_VALUE_RE.match(v):
        return None
    core = re.escape(v).replace(r"\ ", r"[\s\u00a0\u202f]")
    hits = [m for m in re.finditer(rf"(?<![\d,.]){core}\s+(?P<w>[а-яё][а-яё-]+(?:\s+(?!и\b|а\b|но\b)[а-яё-]+){{0,3}})", brief_text or "", re.I)]
    if len(hits) != 1:
        return None
    words = hits[0].group("w").split()
    if _MONTH_RE.match(words[0]):
        return None  # «1 мая 1999 года» is a date, not a count of «Мая» (jury 20.10, R01: KPI «1 · Мая»)
    if words[0].lower() in {"человек", "чел", "штук", "шт", "единиц", "раз", "позиций"}:
        # «пришли 310 человек»: what is counted is said before the figure, in its clause
        before = re.split(r"[,;:.]\s+|\s[—–]\s", (brief_text or "")[: hits[0].start()])[-1].strip()
        bw = [w for w in before.split() if not re.search(r"\d", w) or re.fullmatch(r"(?:19|20)\d{2}", w)]
        if 1 <= len(bw) <= 6 and len(before.split()) <= 6:
            lab = H.cap_first(before)
            return None if lab.lower() in (label or "").lower() else lab
        return None
    stem = words[0].lower()[:5]
    if stem in " ".join((label or "").lower().split()[:2]):
        return None  # the label names what is counted («Новых кладовщиков»)
    while words and words[-1].lower() in {"в", "на", "с", "по", "к", "из", "за", "для", "до", "от"}:
        words.pop()
    return H.cap_first(" ".join(words)) if words else None


_VALUE_PREP_RE = re.compile(r"^(?:до|на|с|со|в|к)\s+(?=[+\-−]?\d)", re.I)
_VALUE_HEDGE = {"около": "≈", "примерно": "≈", "почти": "≈", "более": ">", "свыше": ">", "больше": ">", "менее": "<", "меньше": "<",
                "не более": "≤", "не свыше": "≤", "не больше": "≤", "не менее": "≥", "не меньше": "≥"}  # «не больше 0,5%» — ≤
_YEAR_VALUE_RE = re.compile(r"^(?:19|20)\d{2}(?:\s*(?:г\.?|год\w*))?$", re.I)


def tidy_values(o: DeckOutline) -> list[str]:
    """A large figure is the figure: a preposition is no part of it («до 1 428 млн ₽» → «1 428 млн ₽»), a hedge is its
    sign («около 74%» → «≈ 74%»), a bare year is no key figure («2026 г» beside a phrase cut short)."""
    said: list[str] = []
    for s in o.slides:
        c = s.content
        keep = []
        for n in c.numbers:
            v = " ".join((n.value or "").split())
            nv = _VALUE_PREP_RE.sub("", v)
            m = re.match(r"^((?:не\s+)?(?:около|примерно|почти|более|свыше|больше|менее|меньше))\s+(?=[+\-−]?\d)", nv, re.I)
            if m and " ".join(m.group(1).lower().split()) in _VALUE_HEDGE:
                nv = f"{_VALUE_HEDGE[' '.join(m.group(1).lower().split())]} {nv[m.end():]}"
            if nv != v:
                said.append(f"slide {s.id}: the figure «{v}» → «{nv}»")
                n.value = nv
            if _YEAR_VALUE_RE.match(nv):
                said.append(f"slide {s.id}: the year «{nv}» is no key figure — dropped")
                continue
            keep.append(n)
        c.numbers = keep
        if s.kind in (PatternKind.big_number, PatternKind.stat_row) and not keep and not (c.bullets or c.paragraphs or c.items or c.chart or c.table):
            s.kind = PatternKind.bullets  # (its one figure was a year: the slide says its heading and its words)
    return said


def label_figures(o: DeckOutline, brief_text: str) -> list[str]:
    said: list[str] = []
    for s in o.slides:
        for n in s.content.numbers:
            lab = _counted(n.value, n.label, brief_text)
            if lab:
                said.append(f"slide {s.id}: the count {n.value} labelled by what it counts «{lab}» (was «{n.label}»)")
                n.label = lab
        nums = s.content.numbers
        if not nums:
            continue
        keep = []
        for n in nums:
            if _weak_label(n.value, n.label):
                lab = _label_from(n.value, brief_text)
                if lab and not _weak_label(n.value, lab):
                    said.append(f"slide {s.id}: the figure {n.value} labelled «{lab}» (was «{n.label}»)")
                    n.label = lab
                elif len(nums) > 1:
                    said.append(f"slide {s.id}: the figure {n.value} «{n.label}» says nothing of what it is — dropped")
                    continue
            keep.append(n)
        # a small bare number the brief never writes as a figure is an ordinal or a count made up from words («На
        # втором этапе» → «2 · Этап хакатона», jury 20.10 R04): no key figure of the slide
        c = s.content
        if brief_text:
            for n in [n for n in keep if _unstated_small(n.value, brief_text)]:
                text_left = bool(c.bullets or c.paragraphs or c.items or c.columns or c.chart or c.table)
                if len(keep) > 1 or text_left:
                    keep.remove(n)
                elif s.takeaway and s.kind in (PatternKind.big_number, PatternKind.stat_row):
                    # the slide's one «figure» was made up: its conclusion line is its text
                    keep.remove(n)
                    c.paragraphs = [s.takeaway]
                    s.takeaway = None
                    s.kind = PatternKind.bullets
                else:
                    continue
                said.append(f"slide {s.id}: the figure {n.value} «{n.label}» is not a figure of the brief — dropped")
        s.content.numbers = keep
    return said


_SMALL_INT_RE = re.compile(r"^\s*(\d{1,2})\s*$")


def _unstated_small(value: str, brief_text: str) -> bool:
    m = _SMALL_INT_RE.match(value or "")
    if not m or int(m.group(1)) > 12:
        return False
    n = m.group(1)
    for hit in re.finditer(rf"(?<![\d.,]){n}(?![\d]|[.,]\d)", brief_text):
        before, after = brief_text[max(0, hit.start() - 2):hit.start()], brief_text[hit.end():hit.end() + 2]
        if re.match(r"[.)]\s", after) and (hit.start() == 0 or before.endswith(("\n", "# ", "  "))):
            continue  # «2. Требования к сервису»: the number of a list item
        if re.match(r"\s?[–—-]\s?\d", after) or re.search(r"\d\s?[–—-]\s?$", before):
            continue  # «2–3 варианта»: a range
        return False
    return True


# ------------------------------------------------------------------ a heading that says the slide's point


_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_HEAD_MAX_WORDS = 11


def _has_figure(text: str) -> bool:
    return bool(re.search(r"\d", _YEAR_RE.sub("", re.sub(r"\b\d{1,2}\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", "", text or "", flags=re.I))))


def _shown_norm(s: OutlineSlide) -> str:
    return " ".join(_slide_text(s).lower().split())


# a sentence that states a result: a total, a change, a level against a goal
_RESULT_RE = re.compile(
    r"\b(?:составит|составил[аио]?|составляет|составят|достиг\w*|вырос\w*|выраст\w*|увеличил\w*|сократил\w*|снизил\w*|"
    r"упал\w*|выше|ниже|больше|меньше|рост\w*|падени\w*|экономи\w*|окуп\w*|прибыл\w*|убыт\w*|загрузк\w*|остаются|осталось|"
    r"выполнен\w*|при\s+цели|итог\w*|безубыточн\w*|дефицит\w*|не\s+хватает|недостат\w*|рентабельн\w*|вдвое|втрое|в\s+\d+(?:[.,]\d+)?\s+раза?)\b",
    re.I,
)
# a sentence that goes on from another one or supposes: never a slide's point on its own
_CONT_RE = re.compile(
    r"^(?:ещ[её]|также|дополнительно|кроме\s+того|при\s+этом|для\b|из\s+них|из\s+этой|в\s+том\s+числе|например|это\b|эти\b|"
    r"этот\b|он\b|она\b|оно\b|они\b|его\b|её\b|их\b|предположим|допустим|если\b|по\s+предварительн|однако|но\b|а\b|и\b|поэтому|"
    r"зато|причём|причем|то\s+есть)",
    re.I,
)


def _point_ok(sent: str, max_words: int = _HEAD_MAX_WORDS) -> bool:
    """A sentence that can head the slide: a short complete statement of a result with its figure («За месяц 412 000
    установок при цели 300 000», «Средняя загрузка составит около 74%») — not a lead-in «…:», a question, a «label:
    value» line, a sentence that goes on from another («Ещё 850 000 рублей …», «Для учебного проекта предположим …»)
    or an ask to the designer."""
    from verstka.planning.directives import split_directive

    t = H.strip_end(sent or "")
    n = len(re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}\b)", "", t).split())  # «1 840» is one word of the heading
    if not t or t.endswith((":", "?")) or not _has_figure(t) or n > max_words or n < 4:
        return False
    if not (t[:1].isupper() or t[:1].isdigit()) or _CONT_RE.match(t):
        return False
    lab = re.match(r"^([^:]{1,60}):\s", t)
    if lab and len(lab.group(1).split()) <= 5:
        return False
    if not _RESULT_RE.search(t):
        return False
    return split_directive(t)[0] is None


def _chart_figures(s: OutlineSlide) -> set[float]:
    return {round(v, 2) for vals in _chart_values(s) for v in vals}


def _restates_chart(text: str, s: OutlineSlide) -> bool:
    """A line that only lists the figures the slide's chart draws («Каждую неделю больше: 61 000, 88 000, …»)."""
    from verstka.planning.brief_structure import numbers_of

    figs = {round(v, 2) for v in numbers_of(text or "")}
    shown = _chart_figures(s)
    words = re.findall(r"[а-яёa-z]{2,}", (text or "").lower())
    return len(figs) >= 3 and bool(shown) and figs <= shown and len(words) <= 4


def conclusion_headlines(o: DeckOutline, model: bool = False) -> list[str]:
    """A slide headed by its topic («Удержание», «Установки») whose own text states its point with a figure gets that
    sentence as its heading — the author's words as written, moved, not repeated (the topic stays the slide's
    section): its conclusion line, else a sentence of its notes the slide does not show (the author's text laid out
    as written keeps it there), else its first short sentence when the slide keeps other content."""
    from verstka.planning.faithful import sentences

    said: list[str] = []
    for s in o.slides:
        c = s.content
        if s.takeaway and _restates_chart(s.takeaway, s):
            said.append(f"slide {s.id}: the conclusion line «{s.takeaway[:60]}» only listed the chart's figures — dropped")
            s.takeaway = None
        if s.kind in _FRAME or not _topic(s.headline) or _asks(s) or s.kind in (PatternKind.quote,):
            continue
        if model and len(H.strip_end(s.headline).split()) > 3:
            continue  # a model's heading stays unless it is a bare topic («Хронология», «Оценки», «Главное в цифрах»)
        pick: Optional[str] = None
        where = ""
        if s.takeaway and _point_ok(s.takeaway):
            pick, where = s.takeaway, "takeaway"
        if pick is None and s.notes and not s.takeaway:  # (beside a conclusion line a longer heading leaves it no room)
            shown = _shown_norm(s)
            for sent in sentences(s.notes):
                # (a sentence of the notes adds words to the slide: only a short one heads it)
                if _point_ok(sent, 9) and " ".join(H.strip_end(sent).lower().split()) not in shown and not _restates_chart(sent, s):
                    pick, where = sent, "notes"
                    break
        if pick is None:
            other = bool(c.chart or c.table or c.numbers or c.items or c.columns or len(c.bullets) + len(c.paragraphs) >= 2)
            for field in ("bullets", "paragraphs"):
                lines = getattr(c, field)
                for k, line in enumerate(lines):
                    ss = sentences(line) or [line]
                    if _point_ok(ss[0]) and (other or len(ss) >= 2):
                        pick, where = ss[0], f"{field}:{k}"
                        break
                if pick:
                    break
        if pick is None:
            # a slide of one short sentence that states its result («48 200 заказов, на 12% больше, чем в августе»): the
            # sentence heads it and its own figures stand large under it, each with its words from the sentence
            lone = [*c.bullets, *c.paragraphs]
            if len(lone) == 1 and not (c.chart or c.table or c.numbers or c.items or c.columns) and len(sentences(lone[0]) or [lone[0]]) == 1 and _point_ok(lone[0]):
                nums = _figures_of(lone[0])
                if nums:
                    old = s.headline
                    s.headline = H.strip_end(lone[0])
                    s.section = s.section or old
                    c.bullets, c.paragraphs, c.numbers = [], [], nums
                    s.kind = PatternKind.big_number if len(nums) == 1 else PatternKind.stat_row
                    said.append(f"slide {s.id}: the topic heading «{old}» → its one sentence «{s.headline[:70]}», its figures large")
            continue
        old = s.headline
        s.headline = H.strip_end(pick)
        if not s.section:
            s.section = old
        if where == "takeaway":
            s.takeaway = None
        elif ":" in where:
            field, k = where.split(":")
            lines = getattr(c, field)
            rest = " ".join(x for x in (sentences(lines[int(k)]) or [lines[int(k)]])[1:]).strip()
            if rest:
                lines[int(k)] = rest
            else:
                lines.pop(int(k))
        said.append(f"slide {s.id}: the topic heading «{old}» → the slide's own point «{s.headline[:70]}» ({where.split(':')[0]})")
    return said


_VAL = r"[+\-−]?\d{1,3}(?:[\s\u00a0\u202f]\d{3})*(?:[.,]\d+)?\s?(?:%|млн\s?₽|млрд\s?₽|тыс\.?\s?₽|₽|млн|млрд|тыс\.?|руб\w*|м²|ч|дн\w*|шт\.?|чел\.?)?"
_FIG_CLAUSE_RES = (
    re.compile(rf"^(?P<label>[^—–:]{{2,50}}?)\s*[—–:]\s*(?P<val>{_VAL})$", re.I),  # «Выручка — 312 млн ₽», «План на 4 квартал — 360 млн ₽»
    re.compile(rf"^(?P<label>[^\d—–:]{{3,40}}?)\s+(?P<val>{_VAL})$", re.I),  # «Новых клиентов 57»
    re.compile(rf"^(?P<head>[а-яё]+)\s+(?P<val>{_VAL})\s+(?P<tail>(?:к|в|за|от|по|на)\s+[^,;]{{2,30}})$", re.I),  # «рост 18% к 2 кварталу»
)


def _figures_of(sentence: str) -> list:
    """The figures of a short statement, each with the words its own clause gives it: «Выручка — 312 млн ₽, рост 18% к
    2 кварталу» → 312 млн ₽ «Выручка», 18% «Рост к 2 кварталу»; a clause read no other way gives none (its figure
    stays in the heading)."""
    from verstka.schemas.outline import NumberCallout

    out = []
    for clause in re.split(r",\s+|;\s+", H.strip_end(sentence)):
        clause = clause.strip()
        for k, rx in enumerate(_FIG_CLAUSE_RES):
            m = rx.match(clause)
            if not m:
                continue
            val = " ".join(m.group("val").split())
            lab = f"{m.group('head')} {m.group('tail')}" if k == 2 else m.group("label")
            lab = re.sub(r"\s+(?:—|–|-|составил[аио]?|составляет|составит)$", "", lab.strip(), flags=re.I).strip()
            words = lab.split()
            first = (sentence.split() or [""])[0].lower()
            if not words or len(words) > 6 or (len(words) == 1 and words[0].lower() != first):
                break
            out.append(NumberCallout(value=val, label=H.cap_first(lab)))
            break
    return out[:4]


def tidy(o: DeckOutline) -> list[str]:
    """A conclusion line that repeats a line of the slide (or its heading) is said once."""
    said: list[str] = []
    from verstka.planning.plan_data import _stems as stems

    for s in o.slides:
        c = s.content
        if s.kind == PatternKind.title and (c.paragraphs or c.bullets):
            # a cover's line that only says its title and subtitle once more (qa5: «Verstka — цифровой дизайнер
            # презентаций. Команда «Рекрут 2», задача № 4 VK Tech.» under them) goes
            have = stems(f"{s.headline} {s.subtitle or ''}")
            for field in ("paragraphs", "bullets"):
                lines = getattr(c, field)
                keep = [x for x in lines if not (stems(x) and len(stems(x) & have) >= 0.7 * len(stems(x)))]
                if len(keep) != len(lines):
                    said.append(f"slide {s.id}: the cover's line repeating its title went")
                    setattr(c, field, keep)
        if c.chart is not None and c.chart.title:
            c.chart.title = H.cap_first(c.chart.title)
        if s.subtitle and " ".join(H.strip_end(s.subtitle).lower().split()) == " ".join(H.strip_end(s.headline or "").lower().split()):
            s.subtitle = None  # the subtitle said the heading once more
        hd = " ".join(H.strip_end(s.headline or "").lower().split())
        if s.kind not in _FRAME and hd and not _asks(s):
            # «Топ-5 клиентов дали 41% выручки» as the heading and once more as the slide's one line: said once — its
            # figures large under it when the line was all the slide had
            for field in ("bullets", "paragraphs"):
                lines = getattr(c, field)
                dup = [k for k, x in enumerate(lines) if " ".join(H.strip_end(x).lower().split()) == hd]
                if not dup:
                    continue
                rest = len(c.bullets) + len(c.paragraphs) - len(dup)
                others = bool(c.chart or c.table or c.numbers or c.items or c.columns or rest)
                nums = [] if others else _figures_of(s.headline)
                if others or nums:
                    for k in reversed(dup):
                        lines.pop(k)
                    if nums:
                        c.numbers = nums
                        s.kind = PatternKind.big_number if len(nums) == 1 else PatternKind.stat_row
                    said.append(f"slide {s.id}: a line repeated the heading — said once")
        tk = " ".join(H.strip_end(s.takeaway or "").lower().split())
        if not tk:
            continue
        if tk == " ".join(H.strip_end(s.headline).lower().split()):
            s.takeaway = None
            said.append(f"slide {s.id}: the conclusion line repeated the heading — dropped")
            continue
        for field in ("bullets", "paragraphs"):
            lines = getattr(c, field)
            same = [k for k, x in enumerate(lines) if " ".join(H.strip_end(x).lower().split()) == tk]
            for k in reversed(same):
                lines.pop(k)
                said.append(f"slide {s.id}: a line repeated the conclusion line — said once")
    return said


# ------------------------------------------------------------------ the deck's end


_ASKS_RE = re.compile(
    r"\b(?:просим|прошу|предлагаем|предлагаю|утвердить|согласовать|одобрить|выделить|запрашиваем|что\s+просим|что\s+нужно\s+от|"
    r"решение,?\s+которое|что\s+дальше|следующие\s+шаги|дальнейшие\s+шаги|план\s+действий|next\s+steps|призыв)\b",
    re.I,
)
_THANKS_RE = re.compile(r"^(?:спасибо|благодарю|благодарим|thank|вопросы|questions|q\s*&\s*a)", re.I)
_CONCLUSION_RE = re.compile(r"^(?:главный|итоговый|основной|ключевой|общий|финальный)?\s*(?:вывод|итог)\s*[:—–]\s*(?P<t>.+)$", re.I)


def _slide_text(s: OutlineSlide) -> str:
    c = s.content
    bits = [s.headline, s.subtitle or "", s.takeaway or "", *c.bullets, *c.paragraphs]
    bits += [x for it in [*c.items, *c.columns] for x in (it.title, it.text, *it.bullets)]
    return " ".join(b for b in bits if b)


def _asks(s: OutlineSlide) -> bool:
    return s.kind not in (PatternKind.title, PatternKind.thanks) and bool(_ASKS_RE.search(_slide_text(s)))


def _bare_thanks(s: OutlineSlide) -> bool:
    c = s.content
    return s.kind == PatternKind.thanks and bool(_THANKS_RE.match((s.headline or "").strip())) and not (c.bullets or c.paragraphs or c.items or c.numbers)


def _authors_thanks(brief_text: str) -> bool:
    return bool(re.search(r"(?:слайд|slide)\s*№?\s*\d{1,3}\s*[.:)—–-]?\s*(?:«)?(?:спасибо|благодар|вопросы|thank)", brief_text or "", re.I))


def _conclusion(brief_text: str) -> Optional[str]:
    for line in (brief_text or "").splitlines():
        for sent in H.split_sentences(line.strip()) or []:
            m = _CONCLUSION_RE.match(sent.strip())
            if m:
                return H.cap_first(H.strip_end(m.group("t").strip(" «»\"")))
    return None


def close_story(o: DeckOutline, brief_text: str, *, author_order: bool = False) -> list[str]:
    """The deck ends on its point: its conclusion and what it asks for (or what comes next), not a bare farewell."""
    said: list[str] = []
    slides = o.slides
    if len(slides) < 3:
        return said
    last = slides[-1]
    thanks = _bare_thanks(last) and not _authors_thanks(brief_text)
    body = slides[:-1] if _bare_thanks(last) else slides
    # a planner's deck (not the author's own order): the ask / next steps slide goes last
    if not author_order:
        idx = [i for i, s in enumerate(body) if i > 0 and _asks(s)]
        if idx and idx[-1] != len(body) - 1:
            k, end = idx[-1], len(body) - 1
            moved = body[k]
            slides.remove(moved)
            slides.insert(end, moved)
            said.append(f"slide {moved.id}: the ask «{moved.headline[:60]}» moved to the deck's end")
            body = slides[:-1] if _bare_thanks(slides[-1]) else slides
    if not thanks:
        return said
    prev = body[-1]
    if _asks(prev) or _CONCLUSION_RE.match(prev.headline or "") or (prev.takeaway and _CONCLUSION_RE.match(prev.takeaway)):
        # the story ends on its ask: a farewell the author did not write is no slide of it (jury 20.10: «Спасибо за
        # внимание» after the deck's point)
        if len(slides) <= 3:
            return said  # (a deck of a cover and one slide keeps its closing)
        slides.remove(last)
        said.append(f"slide {last.id}: the farewell «{(last.headline or '')[:40]}» dropped — the deck ends on its ask «{prev.headline[:60]}»")
        return said
    from verstka.planning.agent import ask_shown, brief_asks

    shown = " ".join(_slide_text(s) for s in body)
    asks = [sn for _, sn in brief_asks(brief_text) if not ask_shown(sn, shown)] or [sn for _, sn in brief_asks(brief_text)]
    point = _conclusion(brief_text)
    if asks:
        last.headline = H.cap_first(H.strip_end(asks[0]))
        last.subtitle = point if point and point.lower() not in shown.lower() else None
        said.append(f"slide {last.id}: the farewell carries the brief's ask «{last.headline[:60]}»")
    elif point:
        last.headline = point
        last.subtitle = None
        said.append(f"slide {last.id}: the farewell carries the brief's conclusion «{point[:60]}»")
    elif len(slides) > 3:
        # nothing to end on but a farewell: the deck ends on its last slide of content
        slides.remove(last)
        said.append(f"slide {last.id}: the farewell «{(last.headline or '')[:40]}» dropped — no slide of a farewell the author did not write")
    return said


DEFAULT_MAX_SLIDES = 15  # a deck the planner made (no count asked, no slides dictated): 10–15 slides at most


def _weight(s: OutlineSlide) -> float:
    """How much a slide carries: its words, its figures, a chart or a table (a slide of data is worth keeping)."""
    c = s.content
    w = len(_slide_text(s).split()) + 8 * len(c.numbers)
    w += 40 * bool(c.chart or c.table or c.chart2 or c.formula or c.code) + 60 * bool(s.data)
    return float(w)


def cap_slides(o: DeckOutline, limit: Optional[int], brief_text: str = "") -> list[str]:
    """The deck within its size: the count the person asked for («6–8 слайдов», «не более 10», the form's field), or
    DEFAULT_MAX_SLIDES for a deck the planner made. What goes first: section dividers, the agenda, a farewell the
    author did not write, then the slides that carry least — never the cover, never the last slide (the deck's point),
    never a slide the author dictated («Слайд 3. …», an item of the author's plan)."""
    said: list[str] = []
    if not limit or len(o.slides) <= limit:
        return said
    limit = max(2, int(limit))
    authors_thanks = _authors_thanks(brief_text)

    def drop(s: OutlineSlide, why: str) -> None:
        o.slides.remove(s)
        said.append(f"slide {s.id} «{(s.headline or '')[:50]}» dropped: {why} (the deck has at most {limit} slides)")

    for kinds, why in (((PatternKind.section,), "a section divider"), ((PatternKind.agenda,), "the agenda")):
        for s in [x for x in o.slides[1:] if x.kind in kinds]:
            if len(o.slides) <= limit:
                return said
            drop(s, why)
    for s in [x for x in o.slides[1:] if _bare_thanks(x) and not authors_thanks]:
        if len(o.slides) <= limit:
            return said
        drop(s, "a farewell")
    while len(o.slides) > limit and len(o.slides) > 2:
        middle = o.slides[1:-1] if o.slides[0].kind == PatternKind.title else o.slides[:-1]
        pool = [x for x in middle if x.spec_ref is None and not x.continues]
        if not pool:  # the slides the author dictated stay: their count is the author's
            break
        drop(min(pool, key=_weight), "it carries least")
    return said


# ------------------------------------------------------------------ the passes


def finish_deck(outline: DeckOutline, brief_text: str = "", *, author_order: bool = False, limit: Optional[int] = None) -> tuple[DeckOutline, list[str]]:
    """The deck after the meaning passes (a copy) and what they changed, in English (the plan's warnings).
    `author_order`: the slides are the ones the author dictated, in the author's order — no slide is moved. `limit`:
    the deck's size at most (cap_slides), the last pass."""
    o = outline.model_copy(deep=True)
    said: list[str] = []
    from verstka.planning.proportions import check_outline

    # (the proportions before the tables' conclusions: those are counted from the cells, not said by anyone)
    for step in (lambda: scrub_outline(o), lambda: check_outline(o, brief_text), lambda: tidy_values(o), lambda: split_mixed_units(o), lambda: keep_table_beside_chart(o), lambda: keep_author_tables(o, brief_text), lambda: keep_figures(o) if o.planned_by not in ("agent", "model") else [], lambda: table_conclusions(o), lambda: label_figures(o, brief_text),
                 lambda: tidy(o), lambda: conclusion_headlines(o, model=o.planned_by in ("agent", "model")),
                 lambda: close_story(o, brief_text, author_order=author_order),
                 lambda: true_tense(o, brief_text) if o.planned_by in ("agent", "model") else [],
                 lambda: lead_figure(o), lambda: sensible_labels(o, brief_text), lambda: keep_author_points(o, brief_text), lambda: name_cover(o, brief_text), lambda: promised_counts_kept(o), lambda: ensure_cover(o), lambda: cap_slides(o, limit, brief_text)):
        try:
            said.extend(step())
        except Exception:  # noqa: BLE001 - one pass failing leaves the others
            log.warning("meaning pass failed", exc_info=True)
    return o, [f"meaning: {x}" for x in said]


# ------------------------------------------------------------------ the tense of a model's heading


_FUT_SET_RE = re.compile(r"\s+(?:достигнет|достигнут|составит|составят|будет|будут|окажется)(?:\s+(?:до|около|почти))?\s+(?=[+\-−]?\d)", re.I)
_FUT_UP_RE = re.compile(r"\s+(?:вырастет|вырастут|увеличится|увеличатся|возрастёт|возрастет|возрастут|поднимется|поднимутся)\s+(?P<prep>на|до)\s+(?=[+\-−]?\d)", re.I)
_FUT_DOWN_RE = re.compile(r"\s+(?:сократится|сократятся|снизится|снизятся|уменьшится|уменьшатся|упадёт|упадет|упадут)\s+(?P<prep>на|до)\s+(?=[+\-−]?\d)", re.I)
_PAST_SET_RE = re.compile(r"\s+(?:достиг|достигла|достигло|достигли|составил|составила|составило|составили)(?:\s+(?:до|около|почти))?\s+(?=[+\-−]?\d)", re.I)
_PAST_UP_RE = re.compile(r"\s+(?:вырос|выросла|выросло|выросли|увеличил(?:ся|ась|ось|ись))\s+(?P<prep>на|до)\s+(?=[+\-−]?\d)", re.I)
_PAST_DOWN_RE = re.compile(r"\s+(?:сократил(?:ся|ась|ось|ись)|снизил(?:ся|ась|ось|ись)|уменьшил(?:ся|ась|ось|ись)|упал[аои]?)\s+(?P<prep>на|до)\s+(?=[+\-−]?\d)", re.I)
# what tells a plan, a forecast or a goal in the source («вырастет», «план», «прогноз», «цель», «к концу года»)
_PLAN_SRC_RE = re.compile(
    r"\b(?:план\s+на|в\s+плане|прогноз\w*|цел[ьи]\w*|ожида\w*|планир\w*|будет|будут|составит|составят|достигнет|достигнут|вырастет|вырастут|"
    r"увеличится|сократится|снизится|потребуется|окупится|выйдет|получит|получат|к\s+концу|в\s+следующ\w*|на\s+следующ\w*)\b",
    re.I,
)
_DONE_SRC_RE = re.compile(
    r"\b(?:составил\w*|достиг\w*|вырос\w*|вырастил\w*|увеличил\w*|сократил\w*|снизил\w*|упал\w*|выполнен\w*|получил\w*|"
    r"было|была|были|был|за\s+(?:квартал|год|месяц|период)|в\s+(?:прошл|минувш)\w*)\b|\b(?:\w+(?:ил|ила|ило|или|ался|алась|ались|лся|лась|лись))\b",
    re.I,
)


def _figure_sentences(text: str, brief_text: str) -> list[str]:
    """The brief's sentences that state a figure of `text` (by its digits)."""
    from verstka.planning.brief_structure import numbers_of

    want = {round(v, 2) for v in numbers_of(text or "") if not (1900 <= v <= 2100)}
    if not want:
        return []
    out = []
    for line in (brief_text or "").splitlines():
        for sent in H.split_sentences(line.strip()) or []:
            if want & {round(v, 2) for v in numbers_of(sent)}:
                out.append(sent)
    return out


def _neutral(text: str, rx_set, rx_up, rx_down) -> str:
    """«Рентабельность достигнет 22,4%» → «Рентабельность — 22,4%», «Выручка вырастет на 18%» → «Выручка: рост на 18%»
    — the figure without a tense the source does not give it."""
    t = rx_set.sub(" — ", text)
    t = rx_up.sub(lambda m: ": рост на " if m.group("prep").lower() == "на" else " — ", t)
    t = rx_down.sub(lambda m: ": снижение на " if m.group("prep").lower() == "на" else " — ", t)
    return t


_FUTURE_OF = (
    (r"выросли", "вырастут"), (r"вырос(?:ла|ло)?", "вырастет"), (r"составили", "составят"), (r"составил[ао]?", "составит"),
    (r"достигли", "достигнут"), (r"достиг(?:ла|ло)?", "достигнет"), (r"сократились", "сократятся"), (r"сократил(?:ся|ась|ось)", "сократится"),
    (r"снизились", "снизятся"), (r"снизил(?:ся|ась|ось)", "снизится"), (r"увеличились", "увеличатся"), (r"увеличил(?:ся|ась|ось)", "увеличится"),
    (r"уменьшились", "уменьшатся"), (r"уменьшил(?:ся|ась|ось)", "уменьшится"), (r"упали", "упадут"), (r"упал[ао]?", "упадёт"),
)


def _to_future(text: str) -> str:
    """«Выручка выросла до 360 млн ₽» → «Выручка вырастет до 360 млн ₽»: a plan told as a plan (the future of a verb
    is the same for every gender)."""
    for past, fut in _FUTURE_OF:
        new = re.sub(rf"(?<![\wё]){past}(?=\s+(?:на|до|около|почти)?\s*[+\-−]?\d)", fut, text, count=1, flags=re.I)
        if new != text:
            return new
    return text


def true_tense(o: DeckOutline, brief_text: str) -> list[str]:
    """A model's heading or conclusion line never tells a done fact as a plan («рентабельность достигнет 22,4%» for the
    quarter that closed) nor a plan as done («выручка выросла до 360 млн» for next quarter's plan): where every source
    sentence of its figure says the other tense, the figure is said without one («рентабельность — 22,4%»)."""
    said: list[str] = []
    for s in o.slides:
        if s.kind == PatternKind.title:
            continue
        for field in ("headline", "takeaway"):
            text = getattr(s, field) or ""
            if not text:
                continue
            fut = _FUT_SET_RE.search(text) or _FUT_UP_RE.search(text) or _FUT_DOWN_RE.search(text)
            past = _PAST_SET_RE.search(text) or _PAST_UP_RE.search(text) or _PAST_DOWN_RE.search(text)
            if not (fut or past):
                continue
            new = text
            # the figure the verb tells (the one right after it), and the brief's sentences of that figure
            fsrc = _figure_sentences(text[fut.end():fut.end() + 24], brief_text) if fut else []
            psrc = _figure_sentences(text[past.end():past.end() + 24], brief_text) if past else []
            if fut and fsrc and all(not _PLAN_SRC_RE.search(x) for x in fsrc):
                new = _neutral(new, _FUT_SET_RE, _FUT_UP_RE, _FUT_DOWN_RE)
            if past and psrc and all(_PLAN_SRC_RE.search(x) and not _DONE_SRC_RE.search(x) for x in psrc):
                new = _to_future(new)
            if new != text:
                setattr(s, field, " ".join(new.split()))
                said.append(f"slide {s.id}: «{text[:70]}» told its figure in a tense the brief does not — «{getattr(s, field)[:70]}»")
        said.extend(_done_not_goal(s, brief_text))
    return said


_GOAL_HEAD_RE = re.compile(r"^(?:цель|план|прогноз|целевое?\s+значение|target|goal|plan)$", re.I)
_NOW_HEAD_RE = re.compile(r"^(?:сейчас|текущее?(?:\s+значение)?|now|current)$", re.I)


def _done_not_goal(s: OutlineSlide, brief_text: str) -> list[str]:
    """A table or chart a model labelled «Сейчас → Цель» for a change the brief tells as done («снизилась с 96 до 61»):
    «Было → Стало»."""
    c = s.content
    pairs = []
    if c.table is not None and len(c.table.columns) >= 3:
        pairs.append(("table", c.table.columns, " ".join(" ".join(r) for r in c.table.rows)))
    if c.chart is not None and len(c.chart.categories) == 2:
        pairs.append(("chart", c.chart.categories, " ".join(str(v) for x in c.chart.series for v in x.values)))
    out = []
    for where, heads, vals in pairs:
        gi = [k for k, h in enumerate(heads) if _GOAL_HEAD_RE.match((h or "").strip())]
        if not gi:
            continue
        src = _figure_sentences(vals, brief_text)
        if not src or any(_PLAN_SRC_RE.search(x) for x in src) or not all(_DONE_SRC_RE.search(x) for x in src):
            continue
        for k in gi:
            heads[k] = "Стало"
        for k, h in enumerate(heads):
            if _NOW_HEAD_RE.match((h or "").strip()):
                heads[k] = "Было"
        out.append(f"slide {s.id}: the {where} said «Цель» for what the brief tells as done — «Было → Стало»")
    return out


# ------------------------------------------------------------------ the large figure says the heading's point


def lead_figure(o: DeckOutline) -> list[str]:
    """A slide of large figures whose heading states a figure none of them shows («Операционные расходы выросли на 6% до
    1 428 млн ₽» over a large «40»): the heading's figure comes first, large, with the words the heading gives it."""
    from verstka.planning.brief_structure import numbers_of
    from verstka.schemas.outline import NumberCallout

    said: list[str] = []
    for s in o.slides:
        c = s.content
        if s.kind not in (PatternKind.big_number, PatternKind.stat_row) or not c.numbers:
            continue
        head_vals = [v for v in numbers_of(s.headline or "") if not (1900 <= v <= 2100)]
        if not head_vals:
            continue
        shown = {round(v, 2) for n in c.numbers for v in numbers_of(n.value)}
        if any(round(v, 2) in shown for v in head_vals):
            continue
        pairs = [numbers_of(n.value) for n in c.numbers if "→" in n.value]
        if any(len(p) == 2 and any(abs(round(v, 2) - round(abs(p[1] - p[0]), 2)) < 0.01 or (p[0] and abs(v - abs(p[1] - p[0]) / abs(p[0]) * 100) < 1)
                                   for v in head_vals) for p in pairs):
            continue  # the heading says the change the large «47 → 29» shows (18 minutes, −38%)
        kp = [k for k in H.kpis_of(s.headline) if k.value and re.search(r"\d", k.value)]
        # the figure with a unit (money, a share) first: what the heading measures
        kp.sort(key=lambda k: (not re.search(r"₽|%|руб|млн|млрд|тыс|\$|€", k.value), -len(k.value)))
        if not kp:
            continue
        k = kp[0]
        lab = H.strip_end(k.label or "")
        if _weak_label(k.value, lab) or len(lab.split()) > 7 or re.search(r"\d", lab):
            subj = re.split(r"\s+(?:\w+(?:ли|ла|ло|л|ет|ют|ит|ат|ят|ся|сь))\b", s.headline, maxsplit=1)[0]
            lab = H.strip_end(subj) if 1 <= len(subj.split()) <= 5 and not re.search(r"\d", subj) else ""
        if not lab:
            continue
        c.numbers = [NumberCallout(value=k.value, label=H.cap_first(lab)), *c.numbers][:4]
        if s.kind == PatternKind.big_number and len(c.numbers) > 1:
            s.kind = PatternKind.stat_row
        said.append(f"slide {s.id}: the heading's figure {k.value} set large first (the large figures showed none of it)")
    return said


# ------------------------------------------------------------------ the cover


def ensure_cover(o: DeckOutline) -> list[str]:
    """Every deck opens on its cover: a deck whose first slide is content (the author dictated «Слайд 1: Что
    запустили», a model planned it so) gets one with the deck's title."""
    if not o.slides or o.slides[0].kind == PatternKind.title:
        return []
    title = H.strip_end(o.title or "")
    if not title or title.lower() == "презентация":
        return []
    ids = {s.id for s in o.slides}
    sid = next(x for x in ("cover", "sl0", "cover-0", "cover-1") if x not in ids)
    o.slides.insert(0, OutlineSlide(id=sid, kind=PatternKind.title, headline=title, subtitle=o.subtitle,
                                    rationale="Обложка с названием колоды: автор начал сразу с содержания."))
    return [f"a cover «{title[:60]}» before the first slide «{o.slides[1].headline[:40]}»"]


# ------------------------------------------------------------------ three variants of one deck without a model


_QUESTION_HEAD_RE = re.compile(r"^(?:сколько|как|что|где|когда|почему|зачем|кто|какой|какая|какие|каких|откуда|куда|чем)\b", re.I)
_LEAD_PREP_RE = re.compile(r"^(?:на|в|до|с|со|к|по|за|от|из|при|около|почти|более|менее|свыше)\s+", re.I)


def _thin(s: OutlineSlide, sentences_max: int = 1, words_max: int = 30) -> Optional[str]:
    """The one line a slide of text says (one line of bullets or paragraphs of at most `sentences_max` sentences and
    `words_max` words, nothing else), None for any other slide."""
    c = s.content
    if s.kind in _FRAME or s.kind in (PatternKind.quote,) or c.chart or c.chart2 or c.table or c.numbers or c.items or c.columns or c.code or c.formula:
        return None
    if c.photo_slot or c.image_hint or s.data is not None:
        return None
    lines = [*c.bullets, *c.paragraphs]
    if len(lines) != 1:
        return None
    from verstka.planning.faithful import sentences

    ss = sentences(lines[0]) or [lines[0]]
    return lines[0] if len(ss) <= sentences_max and len(lines[0].split()) <= words_max else None


def _kpi_label(topic: str, clause: str, value: str) -> str:
    t = H.strip_end(topic or "")
    if t and not _QUESTION_HEAD_RE.match(t) and len(t.split()) <= 5 and not re.search(r"\d", t):
        return t
    lab = (clause or "").replace(value, " ")
    lab = re.sub(r"\d[\d\s  .,]*\s*(?:%|млн|млрд|тыс\.?|₽|руб\w*)?", " ", lab)
    lab = " ".join(lab.split()).strip(" ,;:—–-")
    lab = _LEAD_PREP_RE.sub("", lab)
    # (only a word or two of the clause itself: «заказов»; a clause cut around its figure — «у старого приложения было
    # и» — is no label)
    if not lab or len(lab.split()) > 2 or re.search(r"\b(?:и|а|но|или|было|были|был|была)$", lab, re.I):
        return ""
    return H.cap_first(lab)


def _as_figure(s: OutlineSlide, line: str) -> bool:
    """A slide of one sentence with a figure, shown large: the sentence heads it (its point), the figure under it with
    the slide's subject («Ошибки комплектации») or its own words as the label. False when the sentence has no figure."""
    if not _topic(s.headline):
        return False  # the heading already states the slide's point: it stays
    kp = H.kpis_of(line)
    if not kp:
        return False
    k = kp[0]
    head = H.strip_end(line)
    n = len(re.sub(r"(?<=\d)[\s  ](?=\d{3}\b)", "", head).split())
    if n > 14 or head.endswith((":", "?")):
        return False
    label = _kpi_label(s.headline, k.clause, k.value)
    if not label:
        return False
    old = s.headline
    s.headline = head
    s.section = s.section or old
    s.content.bullets, s.content.paragraphs = [], []
    s.content.numbers = [NumberCallout(value=k.value, label=label)]
    s.kind = PatternKind.big_number
    return True


def _merge_pair(a: OutlineSlide, la: str, b: OutlineSlide, lb: str) -> None:
    """Two neighbouring slides of one sentence each as one slide of two columns: each column the slide's subject and its
    sentence; the heading — the first sentence when it states its point, else the two subjects."""
    ta, tb = H.strip_end(a.headline), H.strip_end(b.headline)
    a.content.bullets, a.content.paragraphs = [], []
    a.content.columns = [SlideItem(title=ta, text=H.strip_end(la) + "."), SlideItem(title=tb, text=H.strip_end(lb) + ".")]
    a.kind = PatternKind.two_column
    if _asks(b):
        # the problem beside what is asked for it: the ask heads the slide, the deck still ends on it
        a.headline = tb
        a.content.columns[1] = SlideItem(title="Что предлагаем", text=H.strip_end(lb) + ".")
    elif _point_ok(la, 10):
        a.headline = H.strip_end(la)
    elif len(ta.split()) + len(tb.split()) <= 7 and not _QUESTION_HEAD_RE.match(tb):
        a.headline = f"{ta} и {tb[:1].lower() + tb[1:] if not (len(tb) > 1 and tb[1:2].isupper()) else tb}"
    a.section = a.section or ta
    a.notes = "\n\n".join(x for x in (a.notes, b.notes) if x)


def _same_slide(a: OutlineSlide, b: OutlineSlide) -> bool:
    return a.kind == b.kind and H.strip_end(a.headline) == H.strip_end(b.headline) and _slide_text(a) == _slide_text(b)


def diversify_variants(outlines: dict, limit: Optional[int] = None) -> dict[str, list[str]]:
    """Three variants of a deck the rules laid out (no model) that came out alike — the same form on most slides (jury
    20.10, R14: all 7 slides alike in the three) — take the forms their strategies stand for: the visual one shows a
    slide's one stated figure large under the sentence that states it (the slide's point heads it), the compact one
    puts two neighbouring slides of one sentence each side by side (fewer slides). The structured one stays as laid out.
    The author's sentences stay whole; only their places change. Returns what changed per variant."""
    said: dict[str, list[str]] = {}
    base = outlines.get("structured")
    if base is None:
        return said
    for name in ("visual", "compact"):
        o = outlines.get(name)
        if o is None or len(o.slides) != len(base.slides):
            continue
        alike = sum(1 for a, b in zip(base.slides, o.slides) if _same_slide(a, b))
        if alike < max(2, (len(o.slides) + 1) // 2):
            continue
        out: list[str] = []
        if name == "visual":
            for s in o.slides[1:]:
                line = _thin(s)
                if line and _as_figure(s, line):
                    out.append(f"slide {s.id}: its figure shown large under the sentence that states it")
        else:
            k = 1
            while k < len(o.slides) - 1:
                a, b = o.slides[k], o.slides[k + 1]
                la, lb = _thin(a, 3, 45), _thin(b, 3, 45)
                if la and lb and not _asks(a) and (not _asks(b) or k + 1 == len(o.slides) - 1):
                    _merge_pair(a, la, b, lb)
                    o.slides.remove(b)
                    out.append(f"slide {a.id}: «{H.strip_end(la)[:40]}» and «{H.strip_end(lb)[:40]}» side by side")
                k += 1
        if out:
            said[name] = out
    return said



# ------------------------------------------------------------------ what a key figure's label says


_MONTHS = r"(?:январ|феврал|март|апрел|ма[йяе]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-яё]*"
_COMPARE_LABEL_RE = re.compile(r"^(?:на\s+)?(?:больше|меньше|выше|ниже|дороже|дешевле|быстрее|медленнее|рост|снижение|прирост)$", re.I)
_UNIT_NOUNS = {"строк", "слайдов", "слайда", "минут", "минуты", "секунд", "часов", "часа", "дней", "дня", "раз", "раза", "шагов", "пунктов",
               "вариантов", "символов", "страниц", "штук", "единиц", "позиций"}


def _source_of(s: OutlineSlide, brief_text: str) -> str:
    return " ".join(x for x in (s.headline, s.subtitle or "", s.takeaway or "", s.notes or "", brief_text or "") if x)


def _value_re(value: str) -> str:
    return re.escape(" ".join(value.split())).replace(r"\ ", r"[\s\u00a0\u202f]?")


def sensible_labels(o: DeckOutline, brief_text: str) -> list[str]:
    """Every key figure says what it is (jury 20.10, round 2): a day of a date is no figure («15 · Кампания» of «по 15
    октября»); a bare comparison word is no label — the words that finish it are («12% · Больше» → «Больше, чем в
    августе»); a share labelled by a lone noun takes the slide's subject («0,8% · Заказов» → «Ошибки комплектации»); a
    count of a unit noun beside other content is a requirement, not a result («200 · Строк»)."""
    said: list[str] = []
    for s in o.slides:
        c = s.content
        if not c.numbers:
            continue
        src = _source_of(s, brief_text)
        keep: list[NumberCallout] = []
        for n in c.numbers:
            v = " ".join((n.value or "").split())
            lab = H.strip_end(n.label or "").strip()
            low = lab.lower()
            if not re.search(r"\d", v) and not re.search(r"[×≈∞]", v) and len(c.numbers) > 1:
                said.append(f"slide {s.id}: «{v} · {lab}» has no figure — it is no key figure, dropped")
                continue  # («Яндекс · Профиль CTO» beside «14 · Команда»: a word is no key figure)
            if re.match(r"^слайд", low) or re.search(r"слайд(?:ов|а)?$", f"{v} {low}"):
                said.append(f"slide {s.id}: «{v} · {lab}» is the deck's size said to the planner — dropped")
                continue
            if re.fullmatch(r"\d{1,2}", v) and re.search(rf"(?<![\d,.]){re.escape(v)}\s+{_MONTHS}\b", src, re.I):
                said.append(f"slide {s.id}: «{v} · {lab}» is a day of a date, not a figure — dropped")
                continue
            if _COMPARE_LABEL_RE.match(low):
                m = re.search(rf"{_value_re(v)}\s+(?P<t>(?:больше|меньше|выше|ниже|дороже|дешевле|быстрее|медленнее)[^.;:]{{0,40}})", src, re.I)
                if m:
                    t = H.strip_end(m.group("t").strip(" ,"))
                    n.label = H.cap_first(t)
                    said.append(f"slide {s.id}: the label of {v} says what it compares: «{n.label}»")
                else:
                    n.label = ""
            elif len(lab.split()) == 1 and "%" in v and s.section and not _QUESTION_HEAD_RE.match(s.section) and len(s.section.split()) <= 5:
                n.label = H.cap_first(H.strip_end(s.section))
                said.append(f"slide {s.id}: the share {v} labelled by the slide's subject «{n.label}»")
            elif low in _UNIT_NOUNS and (len(c.numbers) > 1 or c.bullets or c.paragraphs or c.items):
                said.append(f"slide {s.id}: «{v} · {lab}» counts a unit, it is no key figure — dropped")
                continue
            if not (n.label or "").strip() and len(c.numbers) > 1:
                said.append(f"slide {s.id}: the figure {v} says nothing of what it is — dropped")
                continue
            keep.append(n)
        if keep or not (c.bullets or c.paragraphs or c.items or c.chart or c.table):
            c.numbers = keep or c.numbers
        else:
            c.numbers = []
            if s.kind in (PatternKind.big_number, PatternKind.stat_row):
                s.kind = PatternKind.bullets
    return said



_STEM5_RE = re.compile(r"[а-яёa-z]{5,}", re.I)


def _stems5(text: str) -> set[str]:
    return {w.lower()[:5] for w in _STEM5_RE.findall(text or "")}


def keep_author_points(o: DeckOutline, brief_text: str) -> list[str]:
    """A slide the author dictated keeps the author's points (jury 20.10, round 2: with the model down, «Что дальше» became
    a large «×2» over «В ноябре ускорить синхронизацию в 2 раза» — the dark theme and the family plan were gone): a
    sentence of the author's slide whose words the slide does not show comes back as a line of it."""
    if not brief_text or not any(x.spec_ref is not None for x in o.slides):
        return []
    from verstka.planning.brief_structure import is_photo_instruction, read_structure
    from verstka.planning.directives import split_directive
    from verstka.planning.agent import adds_nothing
    from verstka.planning.faithful import designer_ask, sentences

    try:
        specs = {sp.number: sp for sp in read_structure(brief_text).specs}
    except Exception:  # noqa: BLE001 - the slides as made
        return []
    said: list[str] = []
    for s in o.slides:
        sp = specs.get(s.spec_ref) if s.spec_ref is not None else None
        c = s.content
        if sp is None or s.kind in _FRAME or c.table is not None or c.code is not None or c.chart is not None or c.chart2 is not None:
            continue
        text = "\n".join(ln for ln in (getattr(sp, "text", "") or "").splitlines() if not ln.lstrip().startswith("|"))
        text = re.sub(r"\[[^\[\]]{3,}\]", " ", text)
        own = [x for x in (sentences(text) or []) if split_directive(x)[0] is None and len(x.split()) >= 4
               and designer_ask(x) is None and not is_photo_instruction(x)
               and not any(adds_nothing(x, ref) or adds_nothing(ref, x) for ref in (s.takeaway, s.subtitle, s.footnote) if ref)]
        shown = _stems5(_slide_text(s) + " " + " ".join(f"{n.value} {n.label}" for n in c.numbers))
        lost = [x for x in own if len(_stems5(x) - shown) >= 2 and len(_stems5(x) - shown) >= 0.4 * max(1, len(_stems5(x)))]
        if not lost or len(_slide_text(s).split()) > 60:
            continue
        c.bullets = [*c.bullets, *(H.strip_end(x) + "." for x in lost)][:6]
        said.append(f"slide {s.id}: the author's points back on the slide: " + "; ".join(f"«{x[:40]}»" for x in lost))
    return said



_GENERIC_TITLE_RE = re.compile(r"^(?:презентация|presentation|без названия|untitled|слайды|колода|доклад|питч)$", re.I)


def name_cover(o: DeckOutline, brief_text: str) -> list[str]:
    """A cover titled with a bare word («Презентация») takes the deck's subject: the name the text gives its product or
    project in quotes («Ответ24»), else the deck's own title (jury 20.10, round 3: a startup's pitch under «Презентация»)."""
    if not o.slides or o.slides[0].kind != PatternKind.title:
        return []
    cover = o.slides[0]
    if not _GENERIC_TITLE_RE.match(H.strip_end(cover.headline or "").strip()):
        return []
    name = None
    for m in re.finditer(r"«(?P<n>[A-ZА-ЯЁ0-9][^«»]{1,30})»", brief_text or ""):
        if len(m.group("n").split()) <= 4:
            name = m.group("n").strip()
            break
    if name is None and o.title and not _GENERIC_TITLE_RE.match(H.strip_end(o.title)):
        name = H.strip_end(o.title)
    if not name:
        return []
    old = cover.headline
    cover.headline = name
    if _GENERIC_TITLE_RE.match(H.strip_end(o.title or "")):
        o.title = name
    return [f"slide {cover.id}: the cover «{old}» → the deck's subject «{name}»"]



_UNIT_TAIL_RE = re.compile(r",\s*(?P<u>(?:тыс\.?|млн|млрд|трлн)?\s*(?:₽|руб\.?|рублей|\$|€|%|шт\.?|чел\.?|ч|час\w*|мин|дн\w*|п\.\s?п\.)|(?:тыс\.?|млн|млрд)|%)\s*$", re.I)
_COUNT_NAME_RE = re.compile(r"клиент|заказ|сотрудник|пользовател|человек|подписчик|покупател|заявк|сделк|обращени|штук|единиц|устройств", re.I)


def _series_unit(name: str, unit: Optional[str]) -> Optional[str]:
    if unit:
        return " ".join(unit.lower().split())
    m = _UNIT_TAIL_RE.search(name or "")
    return " ".join(m.group("u").lower().split()) if m else None


def split_mixed_units(o: DeckOutline) -> list[str]:
    """Series of different units never share one axis (jury 20.10, round 3: revenue in млн ₽ and clients in pieces as
    one set of columns — the clients' bars crushed the revenue): each becomes a chart of its own side by side, under
    its name and unit."""
    said: list[str] = []
    for s in o.slides:
        ch = s.content.chart
        if ch is None or ch.split or len(ch.series) < 2 or ch.type in ("pie", "doughnut", "scatter"):
            continue
        units = [_series_unit(x.name, x.unit) for x in ch.series]
        known = {u for u in units if u}
        mixed = len(known) >= 2 or (len(known) == 1 and any(u is None and _COUNT_NAME_RE.search(x.name or "") for u, x in zip(units, ch.series))
                                    and not _COUNT_NAME_RE.search(next(x.name for u, x in zip(units, ch.series) if u)))
        if not mixed:
            continue
        ch.split = True
        for u, x in zip(units, ch.series):
            if u and not x.unit:
                x.unit = u
        said.append(f"slide {s.id}: the chart's series measure different things ({', '.join(x.name for x in ch.series)}) — each on its own axis")
    return said



_COUNT_WORDS = {
    2: r"дв(?:а|е|ух|ум|умя)", 3: r"тр(?:и|ёх|ех|ём|ем|емя|ёмя)", 4: r"четыр(?:е|ёх|ех|ём|ем|ьмя)", 5: r"пят(?:ь|и|ью)",
    6: r"шест(?:ь|и|ью)", 7: r"сем(?:ь|и|ью)", 8: r"восем(?:ь|ью)|восьми", 9: r"девят(?:ь|и|ью)", 10: r"десят(?:ь|и|ью)",
}
_PROMISE_RE = re.compile(
    r"(?<![\wё-])(?<!\bв\s)(?<!\bна\s)(?<!\bдо\s)(?<!\bза\s)(?<!\bот\s)(?P<n>" + "|".join(f"(?:{v})" for v in _COUNT_WORDS.values()) + r"|[2-9]|10)\s+"
    r"(?=[а-яё]{3,})(?!раз|процент|млн|млрд|тыс|год|лет|дн|дне|час|минут|секунд|месяц|недел|рубл|человек|сотрудник|клиент|штук|сантиметр|метр|километр|литр|тонн|градус)",
    re.I,
)


def _promise_value(word: str) -> Optional[int]:
    if word.isdigit():
        return int(word)
    for n, rx in _COUNT_WORDS.items():
        if re.fullmatch(rx, word, re.I):
            return n
    return None


def _shown_count(s: OutlineSlide) -> int:
    c = s.content
    return max(len(c.items), len(c.columns), len(c.numbers), len(c.bullets), len(c.paragraphs) if len(c.paragraphs) > 1 else 0)


def promised_counts_kept(o: DeckOutline) -> list[str]:
    """A heading that promises a number of things the slide does not show («оценивается по трём показателям» over two
    cards, «четыре формулы» over three — jury 20.10, round 3) loses the number: «по показателям», «формулы»."""
    said: list[str] = []
    for s in o.slides:
        if s.kind in _FRAME or s.verbatim or s.content.chart is not None or s.content.table is not None:
            continue  # (the author's own words stay as written)
        shown = _shown_count(s)
        if shown < 2:
            continue
        for attr in ("headline", "subtitle"):
            v = getattr(s, attr) or ""
            m = _PROMISE_RE.search(v)
            if not m:
                continue
            n = _promise_value(m.group("n"))
            if n is None or n == shown or re.search(r"\d", v[m.end():m.end() + 1]):
                continue
            new = (v[: m.start()] + v[m.end():]).strip()
            new = H.cap_first(re.sub(r"\s{2,}", " ", new))
            setattr(s, attr, new)
            said.append(f"slide {s.id}: «{v[:50]}» promised {n}, the slide shows {shown} — the number goes")
    return said
