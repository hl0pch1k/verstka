"""Analyst (Agent v2, step 1): what the brief says about its deck — the slides the user dictated («Слайд 3. …» and the
lines under it), the charts, tables and formulas they asked for, the global rules and every data series the brief
holds — read deterministically (`read_structure`), then completed by the `data_extractor` skill for the blocks the
rules did not cover (`enrich_with_model`, one small call per block, in parallel).

The rules rely on punctuation, numbers and a handful of Russian/English markers («Слайд N», «Название:», «— аренда —
120 000 рублей», «со 100 до 115», «Покажи формулу: …», «Вывод: …»), never on the wording of a particular brief. Every
value of every series is a number written in the brief.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from verstka.planning import heuristics as H
from verstka.schemas.brief_structure import BriefStructure, ChartKind, ChartRequest, SlideSpec
from verstka.schemas.outline import FactsExtraction, Series, SlideItem, TableData

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ numbers

# «1 138 500», «13,3», «900 000» (thin and no-break spaces too); never a part of a word, a time («08:00»), an ordinal
# («1-й месяц») or a range's dash
_NUM = r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_MONEY = r"(?:руб(?:лей|ля|ль)?\.?|₽)"
_UNIT = (
    rf"%|₽|\$|€|(?:тыс\.?|млн|млрд)(?:\s?{_MONEY})?|руб(?:лей|ля|ль)?\.?|долл(?:аров|ара|ар)?\.?|евро|чел\.?|человек|шт\.?|п\.\s?п\.|м²"
)
_NUM_RE = re.compile(rf"(?<![\w.,:])(?P<num>{_NUM})(?![\d]|[-‑]\s?(?:й|я|е|го|м|му|х)\b|:\d)(?:\s?(?P<unit>{_UNIT})(?![а-яёa-z]))?", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


def _num(text: str) -> float:
    return float(re.sub(r"[\s  ]", "", text).replace(",", "."))


def _unit(raw: Optional[str]) -> Optional[str]:
    """The unit as the registry writes it: «рублей» → «₽», «тыс. рублей» → «тыс. ₽», «%» stays."""
    if not raw:
        return None
    u = raw.strip().lower()
    money = bool(re.search(r"руб|₽", u))
    for scale, name in (("тыс", "тыс. "), ("млн", "млн "), ("млрд", "млрд ")):
        if u.startswith(scale):
            return f"{name}₽" if money else name.strip()
    if money:
        return "₽"
    if u.startswith("долл") or u == "$":
        return "$"
    if u.startswith("чел"):
        return "чел."
    return raw.strip()


def numbers_of(text: str) -> list[float]:
    """Every figure written in the text (times like «08:00» and ordinals like «1-й» are not figures)."""
    return [_num(m.group("num")) for m in _NUM_RE.finditer(text)]


def _in(value: float, pool: list[float]) -> bool:
    return any(abs(value - p) <= 1e-6 * max(1.0, abs(p)) for p in pool)


# ------------------------------------------------------------------ words

_ORDINALS = {
    "первый": 1, "второй": 2, "третий": 3, "четвертый": 4, "четвёртый": 4, "пятый": 5, "шестой": 6, "седьмой": 7,
    "восьмой": 8, "девятый": 9, "десятый": 10, "одиннадцатый": 11, "двенадцатый": 12,
}  # fmt: skip
_FUTURE_VERBS = {
    "вырастет", "вырастут", "достигнет", "достигнут", "составит", "составят", "увеличит", "сократит", "снизит",
    "повысит", "упадет", "упадёт", "возрастет", "возрастёт", "пойдет", "пойдёт", "уйдет", "уйдёт", "будет", "будут",
    "даст", "дадут", "принесет", "принесёт", "стоит", "стоят", "останется", "потребуется",
}  # fmt: skip
_PAST_VERBS = {"вырос", "упал", "стал", "начал", "сделал", "показал", "достиг", "превысил", "составил"}
_INDECLINABLE = {"меню", "кофе", "какао", "кафе", "шоу", "интервью", "ревю", "такси", "жюри", "пюре", "депо"}
_CONJ = {"а", "и", "но", "то", "есть", "также", "еще", "ещё", "из", "них"}
_PREPS = {"в", "во", "на", "до", "с", "со", "за", "по", "от", "из", "к", "ко", "у", "при", "о", "об", "для", "через", "без", "под", "над"}
_HEAD_WORDS = {
    "структуры": "структура", "структуру": "структура", "распределения": "распределение", "динамики": "динамика",
    "динамику": "динамика", "сравнения": "сравнение", "доли": "доля", "долю": "доля", "изменения": "изменение",
    "роста": "рост", "прогноза": "прогноз", "соотношения": "соотношение", "состава": "состав",
}  # fmt: skip
_STOP = {"до", "после", "изменений", "изменения", "по", "на", "в", "и", "с", "со", "для", "как", "это", "все", "всех", "или", "их", "его", "каждый", "нужна", "нужен", "нужны"}


# nouns that end like a verb form («число» like «росло», «начала» like «стала»)
_NOT_VERBS = {
    "число", "числа", "масло", "весло", "ремесло", "правило", "правила", "начало", "начала", "сигнала", "тело", "дело",
    "село", "стекло", "крыло", "мыло", "одеяло", "зеркало", "покрывало", "шило", "сало", "кресло", "колесо", "время",
    "имя", "семя", "пламя", "вымя", "знамя", "стремя", "темя", "бремя", "моти", "сети", "дети", "пути", "плати",
}  # fmt: skip


def _is_verb(word: str) -> bool:
    w = word.lower().strip(",.;:«»\"")
    if len(w) <= 4 or w in _NOT_VERBS:
        return False
    if H._VERB_END_RE.search(w) or w in _FUTURE_VERBS or w in _PAST_VERBS:
        return True
    # an infinitive («увеличить»), a past form in «-ил» / «-ял» («снизил», «потерял»)
    return len(w) > 5 and bool(re.search(r"(?:ть|ться|ти|ил|ял)$", w))


def _nominative(phrase: str) -> str:
    """«ежемесячную операционную прибыль» → «ежемесячная операционная прибыль», «витрину для десертов» → «витрина для
    десертов»: the words said after a verb or «на» back in the form a label takes; stops at the first preposition."""
    out: list[str] = []
    stop = False
    for w in phrase.split():
        low = w.lower()
        if stop or low in _PREPS:
            stop = True
            out.append(w)
            continue
        core = low.strip(",;")
        tail = w[len(w.rstrip(",;")) :]
        base = w[: len(w) - len(tail)] if tail else w
        if core in _INDECLINABLE or len(core) < 4:
            out.append(w)
        elif core.endswith(("ую", "юю")):
            out.append(base[:-2] + ("ая" if core.endswith("ую") else "яя") + tail)
        elif re.search(r"[бвгджзклмнпрстфхцчшщ]у$", core):
            out.append(base[:-1] + "а" + tail)
        elif re.search(r"[лнр]ю$", core):
            out.append(base[:-1] + "я" + tail)
        else:
            out.append(w)
    return " ".join(out)


def _stems(text: str) -> set[str]:
    ws = re.findall(r"[а-яёa-z]{3,}", text.lower())
    return {w[:5] for w in ws if w not in _STOP}


def _clean(text: str) -> str:
    """A label as a slide shows it: no list marker, no end punctuation, no wrapping quotes, first letter up."""
    t = re.sub(r"^\s*(?:[—–\-•*]|\d+[.)])\s+", "", text.strip())
    t = t.strip().rstrip(".;:,").strip()
    if len(t) >= 2 and t[0] in "«\"“" and t[-1] in "»\"”" and t.count("«") <= 1:
        t = t[1:-1].strip()
    return H.cap_first(t)


def _unquote(text: str) -> str:
    t = text.strip().rstrip(".;").strip()
    pairs = {"«": "»", '"': '"', "“": "”", "„": "“"}
    if len(t) >= 2 and t[0] in pairs and t.endswith(pairs[t[0]]):
        inner = t[1:-1]
        # «А» и «Б» is two quotes, not one wrapped text
        if not (t[0] == "«" and "»" in inner and inner.index("»") < inner.rfind("«") if "«" in inner else False):
            t = inner.strip()
    return t.rstrip(".").strip()


def _plural(n: int, one: str, few: str, many: str) -> str:
    k = n % 100
    if 11 <= k <= 14:
        return many
    k %= 10
    return one if k == 1 else few if 2 <= k <= 4 else many


def sentences_of(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s:
            out.extend(H.split_sentences(s) or [s])
    return out


# ------------------------------------------------------------------ slide specs

_SPEC_HEAD_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:слайд|slide)\s*№?\s*(?P<n>\d{1,2})\s*(?:\*\*)?\s*(?:[.:)—–-]\s*|\s+|$)(?P<title>.*?)\s*(?:\*\*)?\s*$",
    re.I,
)
_NUM_HEAD_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?P<n>\d{1,2})[.)]\s+(?P<title>\S.{0,90})$")
_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _spec_heads(lines: list[str], text: str) -> list[tuple[int, int, str]]:
    """(line index, slide number, title) of each heading of a slide the user describes; [] when the brief does not
    describe slides. «Слайд N» headings count when there are two or more in ascending order; bare «N.» headings only
    when the brief speaks of slides, runs 1, 2, 3 … and every heading has lines of its own under it (a numbered list
    has none)."""
    heads = []
    for i, ln in enumerate(lines):
        m = _SPEC_HEAD_RE.match(ln)
        if m and len(m.group("title").split()) <= 14:
            heads.append((i, int(m.group("n")), _clean(m.group("title")) if m.group("title") else ""))
    if len(heads) >= 2 and all(b[1] > a[1] for a, b in zip(heads, heads[1:])):
        return heads
    if not re.search(r"слайд|slide", text, re.I):
        return []
    heads = []
    for i, ln in enumerate(lines):
        m = _NUM_HEAD_RE.match(ln)
        if m and len(m.group("title").split()) <= 10 and not m.group("title").rstrip().endswith((";", ",")):
            heads.append((i, int(m.group("n")), _clean(m.group("title"))))
    if len(heads) < 3 or [h[1] for h in heads] != list(range(1, len(heads) + 1)):
        return []
    bounds = [h[0] for h in heads] + [len(lines)]
    for k in range(len(heads)):
        if not any(lines[j].strip() for j in range(bounds[k] + 1, bounds[k + 1])):
            return []
    return heads


# ------------------------------------------------------------------ global rules

_RULE_START_RE = re.compile(
    r"^(?:не\s+)?(?:перегружай|используй|покажи|добавь|вынеси|отметь|укажи|выдели|пиши|напиши|оформи|избегай|сохрани|округляй|"
    r"представляй|рассчитывай|складывай|ставь|размести|включи|подчеркни|сократи|придерживайся|следи|давай|делай|помести|"
    r"сделай|обязательно|везде|на\s+каждом\s+слайде|на\s+всех\s+слайдах|в\s+каждом\s+слайде|стиль|тон|цвета?|шрифты?|оформление|"
    r"денежные\s+суммы|все\s+суммы|все\s+числа|подробности|пояснения|заголовки|выводы)\b",
    re.I,
)
_RULE_ANY_RE = re.compile(r"округл|заметк\w*\s+(?:для\s+)?докладчик|speaker notes|\bдолж(?:ен|на|но|ны)\s+быть\b", re.I)
_TASK_RE = re.compile(r"^(?:создай|сделай|подготовь|собери|сгенерируй|нужна|нужно)\b.*презентаци", re.I)
_NOTES_RE = re.compile(r"заметк\w*\s+(?:для\s+)?докладчик|speaker notes|в\s+заметки\b", re.I)
_ROUND_RE = re.compile(r"округл|round(?:ed|ing)?\b", re.I)
_DISCLAIMER_RE = re.compile(r"\bусловн\w*|\bhypothetical\b|\bfictional\b|\billustrative\b", re.I)
_COUNT_RE = re.compile(r"(?:на|из|ровно|не более|не больше|максимум|до|в)\s+(\d{1,2})\s+слайд|(\d{1,2})\s+слайд(?:ов|а)\b|(\d{1,2})\s+slides?\b", re.I)
# «Название: «…»» (a colon only: «Заголовки — выводы» is a rule, not a title)
_TITLE_RE = re.compile(r"^\s*(?:[—–\-•*]\s*)?(?:название|заголовок|title)(?:\s+(?:презентации|колоды|deck))?\s*:\s*(?P<v>.+)$", re.I)
_SUBTITLE_RE = re.compile(r"^\s*(?:[—–\-•*]\s*)?(?:подзаголовок|subtitle)\s*:\s*(?P<v>.+)$", re.I)
_TOPIC_RE = re.compile(r"на\s+тему\s+«(?P<v>[^»]{4,160})»", re.I)


def _is_rule(sentence: str) -> bool:
    s = sentence.strip()
    if _TASK_RE.match(s):
        return False
    return bool(_RULE_START_RE.match(s) or _RULE_ANY_RE.search(s))


# ------------------------------------------------------------------ slide-level requests

_CHART_NOUN_RE = re.compile(r"(диаграмм\w*|график(?:а|ов|и|ом)?\b|гистограмм\w*|\bcharts?\b)", re.I)
_CHART_ASK_RE = re.compile(
    r"\b(нуж(?:ен|на|ны|но)|покажи|покажите|сделай|добавь|построй|отобрази|визуализируй|изобрази|помести|используй|размести|"
    r"представь|приведи)\b|на\s+диаграмм|на\s+график|в\s+виде\s+(?:диаграмм|график)",
    re.I,
)
_TYPE_WORDS: list[tuple[str, ChartKind]] = [
    (r"кольцев", "doughnut"),
    (r"кругов|pie\b", "pie"),
    (r"горизонтальн", "bar"),
    (r"столбчат|столбик|гистограмм|column|bar\b", "column"),
    (r"линейн|line\b", "line"),
    (r"областн|площадн|area\b", "area"),
]
_IMPLIED_TYPES: list[tuple[str, ChartKind]] = [
    (r"структур|распределени|\bдол[яиюей]\b|состав\b|из чего", "pie"),
    (r"динамик|по месяцам|по годам|по кварталам|по неделям|тренд|траектори", "line"),
    (r"сравнени|до и после|было и стало", "column"),
]
_NEG_ASK_RE = re.compile(r"\bне\s+(?:нуж|использ|показыва|добавля|дела|стро|став|рису)", re.I)
_COUNT_WORDS = {"два": 2, "две": 2, "2": 2, "три": 3, "3": 3, "четыре": 4, "4": 4}
_TABLE_ASK_RE = re.compile(r"(таблиц\w*)", re.I)
_FORMULA_RE = re.compile(r"формул\w*\s*[:—–]\s*(?P<f>.+)$", re.I)
_FOOTNOTE_ASK_RE = re.compile(r"^(?:укажи|отметь|подчеркни|напиши|поясни)(?:те)?\s*,?\s*что\s+(?P<t>.+)$|^(?:добавь\s+)?сноск\w*\s*[:—–]\s*(?P<t2>.+)$", re.I)
_FOOTNOTE_STATE_RE = re.compile(r"\bне\s+(?:учитыва\w*|включен\w*|включ[её]н\w*|учтен\w*|учт[её]н\w*)|в\s+расч[её]т\s+не\s+включ\w*", re.I)
_TAKEAWAY_RE = re.compile(r"^(?:финальный|главный|итоговый|основной|ключевой|общий)?\s*(?:вывод|итог|takeaway|conclusion)\s*[:—–]\s*(?P<t>.+)$", re.I)
_LIST_LINE_RE = re.compile(
    r"^\s*(?:[—–\-•*]\s+|\d+[.)]\s+|\d+[-‑]?(?:й|я|е|ый|ой)?\s+(?:месяц|недел[яи]|квартал|день|год|этап|шаг|спринт)\b|"
    r"(?:неделя|этап|шаг|месяц|квартал|спринт)\s+\d+\s*[:—–])",
    re.I,
)
_PAIR_CELLS_RE = re.compile(r"^(?P<label>[^:]{2,60}?)\s*:\s*(?P<cells>.+\S)\s*$")


# ------------------------------------------------------------------ the reading state


@dataclass
class _Block:
    """One part of the brief read on its own: a slide the user described, or a section of a brief without slides."""

    number: Optional[int]
    title: str
    lines: list[str]
    spec: Optional[SlideSpec] = None
    series: list[str] = field(default_factory=list)  # registry ids
    tables: list[int] = field(default_factory=list)
    covered: list[float] = field(default_factory=list)  # figures some series / table / formula shows

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


class _Registry:
    """Series and tables of the whole brief; the same data said twice gets one id."""

    def __init__(self) -> None:
        self.series: list[Series] = []
        self.tables: list[TableData] = []

    def add_series(self, s: Series) -> str:
        key = (tuple(round(v, 6) for v in s.values), tuple(c.lower() for c in s.categories))
        for old in self.series:
            if (tuple(round(v, 6) for v in old.values), tuple(c.lower() for c in old.categories)) == key:
                return old.id
        taken = {x.id for x in self.series}
        n = len(self.series) + 1
        while f"s{n}" in taken:
            n += 1
        s.id = f"s{n}"
        self.series.append(s)
        return s.id

    def add_table(self, t: TableData) -> int:
        for i, old in enumerate(self.tables):
            if old.columns == t.columns and old.rows == t.rows:
                return i
        self.tables.append(t)
        return len(self.tables) - 1

    def get(self, sid: str) -> Optional[Series]:
        return next((s for s in self.series if s.id == sid), None)


# ------------------------------------------------------------------ data readers


_CLAUSE_BOUNDS = (". ", "; ", ": ", " — ", " – ", ", а ", ", и ", ", но ", ", что ", "(")


def _subject(text_before: str) -> tuple[str, bool]:
    """What a figure of the clause measures, from the words before it: «Цель — поднять средний чек» → «средний чек»,
    «Маркетинговый бюджет вырастет» → «Маркетинговый бюджет». The flag: the words came after a verb (said in the
    accusative, to be put back in the nominative)."""
    t = text_before.rstrip(" —–-:,")
    # the clause ends at a sentence mark, a colon, a dash or «, а» / «, и»; a bare comma does not end it («долю
    # расходов на продукты, упаковку и списания»)
    cut = max((t.rfind(b) + len(b) for b in _CLAUSE_BOUNDS if t.rfind(b) != -1), default=0)
    ws = t[cut:].split()
    while ws and ws[0].lower() in _CONJ:
        ws.pop(0)
    after_verb = False
    verbs = [i for i, w in enumerate(ws) if _is_verb(w)]
    if verbs:
        last = verbs[-1]
        if last == len(ws) - 1:
            first = verbs[0]
            ws = ws[:first] if first > 0 else ws[:last]
        else:
            ws = ws[last + 1 :]
            after_verb = True
    # «За 6 месяцев …», «На запуск …»: a leading circumstance is not what is measured
    while ws and ws[0].lower() in _PREPS:
        if len(ws) > 1 and re.match(r"^\d", ws[1]):
            ws = ws[3:]
        else:
            ws = ws[1:]
    ws = [w for w in ws if not re.search(r"\d", w)]
    while ws and ws[-1].lower() in _PREPS | {"—", "–", "-"}:
        ws.pop()
    phrase = " ".join(ws[-8:]).strip(" ,")
    return phrase, after_verb


def _label(phrase: str, after_verb: bool) -> str:
    return H.cap_first(_nominative(phrase) if after_verb else phrase)


def _pair_categories(context: str) -> list[str]:
    low = context.lower()
    if "до и после" in low:
        return ["До", "После"]
    if re.search(r"нынешн|текущ|сейчас|сегодняшн", low) and "прогноз" in low:
        return ["Сейчас", "Прогноз"]
    if re.search(r"цел[ьи]|план|прогноз|ожида|будет|будут|станет|составит|вырастет|вырастут|достигнет|целев|\w+(?:ить|ять|ать)\b|"
                 r"\b(?:увелич|уменьш|сниз|сократ|повыс)ится\b", low):
        return ["Сейчас", "Цель"]
    return ["Было", "Стало"]


_FROM_TO_RE = re.compile(
    rf"(?<![\wё])(?:с|со)\s+(?P<a>{_NUM})\s?(?P<ua>{_UNIT})?(?![\wё\d])\s+до\s+(?P<b>{_NUM})\s?(?P<ub>{_UNIT})?(?![\wё\d:]|[-‑]\s?й)", re.I
)
_VERSUS_RE = re.compile(
    rf"(?P<a>{_NUM})\s?(?P<ua>{_UNIT})?(?P<mid>(?:\s+[а-яё]+){{0,3}}?)\s+против\s+(?P<when>(?:нынешних|текущих|прежних|сегодняшних|прошлых|прошлогодних)\s+)?"
    rf"(?P<b>{_NUM})\s?(?P<ub>{_UNIT})?",
    re.I,
)


def _pairs_of(sentence: str) -> list[Series]:
    """«поднять средний чек с 300 до 330 рублей» → Средний чек: Сейчас 300, Цель 330; «прибыль достигнет 254 795
    рублей против нынешних 120 000» → Сейчас 120 000, Прогноз 254 795."""
    out: list[Series] = []
    for m in _FROM_TO_RE.finditer(sentence):
        name, acc = _subject(sentence[: m.start()])
        if not name:
            continue
        unit = _unit(m.group("ub") or m.group("ua"))
        cats = _pair_categories(sentence)
        out.append(Series(id="", name=_label(name, acc), categories=cats, values=[_num(m.group("a")), _num(m.group("b"))], unit=unit, source_span=sentence[:200]))
    for m in _VERSUS_RE.finditer(sentence):
        name, acc = _subject(sentence[: m.start()])
        if not name:
            continue
        when = (m.group("when") or "").lower()
        cats = ["Было", "Стало"] if re.search(r"прошл|прежн", when) or not when else ["Сейчас", "Прогноз"]
        unit = _unit(m.group("ua") or m.group("ub"))
        out.append(Series(id="", name=_label(name, acc), categories=cats, values=[_num(m.group("b")), _num(m.group("a"))], unit=unit, source_span=sentence[:200]))
    return out


_ITEM_LABEL_FIRST_RE = re.compile(rf"^(?P<label>[^\d]+?)\s*[—–:-]\s*(?:(?:в|на)\s+)?(?P<num>{_NUM})\s?(?P<unit>{_UNIT})?(?![\wё\d])(?P<rest>.*)$", re.I)
_CHUNK_VALUE_FIRST_RE = re.compile(
    rf"^(?:(?:из\s+них|из\s+этой\s+суммы|из\s+этого|еще|ещё|также|и)\s+)*(?P<num>{_NUM})\s?(?P<unit>{_UNIT})(?![\wё\d])\s*(?:[—–-]\s*)?"
    rf"(?:(?P<verb>[а-яё]+)\s+)?(?P<prep>на|в|во)\s+(?P<label>[^\d]+)$",
    re.I,
)


def _ordinal_categories(labels: list[str]) -> list[str]:
    """«первый месяц», «второй», «третий» → «1-й месяц», «2-й месяц», «3-й месяц»."""
    first = labels[0].lower().split()
    if not first or first[0] not in _ORDINALS:
        return labels
    noun = " ".join(first[1:2])
    out = []
    for lab in labels:
        ws = lab.lower().split()
        if not ws or ws[0] not in _ORDINALS:
            return labels
        out.append(f"{_ORDINALS[ws[0]]}-й {' '.join(ws[1:2]) or noun}".strip())
    return out


_AND_SPLIT_RE = re.compile(rf"^(?P<a>.*?(?:{_NUM})\s?(?:{_UNIT})?)\s+и\s+(?P<b>[^\d]+?[—–]\s*(?:(?:в|на)\s+)?(?:{_NUM}).*)$", re.I)


def _chunks(sentence: str) -> list[str]:
    """The parts of an enumeration: split at «,» / «;», and at an «и» that joins two «label — figure» parts
    («… маркетинг — 15 000 и учет — 5 000»), never inside a label («десерты и выпечка — 25%»)."""
    out: list[str] = []
    for c in re.split(r"[,;]\s+(?![^()]*\))", sentence):
        c = c.strip()
        m = _AND_SPLIT_RE.match(c)
        if m:
            out.extend([m.group("a").strip(), m.group("b").strip()])
        elif c:
            out.append(c)
    return out


def _chain(sentence: str, min_items: int = 3) -> Optional[tuple[str, Series]]:
    """An enumeration said in one sentence: «кофе — 60%, десерты и выпечка — 25%, чай — 15%», «первый месяц — 930 000
    рублей, второй — 970 000 …», «70 000 рублей пойдет на витрину, 35 000 рублей — на программу …». Returns (the words
    before the enumeration, the series) when at least `min_items` parts share one unit."""
    s = H.strip_end(sentence)
    lead = ""
    split = H.label_split(s)
    if split and not re.search(r"\d", split[0]) and re.search(r"\d", split[1]):
        lead, s = split[0].strip(), split[1].strip()
    parts = _chunks(s)
    if len(parts) < min_items:
        return None
    labels: list[str] = []
    values: list[float] = []
    units: list[Optional[str]] = []
    value_first = bool(_CHUNK_VALUE_FIRST_RE.match(parts[0])) or bool(_CHUNK_VALUE_FIRST_RE.match(parts[-1]))
    prefix = ""
    accusative = False
    for k, p in enumerate(parts):
        if value_first:
            m = _CHUNK_VALUE_FIRST_RE.match(p)
            if not m:
                return None
            lab = m.group("label").strip()
            if m.group("prep").lower() in ("в", "во"):
                ws = lab.split()
                if ws and len(ws[0]) >= 6 and ws[0].lower().endswith("е"):
                    ws[0] = ws[0][:-1]
                lab = " ".join(ws)
            labels.append(_nominative(lab))
            values.append(_num(m.group("num")))
            units.append(_unit(m.group("unit")))
            continue
        # label first: the figure is the last one of the part, after a dash or a «в»/«на»
        nums = list(_NUM_RE.finditer(p))
        if not nums:
            return None
        m = nums[-1]
        rest = p[m.end() :].strip()
        if len(rest.split()) > 3:
            return None
        before = p[: m.start()].rstrip()
        before = re.sub(r"\s*(?:[—–:-]\s*)?(?:(?:в|на|—)\s*)?$", "", before).rstrip(" —–-:")
        if k == 0:
            if re.search(r"\d", before) or len(before.split()) > 5:
                # «Рост … включает дополнительные расходы на персонал — 20 000»: the words after the last verb, and
                # of them the part after the last «на» when it is short
                phrase, accusative = _subject(before)
                if " на " in f" {phrase} ":
                    head, _, tail = phrase.rpartition(" на ")
                    if 1 <= len(tail.split()) <= 3:
                        prefix, phrase = head, tail
                before = phrase
            else:
                ws = before.split()
                verbs = [i for i, w in enumerate(ws) if _is_verb(w)]
                if verbs and verbs[-1] == len(ws) - 1 and verbs[-1] > 0:
                    before = " ".join(ws[: verbs[-1]])
        elif re.search(r"\d", before) or not before or len(before.split()) > 6:
            return None
        labels.append(before.strip(" ,"))
        values.append(_num(m.group("num")))
        units.append(_unit(m.group("unit")))
    known = {u for u in units if u}
    if len(known) > 1 or any(not lab for lab in labels):
        return None
    unit = next(iter(known), None)
    if accusative:
        labels = [_nominative(lab) for lab in labels]  # «включает … маркетинг, программу лояльности» → «программа»
    cats = _ordinal_categories([lab for lab in labels])
    cats = [H.cap_first(c) for c in cats]
    if len(set(c.lower() for c in cats)) < len(cats):
        return None
    return (lead or prefix), Series(id="", name="", categories=cats, values=values, unit=unit, source_span=sentence[:200])


def _name_from_lead(lead: str) -> str:
    """«Ежемесячные расходы:» → «Ежемесячные расходы»; «Общий бюджет запуска — 180 000 рублей:» → «Общий бюджет запуска»;
    «Нужна круговая диаграмма структуры выручки» → «Структура выручки»."""
    t = H.strip_end(lead)
    m = _CHART_NOUN_RE.search(t)
    if m:
        t = t[m.end() :].strip()
    t = re.split(rf"\s+[—–-]\s+(?={_NUM})|\s+(?:в|на)\s+(?={_NUM})", t)[0]
    um = _LEAD_UNIT_RE.search(t)
    if um:
        t = t[: um.start()]  # «Доходы VK по направлениям, 2019 год, %»: the unit is the series', not its name
    ws = t.split()
    if ws and ws[0].lower() in _HEAD_WORDS:
        ws[0] = _HEAD_WORDS[ws[0].lower()]
    # a year stays («…, 2019 год»: gate 4 G4-11), other digits go
    ws = [w for w in ws if not re.search(r"\d", w) or re.fullmatch(r"(?:1\d{3}|20\d{2})(?:[–—-](?:1\d{3}|20\d{2}))?,?", w)]
    return H.cap_first(" ".join(ws[:8]).strip(" ,—–-"))


# a unit written after the last comma of a data caption («Доходы VK по направлениям, 2019 год, %», «Выручка, тыс. ₽»)
_LEAD_UNIT_RE = re.compile(r",\s*(%|п\.\s?п\.|(?:тыс\.?|млн|млрд)\s*(?:₽|руб\.?|рублей|\$|долл\.?)?|₽|руб\.?|рублей|\$|долл\.?|шт\.?|чел\.?|ед\.?|кг|км|ГВт|МВт|т)\s*:?$", re.I)


def _lead_unit(lead: str) -> Optional[str]:
    """The unit a data caption names after its last comma («…, 2019 год, %» → «%»), None without one."""
    m = _LEAD_UNIT_RE.search(H.strip_end(lead or "").rstrip(":"))
    return _unit(m.group(1)) if m else None


def _name_from_previous(prev: Optional[str], total: float) -> str:
    """An enumeration without a lead of its own takes the subject of the sentence before it when that sentence gives
    the total («Ежемесячные расходы кофейни составляют 780 000 рублей. Продукты … 315 000, зарплаты — …»)."""
    if not prev:
        return ""
    m = next((m for m in _NUM_RE.finditer(prev) if _in(_num(m.group("num")), [total])), None)
    if m is None:
        return ""
    name, _ = _subject(prev[: m.start()])
    return H.cap_first(name)


def _list_groups(lines: list[str]) -> list[tuple[str, list[str], int]]:
    """Runs of list lines («— аренда — 120 000 рублей;», «1-й месяц — …») with the line before them (their lead)."""
    groups: list[tuple[str, list[str], int]] = []
    cur: list[str] = []
    lead = ""
    start = 0
    prev = ""
    for i, ln in enumerate(lines + [""]):
        s = ln.strip()
        if s and _LIST_LINE_RE.match(s):
            if not cur:
                lead, start = prev, i
            cur.append(s)
        else:
            if cur:
                groups.append((lead, cur, start))
                cur = []
            if s:
                prev = s
    return groups


def _strip_marker(line: str) -> str:
    return re.sub(r"^\s*(?:[—–\-•*]|\d+[.)])\s+", "", line.strip()).strip().rstrip(";.,").strip()


def _list_table(lead: str, items: list[str]) -> Optional[TableData]:
    """«Сделай сравнительную таблицу «Сейчас / Цель»:» over «— средний чек: 300 / 330 рублей;» lines → a table."""
    rows: list[list[str]] = []
    width = None
    for it in items:
        m = _PAIR_CELLS_RE.match(_strip_marker(it))
        if not m:
            return None
        cells = [c.strip() for c in m.group("cells").split(" / ")]
        if len(cells) < 2 or not all(re.search(r"\d", c) for c in cells):
            return None
        # «300 / 330 рублей»: the unit written once belongs to every cell
        tail = re.sub(rf"^.*?(?:{_NUM})", "", cells[-1]).strip()
        if tail and tail != "%":
            cells = [c if re.search(r"[^\d\s.,  %]", c) else f"{c} {tail}" for c in cells]
        width = width or len(cells)
        if len(cells) != width:
            return None
        rows.append([_clean(m.group("label"))] + cells)
    if len(rows) < 2:
        return None
    q = re.search(r"«([^»]+/[^»]+)»", lead) or re.search(r"(\w[\w ]*?)\s*/\s*(\w[\w ]*)", lead)
    heads = [h.strip() for h in (q.group(1).split("/") if q and q.re.groups == 1 else [q.group(1), q.group(2)] if q else [])]
    if len(heads) != width:
        heads = [f"Вариант {k + 1}" for k in range(width)]
    return TableData(columns=["Показатель"] + [H.cap_first(h) for h in heads], rows=rows[:7], source_span=lead[:200] or None)


def _list_series(lead: str, items: list[str]) -> Optional[Series]:
    """«Ежемесячные расходы:» over «— аренда — 120 000 рублей;» lines → a series (every line «label — figure unit»,
    one unit)."""
    labels: list[str] = []
    values: list[float] = []
    units: set[str] = set()
    for it in items:
        m = _ITEM_LABEL_FIRST_RE.match(_strip_marker(it))
        if not m or len(m.group("label").split()) > 8:
            return None
        labels.append(_clean(m.group("label")))
        values.append(_num(m.group("num")))
        if m.group("unit"):
            units.add(_unit(m.group("unit")) or "")
        else:
            units.add("")
    if len(values) < 2 or len(units - {""}) > 1 or ("" in units and len(units) > 1 and len(values) > 2):
        return None
    if len(set(lab.lower() for lab in labels)) < len(labels):
        return None
    unit = next(iter(units - {""}), None) or (_lead_unit(lead) if lead else None)
    return Series(id="", name=_name_from_lead(lead) if lead else "", categories=labels, values=values, unit=unit, source_span=(lead or items[0])[:200])


def _list_items(items: list[str]) -> list[SlideItem]:
    out: list[SlideItem] = []
    for it in items:
        s = _strip_marker(it)
        m = re.match(r"^(?P<t>[^—–:]{2,40}?)\s*(?:\s[—–]\s|:\s)(?P<x>.+)$", s)
        if m and len(m.group("t").split()) <= 4:
            out.append(SlideItem(title=_clean(m.group("t")), text=_clean(m.group("x"))))
        else:
            out.append(SlideItem(title=_clean(s)))
    return out


def _markdown_tables(block_text: str) -> list[TableData]:
    _, sections = H.parse_sections(block_text)
    return [t for sec in sections for t in sec.tables]


# ------------------------------------------------------------------ chart requests


def _chart_requests(sentence: str) -> list[ChartRequest]:
    m = _CHART_NOUN_RE.search(sentence)
    if not m:
        return []
    low = sentence.lower()
    ctype: Optional[ChartKind] = next((t for pat, t in _TYPE_WORDS if re.search(pat, low)), None)
    if ctype is None and not _CHART_ASK_RE.search(sentence):
        return []
    before = sentence[: m.start()].lower()
    if _NEG_ASK_RE.search(before) or re.search(r"\bбез\s+$", before):
        return []  # «Не используй здесь диаграммы», «без диаграмм»
    count = 1
    for w, n in _COUNT_WORDS.items():
        if re.search(rf"(?<![\wё]){w}(?![\wё])", before):
            count = n
    # what the chart shows: the words after the chart noun (up to its data), or before «на диаграмме»
    after = sentence[m.end() :].strip()
    if re.match(r"^[.!?]?$", after):
        what = re.sub(r"^.*?\b(?:покажи|покажите|отобрази|представь|визуализируй|изобрази|сделай|добавь|приведи)\s+", "", sentence[: m.start()], flags=re.I)
        what = re.sub(r"\s+(?:на|в\s+виде)\s*$", "", what.strip(), flags=re.I)
    else:
        what = after
    what_main, _, data = what.partition(":")
    parts = [p.strip(" .") for p in data.split(";") if p.strip(" .")] if count > 1 and data else []
    if count > 1 and len(parts) != count:
        parts = [p.strip(" .") for p in re.split(r";\s+", what_main) if p.strip(" .")]
    whats = parts if len(parts) == count else [H.strip_end(what_main)] * count
    if ctype is None:
        ctype = next((t for pat, t in _IMPLIED_TYPES if re.search(pat, " ".join(whats).lower())), None)
    return [ChartRequest(type=ctype, what=H.strip_end(w)) for w in whats]


def _fit(req: ChartRequest, s: Series, block_numbers: list[float]) -> int:
    n = len(s.values)
    t = req.type
    score = 0
    if t in ("pie", "doughnut"):
        if n >= 3 and all(v >= 0 for v in s.values):
            score += 2
            if (s.unit == "%" and abs(sum(s.values) - 100) < 1.5) or _in(sum(s.values), block_numbers):
                score += 1
        elif n == 2:
            return -5
    elif t == "line":
        score += 2 if n >= 4 else (1 if n >= 3 else -1)
    elif t in ("column", "bar"):
        if n == 2 and re.search(r"до и после|сравнен|было|стало|сейчас|текущ", req.what.lower()):
            score += 2
        elif 2 <= n <= 8:
            score += 1
    else:
        score += 1 if n >= 2 else 0
    return score


def _link_requests(block: _Block, reg: _Registry, inline: dict[int, str], block_numbers: list[float]) -> None:
    """Gives each chart request of the slide its data: the enumeration said in the request itself, else the series of
    this slide it names («средний чек до и после» → «Средний чек»), else the one its kind fits best."""
    spec = block.spec
    if spec is None:
        return
    taken = {sid for r in spec.charts for sid in r.series_ids}
    for k, req in enumerate(spec.charts):
        if k in inline:
            req.series_ids = [inline[k]]
            taken.add(inline[k])
    free = [k for k, r in enumerate(spec.charts) if not r.series_ids]
    scored: list[tuple[int, int, str]] = []
    for k in free:
        req = spec.charts[k]
        for sid in block.series:
            s = reg.get(sid)
            if s is None:
                continue
            overlap = len(_stems(req.what) & _stems(s.name + " " + " ".join(s.categories)))
            fit = _fit(req, s, block_numbers)
            if fit < 0:
                continue
            scored.append((3 * overlap + fit, k, sid))
    for score, k, sid in sorted(scored, key=lambda x: (-x[0], x[1])):
        req = spec.charts[k]
        if req.series_ids or sid in taken or score < 2:
            continue
        req.series_ids = [sid]
        taken.add(sid)


def _starting_point(sentence: str) -> Optional[tuple[str, float]]:
    """«линейный график выручки по месяцам, начиная с текущих 900 000 рублей» → («Сейчас», 900 000)."""
    m = re.search(rf"начиная\s+(?:с|со)\s+(?P<when>текущ\w*|нынешн\w*|сегодняшн\w*|исходн\w*)?\s*(?:[а-яё]+\s+)?(?P<num>{_NUM})", sentence, re.I)
    if not m:
        return None
    return ("Сейчас" if m.group("when") else "Старт"), _num(m.group("num"))


# ------------------------------------------------------------------ reading one block


def _read_block(block: _Block, reg: _Registry, all_numbers: list[float]) -> None:
    lines = block.lines
    spec = block.spec
    text = block.text
    block_numbers = numbers_of(text)
    groups = _list_groups(lines)
    in_list: set[int] = set()
    items: list[SlideItem] = []
    for lead, group, start in groups:
        in_list.update(range(start, start + len(group)))
        tbl = _list_table(lead, group)
        if tbl is not None:
            block.tables.append(reg.add_table(tbl))
            block.covered.extend(n for row in tbl.rows for c in row[1:] for n in numbers_of(c))
            continue
        ser = _list_series(lead, group)
        if ser is not None:
            if not ser.name:
                ser.name = block.title or "Данные"
            block.series.append(reg.add_series(ser))
            block.covered.extend(ser.values)
            continue
        items.extend(_list_items(group))
    for t in _markdown_tables(text):
        block.tables.append(reg.add_table(t))
        block.covered.extend(n for row in t.rows for c in row for n in numbers_of(c))
        ss, _ = H.table_series(t, start_id=1)
        for s in ss:
            block.series.append(reg.add_series(s))
    # sentences outside the lists (list leads included: «Общий бюджет запуска — 180 000 рублей:»)
    sentences: list[str] = []
    for i, ln in enumerate(lines):
        if i in in_list or not ln.strip() or H._TABLE_ROW_RE.match(ln) or H._TABLE_RULE_RE.match(ln):
            continue
        sentences.extend(H.split_sentences(ln.strip()) or [ln.strip()])
    inline: dict[int, str] = {}
    starts: list[tuple[int, tuple[str, float]]] = []  # «начиная с текущих 900 000»: (request index, first point)
    prev: Optional[str] = None
    k = 0
    while k < len(sentences):
        sent = sentences[k]
        reqs = _chart_requests(sent) if spec is not None else []
        ch = _chain(sent, min_items=2 if reqs else 3)
        if ch is not None:
            lead, ser = ch
            # «… 20 000 рублей — на обучение сотрудников. Еще 30 000 рублей останется в резерве.»
            if k + 1 < len(sentences) and re.match(r"^(?:еще|ещё|и еще|и ещё|также|оставшиеся)\b", sentences[k + 1], re.I):
                nxt = _CHUNK_VALUE_FIRST_RE.match(H.strip_end(sentences[k + 1]))
                if nxt and _unit(nxt.group("unit")) == ser.unit and len(numbers_of(sentences[k + 1])) == 1:
                    lab = nxt.group("label").strip()
                    if nxt.group("prep").lower() in ("в", "во"):
                        ws = lab.split()
                        if ws and len(ws[0]) >= 6 and ws[0].lower().endswith("е"):
                            ws[0] = ws[0][:-1]
                        lab = " ".join(ws)
                    ser.categories.append(H.cap_first(_nominative(lab)))
                    ser.values.append(_num(nxt.group("num")))
                    k += 1
            ser.name = _name_from_lead(lead) if lead else ""
            if reqs and not ser.name:
                ser.name = _name_from_lead("диаграмма " + reqs[0].what)
            if not ser.name or len(ser.name.split()) > 6:
                ser.name = _name_from_previous(prev, sum(ser.values)) or ser.name or (block.title or "Данные")
            sid = reg.add_series(ser)
            block.series.append(sid)
            block.covered.extend(ser.values)
            if reqs and spec is not None:
                inline[len(spec.charts)] = sid
        for ser in _pairs_of(sent):
            sid = reg.add_series(ser)
            if sid not in block.series:
                block.series.append(sid)
            block.covered.extend(ser.values)
        if spec is not None:
            if reqs:
                start = _starting_point(sent)
                # a request with its own two figures and no labels: «сравнения текущей и прогнозируемой прибыли:
                # 120 000 и 254 795 рублей»
                if ch is None and len(reqs) == 1 and ":" in sent:
                    vals = numbers_of(sent.split(":", 1)[1])
                    if len(vals) == 2:
                        same = next((sid for sid in block.series if sorted(reg.get(sid).values) == sorted(vals)), None)  # type: ignore[union-attr]
                        if same is None:
                            um = list(_NUM_RE.finditer(sent.split(":", 1)[1]))
                            ser = Series(id="", name=_name_from_lead("диаграмма " + reqs[0].what), categories=_pair_categories(sent), values=vals, unit=_unit(um[-1].group("unit")), source_span=sent[:200])
                            same = reg.add_series(ser)
                            block.series.append(same)
                            block.covered.extend(vals)
                        inline[len(spec.charts)] = same
                spec.charts.extend(reqs)
                if start is not None:
                    starts.append((len(spec.charts) - 1, start))
            if _TABLE_ASK_RE.search(sent) and re.search(r"сделай|нуж|покажи|добавь|построй|оформи|в\s+виде|сравнительн", sent, re.I) and not _NEG_ASK_RE.search(sent):
                spec.table = True
            fm = _FORMULA_RE.search(sent)
            if fm and not spec.formula:
                spec.formula = H.strip_end(fm.group("f"))
                block.covered.extend(numbers_of(spec.formula))
            tm = _TAKEAWAY_RE.match(sent)
            if tm and not spec.takeaway:
                spec.takeaway = H.cap_first(_unquote(tm.group("t")))
            fn = _FOOTNOTE_ASK_RE.match(sent)
            if fn and not spec.footnote:
                spec.footnote = H.cap_first(H.strip_end(fn.group("t") or fn.group("t2")))
        prev = sent
        k += 1
    if spec is not None:
        if not spec.footnote:
            st = next((s for s in sentences if _FOOTNOTE_STATE_RE.search(s) and not _is_rule(s)), None)
            if st:
                spec.footnote = H.strip_end(st)
        spec.items = items
        _link_requests(block, reg, inline, block_numbers)
        for idx, (cat, value) in starts:
            req = spec.charts[idx]
            s = reg.get(req.series_ids[0]) if req.series_ids else None
            if s is not None and not _in(value, s.values[:1]) and _in(value, all_numbers) and cat not in s.categories:
                s.categories.insert(0, cat)
                s.values.insert(0, value)
        spec.series_ids = list(dict.fromkeys(block.series))
        spec.table_ids = list(dict.fromkeys(block.tables))



# ------------------------------------------------------------------ the whole brief


def _front_matter(text: str) -> tuple[dict, str]:
    m = _FRONT_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for ln in m.group(1).splitlines():
        k, sep, v = ln.partition(":")
        if sep:
            meta[k.strip().lower()] = v.strip()
    return meta, text[m.end() :]


def _blocks(text: str) -> tuple[list[_Block], list[str]]:
    """The slide blocks (or, without slide specs, the sections) and the global lines (outside any slide)."""
    lines = text.splitlines()
    heads = _spec_heads(lines, text)
    if not heads:
        blocks: list[_Block] = []
        cur: list[str] = []
        title = ""
        for ln in lines:
            if re.match(r"^\s*#{1,6}\s", ln):
                if any(x.strip() for x in cur):
                    blocks.append(_Block(number=None, title=title, lines=cur))
                cur, title = [], ln.lstrip("# ").strip()
            else:
                cur.append(ln)
        if any(x.strip() for x in cur):
            blocks.append(_Block(number=None, title=title, lines=cur))
        return blocks, lines
    glob = lines[: heads[0][0]]
    blocks = []
    bounds = [h[0] for h in heads] + [len(lines)]
    for k, (i, n, title) in enumerate(heads):
        body = lines[i + 1 : bounds[k + 1]]
        while body and not body[-1].strip():
            body.pop()
        if k == len(heads) - 1:
            # the brief's closing rules after the last slide («Не перегружай слайды текстом. …») are global
            while True:
                gaps = [j for j, ln in enumerate(body) if not ln.strip()]
                if not gaps:
                    break
                tail = body[gaps[-1] + 1 :]
                sents = sentences_of("\n".join(tail))
                if sents and all(_is_rule(s) for s in sents):
                    glob = glob + [""] + tail
                    body = body[: gaps[-1]]
                    while body and not body[-1].strip():
                        body.pop()
                else:
                    break
        blk = _Block(number=n, title=title, lines=body)
        blk.spec = SlideSpec(number=n, title=title, text="\n".join(body).strip())
        blocks.append(blk)
    return blocks, glob


def read_structure(text: str) -> BriefStructure:
    """The brief read by rules alone (no model): slide specs, requests, rules and data. Always succeeds."""
    meta, body = _front_matter(text or "")
    blocks, glob = _blocks(body)
    has_specs = any(b.spec is not None for b in blocks)
    st = BriefStructure()
    # title and subtitle: «Название: «…»» wins, then a markdown title, then the first line when it names the deck,
    # then «на тему «…»»
    for ln in body.splitlines():
        m = _TITLE_RE.match(ln)
        if m and st.title is None:
            st.title = _unquote(m.group("v")) or None
        m = _SUBTITLE_RE.match(ln)
        if m and st.subtitle is None:
            st.subtitle = _unquote(m.group("v")) or None
    if st.title is None:
        h1 = re.search(r"^\s*#\s+(.+)$", body, re.M)
        if h1:
            st.title = H.strip_end(h1.group(1))
    glob_text = "\n".join(glob) if has_specs else body
    if st.title is None and has_specs:
        first = next((ln.strip() for ln in glob if ln.strip()), "")
        sent = (H.split_sentences(first) or [first])[0] if first else ""
        if sent and len(sent.split()) <= 14 and not _is_rule(sent) and not _TASK_RE.match(sent) and not _DISCLAIMER_RE.search(sent):
            st.title = H.strip_end(sent)
    if st.title is None:
        tm = _TOPIC_RE.search(body)
        if tm:
            st.title = H.strip_end(tm.group("v"))
    # slide count
    raw = meta.get("slides") or meta.get("slide_count") or meta.get("слайдов")
    if raw and str(raw).isdigit():
        st.slide_count = int(raw)
    else:
        cm = _COUNT_RE.search(body)
        if cm:
            st.slide_count = int(next(g for g in cm.groups() if g))
    # global rules, disclaimer, notes, rounding
    gsents = sentences_of(glob_text)
    st.rules = [H.strip_end(s) + "." if not s.rstrip().endswith(("!", "?")) else s.strip() for s in gsents if _is_rule(s)]
    disc = [H.strip_end(s) for s in gsents if _DISCLAIMER_RE.search(s) and not _is_rule(s) and len(s.split()) <= 25]
    if disc:
        st.disclaimer = ". ".join(disc)
    all_sents = sentences_of(body)
    st.notes_rule = any(_NOTES_RE.search(s) for s in all_sents)
    rs = next((s for s in all_sents if _ROUND_RE.search(s)), None)
    if rs:
        st.rounding = H.strip_end(rs)
    # data, block by block (a brief without slide specs: its markdown tables first, as the facts registry reads them)
    reg = _Registry()
    all_numbers = numbers_of(body)
    if not has_specs:
        _, sections = H.parse_sections(body)
        for t in (t for sec in sections for t in sec.tables):
            reg.add_table(t)
            ss, _ = H.table_series(t, start_id=1)
            for s in ss:
                reg.add_series(s)
    for blk in blocks:
        _read_block(blk, reg, all_numbers)
    st.series = reg.series
    st.tables = reg.tables
    st.specs = [b.spec for b in blocks if b.spec is not None]
    return st


# ------------------------------------------------------------------ the model's part


class ChartHint(BaseModel):
    """The chart a series of the answer fits (data_extractor v2)."""

    series: str = ""
    type: str = ""  # pie / doughnut / line / column / bar / area; anything else is ignored, never a failed answer


class BlockExtraction(FactsExtraction):
    """Output of the `data_extractor` skill (v2): facts, series, tables of one part of the brief, and chart hints."""

    charts: list[ChartHint] = Field(default_factory=list)


def _uncovered(blk: _Block, reg: _Registry) -> list[float]:
    text = _TIME_RE.sub(" ", blk.text)
    covered = list(blk.covered)
    for sid in blk.series:
        s = reg.get(sid)
        if s is not None:
            covered.extend(s.values)
    return [n for n in numbers_of(text) if not _in(n, covered)]


def needs_model(blk: _Block, reg: _Registry) -> bool:
    """A block the rules did not cover: a chart request left without data, or most of its figures (three or more)
    outside every series, table and formula of it."""
    if blk.spec is not None and any(not r.series_ids for r in blk.spec.charts):
        return True
    figures = numbers_of(_TIME_RE.sub(" ", blk.text))
    free = _uncovered(blk, reg)
    return len(free) >= 3 and len(free) > len(figures) / 2


def _language(text: str) -> str:
    return "ru" if re.search(r"[а-яё]", text, re.I) else "en"


def _checked(out: BlockExtraction, block_text: str) -> BlockExtraction:
    """Only what the block says: every series value and every table figure is a number of the block."""
    pool = numbers_of(block_text)
    series = []
    for s in out.series:
        if 2 <= len(s.values) <= 12 and len(s.categories) == len(s.values) and all(_in(v, pool) for v in s.values):
            series.append(s)
    tables = []
    for t in out.tables:
        cells = [c for row in t.rows for c in row]
        if t.columns and t.rows and len(t.rows) <= 7 and len(t.columns) <= 5 and all(_in(n, pool) for c in cells for n in numbers_of(c)):
            tables.append(t)
    facts = [f for f in out.facts if numbers_of(f.value) and all(_in(n, pool) for n in numbers_of(f.value))]
    return BlockExtraction(facts=facts, series=series, tables=tables, charts=out.charts)


def enrich_with_model(
    structure: BriefStructure,
    text: str,
    skills: Any,
    providers: Any,
    deadline: Optional[float] = None,
    progress: Optional[Callable[[dict], None]] = None,
    warnings: Optional[list[str]] = None,
) -> BriefStructure:
    """Runs the data_extractor skill on each block the rules did not cover (in parallel, bounded by the providers'
    concurrency), keeps what the block really says, and returns a new structure with the extra series, tables and
    facts (spec series_ids / table_ids and requests without data filled). No model, or nothing to do: the structure as
    it is. A failed block is skipped (noted in `warnings`)."""
    if skills is None or providers is None or not getattr(providers, "has", lambda r: False)("llm"):
        return structure
    _, body = _front_matter(text or "")
    blocks, _ = _blocks(body)
    st = structure.model_copy(deep=True)
    reg = _Registry()
    reg.series = st.series
    reg.tables = st.tables
    specs = {s.number: s for s in st.specs}
    for blk in blocks:
        if blk.spec is not None and blk.number in specs:
            blk.spec = specs[blk.number]
            blk.series = list(blk.spec.series_ids)
            blk.tables = list(blk.spec.table_ids)
            if blk.spec.formula:
                blk.covered.extend(numbers_of(blk.spec.formula))
        else:
            blk.spec = None
            stems = numbers_of(blk.text)
            blk.series = [s.id for s in st.series if s.values and all(_in(v, stems) for v in s.values)]
        for ti in blk.tables:
            if 0 <= ti < len(st.tables):
                blk.covered.extend(n for row in st.tables[ti].rows for c in row for n in numbers_of(c))
    todo = [b for b in blocks if b.text and needs_model(b, reg)]
    if not todo:
        return st
    if progress is not None:
        which = [str(b.number) for b in todo if b.number is not None]
        msg = f"Уточняю данные слайдов {', '.join(which)} с помощью модели" if which else f"Уточняю данные {len(todo)} {_plural(len(todo), 'раздела', 'разделов', 'разделов')} брифа с помощью модели"
        progress({"type": "agent", "step": "analyst", "message": msg, "slide": None, "variant": None})
    prov = providers.with_deadline(deadline) if deadline is not None and hasattr(providers, "with_deadline") else providers
    lang = _language(body)
    limits = getattr(providers, "limits", None)
    workers = max(1, min(len(todo), int(getattr(limits, "max_concurrency", 4) or 4)))
    results: dict[int, BlockExtraction] = {}

    def run(i: int, blk: _Block) -> tuple[int, BlockExtraction]:
        res = skills.run("data_extractor", prov, {"brief": blk.text, "language": lang})
        parsed = res.parsed
        if not isinstance(parsed, BlockExtraction):
            parsed = BlockExtraction.model_validate(parsed.model_dump() if isinstance(parsed, BaseModel) else parsed)
        return i, _checked(parsed, blk.text)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run, i, b) for i, b in enumerate(todo)]
        for fut in as_completed(futs):
            try:
                i, out = fut.result()
                results[i] = out
            except Exception as e:  # a block the model could not read keeps what the rules found
                log.warning("data_extractor on a block failed: %s", str(e)[:200])
                if warnings is not None:
                    warnings.append(f"data_extractor failed on a block, rules kept: {str(e)[:160]}")
    added_series = added_tables = 0
    for i, blk in enumerate(todo):
        out = results.get(i)
        if out is None:
            continue
        ids: dict[str, str] = {}
        for s in out.series:
            before = len(reg.series)
            new = Series(id="", name=s.name, categories=[str(c) for c in s.categories], values=list(s.values), unit=s.unit, source_span=None)
            sid = reg.add_series(new)
            added_series += len(reg.series) - before
            ids[s.id] = sid
            if sid not in blk.series:
                blk.series.append(sid)
        for t in out.tables:
            before = len(reg.tables)
            ti = reg.add_table(TableData(columns=t.columns, rows=[r[: len(t.columns)] for r in t.rows], unit=t.unit, caption=t.caption))
            added_tables += len(reg.tables) - before
            if ti not in blk.tables:
                blk.tables.append(ti)
        for f in out.facts:
            f.id = f"m{len(st.facts) + 1}"
            f.source_span = (f.source_span or "")[:120] or None
            st.facts.append(f)
        if blk.spec is not None:
            blk.spec.series_ids = list(dict.fromkeys(blk.series))
            blk.spec.table_ids = list(dict.fromkeys(blk.tables))
            _link_requests(blk, reg, {}, numbers_of(blk.text))
            kinds = ("bar", "column", "line", "area", "pie", "doughnut")
            hints = {ids.get(h.series): h.type.lower() for h in out.charts if ids.get(h.series) and h.type.lower() in kinds}
            for req in blk.spec.charts:
                if req.type is None and req.series_ids and req.series_ids[0] in hints:
                    req.type = hints[req.series_ids[0]]
    st.series = reg.series
    st.tables = reg.tables
    # what the model added, the non-zero parts only; nothing added — no line
    added = [f"{n} {_plural(n, *words)}" for n, words in ((added_series, ("ряд данных", "ряда данных", "рядов данных")), (added_tables, ("таблицу", "таблицы", "таблиц"))) if n]
    if progress is not None and added:
        progress({"type": "agent", "step": "analyst", "message": f"Модель добавила {' и '.join(added)}", "slide": None, "variant": None})
    return st


def describe(structure: BriefStructure) -> str:
    """The analyst's report in one plain Russian sentence: «Нашёл в брифе 10 слайдов, 14 рядов данных, 1 таблицу и 1
    заказанную диаграмму»."""
    parts = []
    n = len(structure.specs)
    if n:
        parts.append(f"{n} {_plural(n, 'слайд', 'слайда', 'слайдов')}")
    k = len(structure.series)
    parts.append(f"{k} {_plural(k, 'ряд', 'ряда', 'рядов')} данных")
    t = len(structure.tables)
    if t:
        parts.append(f"{t} {_plural(t, 'таблицу', 'таблицы', 'таблиц')}")
    c = sum(len(s.charts) for s in structure.specs)
    if c:
        parts.append(f"{c} {_plural(c, 'заказанную диаграмму', 'заказанные диаграммы', 'заказанных диаграмм')}")
    f = sum(1 for s in structure.specs if s.formula)
    if f:
        parts.append(f"{f} {_plural(f, 'формулу', 'формулы', 'формул')}")
    head = "Нашёл в брифе " + (", ".join(parts[:-1]) + " и " + parts[-1] if len(parts) > 1 else parts[0])
    if structure.slide_count:
        head += f"; нужно {structure.slide_count} {_plural(structure.slide_count, 'слайд', 'слайда', 'слайдов')}"
    return head
