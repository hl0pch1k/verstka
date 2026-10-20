"""The knowledge base checked against the data tables of the same deck (жюри 5: VKT-D «Цели года по качеству не
достигнуты» while in September FCR 71 % ≥ 70 and NPS 46 ≥ 45; E-D «одобрение совета на превышение бюджета > 10 %» at an
overrun of 5 %; L-D goals retold without the facts — MRR 1,82 of 3 million, churn 5,2 % at a goal of 3 %).

A document says what should be (a goal, a norm, a threshold); the tables say what is. Deterministically, without a model:

- the goals of the documents and of the knowledge slides («NPS клиентов поддержки — не ниже 45 к концу года», «20 000
  учеников к 31 декабря», «MRR 3 млн рублей к декабрю») are found with their direction (reach / stay under), figure and
  unit (`goals`);
- each goal meets the figure of the tables it is about — the words of its subject against a column (and a row) of a
  table, the unit of the same kind (% / money / time / count, scales brought together: «тыс. ₽» against «млн рублей»);
  the latest period of a series, the current column of a «Q2 / Q3» pair, the total row of a table by categories; a rate
  or a cost per unit the table gives by two columns («Ушли за месяц» / «Платящих клиентов» — отток, «Затраты» / «Новых
  клиентов» — стоимость привлечения) (`match`);
- a knowledge slide's line that states the goal becomes the comparison («NPS клиентов поддержки: 46 в сентябре при
  цели не ниже 45 к концу года — цель достигнута»), a heading that only named the goal states it; a line that judges the
  goals against the facts («цели не достигнуты», «отставание от плана») goes or is said right; an ask for an approval a
  threshold needs («одобрение совета на превышение бюджета более чем на 10 %») when the plan/fact of the tables stays
  under that threshold is said as the comparison («по положению порог — 10 %, перерасход — 5 %: в пределах»).

Nothing of the data slides is changed. The figures written come from the tables; the slide's notes say which.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from verstka.knowledge.text import tokens

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ figures and units

_MONTHS = {
    "январ": ("январе", 1), "феврал": ("феврале", 2), "март": ("марте", 3), "апрел": ("апреле", 4), "май": ("мае", 5), "мая": ("мае", 5),
    "мае": ("мае", 5), "июн": ("июне", 6), "июл": ("июле", 7), "август": ("августе", 8), "сентябр": ("сентябре", 9), "октябр": ("октябре", 10),
    "ноябр": ("ноябре", 11), "декабр": ("декабре", 12),
}
_TOTAL_RE = re.compile(r"(?i)^\s*(?:итого|всего|total|сумма|в\s+целом)\b")
_TARGET_COL_RE = re.compile(r"(?i)(?<![а-яё])(?:цел[ьи]\w*|целев\w*|план\w*|норм[аы]\w*|норматив\w*|target|plan|goal)(?![а-яё])")
_PAST_HINT_RE = re.compile(r"(?i)(?<![а-яё])(?:до\s+(?!\d)|прошл\w*|предыдущ\w*|было)")
_FIG_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d+))?(?![\w])")


@dataclass(frozen=True)
class Quantity:
    value: float  # in base units: ₽, %, minutes, items
    kind: str  # "money", "pct", "time", "count"
    shown: str = ""  # as the source writes its unit («тыс. ₽», «%», «мин»)


def _num(text: str) -> Optional[float]:
    m = _FIG_RE.search(text or "")
    if not m:
        return None
    whole = re.sub(r"[   ]", "", m.group(1))
    return float(whole + ("." + m.group(2) if m.group(2) else ""))


def _unit_of(text: str) -> tuple[str, float, str]:
    """(kind, scale to base, unit as written) of a unit text: «тыс. ₽», «млн рублей», «%», «мин», «ч», «сек»."""
    t = (text or "").lower().replace("ё", "е")
    scale = 1.0
    if re.search(r"(?<![а-яa-z])(?:трлн)", t):
        scale = 1e12
    elif re.search(r"(?<![а-яa-z])(?:млрд)", t):
        scale = 1e9
    elif re.search(r"(?<![а-яa-z])(?:млн|миллион)", t):
        scale = 1e6
    elif re.search(r"(?<![а-яa-z])(?:тыс|тысяч|k(?![a-z]))", t):
        scale = 1e3
    if re.search(r"₽|руб|rub|\$|€|долл|евро", t):
        return "money", scale, text.strip()
    if re.search(r"%|процент|п\.\s*п", t):
        return "pct", 1.0, "%"
    if re.search(r"(?<![а-яa-z])(?:сек|с)(?![а-яa-z])|секунд", t):
        return "time", 1 / 60, "с"
    if re.search(r"(?<![а-яa-z])(?:мин)\w*", t):
        return "time", 1.0, "мин"
    if re.search(r"(?<![а-яa-z])(?:ч|час\w*)(?![а-яa-z])", t):
        return "time", 60.0, "ч"
    if re.search(r"(?<![а-яa-z])(?:дн\w*|день|сут\w*)(?![а-яa-z])", t):
        return "time", 1440.0, "дн"
    return "count", scale, text.strip()


def _cell_quantity(cell, unit: Optional[str]) -> Optional[Quantity]:
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        kind, scale, shown = _unit_of(unit or "")
        return Quantity(float(cell) * scale, kind, shown)
    s = str(cell).strip()
    v = _num(s)
    if v is None:
        return None
    m = _FIG_RE.search(s)
    rest = s[m.end():].strip() if m else ""
    kind, scale, shown = _unit_of(rest or unit or "")
    return Quantity(v * scale, kind, shown)


def _fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        s = f"{int(round(v)):,}".replace(",", " ")
    else:
        s = f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")
        if abs(v) >= 100:
            s = f"{v:,.0f}".replace(",", " ")
        elif abs(v) >= 10:
            s = f"{v:,.1f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")
    return s


def say(q: Quantity, like: Optional[Quantity] = None) -> str:
    """A quantity as a slide writes it, in the scale of `like` when given («1 820 тыс. ₽» like «3 млн рублей» → «1,82 млн ₽»)."""
    if q.kind == "pct":
        return f"{_fmt(q.value)} %"
    if q.kind == "time":
        unit = (like.shown if like is not None else q.shown) or "мин"
        div = {"с": 1 / 60, "мин": 1.0, "ч": 60.0, "дн": 1440.0}.get(unit, 1.0)
        if like is None and q.value >= 120 and unit == "мин":
            unit, div = "ч", 60.0
        return f"{_fmt(q.value / div)} {unit}"
    if q.kind == "money":
        ref = like if like is not None else q
        _, scale, _ = _unit_of(ref.shown)
        word = {1e3: "тыс. ₽", 1e6: "млн ₽", 1e9: "млрд ₽", 1e12: "трлн ₽"}.get(scale, "₽")
        return f"{_fmt(q.value / scale)} {word}"
    _, scale, _ = _unit_of(q.shown)
    return _fmt(q.value)


# ------------------------------------------------------------------ the tables' facts


# a column of people or items gone («Ушли за месяц», «Отключились») is the churn its rate speaks of; a cost column over a
# column of new clients is the cost of acquiring one («стоимость привлечения», CAC)
_GONE_RE = re.compile(r"(?i)(?<![а-яё])(?:ушл\w*|ушед\w*|ушло|отключ\w*|отказ\w*|отпис\w*|отток\w*|потерян\w*|churn)")
_COST_RE = re.compile(r"(?i)(?<![а-яё])(?:затрат\w*|расход\w*|бюджет\w*|стоимост\w*|траты|cost|spend)")
_NEW_RE = re.compile(r"(?i)(?<![а-яё])(?:нов\w*|привлеч\w*|new)")


@dataclass
class TableFact:
    words: set[str]
    name: str  # what it is, as a heading would say («Решено с первого контакта», «1-я линия, время первого ответа»)
    qty: Quantity
    when: str = ""  # «в сентябре», «в Q3», «на 30.09.2026», «за Q3»
    source: str = ""  # «podderzhka_q3.xlsx, лист «Обращения»»
    row: Optional[str] = None
    current: bool = True  # the latest period of the table
    target: bool = False  # a target column («Цель», «План»)
    spread: list[tuple[str, Quantity]] = field(default_factory=list)  # per-row values of a derived total (cost per client by channel)


def _stems(text: str) -> set[str]:
    return set(tokens(text or ""))


def _period_of(label: str) -> Optional[tuple[str, int]]:
    """(«в сентябре», order) of a period label: a month, a quarter, a date; None — not a period."""
    t = (label or "").strip().lower().replace("ё", "е")
    for k, (prep, n) in _MONTHS.items():
        if re.match(rf"^{k}\w*(?:\s+\d{{4}})?$", t):
            year = re.search(r"\d{4}", t)
            return f"в {prep}" + (f" {year.group(0)}" if year else ""), n + (int(year.group(0)) * 12 if year else 0)
    m = re.match(r"^(?:q|кв\.?\s*|квартал\s*)?([1-4])(?:\s*(?:кв\.?|квартал))?(?:\s+(\d{4}))?$", t)
    if m and ("q" in t or "кв" in t):
        return f"в Q{m.group(1)}", int(m.group(1)) * 3 + (int(m.group(2)) * 12 if m.group(2) else 0)
    m = re.match(r"^(\d{4})[-.](\d{1,2})$", t) or re.match(r"^(\d{1,2})[-.](\d{4})$", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        y, mo = (a, b) if a > 31 else (b, a)
        return f"в {mo:02d}.{y}", y * 12 + mo
    if re.match(r"^\d{4}$", t):
        return f"в {t} году", int(t) * 12
    return None


def _col_period(name: str) -> tuple[str, Optional[int]]:
    """(«в Q3» / «на 30.09.2026», order) a column name carries, the name without it."""
    m = re.search(r"(?i)\b(?:q|кв\.?\s*)([1-4])\b(?:\s+(\d{4}))?", name)
    if m:
        return f"в Q{m.group(1)}", int(m.group(1)) * 3 + (int(m.group(2)) * 12 if m.group(2) else 0)
    m = re.search(r"(?i)\bна\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", name)
    if m:
        y = int(m.group(3) or 0)
        return f"на {m.group(0)[3:].strip()}", (y * 12 + int(m.group(2))) * 31 + int(m.group(1))
    m = re.search(r"\b(20\d\d)\b", name)
    if m:
        return f"в {m.group(1)} году", int(m.group(1)) * 12
    if re.search(r"(?i)\bпосле\b", name):
        return "после", 2
    if re.search(r"(?i)\bдо\b(?!\s+\d)", name):
        return "до", 1
    return "", None


def _base_name(name: str) -> str:
    t = re.sub(r"(?i)\b(?:q|кв\.?\s*)[1-4]\b(?:\s+\d{4})?|\bна\s+\d{1,2}\.\d{1,2}(?:\.\d{2,4})?|\b20\d\d\b|\b(?:до|после)\b", "", name)
    return " ".join(t.split()).strip(" ,—–-")


def _source(t) -> str:
    return f"{t.file}" + (f", лист «{t.sheet}»" if getattr(t, "sheet", None) else "")


def table_facts(tables: Sequence) -> list[TableFact]:
    """Every figure of the tables a goal may be about: a series' latest value, a category's value in the current
    column, a total row; a rate and a cost per unit two columns give."""
    out: list[TableFact] = []
    for t in tables or []:
        try:
            out.extend(_facts_of(t))
        except Exception:  # noqa: BLE001 - a table of an unusual shape gives none
            log.debug("facts of %s not read", getattr(t, "file", "?"), exc_info=True)
    return out


def _facts_of(t) -> list[TableFact]:
    cols = list(t.columns or [])
    rows = [r for i, r in enumerate(t.rows or []) if i not in set(t.totals or [])]
    totals = [r for i, r in enumerate(t.rows or []) if i in set(t.totals or []) or (r and isinstance(r[0], str) and _TOTAL_RE.match(r[0]))]
    rows = [r for r in rows if not (r and isinstance(r[0], str) and _TOTAL_RE.match(r[0]))]
    if len(cols) < 2 or not rows:
        return []
    units = list(t.units or []) + [None] * len(cols)
    src = _source(t)
    sheet = getattr(t, "sheet", None) or ""
    label_col = 0
    periods = [_period_of(str(r[0])) if r and r[0] is not None else None for r in rows]
    series = sum(1 for p in periods if p) >= max(2, len(rows) - 1)
    numeric = []
    for j in range(1, len(cols)):
        qs = [_cell_quantity(r[j] if j < len(r) else None, units[j]) for r in rows]
        if sum(1 for q in qs if q is not None) >= max(1, len(rows) // 2):
            numeric.append((j, qs))
    out: list[TableFact] = []
    # the columns of one measure at several periods («Время первого ответа Q2», «… Q3»): the latest is the current one
    by_base: dict[str, list[tuple[int, Optional[int]]]] = {}
    for j, _ in numeric:
        when, order = _col_period(cols[j])
        by_base.setdefault(_base_name(cols[j]).lower(), []).append((j, order))
    latest = {}
    for base, js in by_base.items():
        ordered = [x for x in js if x[1] is not None]
        if len(ordered) >= 2:
            top = max(ordered, key=lambda x: x[1])[0]
            for j, _ in js:
                latest[j] = j == top
    if series:
        for j, qs in numeric:
            last = next(((periods[i], q) for i in range(len(rows) - 1, -1, -1) if (q := qs[i]) is not None and periods[i]), None)
            if last is None:
                continue
            (when, _), q = last
            out.append(TableFact(words=_stems(cols[j]) | _stems(sheet), name=_base_name(cols[j]) or cols[j], qty=q, when=when, source=src,
                                 target=bool(_TARGET_COL_RE.search(cols[j]))))
        # a rate of two count columns («Ушли за месяц» of «Платящих клиентов»): the churn
        counts = [(j, qs) for j, qs in numeric if all(q is None or q.kind == "count" for q in qs)]
        for ja, qa in counts:
            if not _GONE_RE.search(cols[ja]):
                continue
            for jb, qb in counts:
                if jb == ja:
                    continue
                i = next((i for i in range(len(rows) - 1, -1, -1) if qa[i] is not None and qb[i] is not None and qb[i].value and periods[i]), None)
                if i is None or qa[i].value >= qb[i].value:
                    continue
                rate = Quantity(round(qa[i].value / qb[i].value * 100, 1), "pct", "%")
                out.append(TableFact(words=_stems(cols[ja]) | _stems(cols[jb]) | _stems("отток") | _stems(sheet), name=f"Отток ({cols[ja].lower()} / {cols[jb].lower()})",
                                     qty=rate, when=periods[i][0], source=src))
        return out
    # categories: each row in each column; the total row
    for j, qs in numeric:
        when, _ = _col_period(cols[j])
        cur = latest.get(j, True)
        tgt = bool(_TARGET_COL_RE.search(cols[j]))
        for r, q in zip(rows, qs):
            if q is None or not r or r[label_col] is None:
                continue
            lab = str(r[label_col]).strip()
            out.append(TableFact(words=_stems(cols[j]) | _stems(lab), name=f"{lab}, {(_base_name(cols[j]) or cols[j]).lower()}", qty=q, when=when,
                                 source=src, row=lab, current=cur, target=tgt))
        for r in totals:
            q = _cell_quantity(r[j] if j < len(r) else None, units[j])
            if q is None:
                continue
            out.append(TableFact(words=_stems(cols[j]), name=_base_name(cols[j]) or cols[j], qty=q, when=when, source=src, current=cur, target=tgt))
    # a cost per new client («Затраты» / «Новых клиентов»): the total and its spread over the rows
    cost = [(j, qs) for j, qs in numeric if _COST_RE.search(cols[j]) and any(q is not None and q.kind == "money" for q in qs)]
    new = [(j, qs) for j, qs in numeric if _NEW_RE.search(cols[j]) and all(q is None or q.kind == "count" for q in qs)]
    for jc, qc in cost:
        for jn, qn in new:
            spread = []
            for r, a, b in zip(rows, qc, qn):
                if a is not None and b is not None and b.value:
                    spread.append((str(r[label_col]).strip(), Quantity(a.value / b.value, "money", a.shown)))
            tot_c = next((_cell_quantity(r[jc] if jc < len(r) else None, units[jc]) for r in totals), None)
            tot_n = next((_cell_quantity(r[jn] if jn < len(r) else None, units[jn]) for r in totals), None)
            if tot_c is None or tot_n is None:
                tot_c = Quantity(sum(q.value for q in qc if q is not None), "money", (next(q for q in qc if q is not None)).shown)
                tot_n = Quantity(sum(q.value for q in qn if q is not None), "count")
            if not tot_n.value:
                continue
            when, _ = _col_period(f"{cols[jc]} {sheet}")
            out.append(TableFact(words=_stems(cols[jc]) | _stems(cols[jn]) | _stems("стоимость привлечения клиента CAC"),
                                 name="Стоимость привлечения клиента", qty=Quantity(tot_c.value / tot_n.value, "money", tot_c.shown),
                                 when=when.replace("в ", "за ", 1) if when else "", source=src, spread=spread))
    return out


# ------------------------------------------------------------------ goals of the documents


@dataclass
class Goal:
    subject: str
    op: str  # ">=" (to reach) or "<=" (to stay under)
    qty: Quantity
    figure: str  # the target as the document writes it («не ниже 45», «20 000»)
    deadline: str = ""  # «к концу года», «к 31 декабря 2026 года»
    sentence: str = ""


_LE = r"(?:не\s+должн\w*\s+превыша\w*|не\s+более|не\s+больше|не\s+выше|не\s+дольше|не\s+позднее|максимум|до|≤|<=)"
_GE = r"(?:не\s+должн\w*\s+(?:быть\s+)?(?:ниже|меньше)|не\s+менее|не\s+меньше|не\s+ниже|минимум|от|≥|>=)"
_NUMU = r"(?P<n>\d{1,3}(?:[   ]\d{3})+|\d+(?:[.,]\d+)?)\s*(?P<u>%|процент\w*|(?:тысяч\w*|тыс\.?|миллион\w*|млн|млрд)\s*(?:₽|руб\w*|рублей)?|₽|руб\w*|мин\w*|час\w*|ч(?![а-яё])|сек\w*|дн\w*|д(?:ня|ней)\b)?"
_DEADLINE_RE = re.compile(r"(?i)\s*(?P<d>к\s+(?:концу\s+(?:года|квартала|\d{4}\s+года)|\d{1,2}\s+[а-яё]+(?:\s+\d{4}\s+года)?|[а-яё]+ю?\s+\d{4}\s+года|декабрю(?:\s+\d{4}(?:\s+года)?)?|\d{4}\s+году))")
_GOAL_DASH_RE = re.compile(rf"(?i)^(?P<s>.{{3,120}}?)\s*,?\s*[—–:-]\s*(?P<op>{_LE}|{_GE})\s+{_NUMU}")
_GOAL_LEAD_RE = re.compile(rf"(?i)^(?P<op>{_LE}|{_GE})\s+{_NUMU}\s+(?P<s>[а-яёa-z].{{3,100}}?)$")
_GOAL_REACH_RE = re.compile(rf"(?i)^(?:(?P<s1>[A-Za-zА-ЯЁа-яё][^\d]{{1,60}}?)\s+)?{_NUMU}\s*(?P<s2>[а-яёa-z][^\d]{{0,60}}?)?\s*(?P<d>к\s+.+)$")
_GOAL_CUE_RE = re.compile(r"(?i)\bцел(?:ь|и|ью|евой|евые|евого)\b")
_GOAL_WORD_RE = re.compile(r"(?i)(?<![а-яё])(?:цел(?:ь|и|ью|ев\w*)|допустим\w*|норм(?:а|ы|у|ой|атив\w*)|порог\w*|лимит\w*|план\s+на\s+\d{4})(?![а-яё])")


def _goal_qty(n: str, u: Optional[str], subject: str) -> Quantity:
    v = float(re.sub(r"[   ]", "", n).replace(",", "."))
    kind, scale, shown = _unit_of(u or "")
    if kind in ("time", "pct"):
        return Quantity(v * scale, kind, shown)
    if kind == "count" and u and re.search(r"(?i)тыс|млн|млрд|миллион|тысяч", u) and re.search(r"(?i)руб|₽|выручк|mrr|затрат|бюджет|стоимост", subject + " " + u):
        kind = "money"
    return Quantity(v * scale, kind, (u or "").strip())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«\d])|\n+", text or "") if s.strip()]


def goals_of(text: str) -> list[Goal]:
    """The goals a text states, one per sentence (or bullet): «X — не ниже 45 к концу года», «Не менее 60 % учеников …»,
    «20 000 учеников к 31 декабря 2026 года», «MRR 3 млн рублей к декабрю 2026 года»."""
    out: list[Goal] = []
    for raw in _sentences(text):
        s = re.sub(r"^[•\-–—*]\s*", "", raw).strip().rstrip(".")
        if not s or len(s) > 220:
            continue
        dl = _DEADLINE_RE.search(s)
        deadline = dl.group("d").strip() if dl else ""
        m = _GOAL_DASH_RE.match(s)
        if m:
            subj = m.group("s").strip(" ,—–:")
            op = "<=" if re.match(_LE, m.group("op"), re.I) else ">="
            out.append(Goal(subj, op, _goal_qty(m.group("n"), m.group("u"), subj), f"{m.group('op')} {m.group('n')}{(' ' + m.group('u')) if m.group('u') else ''}".strip(), deadline, raw))
            continue
        m = _GOAL_LEAD_RE.match(re.sub(_DEADLINE_RE, "", s).strip())
        if m:
            subj = m.group("s").strip(" ,")
            op = "<=" if re.match(_LE, m.group("op"), re.I) else ">="
            out.append(Goal(subj, op, _goal_qty(m.group("n"), m.group("u"), subj), f"{m.group('op')} {m.group('n')}{(' ' + m.group('u')) if m.group('u') else ''}".strip(), deadline, raw))
            continue
        # «План … устанавливает допустимый уровень ежемесячного оттока … на уровне не выше 3 %», «Целевой показатель
        # выручки на конец 2026 года составляет 3 млн рублей»: a writer's sentence of a goal, its figure inside
        if _GOAL_WORD_RE.search(s):
            m = re.search(rf"(?i)(?:(?P<op>{_LE}|{_GE})|(?:составля\w*|равн\w*|установлен\w*(?:\s+на\s+уровне)?|—|:))\s+{_NUMU}", s)
            if m and len(_FIG_RE.findall(re.sub(r"\b20\d\d\b", "", s))) == 1:
                subj = re.sub(r"(?i)(?:\s*(?:на\s+уровне|составля\w*|установлен\w*|равн\w*|на\s+(?:конец\s+)?\d{4}\s+год[а-я]*))+\s*$", "", s[: m.start()]).strip(" ,—–:")
                subj = re.sub(r"(?i)^(?:план\s+на\s+\d{4}\s+год\s+устанавливает\s+|целев\w+\s+показател\w+\s+|цел\w+\s+|допустим\w+\s+уров\w+\s+)", "", subj).strip()
                if subj:
                    if m.group("op"):
                        op = "<=" if re.match(_LE, m.group("op"), re.I) else ">="
                    else:
                        op = "<=" if re.search(r"(?i)допустим|порог|лимит|максим|не\s+выше|не\s+более", s) else ">="
                    fig = f"{m.group('op') + ' ' if m.group('op') else ''}{m.group('n')}{(' ' + m.group('u')) if m.group('u') else ''}".strip()
                    out.append(Goal(subj, op, _goal_qty(m.group("n"), m.group("u"), subj), fig, deadline, raw))
                    continue
        if deadline or _GOAL_CUE_RE.search(s):
            m = _GOAL_REACH_RE.match(s) if deadline else None
            if m:
                subj = " ".join(x for x in (m.group("s1"), m.group("s2")) if x).strip(" ,—–:")
                subj = re.sub(r"(?i)^(?:цель\s*(?:[—–:-]\s*)?|целевой\s+показатель\s+)", "", subj).strip()
                if subj and not re.search(r"\d", subj):
                    out.append(Goal(subj, ">=", _goal_qty(m.group("n"), m.group("u"), subj), f"{m.group('n')}{(' ' + m.group('u')) if m.group('u') else ''}".strip(), deadline, raw))
    return out


# ------------------------------------------------------------------ a goal against the facts

_GENERIC = {"цел", "год", "конц", "месяц", "кварта", "показа", "доля", "довол", "врем"}


def match(goal: Goal, facts: Sequence[TableFact]) -> Optional[TableFact]:
    """The figure of the tables `goal` is about, or None: the most words of its subject in common (a row the goal does
    not name loses), the unit of the same kind, a current column before a past one, never a target column."""
    gw = _stems(goal.subject)
    gnum = {w for w in gw if w.isdigit()}
    gw_words = {w for w in gw if not w.isdigit()}
    best, best_sc = None, 0.0
    for f in facts:
        if f.target or f.qty.kind != goal.qty.kind:
            continue
        fw = {w for w in f.words if not w.isdigit()}
        common = gw_words & fw
        strong = common - _GENERIC
        if not strong:
            continue
        # most of what the goal names, or a name of its own (NPS, MRR, CAC), or two words of it — never one word in
        # passing («Открыть 5 новых офисов» is no goal of «Новых подписчиков»)
        if not (len(strong) >= 2 or any(re.fullmatch(r"[a-z]{2,6}", w) for w in strong)
                or len(strong) >= 0.5 * max(1, len(gw_words - _GENERIC))):
            continue
        fnum = {w for w in _stems(f.row or "") if w.isdigit()}
        if fnum and gnum and not (fnum & gnum):
            continue
        if fnum and not gnum:
            continue
        sc = len(common) + (0.5 if fnum and (fnum & gnum) else 0.0)
        if f.row and not (_stems(f.row) & gw):
            sc -= 0.75  # a row («Республика Татарстан») the goal does not name: the total speaks for the goal
        if not f.current:
            sc -= 0.5
        # the scale must be near: a goal of 3 млн against a figure of 1 820 тыс. — yes; against 9 — no
        if goal.qty.value and f.qty.value and not (0.02 <= f.qty.value / goal.qty.value <= 50):
            continue
        if sc > best_sc:
            best, best_sc = f, sc
    return best if best_sc >= 1.0 else None


@dataclass
class Verdict:
    goal: Goal
    fact: TableFact
    met: bool
    text: str  # the line: «NPS клиентов поддержки: 46 в сентябре при цели не ниже 45 к концу года — цель достигнута»
    short: str  # the heading: «NPS 46 — цель 45 достигнута»
    name: str
    word: str = ""  # «цель достигнута», «61 % цели», «выше цели»


def _name(goal: Goal, fact: TableFact) -> str:
    ab = re.search(r"\(([A-ZА-ЯЁ]{2,6})\)", goal.subject)
    if ab:
        return ab.group(1)
    subj = re.sub(r"\s*\([^()]*\)", "", goal.subject).strip()
    return subj if len(subj.split()) <= 5 else fact.name


def verdict(goal: Goal, fact: TableFact) -> Verdict:
    q, g = fact.qty, goal.qty
    fs, gs = say(q, g), say(g, g)
    when = f" {fact.when}" if fact.when else ""
    dl = f" {goal.deadline}" if goal.deadline else ""
    near = abs(q.value - g.value) <= max(1e-9, abs(g.value) * 0.005)
    if goal.op == ">=":
        met = q.value >= g.value - 1e-9
        word = ("цель достигнута" if met else (f"{_fmt(round(q.value / g.value * 100))} % цели" if g.value and q.value < g.value else "ниже цели"))
        op_word = "не ниже " if re.match(r"(?i)не\s+(?:ниже|менее|меньше)|минимум|от", goal.figure) else ""
    else:
        met = q.value <= g.value + 1e-9
        word = (("на границе нормы" if near else "в пределах нормы") if q.kind == "time" else ("на границе цели" if near else "в пределах цели")) \
            if met else ("дольше нормы" if q.kind == "time" else "выше цели")
        op_word = "не более " if q.kind != "pct" else "не выше "
    norm = "норме" if q.kind == "time" else "цели"
    name = _name(goal, fact)
    subj = goal.subject[:1].upper() + goal.subject[1:]
    text = f"{subj}: {fs}{when} при {norm} {op_word}{gs}{dl} — {word}"
    if fact.spread and len(fact.spread) >= 2:
        hi = max(fact.spread, key=lambda x: x[1].value)
        lo = min((x for x in fact.spread if x[1].value > 0), key=lambda x: x[1].value, default=None)
        if lo is not None and lo[0] != hi[0]:
            text += f"; {hi[0]} — {say(hi[1], g)}, {lo[0]} — {say(lo[1], g)}"
    if goal.op == ">=":
        short = f"{name} {fs} — цель {gs} достигнута" if met else f"{name} {fs} — {word} {gs}"
    else:
        short = f"{name} {fs} — {word} {gs}" if met else f"{name} {fs} — {word} {gs}"
    return Verdict(goal, fact, met, text, short, name, word)


# ------------------------------------------------------------------ the slides

_NEG_RE = re.compile(r"(?i)(?:не\s+(?:достиг\w*|выполн\w*|укладыва\w*|дотягива\w*)|недостиж\w*|отстава\w*|отста[её]т\w*|отстают|срыв\w*|"
                     r"недовыполн\w*|провал\w*|ниже\s+(?:цел|план|норм)\w*|хуже\s+(?:цел|план|норм)\w*)")
_POS_RE = re.compile(r"(?i)(?<!не\s)(?:достигнут\w*|достигли|достигла|достиг\b|выполнен\w*|перевыполн\w*|в\s+пределах\s+(?:цел|норм)\w*|выше\s+цел\w*)")
_VERDICT_TOPIC_RE = re.compile(r"(?i)цел\w*|план\w*|норм\w*|kpi|показател\w*|целев\w*")
_THRESH_RE = re.compile(r"(?i)превышени\w*\s+(?P<what>[^.;]{0,60}?)\s*(?:более|больше|свыше)\s+(?:чем\s+)?на\s+(?P<n>\d+(?:[.,]\d+)?)\s*%")
_APPROVAL_RE = re.compile(r"(?i)(?:одобрени\w*|утвержд\w*|согласовани\w*|разрешени\w*|одобрить|утвердить|согласовать)")


def _lines(s) -> list[tuple[str, str, int]]:
    """(field, text, index) of a slide's words a knowledge slide states."""
    c = s.content
    out = [("headline", s.headline or "", -1), ("subtitle", s.subtitle or "", -1), ("takeaway", s.takeaway or "", -1)]
    out += [("bullet", b, i) for i, b in enumerate(c.bullets)]
    out += [("item", (it.title + " " + it.text).strip(), i) for i, it in enumerate(c.items)]
    out += [("number", f"{n.value} {n.label}", i) for i, n in enumerate(c.numbers)]
    return [x for x in out if x[1].strip()]


