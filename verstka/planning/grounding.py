"""Grounding: a model's slide plan keeps only what the brief says.

A model asked for twelve slides from a four-line brief fills them: a pilot «on 12 thousand users» (copied from an
example of the prompt), «NPS 64%», phases, benefits and recommendations nobody wrote, charts without data, a thanks
slide with «[email]». This pass checks every model plan against the brief, deterministically and without a model,
before anything is rendered:

- figures: every number of a headline, section label, subtitle, text, bullet, item, callout, table cell or caption is a
  figure of the brief's text or title (not of the user's instructions or the audience), value-normalised: «12 400» =
  «12400», «14,5» = «14.5», «15млн» = «15 млн», «13K» = «13 тыс.», «15.10.2026» = «15 октября 2026 года»,
  «двенадцать тысяч» = «12 000», «вдвое» = «в 2 раза», «треть» ≈ 33%, «в каждом третьем случае» ≈ 33%; a hedged
  fraction on its side («больше половины» for 58%, «более чем на треть» for 38%, «почти три четверти» for 71%). A
  figure may be the brief's rounded half up to an integer or one decimal («38%» for 38,3%, «12 тыс.» for 12 400),
  never from the midpoint («15 млн» is not 14,5 млн). It may also be a simple derived value of two brief figures of
  one measure written close together (the two values of a change the brief states; with a unit, one sentence or two
  neighbouring ones; without one, side by side in a sentence; one table row — not the ends of a range): their
  difference, their percent change from the earlier value, their ratio («47 → 29 минут»: «18 минут», «38%»), and a
  share written as «6 из 30» (20%). Anything else is removed with its clause; a headline that loses its figure is
  replaced by a grounded one; a slide whose substance is gone is dropped. Step numbers («Этап 1») and small counts
  in words («три этапа») are not figures; a year is four digits without a separator or a number with «год» («2026»,
  «в 2025 году»; not «2 000»).
- units: a unit written once is the unit of both values of a change («было 47, стало 29 минут», «с 47 минут до 29»,
  «12 дней → 4», «до внедрения 12 дней, после — 4»); a unit the brief does not use with that number is removed
  («NPS 64%» → «NPS 64»); a time unit or a multiple is never given to a number the brief writes without one, but for a
  year («в 2026 году»).
- changes: a rise or a fall of a figure the brief gives only as a level goes with its clause — «NPS вырос до 64»,
  «Повышение удовлетворенности (NPS 64)» when the brief says «NPS 64» and no earlier value. A change stands when the
  brief states one for that figure: a change word («время сократилось до 29 минут», «экономия 2,1 часа»), an earlier
  and a later value of one measure («было 47 минут, стало 29», «NPS 64 (было 41)», «12 дней, после внедрения 4», two
  years; not «было задействовано», «стало понятно», «теперь» or «после внедрения» with nothing earlier, and two
  figures without a unit only side by side), a table's series; when the clause gives both ends and the brief has them
  side by side («с 47 до 29 минут»); or when the figure is the change itself (a derived «на 18 минут»). «на 29 минут»
  is a change by 29, «до 29 минут» a change to 29: each must be what the brief says («выросла до 34%» is not «выросла
  на 34%», but «экономия выросла до 2,1 часа» is a level of savings). A change word without a figure of its own
  («Удовлетворённость выросла: NPS 64») speaks for the figures of its sentence only when the brief does not state that
  change, and then only its own clause goes («NPS 64» stays); «Время на чтение чатов сократилось, NPS 64» stands.
- names glued to digits («Qwen3.8», «Q3», «3-х») must be written in the brief.
- placeholders: «[email]», «[телефон]», «{company}», «<имя>», e-mails, phones and sites the brief does not give,
  «Иван Иванов», «XXX», lorem ipsum. «<5 минут» is a comparison, not a placeholder.
- structure: a chart whose series ids do not resolve becomes a KPI row of its grounded figures (or goes, when they
  are all on other slides already), an unknown kind («freeform») takes the kind its content asks for, a comparison
  with empty columns goes, a divider with nothing after it goes, the agenda names only what the deck still has; a
  figure slide goes only when it is a chart turned into figures or a slide that lost most of its lines, and repeats
  other slides, or when another slide shows exactly its figures — a problem → result pair and a summary KPI slide stay.
- content: a bullet, card or column line whose words are mostly not the brief's (stems compared, stop words left
  out) goes — unless it states a figure of the brief with its unit and claims no change («Работники экономят 18 минут
  в день»: a paraphrase) — and so does a slide left without them («План масштабирования: Фаза 1 …»,
  «Рекомендации по действию»). A section label («Детали», «План или сроки»), a table caption and a quotation's author
  must be the brief's words. Headings, dividers, the agenda and the closing slide are not judged by their words.
- title: the deck's title is grounded in the brief's title line («Название: «Больше прибыли с каждой чашки»»), its
  first statement, otherwise it is the brief's own title.
- Agent v2 (planning/compile.py runs this pass with the brief's structure): every value of a chart — registry series,
  the data written into a chart and its second chart — is a figure of the brief (a value in «тыс. ₽» counts in
  thousands); when the brief allows it («Денежные суммы на диаграммах можно округлять до тысяч рублей») a chart value
  may be the brief's rounded to that step. A formula keeps every operand of the brief or goes whole; a takeaway and a
  footnote lose the clauses of invented figures like any line, never for their words. A slide the user asked for
  («Слайд 3.», `spec_ref`) is never dropped: only its invented figures (and placeholders) go, the model's wording
  stays — the words check is for slides nobody asked for.

The pass never adds content: a deck may come out shorter than its target, which is what the brief supports. It is
idempotent and reports what it changed as warning lines («grounding: …»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from itertools import combinations
from typing import Iterable, Optional, Union

from verstka.planning import heuristics as H
from verstka.planning.plan_json import ALLOWED_KINDS, has_body, kind_by_content
from verstka.schemas.brief_structure import BriefStructure
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import Brief, ChartSpec, DeckOutline, Fact, NumberCallout, OutlineSlide, Series, SlideContent, SlideItem

# ------------------------------------------------------------------ figures

_SPACES = "   "
_SP = f"[{_SPACES}]"
_NB = r"(?![\wё])"
# a unit written glued to its number: «15млн», «13K», «3x», «5ч», «2026г.» — a figure to check, not a name
_GLUED = r"(?:млрд|млн|трлн|тыс|мин|сек|ч|г|[kк]|[xх×]|[mм])"
_NUM_RE = re.compile(
    rf"(?<![\w.,])(?P<num>\d{{1,3}}(?:{_SP}\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?:(?={_GLUED}{_NB})|(?![\w]|[.,]\d))",
    re.I,
)
_CUR = rf"₽|руб(?:\.|л\w*|{_NB})|\$|€|долл\w*|евро{_NB}"
_UNIT_ALTS = (
    rf"(?P<pp>п\.\s?п\.?|пп{_NB}|процентн\w*\s+пункт\w*)"
    rf"|(?P<pct>%|процент\w*)"
    rf"|(?P<scale>тыс\.|тыс{_NB}|тысяч\w*|млн\.?{_NB}|млн\.|миллион\w*|млрд\.?{_NB}|млрд\.|миллиард\w*|трлн\.?)(?:{_SP}?(?P<cur2>₽|руб(?:\.|л\w*)?|\$|€|долл\w*|евро{_NB}))?"
    rf"|(?P<cur>{_CUR})"
    rf"|(?P<time>секунд\w*|сек\.?{_NB}|минут\w*|мин\.?{_NB}|час(?:а|ов|ах|ам)?{_NB}|ч\.?{_NB}|сут(?:ки|ок){_NB}|дн(?:я|ей|и|ям|ях)?{_NB}|день{_NB}"
    rf"|недел\w*|нед\.?{_NB}|месяц\w*|мес\.?{_NB}|год(?:а|у|ы|ов|ах)?{_NB}|лет{_NB}|г\.)"
    rf"|(?P<times>раза?{_NB}|[xх×]{_NB})"
    rf"|(?P<pts>пункт(?:а|ов|ы)?{_NB}|балл(?:а|ов|ы)?{_NB})"
    rf"|(?P<cnt>шт\.?|чел\.?|человек{_NB})"
)
_UNIT_AFTER_RE = re.compile(rf"{_SP}?(?:{_UNIT_ALTS})", re.I)
_UNIT_IN_RE = re.compile(rf"(?<![\wё])(?:{_UNIT_ALTS})", re.I)
# «13K», «12k ₽»: thousands, written glued only («к сентябрю» is a preposition)
_KILO_RE = re.compile(rf"[kк]{_NB}(?:{_SP}?(?P<cur>{_CUR}))?", re.I)
_SCALES = {"тыс": 1e3, "тысяч": 1e3, "млн": 1e6, "миллион": 1e6, "млрд": 1e9, "миллиард": 1e9, "трлн": 1e12}
_TIME_UNITS = (("сек", "sec"), ("мин", "min"), ("час", "h"), ("ч", "h"), ("сут", "d"), ("дн", "d"), ("день", "d"), ("нед", "w"), ("мес", "mo"), ("год", "y"), ("лет", "y"), ("г", "y"))
_STRIPPABLE = {"pct", "pp", "rub", "usd", "eur", "times"}
# a unit taken off a bare number of the brief («NPS 64%» → «NPS 64»); not «в 2 раза» of «месяц 1–2»: «в 2» says nothing
_STRIP_UNITS = _STRIPPABLE - {"times"}
# dates: «15.10.2026», «1 ноября», «15 октября 2026 года»
_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
_DATE_RE = re.compile(
    rf"(?<![\w.,])(?:(?P<d1>\d{{1,2}})\.(?P<m1>\d{{1,2}})\.(?P<y1>\d{{4}}|\d{{2}})(?![\d.,]\d)(?:{_SP}?г(?:\.|{_NB}))?"
    rf"|(?P<d2>\d{{1,2}}){_SP}+(?P<m2>{'|'.join(_MONTHS)})(?:{_SP}+(?P<y2>\d{{4}})(?:{_SP}?(?:года|году|год|г\.|г{_NB}))?)?{_NB})",
    re.I,
)
# «Этап 1», «Неделя 2», «Шаг 3»: a step's number, not a figure
_ORDINAL_BEFORE_RE = re.compile(
    r"(?<![\wё])(?:этап\w*|шаг\w*|фаз\w*|недел\w*|волн\w*|спринт\w*|итераци\w*|верси\w*|вариант\w*|уров\w*|пункт\w*|слайд\w*|step|phase|stage|week|wave|sprint|version|option|level|slide|№|#)\s*$",
    re.I,
)
_LIST_NUMBER_RE = re.compile(r"^\s*\d{1,2}[.)]\s")
# a rise or a fall (and a saving, which is one): «вырос», «рост», «повышение», «снизилось», «сокращение», «экономия»;
# not «повышенная нагрузка» (a level) nor «экономика»
_CHANGE_RE = re.compile(
    r"(?<![\wё])(?:вырос|выраст|рост|прирост|раст[её]т|растут|повы[сш](?!енн)|увелич|улучш|сниз|сниж|сократ|сокращ|уменьш|упал|"
    r"паден|экономи[яюиет]|сэконом|grew|grow|increas|rise|rose|improv|decreas|declin|drop|fell|fall(?!back)|reduc|"
    r"sav(?:e|ed|es|ing))\w*",
    re.I,
)
_SAVING_RE = re.compile(r"(?:эконом|сэконом|sav)", re.I)
# the size of a change written without a verb of change: «на 238 500 рублей больше текущей» (a difference), «Рост
# составит 112,3%», «Прирост — 15%» (a change noun and its size)
_COMPARE_AFTER_RE = re.compile(r"\s*(?:больше|меньше|выше|ниже|дороже|дешевле|more|less|higher|lower)(?![\wё])", re.I)
_SIZE_BEFORE_RE = re.compile(
    r"(?<![\wё])(?:рост|прирост|снижение|сокращение|увеличение|уменьшение|падение)(?:\s+[\wё]+){0,3}\s*(?:состав\w*|—|–|:)\s*"
    r"(?:(?:примерно|около|почти|порядка|более|менее|свыше)\s+)?$",
    re.I,
)
# a change written with its ends: «с 47 до 29», «от 1 200 до 12 400», «47 → 29»; a range «8–25 секунд»
_FROM_RE = re.compile(r"(?<![\wё])(?:с|со|от|from)\s*$", re.I)
_ARROW_BETWEEN_RE = re.compile(r"\s*(?:→|->|—>|=>)\s*")
_TO_BETWEEN_RE = re.compile(r"\s*(?:до|по|to)\s*", re.I)
_RANGE_BETWEEN_RE = re.compile(r"[–—-]")
_SLASH_BETWEEN_RE = re.compile(r"\s*/\s*")  # «Сейчас / Цель: 465 000 / 508 000 рублей» — the unit written once
# «на 18 минут» (the size of a change), «до 29 минут» (the level it came to)
_PREP_RE = re.compile(r"(?<![\wё])(на|до|by|to)\s*[−+\-–]?\s*$", re.I)
_NEXT_WORD_RE = re.compile(rf"{_SP}*([а-яёa-z]+)", re.I)
# an earlier value and a later one of the brief: «было 47 минут, стало 29», «NPS 64 (было 41)», «до внедрения 12 дней,
# после — 4». A marker speaks of the figure right after it; «было задействовано», «стало понятно» are not markers.
_EVENT = r"(?:внедрени|пилот|запуск|начал|переход|миграци|изменени|обучени|автоматизаци|проект|реформ|оптимизаци)\w*"
_EARLIER_MARK = rf"было|был|была|были|раньше|ранее|прежде|до\s+{_EVENT}|before|was|were"
_LATER_MARK = rf"стало|стал|стала|стали|станет|станут|теперь|сейчас|после(?:\s+{_EVENT})?|after|now"
_EARLIER_MARK_RE = re.compile(rf"(?<![\wё])(?:{_EARLIER_MARK})(?![\wё])", re.I)
_LATER_MARK_RE = re.compile(rf"(?<![\wё])(?:{_LATER_MARK})(?![\wё])", re.I)
# «было задействовано», «был запущен», «стало понятно», «стало ясно»: a passive or a state, not a value
_NOT_A_VALUE_RE = re.compile(r"^(?:[а-яё]{2,}но|[а-яё]{3,}(?:ан|ян|ен|ён|ыт|ут|ят)[аоы]?)$", re.I)
_HEDGES = frozenset("примерно приблизительно ровно почти около всего лишь только уже ещё еще более менее свыше порядка целых".split())
# «было 47, стало 29 минут», «12 дней, после внедрения 4», «до внедрения 12 дней, после — 4»: one measure, its unit written once
_LATER_BETWEEN_RE = re.compile(
    rf"\s*[,;]?\s*(?:а\s+|но\s+)?(?:{_LATER_MARK})\s*[:—–-]?\s*(?:(?:{'|'.join(sorted(_HEDGES))})\s+)?",
    re.I,
)
_BARE_END_RE = re.compile(r"\s*(?:[,.;:)!?…]|$)")
# «NPS 64 (было 41)»: the figure before the parenthesis is the later value
_PAREN_EARLIER_RE = re.compile(rf"\s*\(\s*(?:{_EARLIER_MARK})\s*[:—–-]?\s*", re.I)
# «Срок обработки, дней: 12 → 4»: a label naming the unit of the figures after it
_LABEL_UNIT_RE = re.compile(r"^(?P<label>[^:,]{2,80}),\s*(?P<unit>[^:,]{1,24}?)\s*:\s")
_PER_RE = re.compile(r"(?:\s*/\s*[а-яё]+|\s+(?:в|на)\s+[а-яё]+)$", re.I)  # «мин/день», «часов в неделю»
_EARLIER_BEFORE_RE = re.compile(rf"(?<![\wё])(?:{_EARLIER_MARK})\s*[:—–-]?\s*$", re.I)
# «больше половины», «более чем на треть», «почти три четверти», «меньше четверти»: a share on one side of a fraction
_HEDGE_BEFORE_RE = re.compile(
    r"(?<![\wё])(?P<h>больше|более|свыше|меньше|менее|почти|около|примерно|приблизительно)(?:\s+чем)?(?:\s+(?:на|в|у|за))?\s+$",
    re.I,
)
_HEDGE_SIDE = {"больше": "gt", "более": "gt", "свыше": "gt", "меньше": "lt", "менее": "lt", "почти": "almost", "около": "about", "примерно": "about", "приблизительно": "about"}
_HEDGE_SPAN = 15.0  # «больше половины» is 51–65%, not 95%: a share a person would still call so
# clauses for the change check: a parenthesis stays with its clause («Повышение удовлетворенности (NPS 64)»)
# (a parenthesis ends its clause: «(NPS 64) время …»); «и», «а», «но» part two clauses when one of them states a figure
# («Время сократилось до 29 минут и NPS 64», «Бюджет 14,5 млн ₽ и сокращение времени на чаты»)
_CHANGE_CLAUSE_SEP_RE = re.compile(r"\s*[;,]\s+|\s+[—–-]\s+|:\s+|\)\s+(?=\S)|(?<=[.!?])\s+")
_CONJ_RE = re.compile(r"\s+(?:и|а|но|and)\s+", re.I)
# the lenient reading of a before/after the brief writes in its own way («Было: … Стало: …», «До миграции: … После
# миграции: …», «3 инженера вместо 7», «NPS в первом квартале — 41, во втором — 64», «2,4% против 4,8% до пилота»):
# the figures of such sentences may be the ends of a change a plan states. The exact pairing above misses many of these.
_MONTH_STEMS = r"январ|феврал|март|апрел|ма[йея]|июн|июл|август|сентябр|октябр|ноябр|декабр"
_VERSUS_RE = re.compile(r"(?<![\wё])(?:вместо|против|по\s+сравнению|instead|versus|vs\.?)(?![\wё])", re.I)
_PERIOD_RE = re.compile(
    rf"(?<![\wё])(?:(?:{_MONTH_STEMS})\w*|квартал\w*|полугоди\w*|(?:19|20)\d\d\s*(?:год|г\.)\w*|в\s+начале|в\s+конце|сначала|затем)(?![\wё])",
    re.I,
)
_PART_END_RE = re.compile(r"[,;.](?!\d)")
_SENTENCE_SEP_RE = re.compile(r"(?<=[.!?])\s+")
# a letter and a digit glued together: a name («Qwen3.8-27B», «Q3», «1С», «GPT-4», «3-х»), checked as a whole
_NAME_TOKEN_RE = re.compile(r"(?<![\w.\-])(?=[\w.\-]*\d)(?=[\w.\-]*[^\W\d_])\w+(?:[.\-]\w+)*")
_GLUED_UNIT_RE = re.compile(rf"^\d+(?:[.,]\d+)?{_GLUED}$", re.I)


@dataclass
class Fig:
    """A figure as written: its value, decimals, scale word (тыс./млн), unit class and where it stands. `date`: (day,
    month, year or None) of a date; `approx`: the tolerance of a figure in words («треть» ≈ 33%); `hedge`: the side of
    it a hedged share is on («больше половины»: gt, «меньше четверти»: lt, «почти»: almost, «около»: about);
    `inherited`: the unit is the other end's («с 47 до 29 минут», «было 47, стало 29 минут», «с 47 минут до 29»);
    `word_unit`: the unit is part of the word («вдвое», «половина»); `plain`: written as digits alone, no separator
    («2026», not «2 000»)."""

    value: float
    dec: int
    scale: float
    unit: Optional[str]
    start: int
    end: int  # end of the number
    uend: int  # end of the unit (== end without one)
    ustart: int  # start of the unit (== end without one)
    date: Optional[tuple[int, int, Optional[int]]] = None
    approx: float = 0.0
    inherited: bool = False
    word_unit: bool = False
    plain: bool = False
    hedge: Optional[str] = None

    @property
    def mag(self) -> float:
        return self.value * self.scale


def _unit_class(m: re.Match) -> tuple[Optional[str], float]:
    """(unit class, scale) of a unit match."""
    g = m.groupdict()
    if g.get("pp"):
        return "pp", 1.0
    if g.get("pct"):
        return "pct", 1.0
    scale = 1.0
    if g.get("scale"):
        w = g["scale"].lower().rstrip(".")
        scale = next(v for k, v in _SCALES.items() if w.startswith(k))
        cur = g.get("cur2")
        return (_currency(cur) if cur else None), scale
    if g.get("cur"):
        return _currency(g["cur"]), 1.0
    if g.get("time"):
        w = g["time"].lower().rstrip(".")
        return next(c for k, c in _TIME_UNITS if w.startswith(k)), 1.0
    if g.get("times"):
        return "times", 1.0
    if g.get("pts"):
        return "pts", 1.0
    return None, 1.0  # a count: «шт», «человек»


def _currency(word: str) -> str:
    w = word.lower()
    return "usd" if w.startswith(("$", "долл")) else "eur" if w.startswith(("€", "евро")) else "rub"


def name_tokens(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _NAME_TOKEN_RE.finditer(text):
        tok = m.group(0).rstrip(".-")
        if _GLUED_UNIT_RE.match(tok):
            continue
        out.append((m.start(), m.start() + len(tok), tok))
    return out


def _is_year(f: Fig) -> bool:
    """«2026», «в 2025 году», «2024 г.» — not «2 000» or «1 950 клиентов»: four digits written without a separator, or
    with «год» / «г.» after them."""
    if f.date is not None or f.approx or f.dec or f.scale != 1.0 or not 1900 <= f.value <= 2100:
        return False
    return f.unit == "y" or (f.unit is None and f.plain)


def _dates(text: str) -> list[Fig]:
    out = []
    for m in _DATE_RE.finditer(text):
        if m.group("d1"):
            d, mo, y = int(m.group("d1")), int(m.group("m1")), int(m.group("y1"))
            y = y + 2000 if y < 100 else y
        else:
            d, mo = int(m.group("d2")), _MONTHS.index(m.group("m2").lower()) + 1
            y = int(m.group("y2")) if m.group("y2") else None
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            continue
        value = float((y or 0) * 10000 + mo * 100 + d)
        end = m.start() + len(m.group("d1") or m.group("d2"))
        out.append(Fig(value, 0, 1.0, "date", m.start(), end, m.end(), end, date=(d, mo, y)))
    return out


# ------------------------------------------------------------------ figures in words

_CARDINALS: dict[str, tuple[int, int]] = {}  # a word form → (value, rank: 0 units and teens, 1 tens, 2 hundreds)


def _add(forms: str, value: int, rank: int) -> None:
    for w in forms.split():
        _CARDINALS[w] = (value, rank)


_add("один одна одно одного одной одному одним одном одну", 1, 0)
_add("два две двух двум двумя", 2, 0)
_add("три трёх трех трём трем тремя", 3, 0)
_add("четыре четырёх четырех четырём четырем четырьмя", 4, 0)
_add("пять пяти пятью", 5, 0)
_add("шесть шести шестью", 6, 0)
_add("семь семи", 7, 0)
_add("восемь восьми восемью восьмью", 8, 0)
_add("девять девяти девятью", 9, 0)
_add("десять десяти десятью", 10, 0)
for _stem, _v in (("одиннадцат", 11), ("двенадцат", 12), ("тринадцат", 13), ("четырнадцат", 14), ("пятнадцат", 15), ("шестнадцат", 16), ("семнадцат", 17), ("восемнадцат", 18), ("девятнадцат", 19), ("двадцат", 20), ("тридцат", 30)):
    _add(f"{_stem}ь {_stem}и {_stem}ью", _v, 1 if _v >= 20 else 0)
_add("сорок сорока", 40, 1)
_add("пятьдесят пятидесяти пятьюдесятью", 50, 1)
_add("шестьдесят шестидесяти шестьюдесятью", 60, 1)
_add("семьдесят семидесяти семьюдесятью", 70, 1)
_add("восемьдесят восьмидесяти восемьюдесятью", 80, 1)
_add("девяносто девяноста", 90, 1)
_add("сто ста", 100, 2)
_add("двести двухсот", 200, 2)
_add("триста трёхсот трехсот", 300, 2)
_add("четыреста четырёхсот четырехсот", 400, 2)
_add("пятьсот пятисот", 500, 2)
_add("шестьсот шестисот", 600, 2)
_add("семьсот семисот", 700, 2)
_add("восемьсот восьмисот", 800, 2)
_add("девятьсот девятисот", 900, 2)
_MULTIPLES = {"вдвое": 2, "втрое": 3, "вчетверо": 4, "впятеро": 5, "вшестеро": 6, "всемеро": 7, "ввосьмеро": 8, "вдевятеро": 9, "вдесятеро": 10}
_FRACTIONS = {"наполовину": 50.0, "половина": 50.0, "половину": 50.0, "половины": 50.0, "половине": 50.0, "половиной": 50.0, "треть": 100 / 3, "трети": 100 / 3, "третью": 100 / 3, "четверть": 25.0, "четверти": 25.0, "четвертью": 25.0}
_HALF_OF_TIME_RE = re.compile(r"(?:перв|втор)\w*\s+$", re.I)  # «во второй половине года»: a period, not a share
# «каждый третий», «в каждом пятом случае» (a share), not «каждые пять минут» (a period)
_EVERY_NTH_RE = re.compile(
    r"(?<![\wё])кажд\w*\s+(втор|трет|четв[её]рт|пят|шест|седьм|восьм|девят|десят|двадцат|сот)"
    r"(?:ий|ья|ье|ьего|ьей|ьему|ью|ьим|ьем|ый|ой|ая|ое|ого|ому|ом|ую|ым)(?![\wё])",
    re.I,
)
_NTH = {"втор": 2, "трет": 3, "четвёрт": 4, "четверт": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8, "девят": 9, "десят": 10, "двадцат": 20, "сот": 100}
_WORD_RE_ANY = re.compile(r"[а-яё]+", re.I)


def _word_fig(start: int, end: int, value: float, dec: int, unit: str, approx: float = 0.0, text: str = "") -> Fig:
    f = Fig(value, dec, 1.0, unit, start, end, end, end, approx=approx, word_unit=True)
    if approx and text:
        m = _HEDGE_BEFORE_RE.search(text, max(0, start - 40), start)
        if m:
            f.hedge = _HEDGE_SIDE[m.group("h").lower()]
    return f


def _word_figures(text: str) -> list[Fig]:
    """Figures written in words: «двенадцать тысяч», «двадцать пять процентов», «в два раза», «вдвое», «полтора
    миллиона», «половина», «треть», «две трети», «каждый третий». A small count of things or of time («три этапа», «пять
    шагов», «за пять месяцев» of a table's five months, «два раза в день») is read off what the brief lists and is not
    a figure."""
    out: list[Fig] = []
    toks = list(_WORD_RE_ANY.finditer(text))
    taken = 0
    for m in _EVERY_NTH_RE.finditer(text):
        n = next(v for k, v in _NTH.items() if m.group(1).lower().startswith(k))
        out.append(_word_fig(m.start(), m.end(), 100 / n, 1, "pct", 1.0, text))
    every = [(f.start, f.uend) for f in out]
    i = 0
    while i < len(toks):
        m = toks[i]
        w = m.group(0).lower()
        if m.start() < taken or any(a <= m.start() < b for a, b in every) or (m.start() and (text[m.start() - 1].isalnum() or text[m.start() - 1] in "-‑")):
            i += 1
            continue
        nxt = toks[i + 1].group(0).lower() if i + 1 < len(toks) and text[m.end() : toks[i + 1].start()].strip(_SPACES) == "" else ""
        if w in ("две", "двух") and nxt in ("трети", "третей"):
            out.append(_word_fig(m.start(), toks[i + 1].end(), 200 / 3, 1, "pct", 1.0, text))
            i += 2
            continue
        if w in ("три", "трёх", "трех") and nxt in ("четверти", "четвертей"):
            out.append(_word_fig(m.start(), toks[i + 1].end(), 75.0, 0, "pct", 1.0, text))
            i += 2
            continue
        if w in _MULTIPLES:
            out.append(_word_fig(m.start(), m.end(), float(_MULTIPLES[w]), 0, "times"))
            i += 1
            continue
        if w in _FRACTIONS and not _HALF_OF_TIME_RE.search(text[: m.start()]):
            out.append(_word_fig(m.start(), m.end(), _FRACTIONS[w], 1, "pct", 1.0, text))
            i += 1
            continue
        if w in ("полтора", "полторы", "полутора") or w in _CARDINALS:
            value, rank = (1.5, 0) if w.startswith("пол") else _CARDINALS[w]
            dec = 1 if w.startswith("пол") else 0
            end, j = m.end(), i + 1
            while not dec and j < len(toks) and text[end : toks[j].start()].strip(_SPACES) == "" and toks[j].group(0).lower() in _CARDINALS:
                v2, r2 = _CARDINALS[toks[j].group(0).lower()]
                if r2 >= rank or (rank == 1 and v2 >= 10):
                    break
                value, rank, end, j = value + v2, r2, toks[j].end(), j + 1
            um = _UNIT_AFTER_RE.match(text, end)
            unit, scale = _unit_class(um) if um else (None, 1.0)
            if unit == "times" and not re.search(r"(?<![\wё])в\s+$", text[: m.start()], re.I):
                um, unit = None, None  # «один раз в неделю», «два раза в день»: how often, not how many times more
            # a small count of days or steps («за пять месяцев» of a table's five months) is read off the brief, a
            # share, a multiple, a sum or a count in thousands is a figure
            if (value >= 11 or scale > 1.0 or unit in _STRIPPABLE or unit == "pts") and not _ORDINAL_BEFORE_RE.search(text[: m.start()]):
                uend = um.end() if um else end
                out.append(Fig(float(value), dec, scale, unit, m.start(), end, uend, end + (1 if um and um.group(0)[:1] in _SPACES else 0)))
                taken = uend
            i = j
            continue
        i += 1
    return out


def figures(text: str) -> list[Fig]:
    """The figures of a text, each with the unit written right after it («47 минут», «14,5 млн ₽», «64%», «15млн»,
    «13K»), dates and figures in words. Digits of a name («Qwen3.8», «Q3») are not figures. A unit written once is the
    unit of both values of a change or a range: «с 47 до 29 минут», «8–25 секунд», «с 47 минут до 29», «12 дней → 4»,
    «было 47, стало 29 минут», «до внедрения 12 дней, после — 4», «465 000 / 508 000 рублей», and of the figures
    after a label that names it («Срок, дней: 12 → 4»)."""
    names = [(a, b) for a, b, _ in name_tokens(text)]
    out: list[Fig] = [f for f in _dates(text) if not any(a < f.uend and f.start < b for a, b in names)]
    spans = [(f.start, f.uend) for f in out]
    for m in _NUM_RE.finditer(text):
        if any(a <= m.start() < b for a, b in names + spans):
            continue
        raw = m.group("num")
        digits = re.sub(_SP, "", raw).replace(",", ".")
        try:
            value = float(digits)
        except ValueError:
            continue
        dec = len(digits.split(".", 1)[1]) if "." in digits else 0
        unit, scale, ustart, uend = None, 1.0, m.end(), m.end()
        km = _KILO_RE.match(text, m.end())
        um = None if km else _UNIT_AFTER_RE.match(text, m.end())
        if km:
            unit, scale, uend = (_currency(km.group("cur")) if km.group("cur") else None), 1e3, km.end()
        elif um:
            unit, scale = _unit_class(um)
            ustart, uend = m.end() + (1 if um.group(0)[:1] in _SPACES else 0), um.end()
        plain = bool(re.fullmatch(r"\d{4}", raw)) and not km and um is None
        out.append(Fig(value, dec, scale, unit, m.start(), m.end(), uend, ustart, plain=plain))
    spans = [(f.start, f.uend) for f in out]
    out += [f for f in _word_figures(text) if not any(a <= f.start < b for a, b in spans + names)]
    out.sort(key=lambda f: f.start)
    for a, b in zip(out, out[1:]):
        if a.date or b.date or a.approx or b.approx or _ORDINAL_BEFORE_RE.search(text[: a.start]):
            continue
        a_bare = a.unit is None and a.scale == 1.0 and a.uend == a.end
        b_bare = b.unit is None and b.scale == 1.0 and b.uend == b.end
        if a_bare == b_bare or (a.unit is None and a.scale == 1.0 and b.unit is None and b.scale == 1.0):
            continue
        between = text[a.uend : b.start]
        written = bool(_ARROW_BETWEEN_RE.fullmatch(between) or (_TO_BETWEEN_RE.fullmatch(between) and _FROM_RE.search(text[: a.start])))
        if a_bare and (written or _RANGE_BETWEEN_RE.fullmatch(between) or _SLASH_BETWEEN_RE.fullmatch(between)):
            a.unit, a.scale, a.inherited = b.unit, b.scale, True  # «с 47 до 29 минут», «8–25 секунд», «465 000 / 508 000 рублей»
        elif b_bare and written:
            b.unit, b.scale, b.inherited = a.unit, a.scale, True  # «с 47 минут до 29», «12 дней → 4»
        elif _LATER_BETWEEN_RE.fullmatch(between) and (
            (_BARE_END_RE.match(text, a.uend) and _EARLIER_BEFORE_RE.search(text[: a.start])) if a_bare else _BARE_END_RE.match(text, b.uend)
        ):
            # «было 47, стало 29 минут», «12 дней, после внедрения 4», «до внедрения 12 дней, после — 4»: the value
            # without a unit stands alone, the unit is its pair's
            x, y = (a, b) if a_bare else (b, a)
            x.unit, x.scale, x.inherited = y.unit, y.scale, True
    for f in out:
        # «более чем в 2 раза», «почти 2,1», «примерно на 112%»: the side of the true value the figure says it is on
        if f.hedge is None and not f.approx and f.date is None:
            hm = _HEDGE_BEFORE_RE.search(text, max(0, f.start - 40), f.start)
            side = _HEDGE_SIDE[hm.group("h").lower()] if hm else None
            # «больше на 450» is a difference, «более чем на 30%» and «более 900 000» are hedges
            if side in ("gt", "lt") and re.search(r"(?:на|в|у|за)\s+$", hm.group(0), re.I) and not re.search(r"\sчем\s", hm.group(0), re.I):
                side = None
            if side:
                f.hedge = side
    lm = _LABEL_UNIT_RE.match(text)
    um = _UNIT_IN_RE.fullmatch(_PER_RE.sub("", lm.group("unit")).strip()) if lm else None
    if lm and um:
        unit, scale = _unit_class(um)
        stop = next((m.start() for m in _SENTENCE_SEP_RE.finditer(text, lm.end())), len(text))
        for f in out:
            if lm.end() <= f.start < stop and f.unit is None and f.scale == 1.0 and not (f.date or f.approx):
                f.unit, f.scale, f.inherited = unit, scale, True
    return out


def _unit_in(cell: str) -> Optional[tuple[Optional[str], float]]:
    """The unit a table's row or header names after its comma or in parentheses («Время на чтение чатов, мин/день»,
    «Статья, млн ₽ в год», «Срок (дней)», «Активные пользователи, чел.» — a count); None when it names none («Месяц»
    over «Май | Июнь»)."""
    par = re.search(r"\(([^()]*)\)", cell)
    for part in (cell.split(",", 1)[1] if "," in cell else "", par.group(1) if par else ""):
        m = _UNIT_IN_RE.search(part) if part else None
        if m:
            return _unit_class(m)
    return None


@dataclass(eq=False)
class _Placed:
    """A figure of the brief and where it stands: its sentence or table row (`group`), its place in it, whether it is
    a table cell, whether it is a step's number («Неделя 1») rather than a measure."""

    fig: Fig
    group: int
    pos: int
    cell: bool
    ordinal: bool
    changed: bool = False  # the brief states a change of it: a change word, было/стало, both ends, a table's series
    delta: bool = False  # it is the size of a change: «выросла на 34%», «экономия 2,1 часа»
    saving: bool = False  # it is a saving: «экономия 2,1 часа» (a level of savings too: «экономия выросла до 2,1 часа»)
    earlier: bool = False  # it is written as the earlier value: «было 41», «с 47», «в 2024 году»
    seq: int = -1  # its place among the figures of the brief's text: a figure's neighbours are seq ± 1
    context: bool = False  # its sentence speaks of a change or a comparison (see _CONTEXT_RE): a lenient «changed»
    ctx: Optional[frozenset] = None  # the subject stems of its label («зарплаты — в 270 000 рублей»: {зарплат}); None: none
    base: bool = False  # its label is the base of a share («35% выручки»), not its subject
    lead: frozenset = frozenset()  # the stems of the lead its list or sentence has («Прогноз выручки: …»)
    future: bool = False  # it is a plan, a target or a forecast («составит», «Цель», «к шестому месяцу»)


