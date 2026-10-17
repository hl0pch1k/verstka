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
from verstka.schemas.outline import DeckOutline, OutlineSlide, TableData

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
_RATE_RE = re.compile(r"цен|стоимост|средн|дол[яи]|%|процент|ставк|курс|срок|скорост|время|балл|рейтинг|конверси|маржин|рентабел|на\s+одн|за\s+одн|чек|cpl|cpa|ctr|cac|ltv", re.I)
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


def table_conclusion(t: TableData, focus: Optional[list[list[float]]] = None) -> Optional[tuple[str, Optional[str]]]:
    """(the conclusion heading, a line of detail or None) counted from the table's cells; None when the table gives
    no clear one. `focus`: the values of each series a chart of the slide shows — the columns it draws are the ones
    concluded on."""
    if t is None or not t.rows or len(t.columns) < 2:
        return None
    labels, cols, total = _columns(t)
    if not cols or len(labels) < 2:
        return None
    body = [i for i in range(len(labels)) if i != total]
    if focus:
        fsets = [{round(v, 2) for v in f} for f in focus if f]
        hit = [c for c in cols if {round(c.values[i], 2) for i in body if c.values[i] is not None} in fsets]
        if 1 <= len(hit) <= 2:
            cols = hit
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


def table_conclusions(o: DeckOutline) -> list[str]:
    said: list[str] = []
    for s in o.slides:
        if s.kind in _FRAME or s.content.table is None:
            continue
        try:
            got = table_conclusion(s.content.table, _chart_values(s) or None)
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
    stem = words[0].lower()[:5]
    if stem in " ".join((label or "").lower().split()[:2]):
        return None  # the label names what is counted («Новых кладовщиков»)
    while words and words[-1].lower() in {"в", "на", "с", "по", "к", "из", "за", "для", "до", "от"}:
        words.pop()
    return H.cap_first(" ".join(words)) if words else None


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
        s.content.numbers = keep
    return said


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


def conclusion_headlines(o: DeckOutline) -> list[str]:
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
    for s in o.slides:
        c = s.content
        if c.chart is not None and c.chart.title:
            c.chart.title = H.cap_first(c.chart.title)
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
        return said  # the story ends on its ask; the farewell after it is a courtesy, not instead of the point
    from verstka.planning.agent import ask_shown, brief_asks

    shown = " ".join(_slide_text(s) for s in body)
    asks = [sn for _, sn in brief_asks(brief_text) if not ask_shown(sn, shown)] or [sn for _, sn in brief_asks(brief_text)]
    point = _conclusion(brief_text)
    if asks:
        last.headline = H.cap_first(H.strip_end(asks[0]))
        last.subtitle = point if point and point.lower() not in shown.lower() else "Спасибо за внимание"
        said.append(f"slide {last.id}: the farewell carries the brief's ask «{last.headline[:60]}»")
    elif point:
        last.headline = point
        last.subtitle = "Спасибо за внимание"
        said.append(f"slide {last.id}: the farewell carries the brief's conclusion «{point[:60]}»")
    return said


# ------------------------------------------------------------------ the passes


def finish_deck(outline: DeckOutline, brief_text: str = "", *, author_order: bool = False) -> tuple[DeckOutline, list[str]]:
    """The deck after the meaning passes (a copy) and what they changed, in English (the plan's warnings).
    `author_order`: the slides are the ones the author dictated, in the author's order — no slide is moved."""
    o = outline.model_copy(deep=True)
    said: list[str] = []
    for step in (lambda: scrub_outline(o), lambda: table_conclusions(o), lambda: label_figures(o, brief_text),
                 lambda: tidy(o), lambda: conclusion_headlines(o) if o.planned_by not in ("agent", "model") else [],
                 lambda: close_story(o, brief_text, author_order=author_order)):
        try:
            said.extend(step())
        except Exception:  # noqa: BLE001 - one pass failing leaves the others
            log.warning("meaning pass failed", exc_info=True)
    return o, [f"meaning: {x}" for x in said]