def _overrun(tables: Sequence) -> Optional[tuple[float, Quantity, Quantity, str]]:
    """(overrun %, fact total, plan total, source) of a table of plan against fact («План, млн ₽» / «Факт, тыс. ₽»)."""
    for t in tables or []:
        cols = [str(c) for c in (t.columns or [])]
        jp = next((j for j, c in enumerate(cols) if re.search(r"(?i)план|бюджет|лимит", c)), None)
        jf = next((j for j, c in enumerate(cols) if re.search(r"(?i)факт|исполн|потрачен", c)), None)
        if jp is None or jf is None or jp == jf:
            continue
        units = list(t.units or []) + [None] * len(cols)
        tot = [r for i, r in enumerate(t.rows or []) if i in set(t.totals or []) or (r and isinstance(r[0], str) and _TOTAL_RE.match(r[0]))]
        rows = tot or [r for r in t.rows or [] if not (r and isinstance(r[0], str) and _TOTAL_RE.match(r[0]))]
        p = [q for r in rows if (q := _cell_quantity(r[jp] if jp < len(r) else None, units[jp])) is not None]
        f = [q for r in rows if (q := _cell_quantity(r[jf] if jf < len(r) else None, units[jf])) is not None]
        if not p or not f or p[0].kind != f[0].kind:
            continue
        pq = Quantity(sum(q.value for q in p), p[0].kind, p[0].shown)
        fq = Quantity(sum(q.value for q in f), f[0].kind, p[0].shown)
        if pq.value:
            return (fq.value / pq.value - 1) * 100, fq, pq, _source(t)
    return None