@dataclass
class _BriefFigures:
    placed: list[_Placed]
    pairs: set[frozenset[int]] = field(default_factory=set)  # ids of the two values of a change the brief states
    ranges: set[frozenset[int]] = field(default_factory=set)  # «месяц 1–2», «8–25 секунд»: not a change
    shares: list[float] = field(default_factory=list)  # «в 6 случаях из 30»: 20%
    stated: list[tuple[set[str], "_Stems"]] = field(default_factory=list)  # the changes it states: directions, subjects
    texts: dict[int, str] = field(default_factory=dict)  # sentence group → its text


def _clauses(text: str, pos: int = 0, end: Optional[int] = None) -> list[tuple[int, int]]:
    """(start, end) of the clauses of text[pos:end] for the change check."""
    end = len(text) if end is None else end
    out = []
    for a, b in _seps(text, _CHANGE_CLAUSE_SEP_RE, pos, end):
        out.append((pos, a))
        pos = b
    out.append((pos, end))
    return out


def _seps(text: str, rx: re.Pattern, pos: int = 0, end: Optional[int] = None) -> list[tuple[int, int]]:
    """The clause separators of text[pos:end]: `rx`'s, and «и», «а», «но» between two parts (up to «,», «;», «.»)
    one of which states a figure, in digits or in words."""
    end = len(text) if end is None else end
    out = [m.span() for m in rx.finditer(text, pos, end) if m.end() > m.start()]
    for m in _CONJ_RE.finditer(text, pos, end):
        if any(a < m.end() and m.start() < b for a, b in out):
            continue
        stops = [x.start() for x in _PART_END_RE.finditer(text, pos, end)]
        left = text[max([x + 1 for x in stops if x < m.start()] + [pos]) : m.start()]
        right = text[m.end() : min([x for x in stops if x >= m.end()] + [end])]
        if any(re.search(r"\d", x) or _word_figures(x) for x in (left, right)):
            out.append(m.span())
    return sorted(out)


def _sentences(text: str) -> list[tuple[int, int]]:
    out, pos = [], 0
    for m in _SENTENCE_SEP_RE.finditer(text):
        out.append((pos, m.start()))
        pos = m.end()
    out.append((pos, len(text)))
    return out


def _change_governed(text: str, figs: list[Fig]) -> list[tuple[list[tuple[int, int]], list[Fig], bool]]:
    """The changes a text claims: (spans of the change words, the figures they speak of, whether the words are in a
    clause of their own). A change word speaks of the figures of its clause; one in a clause without figures speaks
    for its sentence — of the figures of its clauses that have no change word of their own («Удовлетворённость
    выросла: NPS 64», «NPS 64 — сотрудники довольны улучшением»)."""
    out = []
    for sa, sb in _sentences(text):
        orphan: list[tuple[int, int]] = []
        free: list[Fig] = []
        for a, b in _clauses(text, sa, sb):
            words = [m.span() for m in _CHANGE_RE.finditer(text, a, b)]
            mine = [f for f in figs if a <= f.start < b]
            if words and mine:
                out.append((words, mine, False))
            elif words:
                orphan += words
            else:
                free += mine
        if orphan and free:
            out.append((orphan, free, True))
    return out


_UP_RE = re.compile(r"вырос|выраст|рост|прирост|раст[её]т|растут|повы[сш]|увелич|grew|grow|increas|rise|rose", re.I)
_DOWN_RE = re.compile(r"сниз|сниж|сократ|сокращ|уменьш|упал|паден|decreas|declin|drop|fell|fall|reduc", re.I)


def _direction(word: str) -> str:
    """«up» (вырос, рост), «down» (сократилось, снижение), «any» (улучшение, экономия)."""
    return "up" if _UP_RE.match(word) else "down" if _DOWN_RE.match(word) else "any"


def _change_subject(text: str, a: int, b: int) -> tuple[set[str], list[str]]:
    """The directions of the change words of text[a:b] and the stems of its other content words (what changed)."""
    words = list(_CHANGE_RE.finditer(text, a, b))
    rest = text[a:b]
    for m in reversed(words):
        rest = rest[: m.start() - a] + " " + rest[m.end() - a :]
    rest = _LATER_MARK_RE.sub(" ", _EARLIER_MARK_RE.sub(" ", rest))
    return {_direction(m.group(0)) for m in words}, content_stems(rest, neutral=True)


def _prep(text: str, f: Fig) -> Optional[str]:
    """«by» for «на 18 минут» (the size of a change; not «на 12 400 сотрудниках», a place), «to» for «до 29 минут»."""
    m = _PREP_RE.search(text, max(0, f.start - 8), f.start)
    if not m:
        return None
    if m.group(1).lower() in ("до", "to"):
        return "to"
    nw = _NEXT_WORD_RE.match(text, f.uend)
    words = [text[f.ustart : f.uend]] + ([nw.group(1)] if nw else [])
    if any(re.search(r"(?:ах|ях)$", w, re.I) for w in words if w):
        return None
    return "by"


def _change_context(text: str, f: Fig) -> bool:
    """The text speaks of `f` as a change or a difference: «на 30 рублей», «в 2 раза», «+15», «рост 112%», «на 238 500
    больше», a change word in its clause."""
    if f.unit == "times" or _prep(text, f) == "by" or _COMPARE_AFTER_RE.match(text, f.uend):
        return True
    if re.search(r"[+−]\s*$", text[max(0, f.start - 2) : f.start]):
        return True
    for a, b in _clauses(text):
        if a <= f.start < b:
            return bool(_CHANGE_RE.search(text, a, b) or re.search(r"(?<![\wё])(?:разниц|прирост|больше|меньше|выше|ниже|дополнительн|эконом|сэконом|быстрее|дешевле|дороже)\w*", text[a:b], re.I))
    return False


def _pair_written(text: str, a: Fig, b: Fig) -> bool:
    """«с 47 до 29 минут», «от 1 200 до 12 400», «47 → 29»: a change with both ends."""
    between = text[a.uend : b.start]
    return bool(_ARROW_BETWEEN_RE.fullmatch(between) or (_TO_BETWEEN_RE.fullmatch(between) and _FROM_RE.search(text[: a.start])))


def _governed(text: str, pos: int, cands: list[Fig]) -> Optional[Fig]:
    """The figure a before / after marker ending at `pos` speaks of: the next one, a few words on, with no other
    marker between — none after a passive or a state («было задействовано 12 400», «стало понятно, что … 29»)."""
    f = next((x for x in cands if x.start >= pos), None)
    if f is None:
        return None
    between = text[pos : f.start]
    words = re.findall(r"[^\W\d_]+", between)
    if len(words) > 6 or ";" in between or "(" in between or _EARLIER_MARK_RE.search(between) or _LATER_MARK_RE.search(between):
        return None
    if words and words[0].lower() not in _HEDGES and _NOT_A_VALUE_RE.match(words[0]):
        return None
    return f


def _sides(sn: str, cands: list[Fig]) -> dict[int, tuple[str, int, int]]:
    """id(figure) → (earlier | later, start and end of what marks it) of the figures of a sentence written as an
    earlier or a later value: «было 47», «стало 29», «до внедрения 12 дней», «после — 4», «с 47 до 29», «47 → 29»,
    «NPS 64 (было 41)»."""
    side: dict[int, tuple[str, int, int]] = {}
    for rx, s in ((_EARLIER_MARK_RE, "earlier"), (_LATER_MARK_RE, "later")):
        for m in rx.finditer(sn):
            f = _governed(sn, m.end(), cands)
            if f is not None:
                side.setdefault(id(f), (s, m.start(), m.end()))
    for a, b in zip(cands, cands[1:]):
        if _pair_written(sn, a, b):
            side.setdefault(id(a), ("earlier", a.start, a.start))
            side.setdefault(id(b), ("later", b.start, b.start))
        elif side.get(id(b), ("",))[0] == "earlier" and id(a) not in side and _PAREN_EARLIER_RE.fullmatch(sn[a.uend : b.start]):
            side[id(a)] = ("later", a.uend, a.uend)
    return side


def _marks_directly(sn: str, side: tuple[str, int, int], f: Fig) -> bool:
    """The marker stands right before the figure: «было 1 500», «стало: около 1 950», «после — 4», «(было 41)»."""
    words = re.findall(r"[^\W\d_]+", sn[side[2] : f.start]) if side[2] < f.start else []
    return all(w.lower() in _HEDGES for w in words)


def _whens(sn: str, figs: list[Fig], cands: list[Fig]) -> dict[int, int]:
    """id(figure) → the year it is of: the year of its clause, else the last one before it in the sentence («В 2024
    году выручка 120 млн ₽, в 2025 году — 150 млн ₽»)."""
    years = [(f.start, int(f.value)) for f in figs if _is_year(f)] + [(f.start, f.date[2]) for f in figs if f.date and f.date[2]]
    if not years:
        return {}
    out = {}
    for f in cands:
        clause = next(((a, b) for a, b in _clauses(sn) if a <= f.start < b), (0, len(sn)))
        mine = [y for s, y in years if clause[0] <= s < clause[1]]
        before = [y for s, y in years if s < f.start]
        if len(set(mine)) == 1:
            out[id(f)] = mine[0]
        elif not mine and before:
            out[id(f)] = before[-1]
    return out


# words that name no subject of a figure (a measure's frame, a period, a change, a plan): «доля», «месяц», «составит»
_GENERIC_STEMS = (
    "дол", "процент", "рубл", "руб", "тыс", "млн", "сумм", "итог", "всег", "общ", "состав", "стои", "обход", "показател",
    "значен", "уров", "величин", "текущ", "нынешн", "сейчас", "цел", "план", "прогноз", "рост", "раст", "выраст", "вырос",
    "увелич", "сниж", "сниз", "сократ", "сокращ", "достиг", "будет", "стан", "ожида", "получ", "потреб", "месяц", "месяч",
    "ежемесяч", "ежеднев", "недел", "год", "дней", "дня", "ден", "раз", "перв", "втор", "трет", "четв", "пят", "шест",
    "седьм", "восьм", "девят", "десят", "примерн", "около", "более", "менее", "почт", "нужн", "покаж", "диаграм", "график",
    "кругов", "столбч", "линейн", "структур", "распредел", "сравнен", "добав", "дополнит", "сделай", "таблиц", "слайд",
    "вывод", "финальн", "главн", "основн", "ключев", "включ", "учит", "част", "прочи", "друг", "из", "эт",
    "январ", "феврал", "март", "апрел", "мае", "май", "мая", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр",
    "квартал", "полугод", "начал", "конц", "пилот",
)
_FUTURE_RE = re.compile(
    r"(?<![\wё])(?:цел[ьиеюя]\w*|план\w*|прогноз\w*|планир\w*|будет|будут|составит|составят|вырастет|вырастут|увеличится|"
    r"увеличатся|увеличит|снизится|снизятся|снизит|сократится|сократятся|сократит|достигнет|достигнут|дадут|даст|потребуется|"
    r"потребуют|принес[её]т|окупится|ожида\w*|предполага\w*|пойд[её]т|останется|к\s+\S+\s+месяцу|к\s+концу|через\s+\S+\s+месяц\w*)",
    re.I,
)
_NOW_BEFORE_RE = re.compile(r"(?<![\wё])(?:нынешн\w*|текущ\w*|сейчас|сегодня|было|исходн\w*|против|с|со|от)\s+(?:\S+\s+)?$", re.I)
_PAIR_LEAD_RE = re.compile(r"(?:сейчас|было|до|текущ\w*|факт)\s*/\s*(?:цель|стало|после|прогноз|план)", re.I)
_HEADING_LINE_RE = re.compile(r"^\s*(?:слайд|slide)\s*\d{1,2}\b", re.I)
_DASH_LINE_RE = re.compile(r"^\s*[—–\-•*·]\s+")
_CTX_STOP_RE = re.compile(r"[,;!?]|\.(?!\d)|\s(?:а|но|и|—|–)\s")
_PAIR_BETWEEN_RE = re.compile(r"\s*(?:[^\s\d]{1,12}\s*)?(?:до|по|из|→|->|/|—|–|-)\s*", re.I)


_MARKER_WORDS = frozenset(
    """было был была были стало стал стала стали станет станут теперь после раньше ранее прежде против вместо итого всего
    больше меньше выше ниже число числа количество количества""".split()
)


def _subject(text: str) -> frozenset:
    """The stems of a text that can name a figure's subject: content words, no measure, period or before/after words."""
    words = " ".join(w for w in _WORD_RE.findall(text or "") if w.lower() not in _MARKER_WORDS)
    return frozenset(s for s in content_stems(words, neutral=True) if not s.startswith(_GENERIC_STEMS))


class _BaseLabel(frozenset):
    """The words after a share that name its base, not its subject («35% выручки»): compared leniently."""


def _figure_labels(sn: str, figs: list[Fig], line: bool = False) -> list[frozenset]:
    """For each figure of a sentence (or a list line), the subject its label gives: the words since the figure before
    it (or since a colon — «структуры выручки: кофе — 60%» labels 60% «кофе»), and after it up to the next figure or
    the clause's end («… 35% выручки»). The words before a colon count when the label after it has none."""
    out: list[frozenset] = []
    for k, f in enumerate(figs):
        prev_end = figs[k - 1].uend if k else 0
        # its own clause: after the last comma since the figure before it («1 950 пользователей, 3,2 секунды на …»),
        # after a colon when the words after it name something («структуры выручки: кофе — 60%»)
        seg = prev_end
        if k:  # the first figure's label may hold a comma of its own («продукты, упаковка и списания — 315 000»)
            for m in re.finditer(r"[,;]\s", sn[prev_end : f.start]):
                seg = prev_end + m.end()
        colon = sn.rfind(":", seg, f.start)
        before = sn[(colon + 1) if colon >= 0 else seg : f.start]
        if not _subject(before):
            before = sn[seg : f.start]
        if k and re.search(r"[×*=+÷·]|\s[xх/]\s", sn[figs[k - 1].end : f.start]):
            before = ""  # a formula («100 покупок × 300 рублей»): the words before an operand are the previous one's unit
        nxt = figs[k + 1].start if k + 1 < len(figs) else len(sn)
        m = _CTX_STOP_RE.search(sn, f.uend, nxt)
        after = sn[f.uend : m.start() if m else nxt]
        paired = bool(k) and bool(_PAIR_BETWEEN_RE.fullmatch(sn[figs[k - 1].end : f.start]))
        # a share's words after it are its base («35% выручки», «13,3% выручки»), not its subject: they count only
        # when nothing before names one («65% покупок приходится на утренние часы»)
        if f.unit in ("pct", "pp"):
            label = _subject(before) or (out[k - 1] if paired else frozenset())
            if not label and _subject(after):
                label = _BaseLabel(_subject(after))
            elif line and label:
                label = label | _subject(after)  # a slide's line: «Первый набор: 71% студентов дошли до конца»
        else:
            label = _subject(f"{before} {after}")
        if paired:
            label = label | out[k - 1]  # «с 13,3% до 22,4%», «100 / 115», «8–25 секунд»: one label for both ends
        if not label:
            # «доля покупателей, вернувшихся в течение 30 дней, — 25%»: the label stands before another figure — the
            # words no figure before it has taken («Бюджет 14,5 млн ₽ и 29 минут»: «бюджет» is 14,5's)
            start = sn.rfind(":", 0, f.start)
            taken = frozenset().union(*out) if out else frozenset()
            label = _subject(sn[start + 1 if start >= 0 else 0 : f.start]) - taken
        out.append(label)
    return out


def _brief_figures(text: str) -> _BriefFigures:
    """Every figure of the brief; a table cell without a unit takes the unit its row or its header names. What the
    brief says of each: whether it states a change of it, whether it is a change's size, whether it is the earlier
    value of two; and which of its figures are the two values of a change it states: an earlier and a later value of
    one measure written close together («было 47 минут, стало 29 минут», «NPS 64 (было 41)», «до внедрения 12 дней,
    после — 4», «в 2024 году 120 млн ₽, в 2025 — 150 млн ₽») — not «было задействовано 12 400», «стало понятно»,
    «теперь» or «после внедрения» with nothing earlier. Two figures without a unit are one measure only side by side."""
    res = _BriefFigures([])
    out = res.placed
    header_unit: Optional[tuple[Optional[str], float]] = None
    col_units: list[Optional[tuple[Optional[str], float]]] = []
    in_table = False
    header_cells: list[str] = []
    heading = ""  # the heading of the block («Слайд 4. Вложения и прогноз роста»)
    lead_line = ""  # the lead of a dash list («Ежемесячные расходы:», «Сделай сравнительную таблицу «Сейчас / Цель»:»)
    group = 0
    sides: dict[int, tuple[str, int, int]] = {}
    whens: dict[int, int] = {}
    texts: dict[int, str] = {}  # sentence group → its text
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells):
                continue
            group += 1
            if not in_table:
                in_table = True
                header_unit = _unit_in(cells[0]) if cells else None
                col_units = [_unit_in(c) for c in cells]
                header_cells = cells
                for j, c in enumerate(cells):
                    out.extend(_Placed(f, group, j, True, _ordinal(c, f)) for f in figures(c))
                continue
            row_unit = (_unit_in(cells[0]) if cells else None) or header_unit
            row: list[_Placed] = []
            for j, c in enumerate(cells):
                for f in figures(c):
                    u = row_unit or (col_units[j] if j < len(col_units) else None)
                    if f.unit is None and f.scale == 1.0 and f.date is None and j > 0 and u is not None:
                        f.unit, f.scale = u
                    q = _Placed(f, group, j, True, False, ctx=_subject(cells[0]) if j > 0 else None, lead=_subject(heading))
                    q.future = j > 0 and j < len(header_cells) and bool(re.search(r"цел|план|прогноз|после|стало|target|after|plan|forecast", header_cells[j], re.I))
                    row.append(q)
            # a row of several figures is a series (months, years): the figures of a dynamic, a change is its reading
            for x in row:
                x.changed = len(row) >= 2 or any(_CHANGE_RE.search(c) for c in cells)
            vals = [x for x in row if x.fig.date is None and not _is_year(x.fig)]
            if len(vals) >= 2 and not _eq(vals[0].fig.mag, vals[-1].fig.mag):
                up = "up" if vals[-1].fig.mag > vals[0].fig.mag else "down"
                res.stated.append(({up}, _Stems(content_stems(cells[0], neutral=True))))
            out.extend(row)
            continue
        in_table = False
        if not s:
            lead_line = ""
            continue
        if _HEADING_LINE_RE.match(s):
            heading, lead_line = s, ""
        dash = bool(_DASH_LINE_RE.match(s))
        if not dash and not s.endswith(":"):
            lead_line = ""
        for sn in H.split_sentences(s) or [s]:
            group += 1
            texts[group] = sn
            figs = figures(sn)
            placed = {id(f): _Placed(f, group, k, False, _ordinal(sn, f)) for k, f in enumerate(figs)}
            labels = _figure_labels(sn, figs)
            sn_future = bool(_FUTURE_RE.search(sn)) or (dash and bool(_FUTURE_RE.search(lead_line))) or (bool(_FUTURE_RE.search(heading)) and bool(_CHANGE_RE.search(sn)))
            pair_lead = dash and bool(_PAIR_LEAD_RE.search(lead_line))
            lead_stems = _subject(f"{heading} {lead_line if dash else ''} {sn[: sn.rfind(':')] if ':' in sn else ''}")
            for k, f in enumerate(figs):
                q = placed[id(f)]
                q.ctx, q.lead, q.base = labels[k], lead_stems, isinstance(labels[k], _BaseLabel)
                if pair_lead:
                    # «— покупки в день: 100 / 115» under «Сейчас / Цель»: the second value is the target
                    q.future = k % 2 == 1 and bool(_SLASH_BETWEEN_RE.fullmatch(sn[figs[k - 1].uend : f.start]))
                else:
                    q.future = sn_future and not _NOW_BEFORE_RE.search(sn, max(0, f.start - 30), f.start)
            for words, gov, _ in _change_governed(sn, [f for f in figs if not placed[id(f)].ordinal]):
                saving = any(_SAVING_RE.match(sn, a) for a, _ in words)
                for f in gov:
                    p = placed[id(f)]
                    p.changed = True
                    p.saving = p.saving or saving
                    p.delta = p.delta or saving or _prep(sn, f) == "by"
            # a change's size the verb of another clause speaks for («выручка увеличивается на 26,5%, а прибыль —
            # примерно на 112%»), a difference («на 238 500 рублей больше»), a change noun's size («Рост составит 112,3%»)
            change_sn = bool(_CHANGE_RE.search(sn))
            for f in figs:
                p = placed[id(f)]
                if p.ordinal or f.date is not None or _is_year(f):
                    continue
                by = _prep(sn, f) == "by"
                if (by and (change_sn or _COMPARE_AFTER_RE.match(sn, f.uend))) or (p.changed and _SIZE_BEFORE_RE.search(sn, 0, f.start)):
                    p.changed = p.delta = True
            for a, b in _clauses(sn):
                if _CHANGE_RE.search(sn, a, b):
                    dirs, stems = _change_subject(sn, a, b)
                    res.stated.append((dirs, _Stems(stems)))
            cands = [f for f in figs if not placed[id(f)].ordinal and f.date is None and not _is_year(f) and not f.approx]
            for a, b in zip(cands, cands[1:]):
                between = sn[a.uend : b.start]
                if _pair_written(sn, a, b):
                    placed[id(a)].changed = placed[id(b)].changed = True
                    res.pairs.add(frozenset((id(placed[id(a)]), id(placed[id(b)]))))
                if _RANGE_BETWEEN_RE.fullmatch(between):
                    res.ranges.add(frozenset((id(placed[id(a)]), id(placed[id(b)]))))
                if re.fullmatch(r"\s*(?:[^\W\d_]+\s+){0,2}из\s+", between, re.I) and 0 < a.mag < b.mag and (a.unit == b.unit or None in (a.unit, b.unit)):
                    res.shares.append(a.mag / b.mag * 100)  # «в 6 случаях из 30»
            for f, v in _sides(sn, cands).items():
                sides[id(next(p for p in placed.values() if id(p.fig) == f))] = v
            for f, y in _whens(sn, figs, cands).items():
                whens[id(next(p for p in placed.values() if id(p.fig) == f))] = y
            out.extend(placed[id(f)] for f in figs)
        if s.endswith(":"):
            lead_line = s
    res.texts = texts
    text_figs = [p for p in out if not p.cell and not p.ordinal and p.fig.date is None and not _is_year(p.fig) and not p.fig.approx]
    by_id = {id(p): p for p in out}
    for k, p in enumerate(text_figs):
        p.seq = k
    def marks(rx: re.Pattern, sn: str) -> bool:
        # «было 47», «Было: …», «до внедрения»; not a passive or a state («было задействовано», «стало понятно»)
        for m in rx.finditer(sn):
            nxt = _NEXT_WORD_RE.match(sn, m.end())
            if nxt and _NOT_A_VALUE_RE.match(nxt.group(1)):
                continue
            return True
        return False

    earlier = {g: marks(_EARLIER_MARK_RE, t) for g, t in texts.items()}
    later = {g: marks(_LATER_MARK_RE, t) for g, t in texts.items()}
    per_group: dict[int, int] = {}
    for q in text_figs:
        per_group[q.group] = per_group.get(q.group, 0) + 1
    for p in text_figs:
        sn, g = texts.get(p.group, ""), p.group
        window = (g - 1, g, g + 1)
        if (
            _VERSUS_RE.search(sn)
            or (any(earlier.get(x) for x in window) and any(later.get(x) for x in window) and (earlier.get(g) or later.get(g)))
            or (_PERIOD_RE.search(sn) and per_group.get(g, 0) >= 2)
        ):
            p.context = True
            continue
        # a change word in the figure's own clause («время сократилось до 29 минут»), or another figure of the same
        # unit in the sentence («47 минут и 29 минут»)
        for a, b in _clauses(sn):
            if a <= p.fig.start < b and _CHANGE_RE.search(sn, a, b):
                p.context = True
        same_unit = [q for q in text_figs if q is not p and q.group == g and q.fig.unit is not None and q.fig.unit == p.fig.unit]
        p.context = p.context or bool(same_unit)
    for p in text_figs:
        if sides.get(id(p), ("",))[0] == "earlier":
            p.earlier = True
            p.future = False
    for pa, pb in combinations(text_figs, 2):
        if abs(pa.group - pb.group) > 1:
            continue
        ua, ub = pa.fig.unit, pb.fig.unit
        both_units = ua is not None and ub is not None and (ua == ub or {ua, ub} <= {"pct", "pp"})
        bare = ua is None and ub is None
        near = pb.seq - pa.seq == 1
        if not (both_units or (bare and near)):
            continue
        sa, sb = sides.get(id(pa)), sides.get(id(pb))
        wa, wb = whens.get(id(pa)), whens.get(id(pb))
        if sa and sb and {sa[0], sb[0]} == {"earlier", "later"}:
            # two values without a unit only when each stands right after its marker: «было 1 500, стало 1 950»,
            # «NPS 64 (было 41)» — not «Раньше опрашивали 1 200 сотрудников. Теперь NPS 64»
            if bare and not (_marks_directly(texts[pa.group], sa, pa.fig) and _marks_directly(texts[pb.group], sb, pb.fig)):
                continue
            first = pa if sa[0] == "earlier" else pb
        elif wa and wb and wa != wb:
            first = pa if wa < wb else pb
        elif sa is None and sb and sb[0] == "later" and near and (pa.group != pb.group or sb[1] >= pa.fig.uend):
            # «12 дней, после внедрения 4», «47 минут. Теперь — 29 минут»: the value right before a later one; without
            # a unit only when the marker stands right before the later value («3 400, стало 5 000», not «3 400 заявок,
            # теперь NPS 64»)
            if bare and not _marks_directly(texts[pb.group], sb, pb.fig):
                continue
            first = pa
        else:
            continue
        pa.changed = pb.changed = True
        first.earlier = True
        first.future = False
        res.pairs.add(frozenset((id(pa), id(pb))))
        up = "up" if (pb if first is pa else pa).fig.mag > first.fig.mag else "down"
        for g in {pa.group, pb.group}:
            res.stated.append(({up}, _Stems(content_stems(_LATER_MARK_RE.sub(" ", _EARLIER_MARK_RE.sub(" ", texts[g])), neutral=True))))
    # the two values of a change share their label: «Время ответа: было 47, стало 29 минут» labels 29 too, and so
    # does a level the next sentence says changed («тратят 47 минут на чтение чатов» … «время сократилось до 29 минут»)
    ends_of = [[by_id[i] for i in pair if i in by_id] for pair in res.pairs]
    # «До миграции: 1 950 пользователей, 3,2 секунды … После миграции: 2 400 пользователей, 0,8 секунды»: two
    # sentences of a before/after, their figures of one unit in the same order
    groups = sorted({p.group for p in text_figs if p.context})
    for g in groups:
        for unit in {p.fig.unit for p in text_figs if p.group == g}:
            a = [p for p in text_figs if p.group == g and p.fig.unit == unit]
            if len(a) == 2:
                ends_of.append(a)  # «В мае 18 000 заказов, в августе — 31 000»: one measure at two times
            b = [p for p in text_figs if p.group == g + 1 and p.fig.unit == unit] if g + 1 in groups else []
            if a and len(a) == len(b):
                ends_of.extend([x, y] for x, y in zip(a, b))
    for p in text_figs:
        if p.changed and not p.delta and p.fig.unit is not None:
            q = next((x for x in text_figs if x.seq == p.seq - 1 and x.group in (p.group - 1, p.group - 2) and x.fig.unit == p.fig.unit and not x.changed), None)
            if q is not None:
                ends_of.append([q, p])
    # one label for every figure linked so (transitively: «тратили 47 минут» … «сократилось с 47 минут до 29»)
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        while parent.get(i, i) != i:
            i = parent[i]
        return i

    for ends in ends_of:
        if len(ends) == 2:
            ra, rb = find(id(ends[0])), find(id(ends[1]))
            if ra != rb:
                parent[ra] = rb
    linked = {i for e in ends_of if len(e) == 2 for i in (id(e[0]), id(e[1]))}
    comps: dict[int, list[_Placed]] = {}
    for p in out:
        if id(p) in linked:
            comps.setdefault(find(id(p)), []).append(p)
    for members in comps.values():
        both = frozenset().union(*[m.ctx or frozenset() for m in members])
        base = all(m.base for m in members)
        for m in members:
            m.ctx, m.base = both, base
    return res