def reconcile(slides: list, tables: Sequence, kb_texts: Iterable[str] = ()) -> list[str]:
    """Each knowledge slide (`slides`, changed in place) checked against the tables (see the module); what changed, in
    Russian, for the build's log."""
    facts = table_facts(tables)
    said: list[str] = []
    if not facts and not tables:
        return said
    kb_texts = list(kb_texts or [])
    doc_goals: list[Goal] = []
    for txt in kb_texts:
        doc_goals.extend(goals_of(txt))
    verdicts: list[Verdict] = []
    seen: set[str] = set()
    for g in doc_goals:
        f = match(g, facts)
        if f is not None and g.subject.lower() not in seen:
            seen.add(g.subject.lower())
            verdicts.append(verdict(g, f))
    over = _overrun(tables)
    doc_limit = next((float(m.group("n").replace(",", ".")) for txt in kb_texts or [] for m in [_THRESH_RE.search(txt)] if m), None) if over is not None else None
    for s in slides:
        own: list[Verdict] = []
        sources: set[str] = set()
        c = s.content
        # 1. a line that states a goal → the comparison
        for i, b in enumerate(list(c.bullets)):
            v = _line_verdict(b, facts, verdicts)
            if v is not None:
                c.bullets[i] = v.text
                own.append(v)
                sources.add(v.fact.source)
                said.append(f"«{b[:60]}» — сверено с таблицей: «{v.text[:80]}»")
        for attr in ("subtitle", "takeaway"):
            val = getattr(s, attr) or ""
            v = _line_verdict(val, facts, verdicts)
            if v is not None:
                setattr(s, attr, v.text)
                own.append(v)
                sources.add(v.fact.source)
        for it in c.items:
            v = _line_verdict((it.title + " — " + it.text) if it.text else it.title, facts, verdicts)
            if v is not None:
                it.text = v.text
                own.append(v)
                sources.add(v.fact.source)
        for n in c.numbers:
            v = _line_verdict(f"{n.label} — {n.value}" if re.match(r"(?i)не\s|до\s|от\s", n.value) else f"{n.value} {n.label}", facts, verdicts)
            if v is not None:
                n.value = say(v.fact.qty, v.goal.qty).replace(" %", "%")
                n.label = f"{v.name}{(' ' + v.fact.when) if v.fact.when else ''} · {v.text.rsplit(' — ', 1)[-1]} ({v.goal.figure}{(' ' + v.goal.deadline) if v.goal.deadline else ''})"
                own.append(v)
                sources.add(v.fact.source)
        # a table of norms («Линия | Норматив времени первого ответа»): the fact and the verdict beside each norm
        if c.table is not None:
            got = _table_verdicts(c.table, facts)
            if got:
                own.extend(got)
                sources.update(v.fact.source for v in got)
                said.append(f"таблица «{' | '.join(c.table.columns)[:60]}» — рядом факт и итог по каждой строке")
        # 2. what the slide says of the goals: judged against the facts of the goals it names
        text_all = " ".join(x[1] for x in _lines(s))
        named = [v for v in verdicts if _names(v, text_all)] or own
        named = list({id(v): v for v in [*own, *named]}.values())
        if named:
            fixed = _judge(s, named)
            if fixed:
                said.extend(fixed)
                for v in named:
                    sources.add(v.fact.source)
        # 3. a heading that only named the goals («Отток: целевой порог 3 %», «Справляемся ли») states them: the
        # conclusion with its figure
        head = s.headline or ""
        if own and not _NEG_RE.search(head) and not _POS_RE.search(head) and not any(v.short == head for v in own) and \
                (not re.search(r"\d", re.sub(r"\b20\d\d\b", "", head)) or any(v.goal.figure.split()[-1] in head for v in own)):
            new = _heading(own)
            said.append(f"заголовок «{head[:50]}» — вывод с фактом: «{new}»")
            s.headline = new
        # 4. an ask for an approval a threshold needs, when the tables stay under it
        if over is not None:
            said.extend(_threshold(s, over, sources, doc_limit))
        if sources:
            line = "Факты — из таблиц: " + "; ".join(sorted(sources)) + "."
            s.notes = f"{s.notes}\n{line}".strip() if s.notes else line
    return list(dict.fromkeys(said))