def _eq(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _half_up(x: float, dec: int) -> float:
    return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP))


def _rounds_to(bv: float, f: Fig) -> bool:
    """Whether the plan's figure is the brief's `bv` rounded half up as a person does: to an integer or one decimal
    («38%» for 38,3%, «12 тыс.» for 12 400), at most 5% off; never from the midpoint — «15 млн» or «14 млн» for
    14,5 млн is a new figure, «14,5» is the brief's."""
    if f.dec > 1 or f.approx or bv <= 0:
        return False
    d = Decimal(repr(bv)).scaleb(f.dec)
    if d == d.to_integral_value():
        return False  # nothing to round: the brief's figure is as precise as the plan's
    if d - d.to_integral_value(rounding=ROUND_FLOOR) == Decimal("0.5"):
        return False
    return _eq(_half_up(bv, f.dec), f.value) and abs(bv - f.value) <= 0.05 * bv


def _approx_ok(f: Fig, v: float, tol: float) -> bool:
    """Whether `v` (a figure of the brief, or one derived from two of them) is what the plan's figure says, one of them
    in words: within its tolerance («треть» ≈ 33%), or on the side of the fraction its hedge says — «больше половины»
    for 58%, «более чем на треть» for 38%, «меньше чем на четверть» for 23%, «почти три четверти» for 71%, «около
    половины» for 47%."""
    d = v - f.mag
    if f.hedge == "gt":
        return 0 < d <= _HEDGE_SPAN
    if f.hedge == "lt":
        return 0 < -d <= _HEDGE_SPAN
    if f.hedge == "almost":
        return 0 <= -d <= 5.0
    if f.hedge == "about":
        return abs(d) <= 5.0
    return abs(d) <= tol


def _hedged_ok(f: Fig, v: float) -> bool:
    """A hedged figure in digits against the true value `v` (in the figure's scale): «более чем в 2 раза» for 2,12
    (above it, not far), «почти 2,1 раза» only for a value just under 2,1, «примерно на 112%» for 112,3."""
    x = f.value
    if not x:
        return False
    if f.hedge == "gt":
        return x < v <= x * 1.5 + (15.0 if f.unit in ("pct", "pp") else 0.0)
    if f.hedge == "lt":
        return x * 0.5 <= v < x
    if f.hedge == "almost":
        return x * 0.9 <= v < x
    if f.hedge == "about":
        return abs(v - x) <= 0.05 * max(abs(v), abs(x)) or _eq(_half_up(v, f.dec), x)
    return False


def _same_unit(a: Fig, b: Fig) -> bool:
    return a.unit == b.unit or ({a.unit, b.unit} <= {"pct", "pp"})


def _stems_meet(a: Iterable[str], b: Iterable[str]) -> bool:
    """Two sets of stems share a word (a stem of the other's by four letters or more: «зарплат» / «зарплаты»)."""
    bs = list(b)
    if not bs:
        return False
    for x in a:
        for y in bs:
            k = min(len(x), len(y), 5)
            if k >= 4 and x[:k] == y[:k]:
                return True
            if k == 3 and x == y:
                return True
    return False


def _date_eq(a: tuple[int, int, Optional[int]], b: tuple[int, int, Optional[int]]) -> bool:
    return a[:2] == b[:2] and (a[2] is None or b[2] is None or a[2] == b[2])


# ------------------------------------------------------------------ words

_WORD_RE = re.compile(r"[a-zа-яё]+", re.I)
_STOP = frozenset(
    """и в во на с со к ко по о об обо от до из у за для при без через над под про а но или либо же ли бы не ни что
    чтобы как так там тут где когда если то тот та те это эти этот эта этого этой всё все весь вся всех всем наш наша
    наше наши нашего нам нас ваш ваша ваше ваши вам вас мы вы они он она оно его её ее их им ими свой своя свое своё свои
    который которая которое которые которых также тоже ещё еще уже только лишь более менее очень почти около её
    один одна одно одного одной одному одним одних два две три четыре пять после перед между среди каждый каждая каждое каждые можно нужно будет
    будут было были был была есть быть может могут этом том тем чем кто
    the a an of and or to in on for with by is are be as at from this that these those it its our your their""".split()
)
# words of a slide's frame, neither in nor out of the brief
_NEUTRAL = ("ключев", "основн", "главн", "важн", "кратк", "обзор", "итог", "вывод", "резюм", "повестк", "слайд", "презентац", "раздел")
_THANKS_FRAME = ("спасиб", "вниман", "вопрос", "благодар", "обсужд", "контакт", "связ")
_ENDINGS = sorted(
    """иями ями ами ого его ому ему ыми ими ться тся ется ются ится ятся ает яет ают яют ует уют ила ило или ала ало али
    ела ело ели ила ать ять ить еть ешь ишь ах ях ам ям ов ев ей ой ий ый ая яя ое ее ые ие ых их ым им ом ем ую юю ия ии
    ию ья ье ьи ью ет ит ут ют ят ла ло ли ть сь ся а я о е ы и у ю ь й""".split(),
    key=len,
    reverse=True,
)


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[: -len(e)]
    return w


def content_stems(text: str, neutral: bool = False) -> list[str]:
    """The stems of a text's content words: no stop words, no unit words, no words of the slide frame (unless
    `neutral`), no one- and two-letter words."""
    out = []
    for w in _WORD_RE.findall(text or ""):
        lw = w.lower()
        if len(lw) < 3 or lw in _STOP or _UNIT_IN_RE.fullmatch(lw):
            continue
        s = stem(lw)
        if not neutral and s.startswith(_NEUTRAL):
            continue
        out.append(s)
    return out


class _Stems:
    def __init__(self, stems: Iterable[str]) -> None:
        self.pref: dict[int, set[str]] = {k: set() for k in range(3, 6)}
        for s in stems:
            for k in range(3, 6):
                if len(s) >= k:
                    self.pref[k].add(s[:k])

    def has(self, s: str) -> bool:
        # a long stem by its first five letters, a shorter one by four: «сводок» / «сводки», «чатов» / «чаты»
        k = 5 if len(s) >= 7 else min(4, len(s))
        return k >= 3 and s[:k] in self.pref[k]


# ------------------------------------------------------------------ placeholders

_PLACEHOLDER_RES = [
    re.compile(r"\[[^\[\]]{0,80}\]"),  # [email], [телефон], [Имя Фамилия], [email@company.com]
    re.compile(r"\{\{?[^{}]{0,60}\}\}?"),  # {company}, {{name}}
    re.compile(r"<[^\W\d_]+(?:[ _\-][^\W\d_]+){0,4}>"),  # <имя>, <название компании>; not «<5 минут, … >10 минут»
    re.compile(r"(?<![\wё])(?:lorem|ipsum|dolor\s+sit\s+amet)(?![\wё])", re.I),
    re.compile(r"(?<![\wё])(?:[xх]{3,}|[xх]{2}(?=\s?%))(?![\wё])", re.I),  # XXX, ХХХ, XX%
    re.compile(r"(?<![\wё])[NXХ]\s?%", re.I),  # N%, X%
    re.compile(r"(?<![\wё])(?:tbd|tba|todo)(?![\wё])", re.I),
    re.compile(r"(?<![\wё])(?:иван(?:ов|а)?\s+иван(?:ов|ович)\w*|петр(?:ов)?\s+петров\w*|сидор(?:ов)?\s+сидоров\w*|john\s+doe|jane\s+doe|имя\s+фамилия|фамилия\s+имя|фио)(?![\wё])", re.I),
]
_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s,;)»]+|(?<![\w@.\-])[\w\-]+\.(?:com|ru|org|net|io|рф|info|biz|online|tech)(?:/[^\s,;)»]*)?(?![\w])", re.I)
_PHONE_RE = re.compile(r"(?<![\w+])(?:\+\d{1,3}|8)[\s(\-]*\d{3}[\s)\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?![\w])")
_DANGLING_LABEL_RE = re.compile(
    r"(?<![\wё])(?:контакты|контакт|e-?mail|почта|эл\.\s?почта|телефон|тел\.?|сайт|web|адрес|связь|contacts?|phone|site)\s*:\s*(?=$|[|·•/,;])",
    re.I,
)


def _tidy(t: str) -> str:
    t = re.sub(r"\(\s*\)|\[\s*\]|«\s*»", "", t)
    if t.count("(") != t.count(")"):
        # a parenthesis whose other half went: «NPS 64) Время …» → «NPS 64, Время …» (still two clauses)
        t = re.sub(r"\s*\)\s*(?=[^\s.,;:!?])", ", ", t).replace("(", "").replace(")", "")
    for _ in range(3):
        t = _DANGLING_LABEL_RE.sub("", t)
        t = re.sub(r"\s*([|·•/])\s*(?=[|·•/]|$)", "", t)
        t = re.sub(r"^\s*[|·•/]\s*", "", t)
    t = re.sub(r"\s+([,.;:!?%])", r"\1", t)
    t = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", t)
    t = re.sub(r"[,;:]\s*(?=[.!?]|$)", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = t.strip(" ,;:—–-|·•/")
    return t


# ------------------------------------------------------------------ the brief


@dataclass
class _Clean:
    text: str
    changed: bool = False
    bad: list[str] = field(default_factory=list)  # figures and names not in the brief
    stripped: list[str] = field(default_factory=list)  # «64%» → «64»
    placeholders: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)  # clauses of a change the brief does not state (also in `bad`)
    misread: list[str] = field(default_factory=list)  # the brief's figures given another subject (also in `bad`)


_ORDINAL_TOKEN_RE = re.compile(r"(\d{1,2})-?(?:й|ый|ой|ий|го|ого|его|му|ому|ему|м|ом|ем|я|ая|яя|е|ое|ее|х|ых|их|ти|и)", re.I)
_ORDINAL_WORDS = {1: "перв", 2: "втор", 3: "трет|тр[её]х", 4: "четв[её]рт|четыр[её]х", 5: "пят", 6: "шест", 7: "седьм|сем", 8: "восьм|восем", 9: "девят", 10: "десят"}


class BriefIndex:
    """What the brief says: its figures (with units), the values derived from pairs of them, its words, its title.
    Figures and content words come from the brief's text and title only; the user's instructions and the audience
    may be named on the title slide (and give names and contacts), they ground no figure («не более 12 слайдов,
    доклад на 10 минут» makes neither «12» nor «10 минут» the brief's)."""

    def __init__(self, text: str, title: Optional[str] = None, extra: Iterable[str] = (), audience: Optional[str] = None) -> None:
        body = "\n".join(x for x in (text or "", title or "") if x)
        frame = "\n".join([body] + [e for e in extra if e] + ([audience] if audience else []))
        self.text = body
        self._frame_text = frame
        self._frame: Optional[BriefIndex] = None
        self.lower = frame.lower()
        bf = _brief_figures(body)
        self.placed = bf.placed
        self._pairs, self._ranges, self._shares, self._stated = bf.pairs, bf.ranges, bf.shares, bf.stated
        self.figs = [p.fig for p in self.placed]
        self.stems = _Stems(content_stems(body, neutral=True))
        self._texts = bf.texts
        self._extra: list[tuple[float, Optional[str], str, bool]] = []  # derived of the analyst's before/after pairs
        self._derived = self._derive()
        self._cache: dict[tuple, str] = {}
        self.categories: set[str] = set()  # the analyst's chart categories (lowercase), the neutral words of a chart
        first_line = next((ln for ln in body.splitlines() if ln.strip()), "")
        self._title_subject = _subject(f"{title or ''} {first_line}")
        self.no_guarantee = bool(re.search(r"не\s+(?:представляй|подавай|выдавай|показывай)\s+\w*\s*(?:прогноз|результат)\w*[^.]{0,40}гарантир", body, re.I))
        self._structure_used = False
        doc_title, sections = H.parse_sections(text or "")
        first = next((sn for sec in sections for sn in sec.sentences), "")
        named = title_line(text or "")  # «Название: «Больше прибыли с каждой чашки»» — the user's own title
        self.title = H.strip_end(title or named or doc_title or _first_statement_title(first) or "") or None
        self.title_stems = _Stems(content_stems(f"{self.title or ''} {named or ''} {doc_title or ''} {first}", neutral=True))

    @property
    def frame(self) -> "BriefIndex":
        """The index of the deck's frame — the title slide and the deck's subtitle, which may name the audience or
        what the user asked for («для жюри хакатона «Лидеры цифровой трансформации 2026»»): the brief with them."""
        if self._frame is None:
            self._frame = self if self._frame_text == self.text else BriefIndex(self._frame_text, self.title)
        return self._frame

    @classmethod
    def of(cls, brief: Union[Brief, str]) -> "BriefIndex":
        if isinstance(brief, Brief):
            return cls(brief.text, brief.title_hint, [brief.extra_instructions or ""], audience=brief.audience)
        return cls(brief)

    # -------------------------------------------------------------- figures

    def _derive(self) -> list[tuple[float, Optional[str], str]]:
        """Values a person derives from two figures of one measure: (value, unit, «diff» | «pct» | «ratio» | «share»)
        — their difference, their percent change from the earlier value («было», «с», «в 2024 году», else the first
        written), their ratio; and a share written as «6 из 30». Only two figures written close together: the two
        values of a change the brief states; two with a unit in one sentence or two neighbouring ones; two without a
        unit side by side in one sentence (their difference and ratio only: «1621 фигура и только 81 плейсхолдер»); two
        cells of a table side by side in a row or at its ends — a brief has many unrelated numbers, and all their
        combinations would ground almost anything. The ends of a range («месяц 1–2», «8–25 секунд») are not two values
        to compare, and a share's percent change («38% → 14%» as «−63%») is not derived either: its difference in
        points is."""
        placed = [p for p in self.placed if not p.ordinal and p.fig.date is None and not p.fig.approx and not _is_year(p.fig)]
        out: set[tuple[float, Optional[str], str]] = {(round(x, 6), "pct", "share") for x in self._shares}
        seen: set[tuple] = set()
        for pa, pb in combinations(placed, 2):
            a, b, ua, ub = pa.fig.mag, pb.fig.mag, pa.fig.unit, pb.fig.unit
            if not (ua == ub or {ua, ub} <= {"pct", "pp"}) or _eq(a, b):
                continue
            key2 = frozenset((id(pa), id(pb)))
            kinds = {"diff", "pct", "ratio"}
            level_change = ua is not None and pa.group != pb.group and (
                (pb.changed and not pb.delta and not pa.changed and pa.seq < pb.seq) or (pa.changed and not pa.delta and not pb.changed and pb.seq < pa.seq)
            )
            if not (pa.cell or pb.cell) and key2 not in self._pairs and not level_change:
                # two figures of one unit side by side that the brief does not write as a change of one measure: their
                # difference may be read off («на 238 500 рублей больше»), a percent change or a ratio of them would be
                # a new figure (of two unrelated sums). A level the next sentence says changed («тратят 47 минут» …
                # «время сократилось до 29 минут») is such a change
                kinds = {"diff"}
            if pa.cell or pb.cell:
                # a table compares along its rows: neighbouring cells («До | После») or the row's ends (a series)
                if not (pa.cell and pb.cell and pa.group == pb.group):
                    continue
                row = [p.pos for p in placed if p.group == pa.group]
                if abs(pa.pos - pb.pos) != 1 and {pa.pos, pb.pos} != {min(row), max(row)}:
                    continue
            elif key2 in self._pairs:
                pass
            elif key2 in self._ranges or abs(pa.group - pb.group) > 1:
                continue
            elif ua is None:
                if pa.group != pb.group or abs(pa.seq - pb.seq) != 1:
                    continue
                kinds = {"diff", "ratio"}
            base = pb if pb.earlier and not pa.earlier else pa
            key = (round(a, 6), round(b, 6), ua, id(base) == id(pa), tuple(sorted(kinds)))
            if key in seen:
                continue
            seen.add(key)
            d = abs(a - b)
            if ua in ("pct", "pp"):
                out.update({(round(d, 6), "pct", "diff"), (round(d, 6), "pp", "diff")})
                continue
            out.add((round(d, 6), ua, "diff"))
            if base.fig.mag and "pct" in kinds:
                out.add((round(d / abs(base.fig.mag) * 100, 6), "pct", "pct"))
            lo, hi = sorted((abs(a), abs(b)))
            if lo and "ratio" in kinds:
                out.add((round(hi / lo, 6), "times", "ratio"))
        out.update((v, u, k) for v, u, k, _ in getattr(self, "_extra", []))
        return sorted(out, key=lambda x: x[0])

    def use_structure(self, structure: Optional[BriefStructure]) -> "BriefIndex":
        """The analyst's reading of the brief: every before/after pair it built (a two-point series «Сейчас / Цель», the
        ends of a run over time, a «Сейчас | Цель» table row) is a change of one measure however far apart the brief
        writes its values — its difference, percent change and ratio are the brief's («Выручка вырастет на 26,5%» of
        900 000 → 1 138 500); the target ends are forecasts; the series' categories are a chart's own words. Idempotent."""
        if structure is None or self._structure_used:
            return self
        self._structure_used = True
        pairs: list[tuple[float, float, Optional[str]]] = []
        for s in structure.series:
            vals = [v for v in s.values if v is not None]
            self.categories.update(" ".join(c.lower().split()) for c in s.categories)
            if len(vals) >= 2 and len(vals) == len(s.categories):
                unit = figures(f"1 {s.unit}")[0].unit if s.unit and figures(f"1 {s.unit}") else None
                pairs.append((vals[0], vals[-1], unit))
        for tb in structure.tables:
            if len(tb.columns) < 3:
                continue
            for row in tb.rows:
                cells = [figures(c) for c in row[1:3]]
                if len(cells) == 2 and len(cells[0]) == 1 and len(cells[1]) == 1:
                    a, b = cells[0][0], cells[1][0]
                    if (a.unit == b.unit or None in (a.unit, b.unit)) and not (a.date or b.date):
                        pairs.append((a.mag, b.mag, a.unit or b.unit))
        extra = []
        for a, b, unit in pairs:
            if not a or _eq(a, b):
                continue
            d = abs(b - a)
            if unit in ("pct", "pp"):
                extra += [(round(d, 6), "pct", "diff", True), (round(d, 6), "pp", "diff", True)]
                continue
            extra += [(round(d, 6), unit, "diff", True), (round(d / abs(a) * 100, 6), "pct", "pct", True)]
            lo, hi = sorted((abs(a), abs(b)))
            if lo:
                extra.append((round(hi / lo, 6), "times", "ratio", True))
            self._future_values.add(round(b, 6))
        self._extra = extra
        self._derived = self._derive()
        self._cache.clear()
        return self

    @property
    def _future_values(self) -> set:
        if not hasattr(self, "_fv"):
            self._fv: set = set()
        return self._fv

    def _same(self, f: Fig) -> list[_Placed]:
        """The brief's figures the plan's figure writes: the same value (as written or in full), the same date, a word
        figure within its tolerance (on its side of a hedge: «больше половины» for 58%), else the brief's figure rounded
        as a person rounds it."""
        if f.date is not None:
            return [p for p in self.placed if p.fig.date is not None and _date_eq(p.fig.date, f.date)]
        out = []
        for p in self.placed:
            b = p.fig
            if p.ordinal:
                continue  # «Этап 1», «Слайд 2»: a step's number grounds no figure
            if b.date is not None:
                if _is_year(f) and b.date[2] == int(f.value):
                    out.append(p)  # «в 2026 году» of «15.10.2026»
            elif _eq(b.mag, f.mag) or (f.scale == 1.0 and _eq(b.value, f.value)):
                out.append(p)
            elif (f.approx or b.approx) and (_compatible(f.unit, b.unit) or _compatible(b.unit, f.unit)) and _approx_ok(f, b.mag, max(f.approx, b.approx)):
                out.append(p)  # «треть» for 33%, «33%» for «каждый третий»
        if not out and f.dec == 2 and f.unit is None and f.scale == 1.0:
            # «15.10» — a date without its year read as a number (the rules' facts registry writes it so)
            d, m = int(f.value), int(round((f.value - int(f.value)) * 100))
            out = [p for p in self.placed if p.fig.date is not None and p.fig.date[:2] == (d, m)]
        if not out:
            for p in self.placed:
                b = p.fig
                if b.date is not None:
                    continue
                if f.scale > b.scale:
                    ok = _rounds_to(b.mag / f.scale, f)  # a scale word the brief does not write: 12 400 → «12 тыс.»
                else:
                    ok = (f.scale == b.scale or f.scale == 1.0) and _rounds_to(b.value, f)  # 38,3% → «38%»
                if ok:
                    out.append(p)
        return out

    def _derived_ok(self, f: Fig, kinds: tuple[str, ...] = ("diff", "pct", "ratio", "share")) -> bool:
        for x, ux, kind in self._derived:
            if kind not in kinds:
                continue
            # a bare figure may be a difference («на 18» after «с 47 до 29 минут»), never a share or a ratio; points
            # are the difference of two scores («NPS вырос на 23 пункта»)
            if not (f.unit == ux or (f.unit is None and ux not in ("pct", "pp", "times")) or (f.unit in ("pct", "pp") and ux in ("pct", "pp")) or (f.unit == "pts" and ux is None)):
                continue
            v = x / f.scale
            if f.approx:
                if _approx_ok(f, v, f.approx):
                    return True
            elif f.hedge:
                # «более чем в 2 раза» of 2,12 is true, «почти в 2,1 раза» of it is not: the hedge's side counts
                if _hedged_ok(f, v) or (f.hedge == "about" and _eq(v, f.value)):
                    return True
            elif _eq(v, f.value) or (v and _eq(_half_up(v, f.dec), f.value) and abs(v - f.value) <= 0.05 * abs(v)):
                return True
        return False

    def _derived_near(self, f: Fig) -> Optional[float]:
        """The derived value (in the figure's scale) a hedged figure speaks of: the nearest within 10% of it."""
        best: Optional[float] = None
        for x, ux, kind in self._derived:
            if not (f.unit == ux or (f.unit in ("pct", "pp") and ux in ("pct", "pp")) or (f.unit is None and ux not in ("pct", "pp", "times"))):
                continue
            v = x / f.scale
            if f.value and abs(v - f.value) <= 0.1 * abs(f.value) and (best is None or abs(v - f.value) < abs(best - f.value)):
                best = v
        return best

    # -------------------------------------------------------------- what a figure means

    def bound(self, text: str, f: Fig, figs: Optional[list[Fig]] = None) -> bool:
        """Whether the text uses the brief's figure for what the brief says it is: the words of its label (since the
        figure before it, up to the next one) name the subject the brief's label gives it, or its list's lead, or do not
        name another item of the same list or sentence. «Аренда обходится в 25 000 рублей» when the brief's 25 000 is
        «коммунальные услуги» (and its 120 000 «аренда») is not; «Зарплаты — 315 000» when 315 000 is «продукты» is
        not; «Вложения — 180 000 ₽» under the brief's «Вложения и прогноз роста» is. A text that names no subject,
        and a figure the brief gives no label, pass: nothing to compare."""
        figs = figs if figs is not None else [x for x in figures(text) if not _ordinal(text, x)]
        if f not in figs:
            return True
        mine = _figure_labels(text, figs, line=True)[figs.index(f)]
        if not mine or isinstance(mine, _BaseLabel):
            return True  # nothing named, or only a share's base («13,3% выручки»)
        same = [p for p in self._same(f) if f.unit is None or p.fig.unit is None or _compatible(f.unit, p.fig.unit)]
        if not same or any(not p.ctx for p in same):
            return True  # the brief writes this figure somewhere without a label: nothing to compare
        for p in same:
            own = p.ctx or frozenset()
            if not own or _stems_meet(mine, own):
                return True  # the brief gives it no label (nothing to compare), or the same one
            # the items of the same enumeration («зарплаты — в 270 000 рублей, аренда — в 120 000 рублей»): figures of
            # the same unit in its sentence or its list, not the other end of its own pair or range
            sibs = frozenset().union(*[q.ctx for q in self.placed if self._sibling(p, q)]) - own
            if _stems_meet(mine, sibs):
                continue  # it names another item's subject: the figure is that item's neighbour, not its value
            if _stems_meet(mine, p.lead) or _stems_meet(mine, self._title_subject):
                return True
            # a word that labels another figure of the same unit («чеки с едой» — 20% → 30%) for this one («35%»): the
            # figure is given that other subject; a word the brief labels nothing with says nothing against it
            others = [q.ctx for q in self.placed if q.ctx and not q.base and q is not p and not _eq(q.fig.mag, p.fig.mag)]
            if any(_stems_meet(mine, c - own) for c in others):
                continue
            return True
        return False

    def _sibling(self, p: "_Placed", q: "_Placed") -> bool:
        if q is p or not q.ctx or q.base or not _same_unit(p.fig, q.fig) or q.cell != p.cell:
            return False
        if q.group == p.group:
            sn = self._texts.get(p.group, "")
            a, b = (q, p) if q.fig.start < p.fig.start else (p, q)
            return not (sn and _PAIR_BETWEEN_RE.fullmatch(sn[a.fig.end : b.fig.start]))
        return bool(q.lead) and q.lead == p.lead and abs(q.group - p.group) <= 8 and not p.cell

    def future_figure(self, f: Fig) -> bool:
        """The brief states this figure (or the change it is of) as a plan, a target or a forecast."""
        same = self._same(f)
        if same:
            return all(p.future or round(p.fig.mag, 6) in self._future_values for p in same)
        return self._derived_ok(f) and bool(self._future_values or any(p.future for p in self.placed))

    def verdict(self, f: Fig) -> str:
        """«ok» — the brief's figure (or one derived from two of them); «strip» — the brief's number with a unit the
        brief does not give it; «bad» — not the brief's."""
        key = (f.value, f.dec, f.scale, f.unit, f.date, f.approx, f.word_unit, f.hedge, _is_year(f))
        if key in self._cache:
            return self._cache[key]
        same = self._same(f)
        if f.date is not None:
            v = "ok" if same else "bad"
        elif same and (f.unit is None or any(_compatible(f.unit, p.fig.unit) for p in same)):
            v = "ok"
        elif self._derived_ok(f):
            v = "ok"
        elif same and f.unit is not None and any(p.fig.unit is None and p.context and self._unit_nearby(p, f.unit) for p in same):
            v = "ok"  # «было 47 минут — стало 29»: 29 is in minutes too
        elif same and all(p.fig.unit is None for p in same) and f.unit in _STRIP_UNITS and not f.word_unit:
            v = "strip"
        elif same and _is_year(f):
            v = "ok"  # «в 2026 году»; a number without a unit takes no other time unit («64 дня» for NPS 64)
        else:
            v = "bad"
        self._cache[key] = v
        return v

    def _unit_nearby(self, p: _Placed, unit: str) -> bool:
        """A figure next to `p` (the one before or after it in the brief's text) carries `unit`."""
        return any(q is not p and not q.cell and q.seq >= 0 and abs(q.seq - p.seq) == 1 and q.fig.unit == unit for q in self.placed)

    def _pair_in_brief(self, a: Fig, b: Fig) -> bool:
        """Both ends of a change are the brief's, of one measure, side by side: one table row; one sentence or two
        neighbouring ones with the same unit; or the two values of a change the brief states («было 1 200, стало
        2 000», «NPS 64 (было 41)») — not any two figures without a unit («NPS 64. В пилоте 41 команда.»)."""
        def unit_ok(f: Fig, p: _Placed) -> bool:
            # the brief may write the unit once: «было 47 минут — стало 29» (29 in minutes as well)
            return f.unit is None or _compatible(f.unit, p.fig.unit) or (p.fig.unit is None and p.context and self._unit_nearby(p, f.unit))

        for pa in self._same(a):
            if not unit_ok(a, pa):
                continue
            for pb in self._same(b):
                if pb is pa or not unit_ok(b, pb):
                    continue
                if pa.cell and pb.cell and pa.group == pb.group:
                    return True
                if pa.cell or pb.cell or abs(pa.group - pb.group) > 1:
                    continue
                if frozenset((id(pa), id(pb))) in self._pairs:
                    return True
                ua, ub = pa.fig.unit, pb.fig.unit
                if ua is not None and ub is not None and (ua == ub or {ua, ub} <= {"pct", "pp"}):
                    return True
                if pa.context and pb.context and (ua == ub or None in (ua, ub)) and abs(pa.seq - pb.seq) <= 2:
                    return True  # «Было: …, NPS 41. Стало: …, NPS 64», «в мае 18 000, в августе — 31 000»
        return False

    def change_ok(self, text: str, figs: list[Fig], words: Iterable[tuple[int, int]] = ()) -> bool:
        """Whether a change the text claims of `figs` is what the brief says: the text gives both ends of it and the
        brief has them side by side («с 47 до 29 минут»); a figure after «на» is the size of a change the brief states
        or derives («на 18 минут», «на 38%», «на 34%» of «выросла на 34%»); after «до», a level the brief says a change
        came to («до 29 минут» of «сократилось до 29 минут» or «было 47, стало 29»), not the size of one («выросла до
        34%» of «выросла на 34%») unless a saving («экономия выросла до 2,1 часа»: a level of savings); otherwise a
        figure of a change the brief states, or a value derived from two of its figures. «NPS вырос до 64» against
        «NPS 64» is not; nor «сократилось на 29 минут» against «сократилось до 29 минут». Dates and years are when, not
        what changed."""
        figs = [f for f in figs if f.date is None and not _is_year(f)]
        if not figs:
            return True
        savings = [a for a, _ in words if _SAVING_RE.match(text, a)]  # «Экономия времени выросла до 2,1 часа»
        paired: set[int] = set()  # the ends of a change the brief does not have side by side («NPS вырос с 29 до 64»)
        for a, b in zip(figs, figs[1:]):
            if _pair_written(text, a, b):
                if self._pair_in_brief(a, b):
                    return True
                paired |= {id(a), id(b)}
        for f in figs:
            if id(f) in paired:
                continue
            prep = _prep(text, f)
            same = self._same(f)
            if prep == "by":
                if any(p.delta for p in same) or self._derived_ok(f, ("diff", "pct")):
                    return True
            elif prep == "to":
                saving = any(a < f.start and not _seps(text, _CLAUSE_SEP_RE, a, f.start) for a in savings)
                if any((p.changed or p.context) and (not p.delta or p.saving or saving) for p in same):
                    return True
            elif any(p.changed or p.context for p in same) or (not same and self._derived_ok(f)):
                return True
        return False

    def change_stated(self, text: str, a: int, b: int) -> bool:
        """Whether the brief states the change text[a:b] claims without a figure: a change the same way (or a saving,
        an improvement) of something the clause names («Время на чтение чатов сократилось» of «время сократилось до
        29 минут»; not «Удовлетворённость выросла» of it)."""
        dirs, stems = _change_subject(text, a, b)
        if not stems:
            return False
        for bdirs, bstems in self._stated:
            if (dirs & bdirs or "any" in dirs or "any" in bdirs) and any(bstems.has(x) for x in stems):
                return True
        return False

    def fix_hedges(self, text: str) -> str:
        """A hedge on the wrong side of the true value turned: «почти в 2,1 раза» of 2,12 → «более чем в 2,1 раза»,
        «более чем на 30%» of 26,5% → «почти на 30%». A figure the brief writes as it is keeps its hedge."""
        out = text
        for f in sorted(figures(text), key=lambda x: -x.start):
            if f.approx or f.hedge not in ("almost", "gt", "lt") or f.date is not None:
                continue
            if any(_eq(p.fig.value, f.value) for p in self._same(f)):
                continue
            v = self._derived_near(f)
            if v is None or _eq(v, f.value):
                continue
            want = "более чем" if v > f.value and f.hedge in ("almost", "lt") else "почти" if v < f.value and f.hedge == "gt" else None
            if want is None:
                continue
            m = _HEDGE_BEFORE_RE.search(out, max(0, f.start - 40), f.start)
            if m is None:
                continue
            prep = re.search(r"(на|в|у|за)\s+$", m.group(0))
            word = want if not m.group("h")[:1].isupper() else want[:1].upper() + want[1:]
            out = out[: m.start()] + word + (f" {prep.group(1)}" if prep else "") + " " + out[f.start :]
        return out

    def forecast_line(self, text: str) -> bool:
        """The line states a figure the brief gives as a plan, a target or a forecast (or a change of one)."""
        figs = [f for f in figures(text) if not _ordinal(text, f) and f.date is None and not _is_year(f)]
        return any(self.verdict(f) == "ok" and self.future_figure(f) for f in figs)

    def token_ok(self, tok: str) -> bool:
        if re.search(rf"(?<![\w]){re.escape(tok.lower())}(?![\w])", self.lower) is not None:
            return True
        # «к 6-му месяцу» of «к шестому месяцу», «3-х» of «трёх»: an ordinal (or a count) in digits of the brief's word
        m = _ORDINAL_TOKEN_RE.fullmatch(tok)
        if m is None:
            return False
        n = int(m.group(1))
        if any(not p.fig.date and not p.fig.approx and _eq(p.fig.value, n) and p.fig.scale == 1.0 for p in self.placed):
            return True
        word = _ORDINAL_WORDS.get(n)
        return bool(word and re.search(rf"(?<![\wё])(?:{word})\w*", self.lower))

    def written(self, fragment: str) -> bool:
        return fragment.strip().lower() in self.lower

    # -------------------------------------------------------------- words

    def ratio(self, text: str) -> Optional[float]:
        """The share of the text's content words the brief has; None for a text without content words."""
        stems = content_stems(text)
        if not stems:
            return None
        hit = sum(1 for s in stems if self.stems.has(s))
        return hit / len(stems)

    def grounded_figure(self, text: str) -> bool:
        return any(self.verdict(f) != "bad" and not _ordinal(text, f) for f in figures(text))

    def unit_figure(self, text: str) -> bool:
        """A figure of the brief with the unit the brief gives it («18 минут», «14,5 млн ₽», «1 ноября») — not a bare
        number, which may be the brief's for something else, nor a year."""
        return any(
            (f.unit is not None or f.scale > 1.0) and not _is_year(f) and not _ordinal(text, f) and self.verdict(f) == "ok"
            for f in figures(text)
        )

    # -------------------------------------------------------------- cleaning

    def clean(self, text: Optional[str]) -> _Clean:
        """The text without placeholders, with units the brief does not use taken off its figures, and without the
        clauses of figures, names and changes the brief does not have (or of its figures given another subject).
        Repeated until nothing more goes: a clause that went can leave a figure next to other words."""
        c = self._clean_once(text)
        for _ in range(3):
            if not c.changed or not c.text:
                break
            c2 = self._clean_once(c.text)
            if not c2.changed:
                break
            c = _Clean(
                c2.text, True, c.bad + [x for x in c2.bad if x not in c.bad], c.stripped + c2.stripped, c.placeholders + c2.placeholders,
                c.changes + [x for x in c2.changes if x not in c.changes], c.misread + [x for x in c2.misread if x not in c.misread],
            )
        return c

    def _clean_once(self, text: Optional[str]) -> _Clean:
        if not text:
            return _Clean(text or "")
        t = text
        ph: list[str] = []
        for rx in _PLACEHOLDER_RES + [_EMAIL_RE, _URL_RE, _PHONE_RE]:
            def repl(m: re.Match) -> str:
                if self.written(m.group(0)):
                    return m.group(0)
                ph.append(m.group(0).strip())
                return " "

            t = rx.sub(repl, t)
        if ph:
            t = _tidy(t)
        bad_spans: list[tuple[int, int]] = []
        bad: list[str] = []
        for a, b, tok in name_tokens(t):
            if not self.token_ok(tok):
                bad_spans.append((a, b))
                bad.append(tok)
        edits: list[tuple[int, int]] = []
        stripped: list[str] = []
        good: list[Fig] = []
        misread: list[str] = []
        figs_t = [f for f in figures(t) if not _ordinal(t, f)]
        for f in figs_t:
            v = self.verdict(f)
            if v == "ok" and f.date is None and not _is_year(f) and not f.approx:
                literal = [p for p in self._same(f) if f.unit is None or p.fig.unit is None or _compatible(f.unit, p.fig.unit)]
                # the size of a change («на 30 рублей», «в 2 раза», «рост 112%»), not a level it came to («до 35%»)
                change = _change_context(t, f) and _prep(t, f) != "to"
                if literal:
                    # the brief's figure with another subject («Аренда обходится в 25 000 рублей» for the brief's
                    # «коммунальные услуги — 25 000»): as wrong as an invented one — unless the text states a change
                    # and the figure is one of the brief's changes («на 30 рублей» of 300 → 330)
                    if not self.bound(t, f, figs_t) and not (change and self._derived_ok(f)):
                        v = "bad"
                        misread.append(t[f.start : f.uend].strip())
                elif not change and not self._derived_ok(f, ("share",)):
                    # a percent change or a ratio of the brief's figures is a change: «Расходы на аренду составляют
                    # 75% бюджета» is not «маркетинг вырастет на 75%»
                    v = "bad"
            if v == "strip":
                edits.append((f.end, f.uend))
                stripped.append(t[f.start : f.uend])
            elif v == "bad":
                bad_spans.append((f.start, f.uend))
                bad.append(t[f.start : f.uend])
            if v != "bad":
                good.append(f)
        changes: list[str] = []
        for words, gov, orphan in _change_governed(t, good):
            if not orphan:
                if self.change_ok(t, gov, words):
                    continue
                # the change words and their figures go with their clauses (a parenthesis is a clause of its own there)
                spans = words + [(f.start, f.uend) for f in gov]
            else:
                # a change word in a clause without figures («Время на чтение чатов сократилось, NPS 64»): a change the
                # brief states stands; another one speaks of the sentence's figures, and when the brief states no change
                # of them only its own clause goes — never a figure the brief has («Удовлетворённость выросла: NPS 64»
                # → «NPS 64»)
                cl = [(a, b) for a, b in _clauses(t) if any(a <= w < b for w, _ in words)]
                words = [w for w in words if not any(a <= w[0] < b and self.change_stated(t, a, b) for a, b in cl)]
                if not words or self.change_ok(t, gov, words):
                    continue
                spans = words
            bad_spans.extend(spans)
            changes.append(_clause_text(t, spans))
        bad.extend(changes)
        if bad_spans:
            t, edits = _drop_clauses(t, bad_spans, edits)
        for a, b in sorted(edits, reverse=True):
            t = t[:a] + t[b:]
        if edits or bad_spans:
            t = _tidy(t)
        return _Clean(t, t != text, bad, stripped, ph, changes, misread)