def _table_verdicts(t, facts: Sequence[TableFact]) -> list[Verdict]:
    """Each row of a table of norms («1-я линия | не более 15 минут») against its fact: two columns are added — the
    fact («Факт, Q3») and the verdict; nothing when most rows meet no fact."""
    # a «Факт» column the writer filled (from the documents, which have no facts — жюри 5: «12 минут» at 14 in the
    # table) gives way to the tables' own figures
    keep = [j for j, c in enumerate(t.columns or []) if j == 0 or not re.search(r"(?i)факт|итог|статус|выполнен", str(c))]
    cols = [t.columns[j] for j in keep]
    rows = [[(list(r) + [""] * len(t.columns))[j] for j in keep] for r in t.rows]
    if len(cols) < 2:
        return []
    found: list[tuple[int, Verdict]] = []
    for i, row in enumerate(rows):
        if not row:
            continue
        for j in range(1, min(len(row), len(cols))):
            head = re.sub(r"(?i)^(?:норматив|норма|цель|целевой\s+показатель|целевое\s+значение)\s*", "", cols[j]).strip() or cols[j]
            gs = goals_of(f"{head} {row[0]} — {row[j]}")
            if len(gs) != 1:
                continue
            g = gs[0]
            if not re.search(r"(?i)не\s+(?:более|менее|ниже|выше|больше|меньше|дольше)|максимум|минимум|до\s|от\s", g.figure):
                continue
            f = match(g, facts)
            if f is None:
                continue
            v = verdict(g, f)
            v.name = str(row[0]).strip()
            v.short = f"{v.name} {say(f.qty, g.qty)} — {v.word} {say(g.qty, g.qty)}"
            found.append((i, v))
            break
    if len(found) < max(1, (len(rows) + 1) // 2):
        return []
    whens = {v.fact.when for _, v in found}
    when = next(iter(whens)).replace("в ", "", 1) if len(whens) == 1 and next(iter(whens)) else ""
    t.columns = [*cols, f"Факт{', ' + when if when else ''}", "Итог"]
    by = dict(found)
    w = len(cols)
    t.rows = [[*(list(r) + [""] * w)[:w], say(by[i].fact.qty, by[i].goal.qty) if i in by else "—", by[i].word if i in by else ""]
              for i, r in enumerate(rows)]
    return [v for _, v in found]


def _names(v: Verdict, text: str) -> bool:
    gw = {w for w in _stems(v.goal.subject) if not w.isdigit()} - _GENERIC
    fw = {w for w in _stems(v.fact.name) if not w.isdigit()} - _GENERIC
    tw = _stems(text)
    return bool(gw and len(gw & tw) >= min(2, len(gw))) or bool(fw and len(fw & tw) >= min(2, len(fw)))


def _line_verdict(line: str, facts: Sequence[TableFact], verdicts: list[Verdict]) -> Optional[Verdict]:
    if not line or re.search(r"\bпри\s+(?:цели|норме)\b", line):
        return None
    gs = goals_of(line)
    if len(gs) != 1:
        return None
    g = gs[0]
    f = match(g, facts)
    if f is None:
        # the writer's words of a goal the documents state with the same figure («целевой показатель ежемесячной
        # выручки … 3 млн рублей» — the document's «MRR 3 млн рублей к декабрю»): that goal's comparison
        return next((v for v in verdicts if v.goal.op == g.op and v.goal.qty.kind == g.qty.kind
                     and abs(v.goal.qty.value - g.qty.value) <= 1e-6 * max(1.0, g.qty.value)), None)
    # the document's own goal of that figure speaks for it (its subject, not the writer's «целевой NPS …»)
    same = next((v for v in verdicts if v.fact is f and v.goal.op == g.op and abs(v.goal.qty.value - g.qty.value) <= 1e-6 * max(1.0, g.qty.value)), None)
    return same if same is not None else verdict(g, f)


def _judge(s, named: list[Verdict]) -> list[str]:
    """The slide's verdicts on the goals it names, set against the facts: a wrong one goes (a heading says the right one)."""
    said: list[str] = []
    met = [v for v in named if v.met]
    missed = [v for v in named if not v.met]
    right = (f"{_join([v.name for v in met])}: {'цели достигнуты' if len(met) > 1 else 'цель достигнута'}" if not missed else
             f"{_join([v.name for v in missed])}: {'ниже целей' if len(missed) > 1 else ('дольше нормы' if missed[0].fact.qty.kind == 'time' else 'ниже цели') if missed[0].goal.op == '>=' else 'выше цели'}"
             + (f", {_join([v.name for v in met])} — в цели" if met else ""))
    lines_of = [v.text for v in named]

    def wrong(text: str) -> bool:
        if not text or not _VERDICT_TOPIC_RE.search(text) and not _NEG_RE.search(text):
            return False
        if re.search(r"\bпри\s+(?:цели|норме)\b", text):
            return False  # a comparison already
        neg = bool(_NEG_RE.search(text))
        pos = bool(_POS_RE.search(text)) and not neg
        if neg and missed and not met:
            return False
        if pos and met and not missed:
            return False
        return neg or pos

    if wrong(s.headline or ""):
        right = _upper(right)
        said.append(f"заголовок «{s.headline[:60]}» противоречит таблицам → «{right}»")
        s.headline = right
    for attr in ("subtitle", "takeaway"):
        val = getattr(s, attr)
        if val and wrong(val):
            said.append(f"«{val[:60]}» противоречит таблицам — убрано")
            setattr(s, attr, None)
    c = s.content
    keep = []
    for b in c.bullets:
        if wrong(b):
            said.append(f"«{b[:60]}» противоречит таблицам — убрано")
            continue
        keep.append(b)
    c.bullets = keep
    c.items = [it for it in c.items if not wrong(f"{it.title} {it.text}")]
    if said:
        # the slide says the comparison of each goal it judged, once
        have = " ".join(c.bullets)
        add = [t for t in lines_of if t not in have]
        if c.numbers or c.items or c.table is not None or c.chart is not None:
            if add and not s.subtitle:
                s.subtitle = add[0]
        else:
            c.bullets = add + c.bullets
    return said


def _heading(own: list[Verdict]) -> str:
    """The heading of a slide of goals against facts: the first one missed with its figures, then how the rest stand;
    all met — which ones."""
    own = list({v.goal.subject: v for v in own}.values())
    if len(own) == 1:
        return _upper(own[0].short)
    missed = [v for v in own if not v.met]
    met = [v for v in own if v.met]
    if not missed:
        return _upper(f"{_join([v.name for v in met][:3])}: цели достигнуты")
    if len(own) == 2:
        return _upper(f"{own[0].short}; {_lower(own[1].short)}")
    head = missed[0].short
    if len(missed) == 2:
        return _upper(f"{head}; {_lower(missed[1].name)} — {missed[1].word}")
    if len(missed) > 2:
        return _upper(f"{head}; ещё {len(missed) - 1} — не в цели")
    return _upper(f"{head}; остальные — {'в норме' if all(v.fact.qty.kind == 'time' for v in met) else 'в цели'}")


def _upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _lower(name: str) -> str:
    return name if re.match(r"^[A-ZА-ЯЁ0-9]{2,}", name) else name[:1].lower() + name[1:]


def _join(names: list[str]) -> str:
    names = list(dict.fromkeys(names))
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " и " + names[-1]


def _threshold(s, over: tuple[float, Quantity, Quantity, str], sources: set[str], doc_limit: Optional[float] = None) -> list[str]:
    pct, fact, plan, src = over
    said: list[str] = []
    c = s.content

    def fix(text: str) -> Optional[str]:
        m = _THRESH_RE.search(text or "")
        if not m:
            return None
        n = float(m.group("n").replace(",", "."))
        line = (f"По положению порог превышения — {_fmt(n)} %, перерасход по таблице — {_fmt(round(pct, 1))} % "
                f"({say(fact, plan)} при плане {say(plan, plan)}): " + ("в пределах порога" if pct <= n else "порог превышен"))
        if _APPROVAL_RE.search(text) and pct <= n and re.match(r"(?i)^\s*(?:шаг\s+\d+\s*[/:.]\s*)?(?:получить|запросить|согласовать|утвердить|одобрить|нужно|необходимо|требуется)", text):
            return line  # an ask for the approval the threshold needs: under the threshold it is not needed
        return f"{text.rstrip('. ')}. {line}" if line not in text else None

    for i, b in enumerate(list(c.bullets)):
        nb = fix(b)
        if nb:
            c.bullets[i] = nb
            said.append(f"«{b[:60]}» — сверено с планом и фактом таблицы")
    for it in c.items:
        nt = fix(it.text)
        if nt:
            it.text = nt
            said.append(f"«{it.text[:60]}» — сверено с планом и фактом таблицы")
    for attr in ("subtitle", "takeaway"):
        val = getattr(s, attr)
        nv = fix(val or "")
        if nv:
            if _APPROVAL_RE.search(val or "") and pct <= float(_THRESH_RE.search(val).group("n").replace(",", ".")):
                nv = None if attr == "takeaway" else nv
            setattr(s, attr, nv)
            said.append(f"«{(val or '')[:60]}» — сверено с планом и фактом таблицы")
    # «… корректировка бюджета делают одобрение совета необходимым» without a figure, when the documents' threshold is
    # not reached by the tables' plan and fact: not so
    if doc_limit is not None and pct <= doc_limit:
        def needs(val: str) -> bool:
            return bool(val and _APPROVAL_RE.search(val) and re.search(r"(?i)превышени|перерасход|корректировк\w*\s+бюджет|перераспределени\w*\s+(?:средств|бюджет)", val)
                        and not _THRESH_RE.search(val) and re.search(r"(?i)необходим|требу|нужн", val))
        for attr in ("subtitle", "takeaway"):
            val = getattr(s, attr)
            if val and needs(val):
                setattr(s, attr, None)
                said.append(f"«{val[:60]}» — одобрение по таблице не нужно: перерасход {_fmt(round(pct, 1))} % при пороге {_fmt(doc_limit)} %")
        keep = [b for b in c.bullets if not needs(b)]
        if len(keep) != len(c.bullets):
            said.append(f"строка об одобрении — по таблице не нужно: перерасход {_fmt(round(pct, 1))} %")
            c.bullets = keep
    if said:
        sources.add(src)
    return said


__all__ = ["Goal", "TableFact", "Verdict", "goals_of", "match", "reconcile", "say", "table_facts", "verdict"]