# a change told as done → the same change as a plan: (past forms, singular future, plural future)
_PAST_TO_FUTURE = [
    (r"вырос(?:ла|ло)?", "вырастет", None), (r"выросли", None, "вырастут"),
    (r"увеличил(?:ся|ась|ось)", "увеличится", None), (r"увеличились", None, "увеличатся"),
    (r"увеличил[аo]?", "увеличит", None), (r"увеличили", None, "увеличат"),
    (r"снизил(?:ся|ась|ось)", "снизится", None), (r"снизились", None, "снизятся"),
    (r"снизил[ао]?", "снизит", None), (r"снизили", None, "снизят"),
    (r"сократил(?:ся|ась|ось)", "сократится", None), (r"сократились", None, "сократятся"),
    (r"сократил[ао]?", "сократит", None), (r"сократили", None, "сократят"),
    (r"уменьшил(?:ся|ась|ось)", "уменьшится", None), (r"уменьшились", None, "уменьшатся"),
    (r"повысил(?:ся|ась|ось)", "повысится", None), (r"повысились", None, "повысятся"),
    (r"повысил[ао]?", "повысит", None), (r"повысили", None, "повысят"),
    (r"удвоил(?:ся|ась|ось)", "удвоится", None), (r"удвоились", None, "удвоятся"),
    (r"достиг(?:ла|ло)?", "достигнет", None), (r"достигли", None, "достигнут"),
    (r"составил[ао]?", "составит", None), (r"составили", None, "составят"),
    (r"упал[ао]?", "упадёт", None), (r"упали", None, "упадут"),
    (r"сэкономил[ао]?", "сэкономит", None), (r"сэкономили", None, "сэкономят"),
    (r"принесл[аио]|принёс|принес", "принесёт", None), (r"стал[ао]?", "станет", None), (r"стали", None, "станут"),
]
_PAST_RES = [(re.compile(rf"(?<![\wё])(?:{rx})(?![\wё])", re.I), s or p) for rx, s, p in _PAST_TO_FUTURE]
PAST_CHANGE_RE = re.compile(r"(?<![\wё])(?:" + "|".join(rx for rx, _, _ in _PAST_TO_FUTURE) + r")(?![\wё])", re.I)


def to_future(text: str) -> str:
    """«Прибыль выросла в 2 раза» → «Прибыль вырастет в 2 раза»: past-tense change verbs as the same change planned."""
    out = text
    for rx, fut in _PAST_RES:
        out = rx.sub(lambda m, fut=fut: (fut[:1].upper() + fut[1:]) if m.group(0)[:1].isupper() else fut, out)
    return out


def _clause_text(t: str, spans: list[tuple[int, int]]) -> str:
    cl = [(a, b) for a, b in _clauses(t) if any(a <= s < b or a < e <= b for s, e in spans)]
    return t[min(a for a, _ in cl) : max(b for _, b in cl)].strip(" .;,") if cl else ""


_TITLE_LINE_RE = re.compile(
    r"^[ \t]*(?:название|заголовок|тема)(?:[ \t]+(?:презентации|доклада|выступления))?[ \t]*[:—–-][ \t]*(?P<t>\S[^\n]*?)[ \t]*$", re.I | re.M
)


def unquote(text: Optional[str]) -> str:
    """«Больше прибыли с каждой чашки». → Больше прибыли с каждой чашки: a title as the user wrote it in quotes."""
    t = (text or "").strip().rstrip(".;").strip()
    pairs = {"«": "»", '"': '"', "“": "”", "„": "“", "'": "'"}
    if len(t) >= 2 and t[0] in pairs and t.endswith(pairs[t[0]]):
        o, c, inner = t[0], pairs[t[0]], t[1:-1]
        depth = 0
        for ch in inner:  # «А» и «Б» is two quotations, not one
            depth += 1 if ch == o and o != c else -1 if ch == c else 0
            if depth < 0:
                break
        if depth == 0:
            t = inner.strip()
    return t


def title_line(text: str) -> Optional[str]:
    """The deck's title the brief states on a line of its own: «Название: «…»», «Заголовок презентации: …»,
    «Тема: …»."""
    m = _TITLE_LINE_RE.search(text or "")
    t = unquote(m.group("t")) if m else ""
    return t if 1 <= len(t.split()) <= 16 else None


def _first_statement_title(first: str) -> Optional[str]:
    if not first:
        return None
    parts = H.label_split(first)
    if parts and parts[1].strip() and 2 <= len(parts[0].split()) <= 12:
        return H.cap_first(H.strip_end(parts[0]))
    return H.cap_first(H.strip_end(first)) if len(first.split()) <= 14 else None


def _compatible(pu: Optional[str], bu: Optional[str]) -> bool:
    return pu == bu or {pu, bu} <= {"pct", "pp"} or (bu is None and pu == "pts")


def _ordinal(text: str, f: Fig) -> bool:
    """«Этап 1», «Неделя 2», «1. …»: the number of a step or of a list line."""
    if f.unit is not None or f.dec or f.value > 20 or f.date is not None:
        return False
    return bool(_ORDINAL_BEFORE_RE.search(text[: f.start])) or (f.start <= 3 and bool(_LIST_NUMBER_RE.match(text)))


_CLAUSE_SEP_RE = re.compile(r"\s*[;,]\s+|\s+[—–-]\s+|:\s+|\s*\(\s*|\s*\)\s*|(?<=[.!?])\s+")


def _drop_clauses(t: str, spans: list[tuple[int, int]], edits: list[tuple[int, int]]) -> tuple[str, list[tuple[int, int]]]:
    """The text without the clauses that hold `spans`; `edits` (spans to cut later) moved to the new text. A sentence
    whose last clause goes keeps its end mark: «Время сократилось, в пилоте 12 000 пользователей. NPS 64» → «Время
    сократилось. NPS 64», not two sentences run together."""
    seps = _seps(t, _CLAUSE_SEP_RE)
    clauses: list[tuple[int, int]] = []
    sep_before: list[Optional[tuple[int, int]]] = []
    pos, last_sep = 0, None
    for a, b in seps:
        clauses.append((pos, a))
        sep_before.append(last_sep)
        last_sep, pos = (a, b), b
    clauses.append((pos, len(t)))
    sep_before.append(last_sep)
    keep = [not any(ca <= sa < cb or ca < sb <= cb or (sa <= ca and cb <= sb) for sa, sb in spans) for ca, cb in clauses]
    out: list[str] = []
    new_edits: list[tuple[int, int]] = []
    first, offset = True, 0
    gap: list[str] = []  # the separators since the last clause kept
    for (ca, cb), sep, k in zip(clauses, sep_before, keep):
        if sep is not None:
            gap.append(t[sep[0] : sep[1]])
        if not k:
            end = re.search(r"[.!?…]+$", t[ca:cb].rstrip())
            if end and out and not re.search(r"[.!?…]\s*$", out[-1]):
                out.append(end.group(0))
                offset += len(end.group(0))
            continue
        if not first and gap:
            s = gap[-1]
            if len(gap) > 1:
                # clauses went between: a new sentence after an end mark («… 23%. Время …», not «23%.; Время»), a
                # comma for a parenthesis whose other half went («NPS 64, время …», not «NPS 64 (время …»)
                if re.search(r"[.!?…]$", out[-1].rstrip()) or (re.search(r"[()]", s) and re.match(r"(?:и|а|но|and)\s", t[ca:cb], re.I)):
                    s = " "
                elif re.search(r"[()]", s):
                    s = ", "
            out.append(s)
            offset += len(s)
        piece_start = offset
        gap = []
        out.append(t[ca:cb])
        for ea, eb in edits:
            if ca <= ea and eb <= cb:
                new_edits.append((piece_start + ea - ca, piece_start + eb - ca))
        offset += cb - ca
        first = False
    return "".join(out), new_edits


# ------------------------------------------------------------------ the report


class _Log:
    def __init__(self) -> None:
        self.bad: list[str] = []
        self.units: list[str] = []
        self.placeholders: list[str] = []
        self.dropped: list[str] = []
        self.lines: list[str] = []
        self.changes: list[str] = []
        self.notes: list[str] = []
        self.misread: list[str] = []

    def take(self, c: _Clean) -> None:
        self.changes.extend(x for x in c.changes if x not in self.changes)
        self.misread.extend(x for x in c.misread if x not in self.misread)
        self.bad.extend(x for x in c.bad if x not in self.bad and x not in c.changes and x not in c.misread)
        self.units.extend(x for x in c.stripped if x not in self.units)
        self.placeholders.extend(x for x in c.placeholders if x not in self.placeholders)

    def report(self) -> list[str]:
        out = []
        if self.bad:
            out.append("grounding: figures and names not in the brief removed: " + ", ".join(f"«{x}»" for x in self.bad[:12]) + (" …" if len(self.bad) > 12 else ""))
        if self.changes:
            out.append("grounding: changes the brief does not state removed: " + ", ".join(f"«{x}»" for x in self.changes[:12]))
        if self.misread:
            out.append("grounding: figures of the brief given another subject removed: " + ", ".join(f"«{x}»" for x in self.misread[:12]))
        if self.units:
            out.append("grounding: units the brief does not give removed: " + ", ".join(f"«{x}»" for x in self.units[:12]))
        if self.placeholders:
            out.append("grounding: placeholders removed: " + ", ".join(f"«{x}»" for x in self.placeholders[:12]))
        out.extend(self.lines)
        if self.dropped:
            out.append("grounding: slides not supported by the brief dropped: " + "; ".join(self.dropped))
        if self.notes:
            out.append("grounding: speaker notes with figures or changes not in the brief dropped: " + "; ".join(f"«{_q(x, 80)}»" for x in self.notes[:8]) + (" …" if len(self.notes) > 8 else ""))
        return out


def _q(text: Optional[str], n: int = 60) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


# ------------------------------------------------------------------ the pass


def _keep_line(idx: BriefIndex, c: _Clean) -> str:
    """A bullet, a paragraph, a card or a caption after cleaning: kept when it says what the brief says — content words
    mostly the brief's; a figure of the brief with its unit and no change claimed (a paraphrase: «Работники экономят
    18 минут в день», «Требуется 14,5 млн ₽ для расширения»); or a figure of the brief with at least a quarter of
    them. What is left after an invented figure's clause went must stand on its own: three content words mostly the
    brief's, or a figure of the brief with half of them."""
    t = c.text.strip()
    if not t:
        return ""
    r = idx.ratio(t)
    if c.bad:
        n = len(content_stems(t))
        if idx.grounded_figure(t) and r is not None and r >= 0.5:
            return t
        return t if (n >= 3 and r is not None and r >= 0.5) else ""
    if r is None or r >= 0.5:
        return t
    if idx.unit_figure(t) and not _CHANGE_RE.search(t):
        return t
    # a bare figure of the brief grounds a line that also speaks the brief's words: «Внедрение в 3 департаментах» is
    # not grounded by a «3» the brief uses for something else
    if r >= 0.25 and idx.grounded_figure(t):
        return t
    return ""


def _item_text(it: SlideItem) -> str:
    return " ".join(x for x in [it.title, it.text, it.number or "", " ".join(it.bullets)] if x)


def _ground_item(idx: BriefIndex, it: SlideItem, log: _Log, *, judge: bool = True) -> Optional[SlideItem]:
    title, text = idx.clean(it.title), idx.clean(it.text)
    number = idx.clean(it.number) if it.number else None
    bullets = [idx.clean(b) for b in it.bullets]
    for c in [title, text] + bullets + ([number] if number else []):
        log.take(c)
    it.title = title.text
    it.text = _keep_line(idx, text) if (text.bad and judge) else text.text
    it.number = number.text if number is not None and number.text and not number.bad else None
    it.bullets = [x for x in (_keep_line(idx, b) if judge else b.text for b in bullets) if x]
    if not (it.title or it.text or it.bullets or it.number):
        return None
    if title.bad and not it.text and not it.bullets:
        return None  # «Охват: 12 000 пользователей» without its figure says nothing
    if judge:
        whole = _Clean(_item_text(it), bad=title.bad + text.bad)
        if not _keep_line(idx, whole):
            return None
        if not (it.text or it.bullets or it.number) and (text.bad or any(b.bad for b in bullets)):
            return None  # only the title is left of a card whose text was invented
    return it


def _ground_number(idx: BriefIndex, n: NumberCallout, log: _Log) -> Optional[NumberCallout]:
    value = (n.value or "").strip()
    label = n.label or ""
    if not value:
        return None
    joined = f"{value} {label}"
    figs = [f for f in figures(joined) if f.start < len(value)]
    if not figs and not name_tokens(value):
        c = idx.clean(label)
        log.take(c)
        n.label = c.text
        return n  # a value without digits («да», «×2»): as it is
    all_figs = [x for x in figures(joined) if not _ordinal(joined, x)]
    for f in figs:
        v = idx.verdict(f)
        if v == "bad":
            log.bad.append(joined[f.start : f.uend].strip())
            return None
        if v == "ok" and label.strip() and f.date is None and not _is_year(f) and not f.approx:
            literal = [p for p in idx._same(f) if f.unit is None or p.fig.unit is None or _compatible(f.unit, p.fig.unit)]
            change = _change_context(joined, f) and _prep(joined, f) != "to"
            if literal and not idx.bound(joined, f, all_figs) and not (change and idx._derived_ok(f)):
                # «315 000 ₽ — Зарплаты» when the brief's 315 000 is «продукты»
                log.misread.append(joined.strip())
                return None
        if v == "strip":
            log.units.append(joined[f.start : f.uend].strip())
            value, label = _cut(value, label, f.end, f.uend)
    for a, b, tok in name_tokens(value):
        if not idx.token_ok(tok):
            log.bad.append(tok)
            return None
    c = idx.clean(label)
    log.take(c)
    n.value, n.label = value, c.text
    return n


def _cut(value: str, label: str, a: int, b: int) -> tuple[str, str]:
    """`value` and `label` without joined[a:b] of joined = value + " " + label (a unit may stand in either)."""
    n = len(value)
    value = value[: min(a, n)] + value[min(b, n) :]
    la, lb = max(a - n - 1, 0), max(b - n - 1, 0)
    return value.strip(), (label[:la] + label[lb:]).strip()


def _figures_on(s: OutlineSlide) -> set[float]:
    """The values a slide shows (as written, unit aside)."""
    c = s.content
    texts = [s.headline, s.subtitle or ""] + c.bullets + c.paragraphs + [_item_text(i) for i in c.items + c.columns]
    vals = {f.value for t in texts for f in figures(t)}
    for n in c.numbers:
        vals.update(f.value for f in figures(n.value))
    if c.table is not None:
        vals.update(f.value for row in c.table.rows for cell in row for f in figures(cell))
    return vals


def _number_values(s: OutlineSlide) -> set[float]:
    return {f.value for n in s.content.numbers for f in figures(n.value)}


def _fact_number(f: Fact) -> NumberCallout:
    value = f.value.strip()
    unit = (f.unit or "").strip()
    if unit and not value.endswith(unit) and unit.lower() not in value.lower():
        value = f"{value}{unit}" if unit == "%" else f"{value} {unit}"
    return NumberCallout(value=value, label=f.label, fact_id=f.id)


def ground_facts(facts: list[Fact], idx: BriefIndex, log: Optional[_Log] = None) -> list[Fact]:
    """The facts registry without figures the brief does not have; a unit the brief does not give a figure is taken
    off («64» of «NPS 64» is not «64 %»)."""
    log = log or _Log()
    out = []
    for f in facts:
        joined = f"{f.value} {f.unit or ''}".strip()
        figs = figures(joined)
        if not figs:
            out.append(f)
            continue
        verdicts = [idx.verdict(x) for x in figs]
        if "bad" in verdicts:
            log.lines.append(f"grounding: fact {f.id} «{_q(joined)}» dropped (not in the brief)")
            continue
        if "strip" in verdicts:
            cleaned = idx.clean(joined).text
            vfig = figures(f.value)
            if vfig and idx.verdict(vfig[0]) == "strip":
                f.value = f.value[: vfig[0].end].strip()
            if f.unit and idx.clean(f"{f.value} {f.unit}").text != f"{f.value} {f.unit}":
                f.unit = None
            log.lines.append(f"grounding: fact {f.id} «{_q(joined)}» → «{_q(cleaned)}» (the brief gives no such unit)")
        out.append(f)
    return out


def grounded_facts(facts: list[Fact], brief: Union[Brief, str]) -> tuple[list[Fact], list[str]]:
    """ground_facts for the facts registry of a brief, with what it changed as warning lines."""
    log = _Log()
    out = ground_facts(facts, BriefIndex.of(brief), log)
    return out, log.report()


def unit_scale(unit: Optional[str]) -> float:
    """What one of a chart's values is worth by its unit: «тыс. ₽» — a thousand, «млн руб.» — a million."""
    u = (unit or "").lower()
    for word, k in (("трлн", 1e12), ("млрд", 1e9), ("миллиард", 1e9), ("млн", 1e6), ("миллион", 1e6), ("тыс", 1e3)):
        if re.search(rf"(?<![а-яё]){word}", u):
            return k
    return 1.0


def rounding_step(rule: Optional[str]) -> Optional[float]:
    """The step the brief lets chart values be rounded to («можно округлять до тысяч рублей» → 1000), or None."""
    r = (rule or "").lower()
    if not r or "округл" not in r and "до тысяч" not in r:
        return None
    for rx, step in ((r"миллион|млн", 1e6), (r"тысяч|тыс\.", 1e3), (r"сот(?:ен|ни)", 100.0), (r"десятк|десятков", 10.0)):
        if re.search(rx, r):
            return step
    return None


def _num_text(v: float) -> str:
    v = round(float(v), 6)
    return str(int(v)) if v.is_integer() else f"{v:.6f}".rstrip("0").rstrip(".")


def value_ok(idx: BriefIndex, v: float, scale: float = 1.0, step: Optional[float] = None) -> bool:
    """A chart's value is a figure of the brief (in the chart's unit: `scale` 1000 for «тыс. ₽»), or — when the brief
    allows rounding to `step` — the brief's figure rounded to it (half up; either neighbour of a figure exactly between
    two: 1 138 500 → 1 139 000 or 1 138 000)."""
    full = round(float(v) * scale, 6)
    for x in dict.fromkeys((full, round(float(v), 6))):  # a value written in full under a «тыс.» unit is read as it is
        figs = figures(_num_text(x))
        if figs and idx.verdict(figs[0]) != "bad":
            return True
    if not step or not full or abs(full) < step or not _eq(round(full / step) * step, full):
        return False
    for p in idx.placed:
        b = p.fig
        if b.date is not None or p.ordinal or _is_year(b) or abs(b.mag) < step:
            continue
        q = Decimal(repr(abs(b.mag))) / Decimal(repr(step))
        near = float(q.quantize(Decimal(1), rounding=ROUND_HALF_UP)) * step
        low = float(q.to_integral_value(rounding=ROUND_FLOOR)) * step
        sign = -1.0 if b.mag < 0 else 1.0
        if _eq(sign * near, full) or (q - q.to_integral_value(rounding=ROUND_FLOOR) == Decimal("0.5") and _eq(sign * low, full)):
            return True
    return False


def _series_ok(s: Series, idx: BriefIndex, step: Optional[float] = None) -> bool:
    scale = unit_scale(s.unit)
    return bool(s.values) and all(v is not None and value_ok(idx, v, scale, step) for v in s.values)


def inline_ok(chart: ChartSpec, idx: BriefIndex, step: Optional[float] = None) -> bool:
    """The data written into a chart (Agent v2) is the brief's: every value of every series."""
    scale = unit_scale(chart.unit)
    vals = [v for ser in chart.series for v in ser.values]
    return bool(vals) and all(v is not None and value_ok(idx, v, scale, step) for v in vals)


def _headline_from(idx: BriefIndex, s: OutlineSlide) -> str:
    """A heading for a slide whose own heading was not grounded: its section, else its first line, card or figure."""
    c = s.content
    cands = []
    if s.section:
        cands.append(s.section)
    cands += c.bullets[:1] + c.paragraphs[:1]
    cands += [i.title for i in c.items[:1] + c.columns[:1] if i.title]
    cands += [H.cap_first(n.label) for n in c.numbers[:1] if n.label]
    for x in cands:
        cl = idx.clean(x)
        if cl.text and not cl.bad and not cl.placeholders and ((idx.ratio(cl.text) or 0) >= 0.5 or idx.grounded_figure(cl.text)):
            return H.cap_first(H.short(cl.text, 12))
    return ""


def _ground_headline(idx: BriefIndex, s: OutlineSlide, log: _Log, notes: Optional[list[str]] = None, fallback: Optional[str] = None) -> bool:
    """False when the heading had to go and nothing grounded replaces it. The change is said in `notes` (the caller
    reports it once the slide is kept), or in the log. A slide the user asked for keeps the model's wording of what is
    left of its heading, else takes `fallback` (the title the user gave that slide)."""
    c = idx.clean(s.headline)
    log.take(c)
    old = s.headline
    ok = c.text and not c.bad and not c.placeholders
    lenient = s.spec_ref is not None
    if c.bad:
        rest = c.text
        if rest and len(rest.split()) >= 3 and (lenient or (idx.ratio(rest) or 0) >= 0.5):
            s.headline = H.cap_first(rest)
            ok = True
        elif lenient and fallback:
            s.headline = fallback
            ok = True
    elif c.placeholders and c.text:
        s.headline = c.text
        ok = True
    elif ok:
        s.headline = c.text
    if not ok:
        new = _headline_from(idx, s)
        if not new:
            return False
        s.headline = new
    if s.headline != old and (c.bad or c.placeholders or not old.strip()):
        line = f"grounding: slide {s.id}: heading «{_q(old)}» → «{_q(s.headline)}»"
        (notes if notes is not None else log.lines).append(line)
    return True


def _ground_label(idx: BriefIndex, text: Optional[str], log: _Log) -> Optional[str]:
    """A section label («Результаты пилота»), a quotation's author: shown on the slide as they are, so the brief's
    words and figures only — «Детали», «План или сроки», «Фаза 2: 50% сотрудников» go whole."""
    if not text or not text.strip():
        return text
    c = idx.clean(text)
    log.take(c)
    r = idx.ratio(c.text) if c.text else None
    if c.bad or c.placeholders or not c.text or (r is not None and r < 0.5):
        return None
    return c.text


def _ground_section(idx: BriefIndex, s: OutlineSlide, log: _Log) -> None:
    if not s.section:
        return
    old = s.section
    s.section = _ground_label(idx, s.section, log)
    if s.section is None:
        log.lines.append(f"grounding: slide {s.id}: section label «{_q(old)}» removed (not the brief's)")


def _as_lines(s: OutlineSlide, lines: list[str]) -> None:
    """A slide of cards or columns with one left: its lines (with its figures, when it has any)."""
    lines = [x for x in lines if x]
    s.content.items, s.content.columns = [], []
    s.content.bullets, s.content.paragraphs = (lines, []) if len(lines) >= 2 else ([], lines)
    s.kind = K.bullets if len(lines) >= 2 or not s.content.numbers else (K.big_number if len(s.content.numbers) == 1 else K.stat_row)


def _model_line(idx: BriefIndex, c: _Clean) -> str:
    """A line the model wrote on a slide the user asked for (or a takeaway, a footnote): kept in the model's words,
    only the clauses of invented figures, names and changes (and placeholders) gone — and what is left of such a line
    must still say something (three content words), not «Окупаемость вложений» of «Окупаемость вложений — 2 месяца»."""
    t = c.text.strip()
    if not t:
        return ""
    if c.bad and len(content_stems(t, neutral=True)) < 3:
        return ""
    return t


def _line(idx: BriefIndex, c: _Clean, lenient: bool) -> str:
    return _model_line(idx, c) if lenient else _keep_line(idx, c)


def _body(c: SlideContent) -> bool:
    """The slide shows something besides its heading (a formula and a second chart count)."""
    return has_body(c.model_dump()) or bool((c.formula or "").strip()) or c.chart2 is not None


def _kind_for(c: SlideContent) -> K:
    """The kind of what is left on a slide the user asked for: by its content; a formula alone is shown large."""
    if has_body(c.model_dump()):
        return K(kind_by_content(c.model_dump()))
    return K.big_number if (c.formula or "").strip() else K.bullets


def _chart_data(idx: BriefIndex, chart: ChartSpec, series_ids: set[str], step: Optional[float], log: _Log, s: OutlineSlide, which: str, lenient: bool) -> Optional[ChartSpec]:
    """The chart with the brief's data only: the data written into it goes when a value is not the brief's (rounded
    to `step` when the brief allows it); its ids name only registry series left after grounding. None when no data
    is left."""
    if chart.series and not inline_ok(chart, idx, step):
        scale = unit_scale(chart.unit)
        bad = [_num_text(v) for ser in chart.series for v in ser.values if v is None or not value_ok(idx, v, scale, step)]
        log.lines.append(f"grounding: slide {s.id}: {which} data not in the brief removed: " + ", ".join(f"«{x}»" for x in bad[:8]))
        chart.categories, chart.series = [], []
    ids = [x for x in chart.series_ids if x in series_ids]
    if not ids and not chart.series:
        return None
    chart.series_ids = ids
    if chart.title:
        chart.title = _line(idx, _take(idx.clean(chart.title), log), lenient) or None
    return chart


_OP_RE = re.compile(r"\s*([×x*хX·+\-−–÷/:=])\s*")


def formula_arithmetic_ok(text: Optional[str]) -> bool:
    """Whether a formula's sides agree («100 × 300 × 30 = 900 000» yes; «115 × 300 × 30 = 900 000» no): the figures
    and the operators between them (×, ·, *, +, −, ÷, /) on each side of «=», computed left to right with × and ÷
    first; a difference of 0,5% (a rounded result) is fine. A formula of words («Выручка = покупки × чек × дни»), or
    one without «=», is not a calculation to check."""
    t = " ".join((text or "").split())
    if "=" not in t:
        return True
    figs = [f for f in figures(t) if f.date is None]
    if len(figs) < 2:
        return True
    tokens: list = []
    pos = 0
    for f in figs:
        between = t[pos : f.start]
        ops = [m.group(1) for m in _OP_RE.finditer(between)]
        if tokens and ops:
            tokens.append(ops[-1] if ops[-1] != "=" or "=" not in ops else "=")
            if "=" in ops:
                tokens[-1] = "="
        elif tokens and not ops:
            return True  # two figures without an operator: not a formula this check reads
        tokens.append(f.mag if f.scale != 1.0 else f.value)
        pos = f.end  # «115 ×» reads as a multiple: the operator is what follows the number
    if "=" not in tokens:
        return True

    def value(side: list) -> Optional[float]:
        if not side or not isinstance(side[0], float):
            return None
        terms: list[float] = []
        signs: list[str] = []
        cur = side[0]
        i = 1
        while i + 1 < len(side):
            op, x = side[i], side[i + 1]
            if not isinstance(x, float):
                return None
            if op in "×x*хX·":
                cur *= x
            elif op in "÷/:":
                if not x:
                    return None
                cur /= x
            elif op in "+-−–":
                terms.append(cur)
                signs.append(op)
                cur = x
            else:
                return None
            i += 2
        terms.append(cur)
        total = terms[0]
        for op, x in zip(signs, terms[1:]):
            total = total + x if op == "+" else total - x
        return total

    k = tokens.index("=")
    left, right = value(tokens[:k]), value(tokens[k + 1 :])
    if left is None or right is None:
        return True
    return abs(left - right) <= 0.005 * max(abs(left), abs(right), 1.0)


def _ground_formula(idx: BriefIndex, text: Optional[str], log: _Log, s: OutlineSlide) -> Optional[str]:
    """A formula («100 × 300 × 30 = 900 000 рублей») shows every operand as the brief has it, or goes whole: a
    formula with one invented figure is a wrong calculation. An operand may carry a unit the brief writes apart from
    it («30 дней» of «30 рабочих дней»), never a percent it does not have. Its sides must agree: «115 × 300 × 30 =
    900 000» of the brief's figures is a wrong calculation too."""
    t = " ".join((text or "").split())
    if not t:
        return None
    if not formula_arithmetic_ok(t):
        log.lines.append(f"grounding: slide {s.id}: formula «{_q(t, 80)}» removed (its sides do not agree)")
        return None
    for f in figures(t):
        if idx.verdict(f) != "bad":
            continue
        bare = figures(t[f.start : f.end])
        if f.unit not in ("pct", "pp") and bare and idx.verdict(bare[0]) != "bad":
            continue
        log.bad.append(t[f.start : f.uend].strip())
        log.lines.append(f"grounding: slide {s.id}: formula «{_q(t, 80)}» removed (a figure not in the brief)")
        return None
    for _, _, tok in name_tokens(t):
        if not idx.token_ok(tok):
            log.bad.append(tok)
            log.lines.append(f"grounding: slide {s.id}: formula «{_q(t, 80)}» removed (a name not in the brief)")
            return None
    return t


def _ground_side(idx: BriefIndex, text: Optional[str], log: _Log) -> Optional[str]:
    """A takeaway or a footnote: the model's (or the user's) words, without invented figures and placeholders."""
    if not text or not text.strip():
        return None
    c = idx.clean(text)
    log.take(c)
    return _model_line(idx, c) or None


def _ground_content_slide(idx: BriefIndex, s: OutlineSlide, log: _Log, series_ids: set[str], facts: dict[str, Fact], from_chart: set[int], thinned: set[int], step: Optional[float] = None, fallback: Optional[str] = None) -> Optional[OutlineSlide]:
    """A content slide with only what the brief says. A slide the user asked for (`spec_ref`) is `lenient`: its lines
    are the model's wording and stay unless an invented figure took their substance; it is never dropped — whatever
    is left of it keeps a kind its content supports (`fallback`: the heading the user gave it)."""
    c = s.content
    lenient = s.spec_ref is not None
    # subtitle
    if s.subtitle:
        sc = idx.clean(s.subtitle)
        log.take(sc)
        s.subtitle = _line(idx, sc, lenient) or None
    # lines
    units = len(c.bullets) + len(c.paragraphs) + len(c.items) + sum(len(col.bullets) + bool(col.text) for col in c.columns)
    c.bullets = [x for x in (_line(idx, _take(idx.clean(b), log), lenient) for b in c.bullets) if x]
    c.paragraphs = [x for x in (_line(idx, _take(idx.clean(p), log), lenient) for p in c.paragraphs) if x]
    # items and columns
    c.items = [x for x in (_ground_item(idx, it, log, judge=not lenient) for it in c.items) if x is not None]
    cols = []
    for col in c.columns:
        t = idx.clean(col.title)
        log.take(t)
        col.title = t.text if not t.bad else ""
        col.bullets = [x for x in (_line(idx, _take(idx.clean(b), log), lenient) for b in col.bullets) if x]
        if col.text:
            col.text = _line(idx, _take(idx.clean(col.text), log), lenient)
        if col.bullets or col.text:
            cols.append(col)
    c.columns = cols
    left = len(c.bullets) + len(c.paragraphs) + len(c.items) + sum(len(col.bullets) + bool(col.text) for col in c.columns)
    # figures
    c.numbers = [x for x in (_ground_number(idx, n, log) for n in c.numbers) if x is not None]
    # table
    if c.table is not None:
        tbl = c.table
        head = [idx.clean(x) for x in tbl.columns]
        for h in head:
            log.take(h)
        tbl.columns = [h.text for h in head]
        if tbl.caption:
            tbl.caption = _line(idx, _take(idx.clean(tbl.caption), log), lenient) or None
        rows = []
        for row in tbl.rows:
            cells = [idx.clean(x) for x in row]
            for x in cells:
                log.take(x)
            if any(x.bad for x in cells):
                continue
            joined = " ".join(x.text for x in cells)
            r = idx.ratio(joined)
            if not lenient and r is not None and r < 0.5 and not idx.grounded_figure(joined):
                continue  # a row of words the brief does not have
            rows.append([x.text for x in cells])
        units += len(tbl.rows)
        left += len(rows)
        tbl.rows = rows
        if not rows:
            c.table = None
    # quote: only the brief's own words, and its author the brief's
    if c.quote:
        q = idx.clean(c.quote)
        log.take(q)
        if q.bad or (idx.ratio(q.text) or 0) < 0.8:
            c.quote, c.quote_author = None, None
        else:
            c.quote_author = _ground_label(idx, c.quote_author, log)
    # a formula, a takeaway, a footnote
    if c.formula:
        c.formula = _ground_formula(idx, c.formula, log, s)
    s.takeaway = _ground_side(idx, s.takeaway, log)
    s.footnote = _ground_side(idx, s.footnote, log)
    # charts: every value the brief's; a second chart without data goes, and takes the place of a first one without
    if c.chart2 is not None:
        c.chart2 = _chart_data(idx, c.chart2, series_ids, step, log, s, "second chart", lenient)
    if c.chart is not None:
        ch = _chart_data(idx, c.chart, series_ids, step, log, s, "chart", lenient)
        if ch is None and c.chart2 is not None:
            ch, c.chart2 = c.chart2, None
            log.lines.append(f"grounding: slide {s.id}: the second chart takes the place of a chart without data")
        if ch is not None:
            c.chart = ch
        else:
            refs = [x for x in list(c.chart.series_ids) + list(s.fact_refs) if x in facts]
            nums = list(c.numbers)
            for fid in dict.fromkeys(refs):
                n = _ground_number(idx, _fact_number(facts[fid]), _Log())
                shown = {f.value for x in nums for f in figures(x.value)}
                if n is not None and not any(_eq(f.value, v) for f in figures(n.value) for v in shown):
                    nums.append(n)
            c.chart = None
            c.numbers = nums
            if nums:
                s.kind = K.stat_row if len(nums) >= 2 else K.big_number
                if not lenient:
                    from_chart.add(id(s))
            elif lenient:
                log.lines.append(f"grounding: slide {s.id} «{_q(s.headline)}»: chart without data removed (the slide the brief asks for stays)")
                s.kind = _kind_for(c)
            else:
                log.dropped.append(f"{s.id} «{_q(s.headline or s.section)}» (chart without data)")
                return None
    elif c.chart2 is not None:
        c.chart, c.chart2 = c.chart2, None
    # the kind the content now supports
    lines = c.bullets + c.paragraphs
    k = s.kind
    gone: Optional[str] = None  # why a slide nobody asked for goes
    if k in (K.stat_row, K.big_number):
        if not c.numbers:
            if not lines:
                gone = "no figure of the brief left"
            else:
                s.kind = K.bullets
        else:
            s.kind = K.big_number if len(c.numbers) == 1 else K.stat_row
    elif k in (K.cards, K.process, K.timeline, K.team):
        if len(c.items) >= 2:
            pass
        elif len(c.items) == 1:
            it = c.items[0]
            line = f"{it.title}: {it.text}" if it.title and it.text else (it.title or it.text)
            _as_lines(s, lines + [H.strip_end(line)] + it.bullets)
        elif lines or c.numbers:
            s.kind = K(kind_by_content(c.model_dump()))
        else:
            gone = ""
    elif k in (K.two_column, K.comparison):
        if not c.columns and len([i for i in c.items if i.text or i.bullets]) >= 2:
            c.columns, c.items = [i for i in c.items if i.text or i.bullets], []
        elif not c.columns:
            c.items = []
        if len(c.columns) >= 2:
            pass
        elif len(c.columns) == 1:
            col = c.columns[0]
            _as_lines(s, lines + col.bullets + ([col.text] if col.text else []))
        elif lines or c.numbers or c.items:
            s.kind = K(kind_by_content(c.model_dump()))
        else:
            gone = "empty columns"
    elif k == K.table:
        if c.table is None:
            if lines or c.numbers:
                s.kind = K(kind_by_content(c.model_dump()))
            else:
                gone = "no row of the brief left"
    elif k == K.chart and c.chart is None:
        if _body(c):
            s.kind = _kind_for(c)
        else:
            gone = "chart without data"
    elif k == K.quote:
        if not c.quote:
            if lines:
                s.kind = K.bullets
            else:
                gone = "a quotation the brief does not have"
    elif k in (K.bullets, K.image_text):
        if not (lines or c.numbers or c.items or c.columns or c.table or c.chart):
            gone = ""
        elif len(lines) <= 1 and (c.numbers or c.items or c.columns or c.table or c.chart):
            s.kind = K(kind_by_content(c.model_dump()))  # one line and a figure: the figure's slide, the line under it
    if gone is not None:
        if not lenient and not c.formula:
            log.dropped.append(f"{s.id} «{_q(s.headline or s.section)}»" + (f" ({gone})" if gone else ""))
            return None
        s.kind = _kind_for(c)
    # the heading
    said: list[str] = []
    if not _ground_headline(idx, s, log, said, fallback):
        if not lenient:
            log.dropped.append(f"{s.id} «{_q(s.section)}» (no grounded heading)")
            return None
        s.headline = H.cap_first(idx.clean(s.headline).text) or fallback or ""
    # the slide as a whole: invented when its words are mostly not the brief's, or when most of its lines were not
    # the brief's («Рекомендации по действию»: one of three lines survives), and no figure of the brief is left on it —
    # never a slide the user asked for (its wording is the model's by design)
    if lenient:
        log.lines.extend(said)
        return s
    body = " ".join([s.headline, s.subtitle or ""] + s.content.bullets + s.content.paragraphs + [_item_text(i) for i in s.content.items + s.content.columns])
    has_fig = bool(s.content.numbers or s.content.chart or s.content.table or s.content.formula) or idx.grounded_figure(body)
    r = idx.ratio(body)
    if not has_fig and ((r is not None and r < 0.34) or (units >= 2 and left * 2 < units)):
        log.dropped.append(f"{s.id} «{_q(s.headline or s.section)}»")
        return None
    if units >= 2 and left * 2 < units:
        thinned.add(id(s))  # most of its lines were not the brief's: it stays only if it says a figure no other slide does
    log.lines.extend(said)
    return s


def _take(c: _Clean, log: _Log) -> _Clean:
    log.take(c)
    return c


def _notes(idx: BriefIndex, notes: str, log: _Log) -> str:
    """Speaker notes without placeholders and without a sentence with a figure or a change the brief does not have."""
    if not notes:
        return notes
    out = []
    for sn in re.split(r"(?<=[.!?])\s+", notes):
        c = idx.clean(sn)
        if c.placeholders:
            log.take(_Clean("", placeholders=c.placeholders))
        if c.bad:
            log.notes.append(sn.strip())
            # only the clause of the figure the brief does not have goes: the rest of a sentence of right figures stays
            # when it still says something
            rest = c.text.strip()
            if rest and len(content_stems(rest, neutral=True)) >= 4 and not idx.clean(rest).bad:
                out.append(rest if rest.endswith((".", "!", "?")) else rest + ".")
            continue
        if c.text:
            out.append(c.text)
    return " ".join(out)


def _slide_words(s: OutlineSlide) -> str:
    c = s.content
    return " ".join([s.headline, s.section or "", s.subtitle or ""] + c.bullets + c.paragraphs + [_item_text(i) for i in c.items + c.columns] + [n.label for n in c.numbers])


def ground_outline(outline: DeckOutline, brief: Union[Brief, str], index: Optional[BriefIndex] = None, structure: Optional[BriefStructure] = None) -> tuple[DeckOutline, list[str]]:
    """The plan with only what the brief says, and what was changed (warning lines). See the module docstring.
    `structure` (Agent v2, the analyst's reading of the brief) gives the rounding the brief allows for chart values
    and the titles of the slides the user asked for (a heading left without anything grounded takes its slide's)."""
    idx = index or BriefIndex.of(brief)
    if structure is not None:
        idx.use_structure(structure)
    o = outline.model_copy(deep=True)
    log = _Log()
    step = rounding_step(structure.rounding) if structure is not None else None
    if structure is not None:
        _ground_series_labels(o, idx, structure, log)
    spec_titles = {sp.number: unquote(sp.title) for sp in structure.specs if sp.title} if structure is not None else {}
    o.facts = ground_facts(o.facts, idx, log)
    before = [x.id for x in o.series]
    o.series = [x for x in o.series if _series_ok(x, idx, step)]
    if len(o.series) != len(before):
        log.lines.append("grounding: series not in the brief dropped: " + ", ".join(x for x in before if x not in {y.id for y in o.series}))
    facts = {f.id: f for f in o.facts}
    series_ids = {x.id for x in o.series}
    # the deck's title: the brief's title line or first statement
    tc = idx.clean(o.title)
    title_ok = tc.text == (o.title or "").strip() and o.title and not tc.bad and not tc.placeholders
    if title_ok and idx.title:
        stems = content_stems(o.title, neutral=True)
        title_ok = not stems or sum(idx.title_stems.has(x) for x in stems) / len(stems) >= 0.6
        # the brief's own words: a title it writes (its first line «Кофейня «Точка кофе»: план …»), the one the analyst
        # read from it («Название: …»)
        named = unquote(structure.title) if structure is not None and structure.title else None
        title_ok = title_ok or idx.written(o.title) or (named is not None and o.title.strip() == named)
    if not title_ok and idx.title:
        log.lines.append(f"grounding: deck title «{_q(o.title)}» → «{_q(idx.title)}» (the brief's own title)")
        o.title = idx.title
    fx = idx.frame  # the title slide and the deck's subtitle may name the audience
    if o.subtitle:
        sc = fx.clean(o.subtitle)
        log.take(sc)
        o.subtitle = _keep_line(fx, sc) or None
    n = len(o.slides)
    kept: list[OutlineSlide] = []
    from_chart: set[int] = set()
    thinned: set[int] = set()
    for i, s in enumerate(o.slides):
        s.notes = _notes(idx, s.notes, log)
        position = "first" if i == 0 else "last" if i == n - 1 else "middle"
        if s.kind.value not in ALLOWED_KINDS or ((s.kind == K.section or (s.kind == K.title and i > 0)) and has_body(s.content.model_dump())):
            new = kind_by_content(s.content.model_dump(), position)
            log.lines.append(f"grounding: slide {s.id}: kind {s.kind.value} → {new}")
            if s.kind == K.section and not s.section:
                s.section = s.headline  # the divider's name, checked below like every section label
            s.kind = K(new)
        if s.kind == K.title:
            c = fx.clean(s.headline)
            log.take(c)
            r = fx.ratio(c.text)
            if c.bad or c.placeholders or not c.text or (r is not None and r < 0.5):
                if s.headline != o.title:
                    log.lines.append(f"grounding: title slide heading «{_q(s.headline)}» → «{_q(o.title)}»")
                s.headline = o.title
            else:
                s.headline = c.text  # a unit the brief does not give taken off, if any
            if s.subtitle:
                sc = fx.clean(s.subtitle)
                log.take(sc)
                s.subtitle = _keep_line(fx, sc) or None
            s.takeaway = _ground_side(fx, s.takeaway, log)
            s.footnote = _ground_side(fx, s.footnote, log)  # «Все исходные данные и прогнозы условные»
            kept.append(s)
            continue
        if s.kind == K.thanks:
            c = idx.clean(s.headline)
            log.take(c)
            s.headline = c.text if c.text and not c.bad and not c.placeholders else "Спасибо за внимание"
            if s.subtitle:
                old = s.subtitle
                sc = idx.clean(s.subtitle)
                log.take(sc)
                stems = content_stems(sc.text, neutral=True)
                ok = sc.text and not sc.bad and all(idx.stems.has(x) or x.startswith(_THANKS_FRAME) for x in stems)
                s.subtitle = sc.text if ok else None
                if s.subtitle != old:
                    log.lines.append(f"grounding: closing slide subtitle «{_q(old)}» → {('«' + _q(s.subtitle) + '»') if s.subtitle else 'none'}")
            s.content.bullets = [x for x in (_keep_line(idx, _take(idx.clean(b), log)) for b in s.content.bullets) if x]
            s.content.paragraphs = [x for x in (_keep_line(idx, _take(idx.clean(b), log)) for b in s.content.paragraphs) if x]
            s.takeaway = _ground_side(idx, s.takeaway, log)
            s.footnote = _ground_side(idx, s.footnote, log)
            kept.append(s)
            continue
        if s.kind == K.section:
            if not _ground_headline(idx, s, log, fallback=spec_titles.get(s.spec_ref) if s.spec_ref is not None else None):
                if s.spec_ref is None:
                    log.dropped.append(f"{s.id} (divider without a grounded name)")
                    continue
                s.headline = spec_titles.get(s.spec_ref) or H.cap_first(idx.clean(s.headline).text)
            s.takeaway = _ground_side(idx, s.takeaway, log)
            s.footnote = _ground_side(idx, s.footnote, log)
            kept.append(s)
            continue
        if s.kind == K.agenda:
            items = []
            for it in s.content.items:
                c = idx.clean(it.title)
                log.take(c)
                if c.text and not c.bad:
                    it.title = c.text
                    items.append(it)
            s.content.items = items
            c = idx.clean(s.headline)
            log.take(c)
            s.headline = c.text if c.text and not c.bad else "О чём поговорим"
            kept.append(s)
            continue
        g = _ground_content_slide(idx, s, log, series_ids, facts, from_chart, thinned, step, spec_titles.get(s.spec_ref) if s.spec_ref is not None else None)
        if g is not None:
            kept.append(g)
    kept = _dedupe_figures(kept, idx, log, from_chart, thinned)
    # a section label is shown on its slide (a kicker, a tag): the brief's words only, checked after the headings
    # (a divider's name copied into it included) and before the agenda is matched against the deck's words
    for s in kept:
        _ground_section(idx, s, log)
    kept = _prune_frames(kept, idx, log)
    ids = {f.id for f in o.facts}
    for s in kept:
        s.fact_refs = [x for x in s.fact_refs if x in ids]
        for nc in s.content.numbers:
            if nc.fact_id and nc.fact_id not in ids:
                nc.fact_id = None
    o.slides = kept
    return o, log.report()


_NEUTRAL_CATEGORY_RE = re.compile(
    r"^(?:сейчас|цель|целев\w*|прогноз\w*|план\w*|текущ\w*|нынешн\w*|было|стало|до|после|факт|итого|всего|остальное|прочее|"
    r"\d{1,2}\s*-?\s*(?:й|ый|ой|ий)?\s*(?:месяц|квартал|недел[яи]|год)|(?:месяц|квартал|неделя)\s+\d{1,2}|now|target|before|after|forecast)$",
    re.I,
)


def _category_ok(idx: BriefIndex, cat: str) -> bool:
    """A chart's category is the brief's words, the analyst's category, or a neutral label («Сейчас», «Цель», «Прогноз»,
    «3-й месяц») — never an invented year, city or name («2027 год», «2028 год (Москва)»)."""
    c = " ".join((cat or "").split())
    if not c:
        return False
    if c.lower() in idx.categories or _NEUTRAL_CATEGORY_RE.match(c):
        return True
    cl = idx.clean(c)
    if cl.bad or cl.placeholders:
        return False
    r = idx.ratio(c)
    return r is None or r >= 0.5


def _ground_series_labels(o: DeckOutline, idx: BriefIndex, structure: BriefStructure, log: _Log) -> None:
    """The series the slides draw carry the brief's labels: invented categories («2027 год», «Москва») take the
    brief's series' of the same values, or the series goes; the brief's values under other labels than the brief's
    («Продукты» at 270 000 when the brief's «Продукты» is 315 000) take the brief's series."""
    try:
        from verstka.planning.agent import _similar_data, chart_of, label_conflicts
    except Exception:  # noqa: BLE001 - the agent's helpers: without them the values are still checked
        return
    brief_series = [s for s in structure.series if s.values and len(s.values) == len(s.categories)]
    own = {id(s) for s in brief_series}
    keep = []
    for s in o.series:
        if id(s) in own or any(s.id == b.id and s.values == b.values and s.categories == b.categories for b in brief_series):
            keep.append(s)
            continue
        probe = ChartSpec(type="column", unit=s.unit, categories=list(s.categories), series=[{"name": s.name, "values": list(s.values)}])
        match = None
        for b in brief_series:
            want = chart_of([b])
            if want is not None and _similar_data(want, probe):
                match = (b, label_conflicts(want, probe))
                break
        bad_cats = [c for c in s.categories if not _category_ok(idx, c)]
        if match is not None and (match[1] or bad_cats):
            b = match[0]
            why = f"labels not the brief's ({', '.join(bad_cats[:3])})" if bad_cats else f"values under other labels than the brief's ({', '.join(match[1][:3])})"
            log.lines.append(f"grounding: series {s.id}: {why} → the brief's series «{_q(b.name, 40)}»")
            s.categories, s.values, s.unit = list(b.categories), list(b.values), b.unit  # the brief's values in full
            keep.append(s)
            continue
        if bad_cats:
            log.lines.append(f"grounding: series {s.id} dropped: categories not in the brief ({', '.join(f'«{_q(c, 30)}»' for c in bad_cats[:3])})")
            continue
        keep.append(s)
    o.series = keep


def _dedupe_figures(slides: list[OutlineSlide], idx: BriefIndex, log: _Log, from_chart: set[int], thinned: set[int]) -> list[OutlineSlide]:
    """Figure slides the grounding made or emptied say only what no other slide says: a chart turned into figures
    keeps only the figures no other slide shows (and goes when none is left); a slide that lost most of its lines goes
    when the figures left on it are all shown on other slides («Ключевые преимущества»: one card of four, repeating the
    result slide). Of two figure slides that show exactly the same figures, the one whose heading the brief supports
    less goes. A figure slide the model planned whole is never dropped for showing some of another slide's figures: a
    problem → result pair («47 минут» → «47 → 29 минут») and a summary KPI slide after the single figures stay."""
    out = list(slides)
    for s in list(out):
        if id(s) not in from_chart or s.spec_ref is not None:
            continue
        others = set().union(*[_figures_on(x) for x in out if x is not s]) if len(out) > 1 else set()
        nums = [n for n in s.content.numbers if not any(any(_eq(f.value, v) for v in others) for f in figures(n.value))]
        if not nums:
            out.remove(s)
            log.dropped.append(f"{s.id} «{_q(s.headline)}» (a chart without data whose figures are on other slides)")
            continue
        s.content.numbers = nums
        s.kind = K.big_number if len(nums) == 1 else K.stat_row
        log.lines.append(f"grounding: slide {s.id} «{_q(s.headline)}»: a chart without data → {s.kind.value} of its figures")
    figs = [s for s in out if s.kind in (K.big_number, K.stat_row) and s.content.numbers and len(s.content.bullets) + len(s.content.paragraphs) <= 1 and not s.content.items]
    for a in figs:
        if a not in out or a.spec_ref is not None:
            continue  # a slide the user asked for stays, whatever other slides show
        va = _number_values(a)
        if not va:
            continue
        weak = id(a) in from_chart or id(a) in thinned
        for b in figs:
            if b is a or b not in out:
                continue
            vb = _number_values(b)
            if not (va == vb or (weak and va < vb)):
                continue
            ra, rb = idx.ratio(a.headline) or 0, idx.ratio(b.headline) or 0
            if va < vb or ra < rb or (ra == rb and out.index(a) > out.index(b)):
                out.remove(a)
                log.dropped.append(f"{a.id} «{_q(a.headline)}» (repeats the figures of {b.id})")
                break
    for s in list(out):
        if id(s) not in thinned or s.spec_ref is not None:
            continue
        others = [x for x in out if x is not s and id(x) not in thinned and x.kind not in (K.title, K.thanks)]
        shown = set().union(*[_figures_on(x) for x in others]) if others else set()
        mine = _figures_on(s)
        if mine and all(any(_eq(v, w) for w in shown) for v in mine):
            out.remove(s)
            log.dropped.append(f"{s.id} «{_q(s.headline or s.section)}» (what is left of it repeats other slides)")
    return out


def _prune_frames(slides: list[OutlineSlide], idx: BriefIndex, log: _Log) -> list[OutlineSlide]:
    """The agenda names only what the deck or the brief has (not «План масштабирования» when neither does); a divider
    with no content slide after it goes."""
    out = []
    for i, s in enumerate(slides):
        if s.kind == K.section and s.spec_ref is None:
            nxt = next((x for x in slides[i + 1 :]), None)
            if nxt is None or nxt.kind in (K.section, K.thanks, K.agenda):
                log.dropped.append(f"{s.id} «{_q(s.headline or s.section)}» (a divider with nothing after it)")
                continue
        out.append(s)
    deck = _Stems(content_stems(" ".join(_slide_words(s) for s in out if s.kind not in (K.agenda, K.title, K.thanks)), neutral=True))
    final = []
    for s in out:
        if s.kind == K.agenda:
            items = []
            for it in s.content.items:
                stems = content_stems(it.title, neutral=True)
                if stems and all(deck.has(x) or idx.stems.has(x) for x in stems):
                    items.append(it)
            if len(items) != len(s.content.items):
                gone = [it.title for it in s.content.items if it not in items]
                log.lines.append("grounding: agenda items without slides removed: " + ", ".join(f"«{_q(x, 40)}»" for x in gone))
            s.content.items = items
            if len(items) < 2 and s.spec_ref is None:
                log.dropped.append(f"{s.id} «{_q(s.headline or s.section)}» (agenda with fewer than two sections left)")
                continue
        final.append(s)
    return final
