"""Профиль датасета (описание решения §2.2): `profile_table(t: Table) -> DatasetProfile`.

Для каждой колонки — тип (число, проценты, деньги, дата, период, категория, текст, логическое, идентификатор), роль (ось
времени, измерение, метрика, идентификатор, подпись, атрибут), пропуски, число разных значений, min/max/медиана, выбросы и
образцы. Для таблицы — ось времени с частотой и пропущенными периодами, метрики и измерения, иерархии («город → регион»),
части целого, размер, природа («Временной ряд · 21 строка · 3 колонки») и пригодность для графика.

Всё считается детерминированным кодом, без модели: один и тот же `Table` всегда даёт один и тот же профиль. Чтение
устойчиво к «сырым» ячейкам: кроме чисел и ISO-строк, которые отдаёт чтение файлов, понимает «1 234,5», «46 %»,
«1,24 млрд ₽», «янв 2025», «IV кв. 2025», «31.01.2025». Разбор строк идёт по уникальным значениям, статистика — в numpy:
100 тыс. строк × 10 колонок — меньше секунды."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import numpy as np

from verstka.schemas.data import (
    NATURE_LABELS,
    Cell,
    ColumnProfile,
    DatasetProfile,
    DatasetSize,
    Nature,
    Outlier,
    Table,
    TimeAxis,
    TimeFreq,
)

__all__ = [
    "profile_table",
    "parse_number_value",
    "parse_time_value",
    "period_iso",
    "count_ru",
]

# ── пороги ────────────────────────────────────────────────────────────────────────────────────────────────────────────
_SHARE_OK = 0.95  # доля значений, которые должны прочитаться, чтобы колонка получила тип (числа, даты)
_MIN_OUTLIER_N = 12  # меньше значений — выбросов не ищем (правило Тьюки на коротком ряду ненадёжно)
_TUKEY_K = 1.5
_SMALL_ROWS, _MEDIUM_ROWS = 12, 60
_LABEL_UNIQUE_MAX = 60  # все строки разные и их не больше 60 — подписи для сравнения (категории), больше — подписи строк
_SAMPLES = 3
_MISSING_PERIODS_MAX = 1000
_SAMPLE_UNIQUE = 2000  # больше уникальных строк — тип сначала проверяется по детерминированной выборке
_NO_ORD = np.int64(-(2**62))

_MISSING = frozenset(
    {"", "-", "--", "—", "–", "−", "н/д", "н.д.", "нд", "н/а", "нет данных", "n/a", "na", "nan", "null", "none", "#н/д",
     "#n/a", "?", "…", "..."}
)
_BOOL_TRUE = frozenset({"да", "true", "yes", "истина", "y", "д"})
_BOOL_FALSE = frozenset({"нет", "false", "no", "ложь", "n"})
_TOTAL_RE = re.compile(r"^(?:итого|всего|итог|total|grand total|в целом)(?:\b|$)")
_TOTAL_FIRST = frozenset("ивtg")

# подсказки по имени колонки
_YEAR_NAME = re.compile(r"(?:^|[^а-яёa-z])(?:год|года|годы|year|г)(?:[^а-яёa-z]|$)")
_ID_NAME = re.compile(
    r"(?:^|[^а-яёa-z])(?:id|ид|no|номер|код|артикул|инн|огрн|кпп|sku|uuid|guid|идентификатор|ключ)(?:[^а-яёa-z]|$)|[№#]"
)
_MONEY_NAME = re.compile(
    r"выручк|доход|прибыл|стоимост|цен[аыу]|бюджет|затрат|расход|зарплат|оклад|чек|оборот|себестоим|revenue|price|cost|"
    r"income|profit|sales"
)
_PERCENT_NAME = re.compile(r"%|процент|доля|доли|share|percent|конверси")
_FRACTION_NAME = re.compile(r"доля|доли|share|удельн")
_CHANGE_NAME = re.compile(r"изменени|(?:^|[^а-яё])(?:при)?рост|динамик|разниц|отклонени|к прошл|г/г|yoy|δ|дельта|\bvs\b")
_KPI_LABEL = re.compile(r"показател|метрик|kpi|индикатор|параметр")
_PARENT_NAME = re.compile(
    r"регион|област|край|округ|стран|республик|континент|категори|групп|раздел|отдел|департамент|подразделени|дивизион|"
    r"направлени|сегмент|отрасл|бренд|марк[аи]|семейств|филиал|класс|тип"
)
_UNIT_WORDS = frozenset(
    {"шт", "мин", "ч", "час", "часов", "сек", "с", "дн", "дней", "чел", "кг", "т", "г", "л", "км", "м", "см", "мм", "гб",
     "тб", "мб", "квт", "раз", "ед", "п", "пункт", "пунктов", "балл", "баллов", "мес"}
)
_ID_VALUE = re.compile(r"^(?=.*\d)[0-9a-zа-яё_\-/.#:№]{2,40}$", re.I)

# ── числа ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
_CURRENCY = {"₽": "₽", "руб": "₽", "рублей": "₽", "рубля": "₽", "рубль": "₽", "р": "₽", "rub": "₽", "$": "$", "usd": "$",
             "долл": "$", "долларов": "$", "доллара": "$", "€": "€", "eur": "€", "евро": "€", "£": "£", "¥": "¥"}
_SCALES = {"тыс": 1e3, "млн": 1e6, "млрд": 1e9, "трлн": 1e12, "k": 1e3, "m": 1e6, "bn": 1e9}
_NUM_RE = re.compile(r"^(?P<core>\d(?:[\d.,'’]|[ \u00a0\u202f\u2009](?=\d))*)\s*(?P<suf>\D*)$")
_SUF_RE = re.compile(
    r"^(?:(?P<scale>тыс|млн|млрд|трлн|k|m|bn)(?![а-яёa-z])\.?\s*)?"
    r"(?:(?P<cur>₽|руб(?:лей|ля|ль)?|р|rub|\$|usd|€|eur|евро|£|¥|долл(?:аров|ара)?)(?![а-яёa-z])\.?\s*)?"
    r"(?P<pct>%|проц(?:ент(?:ов|а)?)?)?\.?\s*"
    r"(?P<rest>.*)$"
)
_PP_RE = re.compile(r"^(?:п\.?\s?п\.?|пп\.?|pp|б\.?\s?п\.?)$")
_GROUP_SEP = re.compile(r"[ \u00a0\u202f\u2009'’]")


@dataclass(frozen=True)
class _Num:
    value: float  # без множителя («1,24 млрд» → 1.24)
    factor: float  # множитель («млрд» → 1e9)
    mark: str  # единица из ячейки («млрд ₽», «%», «мин»); пусто — без единицы
    pct: bool
    money: bool
    signed: bool  # число со знаком «+» («+23%») — похоже на изменение


def _core_float(core: str, english: bool = False) -> Optional[float]:
    """«1 234,5», «1.234,5», «1,234.5» → число; одна запятая — десятичная («1,5»), кроме записи «$1,200»."""
    if english and core.count(",") == 1 and "." not in core and re.fullmatch(r"\d{1,3},\d{3}", core):
        core = core.replace(",", "")
    parts = _GROUP_SEP.split(core)
    if len(parts) > 1:  # «1 234,5»: группы после первой — ровно по три цифры
        if not parts[0] or len(re.match(r"\d*", parts[0]).group()) > 3:
            return None
        for p in parts[1:]:
            m = re.match(r"\d+", p)
            if not m or len(m.group()) != 3:
                return None
        core = "".join(parts)
    dots, commas = core.count("."), core.count(",")
    if dots and commas:
        dec, thou = (".", ",") if core.rfind(".") > core.rfind(",") else (",", ".")
        if core.count(dec) > 1:
            return None
        core = core.replace(thou, "").replace(dec, ".")
    elif commas > 1 or dots > 1:
        sep = "," if commas else "."
        groups = core.split(sep)
        if any(len(g) != 3 for g in groups[1:]) or len(groups[0]) > 3:
            return None
        core = core.replace(sep, "")
    elif commas:
        core = core.replace(",", ".")
    try:
        return float(core)
    except ValueError:
        return None


def _parse_number_str(s: str) -> Optional[_Num]:
    """Строка с числом: «1 234,5», «46 %», «+23%», «−5», «1,24 млрд ₽», «356 тыс. ₽», «$1,200», «120 мин», «+6 п.»."""
    t = s.strip().lower()
    if not t:
        return None
    sign, signed = 1.0, False
    if t[0] in "+-−–":
        signed = t[0] == "+"
        sign = -1.0 if t[0] != "+" else 1.0
        t = t[1:].lstrip()
    money_pre = ""
    if t and t[0] in "$€£¥₽":
        money_pre, t = _CURRENCY[t[0]], t[1:].lstrip()
        if t and t[0] in "+-−–" and not signed and sign > 0:
            signed, sign = t[0] == "+", (-1.0 if t[0] != "+" else 1.0)
            t = t[1:].lstrip()
    m = _NUM_RE.match(t)
    if not m:
        return None
    v = _core_float(m.group("core"), english=money_pre in ("$", "£"))
    if v is None:
        return None
    suf = m.group("suf").strip()
    factor, mark_parts, pct, money = 1.0, [], False, bool(money_pre)
    if suf:
        sm = _SUF_RE.match(suf)
        if not sm:
            return None
        if sm.group("scale"):
            factor = _SCALES[sm.group("scale")]
            mark_parts.append("тыс." if sm.group("scale") == "тыс" else sm.group("scale"))
        cur = sm.group("cur")
        if cur:
            money = True
            mark_parts.append(_CURRENCY.get(cur, "₽"))
        if sm.group("pct"):
            pct = True
            mark_parts.append("%")
        rest = sm.group("rest").strip()
        if rest:
            if len(rest) > 24:
                return None
            if _PP_RE.match(rest):
                pct = True
                mark_parts.append("п.п.")
            else:
                mark_parts.append(rest)
    if money_pre and money_pre not in mark_parts:
        mark_parts.append(money_pre)
    return _Num(sign * v, factor, " ".join(mark_parts), pct, money, signed)


def parse_number_value(cell: Cell) -> Optional[float]:
    """Число ячейки с множителем («1,24 млрд» → 1.24e9, «46 %» → 46.0); None — не число или пусто."""
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return None if isinstance(cell, float) and math.isnan(cell) else float(cell)
    r = _parse_number_str(_norm(cell))
    return None if r is None else r.value * r.factor


# ── даты и периоды ────────────────────────────────────────────────────────────────────────────────────────────────────
_MONTHS: dict[str, int] = {}
for _k, _forms in enumerate(
    [
        ("январь", "января", "янв", "january", "jan"),
        ("февраль", "февраля", "фев", "февр", "february", "feb"),
        ("март", "марта", "мар", "march", "mar"),
        ("апрель", "апреля", "апр", "april", "apr"),
        ("май", "мая", "may"),
        ("июнь", "июня", "июн", "june", "jun"),
        ("июль", "июля", "июл", "july", "jul"),
        ("август", "августа", "авг", "august", "aug"),
        ("сентябрь", "сентября", "сен", "сент", "september", "sep", "sept"),
        ("октябрь", "октября", "окт", "october", "oct"),
        ("ноябрь", "ноября", "ноя", "нояб", "november", "nov"),
        ("декабрь", "декабря", "дек", "december", "dec"),
    ],
    start=1,
):
    for _f in _forms:
        _MONTHS[_f] = _k
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_YSUF = r"(?:\s*(?:г\.?|года?))?"
_Q = r"([1-4]|iv|i{1,3})"
_ISO_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[t ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:?\d{2})?)?$")
_YMD = re.compile(r"^(\d{4})[./](\d{1,2})[./](\d{1,2})$")
_DMY = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})" + _YSUF + r"(?:[t ]\d{1,2}:\d{2}(?::\d{2})?)?$")
_ISO_MONTH = re.compile(r"^(\d{4})[-./](\d{1,2})$")
_MY = re.compile(r"^(\d{1,2})[./-](\d{4})" + _YSUF + "$")
_ISO_Q = re.compile(r"^(\d{4})" + _YSUF + r"\s*[-–,]?\s*q\s*([1-4])$")
_Q_FIRST = re.compile(r"^q\s*([1-4])[\s\-–'’/.,]*(\d{4}|\d{2})" + _YSUF + "$")
_Q_RU = re.compile(r"^" + _Q + r"\s*(?:-?й\s*)?(?:кв\.?|квартал[ае]?|q)\s*[\s\-–'’,]*(\d{4}|\d{2})" + _YSUF + "$")
_Y_Q_RU = re.compile(r"^(\d{4})" + _YSUF + r"\s*[-–,]?\s*" + _Q + r"\s*(?:-?й\s*)?(?:кв\.?|квартал)$")
_WEEK = re.compile(r"^(\d{4})-?w(\d{1,2})$")
_YEAR = re.compile(r"^(\d{4})" + _YSUF + "$")
_MONTH_NAME = re.compile(r"^(?:(\d{1,2})\s+)?([a-zа-яё]+)\.?[\s\-–'’.,/]*(\d{4}|\d{2})" + _YSUF + "$")


def _year(s: str) -> Optional[int]:
    y = int(s)
    if len(s) == 2:
        y += 2000 if y < 70 else 1900
    return y if 1900 <= y <= 2100 else None


def _qnum(s: str) -> int:
    return int(s) if s.isdigit() else _ROMAN[s]


def _day(y: Optional[int], m: int, d: int) -> Optional[tuple[str, int]]:
    if y is None:
        return None
    try:
        return "day", date(y, m, d).toordinal()
    except ValueError:
        return None


def _month(y: Optional[int], m: int) -> Optional[tuple[str, int]]:
    return ("month", y * 12 + m - 1) if y is not None and 1 <= m <= 12 else None


def _quarter(y: Optional[int], q: int) -> Optional[tuple[str, int]]:
    return ("quarter", y * 4 + q - 1) if y is not None and 1 <= q <= 4 else None


def _parse_time_str(s: str) -> Optional[tuple[str, int]]:
    """Строка (уже нижний регистр, пробелы схлопнуты) → (зернистость, порядковый номер периода) или None."""
    if len(s) < 4 or len(s) > 40:
        return None
    if len(s) >= 10 and s[4] == "-" and s[7] == "-" and (len(s) == 10 or s[10] in " t"):
        try:
            return "day", date.fromisoformat(s[:10]).toordinal()
        except ValueError:
            pass
    c = s[0]
    if c.isdigit():
        if m := _ISO_DAY.match(s):
            return _day(_year(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := _YEAR.match(s):
            y = _year(m.group(1))
            return ("year", y) if y is not None else None
        if m := _ISO_MONTH.match(s):
            return _month(_year(m.group(1)), int(m.group(2)))
        if m := _DMY.match(s):
            return _day(_year(m.group(3)), int(m.group(2)), int(m.group(1)))
        if m := _YMD.match(s):
            return _day(_year(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := _MY.match(s):
            return _month(_year(m.group(2)), int(m.group(1)))
        if m := _ISO_Q.match(s):
            return _quarter(_year(m.group(1)), int(m.group(2)))
        if m := _Y_Q_RU.match(s):
            return _quarter(_year(m.group(1)), _qnum(m.group(2)))
        if m := _WEEK.match(s):
            y = _year(m.group(1))
            if y is None:
                return None
            try:
                return "week", (date.fromisocalendar(y, int(m.group(2)), 1).toordinal() - 1) // 7
            except ValueError:
                return None
    if m := _Q_RU.match(s):
        return _quarter(_year(m.group(2)), _qnum(m.group(1)))
    if m := _Q_FIRST.match(s):
        return _quarter(_year(m.group(2)), int(m.group(1)))
    if m := _MONTH_NAME.match(s):
        k = _MONTHS.get(m.group(2))
        if k is None:
            return None
        y = _year(m.group(3))
        if m.group(1):
            return _day(y, k, int(m.group(1)))
        return _month(y, k)
    return None


def parse_time_value(cell: Cell) -> Optional[tuple[str, int]]:
    """Дата или период ячейки → (зернистость day|week|month|quarter|year, порядковый номер периода); None — не время.
    Номер — день от начала эры, неделя (понедельник), год·12+месяц, год·4+квартал или год; `period_iso` возвращает ISO."""
    if not isinstance(cell, str):
        return None
    return _parse_time_str(_norm(cell).lower())


def period_iso(gran: str, ordinal: int) -> str:
    """ISO периода: «2025-01-31», «2025-W05», «2025-01», «2025-Q1», «2025»."""
    o = int(ordinal)
    if gran == "month":
        return f"{o // 12:04d}-{o % 12 + 1:02d}"
    if gran == "quarter":
        return f"{o // 4:04d}-Q{o % 4 + 1}"
    if gran == "year":
        return f"{o:04d}"
    if gran == "week":
        y, w, _ = date.fromordinal(o * 7 + 1).isocalendar()
        return f"{y:04d}-W{w:02d}"
    return date.fromordinal(o).isoformat()


# ── тексты ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _plural(n: int, one: str, few: str, many: str) -> str:
    m10, m100 = n % 10, n % 100
    return one if m10 == 1 and m100 != 11 else few if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else many


def _group(n: int) -> str:
    """12345 → «12 345» (неразрывный пробел между разрядами)."""
    s = str(abs(n))
    out = []
    while len(s) > 3:
        out.insert(0, s[-3:])
        s = s[:-3]
    out.insert(0, s)
    return ("-" if n < 0 else "") + "\u00a0".join(out)


def count_ru(n: int, one: str, few: str, many: str) -> str:
    """«1 строка», «3 строки», «512 строк», «100 000 строк»."""
    return f"{_group(n)} {_plural(n, one, few, many)}"


def _fmt(x: float) -> str:
    """Число по-русски: 224.0 → «224», 12.345 → «12,35», 1234.5 → «1 235»."""
    if not math.isfinite(x):
        return str(x)
    if abs(x) >= 100 or float(x).is_integer():
        return _group(int(round(x)))
    whole, _, frac = f"{abs(x):.2f}".rstrip("0").rstrip(".").partition(".")
    return ("-" if x < 0 else "") + _group(int(whole)) + ("," + frac if frac else "")


# ── разбор колонки ────────────────────────────────────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    """Без пробелов по краям, неразрывные и двойные пробелы — один обычный."""
    t = s.strip()
    if "  " in t or "\u00a0" in t or "\u202f" in t or "\u2009" in t or "\t" in t or "\n" in t or "\r" in t:
        return " ".join(t.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ").split())
    return t


@dataclass
class _Col:
    j: int
    name: str
    unit: Optional[str]
    cells: list
    kind: str = "empty"  # number | time | bool | string | empty
    type: str = "text"
    role: str = "text"
    present: Optional[np.ndarray] = None  # bool по строкам: значение есть (строки «Итого» — нет)
    num: Optional[np.ndarray] = None  # числа по строкам (nan — нет)
    num_total: Optional[np.ndarray] = None  # числа в строках «Итого»
    tord: Optional[np.ndarray] = None  # номер периода по строкам (_NO_ORD — нет)
    gran: Optional[str] = None
    svals: Optional[list] = None  # нормализованные строки по строкам (None — нет)
    missing: int = 0
    distinct: int = 0
    mixed_units: bool = False
    signed: bool = False
    mark: str = ""  # общая единица из ячеек («%», «млн ₽»)
    fraction: bool = False
    free_text: bool = False  # длинный текст (комментарии), а не подпись строки
    outlier_rows: list[int] = field(default_factory=list)
    outliers: list[Outlier] = field(default_factory=list)


def _key_kind(v: Any) -> tuple[str, Any]:
    """Уникальное значение ячейки → ('miss'|'total'|'bool'|'num'|'str', значение)."""
    if v is None:
        return "miss", None
    if isinstance(v, bool):
        return "bool", v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return "miss", None
        return "num", float(v)
    if isinstance(v, str):
        s = _norm(v)
        if len(s) > 40:
            return "str", s
        low = s.lower()
        if low in _MISSING:
            return "miss", None
        if _TOTAL_RE.match(low):
            return "total", s
        if low in _BOOL_TRUE:
            return "bool", True
        if low in _BOOL_FALSE:
            return "bool", False
        return "str", s
    return "str", _norm(str(v))


def _sample(keys: list) -> list:
    if len(keys) <= _SAMPLE_UNIQUE:
        return keys
    step = len(keys) / (_SAMPLE_UNIQUE // 2)
    return keys[: _SAMPLE_UNIQUE // 2] + [keys[int(i * step)] for i in range(_SAMPLE_UNIQUE // 2)]


def _enough(ok: int, total: int) -> bool:
    if total <= 0:
        return False
    return ok == total if total <= 20 else ok >= _SHARE_OK * total


def _unit_from_name(name: str) -> Optional[str]:
    """«Выручка, млн ₽» / «Доля (%)» → единица, если чтение её не отделило."""
    m = re.match(r"^(.*\S)\s*(?:,\s*|\(\s*)([^,()]{1,16}?)\s*\)?$", name)
    if not m:
        return None
    u = m.group(2).strip()
    probe = _parse_number_str("1 " + u)
    if probe is None or not probe.mark:
        return None
    if probe.pct or probe.money or probe.factor != 1.0 or probe.mark.rstrip(".") in _UNIT_WORDS:
        return u
    return None


def _str_of(k: Any) -> str:
    """Значение ячейки как строка для категорий и подписей: строка как в файле, число без «.0»."""
    if isinstance(k, str):
        return _norm(k)
    if isinstance(k, float) and k.is_integer():
        return str(int(k))
    return str(k)


def _analyze(j: int, name: str, unit: Optional[str], cells: list, total: np.ndarray, first_col: bool) -> _Col:
    n = len(cells)
    c = _Col(j=j, name=name, unit=unit, cells=cells)
    cnt = Counter(cells)
    kinds: dict[Any, tuple[str, Any]] = {k: _key_kind(k) for k in cnt}
    rows = {"miss": 0, "total": 0, "bool": 0, "num": 0, "str": 0}
    for k, (kk, _) in kinds.items():
        rows[kk] += cnt[k]
    present_rows = rows["bool"] + rows["num"] + rows["str"]
    lname = name.lower()
    n_total = int(total.sum())
    if present_rows == 0:
        c.kind, c.type, c.role = "empty", "text", "attribute"
        c.present = np.zeros(n, dtype=bool)
        c.missing = n - n_total
        return c

    # логическое: да/нет, true/false
    if rows["bool"] and _enough(rows["bool"], present_rows):
        c.kind, c.type, c.role = "bool", "boolean", "dimension"
        bmap = {k: v for k, (kk, v) in kinds.items() if kk == "bool"}
        c.svals = [bmap.get(v) for v in cells]
        _finish_strings(c, total)
        return c

    str_keys = [k for k, (kk, _) in kinds.items() if kk == "str"]

    # время: строки-даты и периоды
    if str_keys and rows["num"] == 0:
        tmap = _try_time(str_keys, kinds, cnt, rows["str"], lname, cells, first_col)
        if tmap is not None:
            gran, lookup = tmap
            c.kind, c.gran = "time", gran
            c.type = "date" if gran == "day" else "period"
            c.role = "attribute"
            tord = np.fromiter((lookup.get(v, _NO_ORD) for v in cells), dtype=np.int64, count=n)
            if n_total:
                tord[total] = _NO_ORD
            c.tord = tord
            c.present = tord != _NO_ORD
            c.missing = n - n_total - int(c.present.sum())
            c.distinct = int(np.unique(tord[c.present]).size)
            return c

    # числа: родные и из строк («1 234,5», «46 %», «1,24 млрд ₽»)
    parsed: dict[Any, _Num] = {}
    if str_keys:
        cand = _sample(str_keys)
        if len(cand) < len(str_keys):
            ok = sum(cnt[k] for k in cand if _parse_number_str(kinds[k][1]) is not None)
            cand = str_keys if ok >= 0.9 * sum(cnt[k] for k in cand) else []
        leading_zero = 0
        for k in cand:
            s = kinds[k][1]
            r = _parse_number_str(s)
            if r is not None:
                parsed[k] = r
                leading_zero += 1 if len(s) >= 2 and s[0] == "0" and s.isdigit() else 0
        ok_rows = sum(cnt[k] for k in parsed)
        if not parsed or not _enough(rows["num"] + ok_rows, rows["num"] + rows["str"]) or leading_zero * 2 >= len(parsed):
            parsed = {}
    if (rows["num"] and not str_keys) or parsed:
        marks: Counter = Counter()
        if rows["num"]:
            marks[""] += rows["num"]
        factors = {1.0} if rows["num"] else set()
        pct_rows = money_rows = signed_rows = 0
        for k, r in parsed.items():
            w = cnt[k]
            marks[r.mark] += w
            factors.add(r.factor)
            pct_rows += w if r.pct else 0
            money_rows += w if r.money else 0
            signed_rows += w if r.signed else 0
        mixed_scale = len(factors) > 1
        lookup: dict[Any, float] = {k: v for k, (kk, v) in kinds.items() if kk == "num"}
        for k, r in parsed.items():
            lookup[k] = r.value * r.factor if mixed_scale else r.value
        c.kind = "number"
        num = np.fromiter((lookup.get(v, np.nan) for v in cells), dtype=float, count=n)
        if n_total:
            c.num_total = num[total].copy()
            num[total] = np.nan
        c.num = num
        c.present = ~np.isnan(num)
        c.missing = n - n_total - int(c.present.sum())
        nn = max(rows["num"] + sum(cnt[k] for k in parsed), 1)
        c.signed = signed_rows > 0 and signed_rows >= 0.5 * nn
        c.mixed_units = len(marks) > 1
        if len(marks) == 1 and not mixed_scale:
            c.mark = next(iter(marks))
        _type_number(c, lname, pct_rows / nn, money_rows / nn, first_col)
        return c

    # строки: идентификатор, категория, текст
    c.kind = "string"
    smap = {k: (v if kk == "str" else _str_of(k)) for k, (kk, v) in kinds.items() if kk in ("str", "num", "bool")}
    c.svals = [smap.get(v) for v in cells]
    _finish_strings(c, total)
    _type_string(c, lname)
    return c


def _finish_strings(c: _Col, total: np.ndarray) -> None:
    sv = c.svals or []
    if total.any():
        for i in np.flatnonzero(total):
            sv[i] = None
    c.present = np.fromiter((v is not None for v in sv), dtype=bool, count=len(sv))
    c.missing = int(len(sv) - int(total.sum()) - int(c.present.sum()))
    c.distinct = len({v for v in sv if v is not None})


def _try_time(str_keys: list, kinds: dict, cnt: Counter, str_rows: int, lname: str, cells: list,
              first_col: bool) -> Optional[tuple[str, dict]]:
    cand = _sample(str_keys)
    if len(cand) < len(str_keys):
        ok = sum(cnt[k] for k in cand if _parse_time_str(kinds[k][1].lower()) is not None)
        if ok < 0.9 * sum(cnt[k] for k in cand):
            return None
    parsed: dict[Any, tuple[str, int]] = {}
    for k in str_keys:
        r = _parse_time_str(kinds[k][1].lower())
        if r is not None:
            parsed[k] = r
    if not _enough(sum(cnt[k] for k in parsed), str_rows):
        return None
    grans = Counter()
    for k, (g, _) in parsed.items():
        grans[g] += cnt[k]
    gran, g_rows = grans.most_common(1)[0]
    if not _enough(g_rows, str_rows):
        return None
    lookup = {k: o for k, (g, o) in parsed.items() if g == gran}
    if gran == "year" and not _YEAR_NAME.search(lname) and not first_col:
        # «2025» без подсказки в имени — год, только если идёт по порядку (иначе это числа вроде «1987»)
        seq = [lookup[v] for v in cells if v in lookup]
        if len(seq) < 3 or not (all(a < b for a, b in zip(seq, seq[1:])) or all(a > b for a, b in zip(seq, seq[1:]))):
            return None
    return gran, lookup


def _type_number(c: _Col, lname: str, pct_share: float, money_share: float, first_col: bool) -> None:
    v = c.num[c.present]
    integral = v.size > 0 and bool(np.all(np.mod(v, 1) == 0))
    uniq = np.unique(v)
    c.distinct = int(uniq.size)
    unit = c.unit if c.unit is not None else (c.mark or _unit_from_name(c.name))
    if c.unit is None and unit:
        c.unit = unit
    lunit = (unit or "").lower()
    # идентификатор: по имени или номера строк 1..n
    if integral and v.size >= 3 and uniq.size == v.size:
        steps = np.diff(v)
        row_numbers = first_col and bool(np.all(steps == 1)) and v[0] in (0, 1) and v.size >= 5
        if _ID_NAME.search(lname) or row_numbers:
            c.type, c.role = "id", "id"
            return
    # год числами: «2023, 2024, 2025» с подсказкой в имени или первой колонкой подряд
    if integral and v.size >= 1 and float(v.min()) >= 1900 and float(v.max()) <= 2100 and not unit:
        steps = np.diff(v)
        ordered = v.size >= 3 and (bool(np.all(steps > 0)) or bool(np.all(steps < 0))) and float(np.abs(steps).max()) <= 10
        if _YEAR_NAME.search(lname) or (first_col and ordered):
            c.kind, c.gran, c.type, c.role = "time", "year", "period", "attribute"
            tord = np.full(len(c.num), _NO_ORD, dtype=np.int64)
            tord[c.present] = c.num[c.present].astype(np.int64)
            c.tord = tord
            return
    c.role = "metric"
    vmin = float(v.min()) if v.size else 0.0
    vmax = float(v.max()) if v.size else 0.0
    if "%" in lunit or "п.п" in lunit or "процент" in lunit or pct_share >= _SHARE_OK or "%" in lname:
        c.type = "percent"
    elif _PERCENT_NAME.search(lname) and v.size and vmin >= 0 and vmax <= 100 and not _has_currency(lunit):
        c.type = "percent"
        c.fraction = bool(vmax <= 1.0) and bool(_FRACTION_NAME.search(lname))
    elif _has_currency(lunit) or money_share >= _SHARE_OK or (not unit and _MONEY_NAME.search(lname)):
        c.type = "money"
    else:
        c.type = "number"


def _has_currency(lunit: str) -> bool:
    return any(s in lunit for s in ("₽", "руб", "р.", "$", "€", "£", "¥", "usd", "eur", "rub", "долл", "евро"))


def _type_string(c: _Col, lname: str) -> None:
    vals = [v for v in (c.svals or []) if v is not None]
    present = len(vals)
    uniq = list(dict.fromkeys(vals))
    sample = _sample(uniq)
    all_unique = c.distinct == present
    if present and sample:
        id_like = sum(1 for s in sample if " " not in s and _ID_VALUE.match(s))
        if (_ID_NAME.search(lname) and c.distinct >= _SHARE_OK * present) or (
            all_unique and present >= 3 and id_like >= _SHARE_OK * len(sample)
        ):
            c.type, c.role = "id", "id"
            return
        avg_len = sum(len(s) for s in sample) / len(sample)
        avg_words = sum(s.count(" ") + 1 for s in sample) / len(sample)
        if avg_len > 40 or avg_words > 5:
            c.type, c.role, c.free_text = "text", "text", True
            return
    if all_unique:
        if present <= _LABEL_UNIQUE_MAX:
            c.type, c.role = "category", "dimension"
        else:
            c.type, c.role = "text", "text"
        return
    if c.distinct <= 200 or c.distinct <= 0.5 * present:
        c.type, c.role = "category", "dimension"
    else:
        c.type, c.role = "text", "text"


# ── выбросы ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _find_outliers(c: _Col) -> None:
    """Правило Тьюки (1,5 межквартильного размаха) и отрыв: значение за границей Тьюки — выброс, если оно (и всё, что
    дальше) отделено от остальных промежутком больше 1,5 размаха. Так длинный, но сплошной хвост («время ответа»)
    остаётся данными, а три оторванных значения — выбросами. Меньше 12 значений — выбросов нет."""
    present = c.present
    x = c.num[present]
    if x.size < _MIN_OUTLIER_N:
        return
    xs = np.sort(x)
    q1, q3 = np.percentile(xs, [25, 75])
    iqr = float(q3 - q1)
    if iqr <= 0:
        return
    gap = _TUKEY_K * iqr
    hi_fence, lo_fence = float(q3 + gap), float(q1 - gap)
    cut_hi = cut_lo = None
    i = int(np.searchsorted(xs, hi_fence, side="right"))
    if i < xs.size:
        tail = np.concatenate(([xs[i - 1]], xs[i:])) if i > 0 else xs[i:]
        jumps = np.flatnonzero(np.diff(tail) > gap)
        if jumps.size:
            cut_hi = float(tail[jumps[0] + 1])
    k = int(np.searchsorted(xs, lo_fence, side="left"))
    if k > 0:
        head = np.concatenate((xs[:k], [xs[k]])) if k < xs.size else xs[:k]
        jumps = np.flatnonzero(np.diff(head) > gap)
        if jumps.size:
            cut_lo = float(head[jumps[-1]])
    if cut_hi is None and cut_lo is None:
        return
    vals = np.where(present, c.num, np.nan)
    with np.errstate(invalid="ignore"):
        mask = np.zeros(vals.size, dtype=bool)
        if cut_hi is not None:
            mask |= vals >= cut_hi
        if cut_lo is not None:
            mask |= vals <= cut_lo
    rows = np.flatnonzero(mask)
    c.outlier_rows = [int(r) for r in rows]
    apart = "и отдельно от остальных значений"
    hi_txt = f"выше границы {_fmt(hi_fence)} (третий квартиль + 1,5 межквартильного размаха) {apart}"
    lo_txt = f"ниже границы {_fmt(lo_fence)} (первый квартиль − 1,5 межквартильного размаха) {apart}"
    c.outliers = [
        Outlier(column=c.name, row=int(r), value=float(c.num[r]), reason=hi_txt if c.num[r] > q3 else lo_txt) for r in rows
    ]


# ── ось времени ───────────────────────────────────────────────────────────────────────────────────────────────────────
_EPOCH = date(1970, 1, 1).toordinal()


def _derive_freq(gran: str, days: np.ndarray) -> str:
    """Частота по уникальным номерам периодов (по возрастанию). У дат — месяц, квартал или год, если на каждый период
    приходится одна дата («2025-01-01», «2025-02-01» …), неделя — если все даты в один день недели через 7 дней."""
    if gran != "day" or days.size < 2:
        return gran
    d64 = (days - _EPOCH).astype("datetime64[D]")
    months = d64.astype("datetime64[M]").astype(np.int64) + 1970 * 12
    if np.unique(months).size == days.size:
        g = int(np.gcd.reduce(np.diff(months)))
        return "year" if g % 12 == 0 else "quarter" if g % 3 == 0 else "month"
    if np.unique((days - 1) % 7).size == 1 and bool(np.all(np.diff(days) % 7 == 0)):
        return "week"
    return "day"


def _to_freq(freq: str, days: np.ndarray) -> np.ndarray:
    """Номера дней → номера периодов частоты."""
    if freq == "day" or freq == "irregular":
        return days
    if freq == "week":
        return (days - 1) // 7
    d64 = (days - _EPOCH).astype("datetime64[D]")
    months = d64.astype("datetime64[M]").astype(np.int64) + 1970 * 12
    if freq == "month":
        return months
    if freq == "quarter":
        return (months // 12) * 4 + (months % 12) // 3
    return months // 12


def _sorted_rows(ords: np.ndarray) -> bool:
    if ords.size < 3:
        return True
    d = np.diff(ords)
    return bool((d >= 0).mean() >= _SHARE_OK or (d <= 0).mean() >= _SHARE_OK)


def _time_axis(c: _Col, metrics: list[_Col]) -> TimeAxis:
    valid = c.present
    ords = c.tord[valid]
    uniq = np.unique(ords)
    freq = _derive_freq(c.gran or "day", uniq)
    iso_gran = freq
    per = _to_freq(freq, c.tord[valid]) if c.gran == "day" else ords
    uper = np.unique(per)
    has_val = np.zeros(len(c.tord), dtype=bool)
    if metrics:
        for m in metrics:
            has_val |= m.present
    else:
        has_val[:] = True
    with_val = np.unique((_to_freq(freq, c.tord[valid & has_val]) if c.gran == "day" else c.tord[valid & has_val]))
    missing: list[str] = []
    out_freq: str = freq
    if uper.size >= 2:
        steps = np.diff(uper)
        g = max(int(np.gcd.reduce(steps)), 1)
        lo, hi = int(uper[0]), int(uper[-1])
        expected = np.arange(lo, hi + 1, g, dtype=np.int64)
        if freq == "day":
            wd = (uper - 1) % 7
            if uper.size >= 5 and not bool(np.any(wd >= 5)):  # только рабочие дни — выходные не пропуски
                expected = expected[((expected - 1) % 7) < 5]
        coverage = uper.size / max(expected.size, 1)
        if coverage < 0.5:
            out_freq = "irregular"
        else:
            gaps = np.setdiff1d(expected, with_val, assume_unique=False)
            missing = [period_iso(iso_gran, int(o)) for o in gaps[:_MISSING_PERIODS_MAX]]
    if out_freq == "irregular":
        start, end = period_iso(c.gran or "day", int(uniq[0])), period_iso(c.gran or "day", int(uniq[-1]))
        points = int(uniq.size)
    else:
        start, end = period_iso(iso_gran, int(uper[0])), period_iso(iso_gran, int(uper[-1]))
        points = int(uper.size)
    tf: TimeFreq = out_freq  # type: ignore[assignment]
    return TimeAxis(column=c.name, freq=tf, start=start, end=end, points=points, missing_periods=missing)


def _axis_candidate(c: _Col, has_row_label: bool) -> bool:
    ords = c.tord[c.present]
    if ords.size == 0:
        return False
    if _sorted_rows(ords):
        return True
    if has_row_label:
        return False
    uniq = np.unique(ords)
    if _derive_freq(c.gran or "day", uniq) != "day" or c.gran != "day":
        return True
    # ежедневные даты не по порядку (длинный формат) — ось, если дни идут почти без пропусков
    return uniq.size >= 2 and uniq.size / (int(uniq[-1] - uniq[0]) + 1) >= 0.5


# ── иерархии и части целого ───────────────────────────────────────────────────────────────────────────────────────────
def _codes(c: _Col) -> np.ndarray:
    d: dict[Any, int] = {}
    return np.fromiter((-1 if v is None else d.setdefault(v, len(d)) for v in c.svals), dtype=np.int64, count=len(c.svals))


def _hierarchies(cols: list[_Col]) -> list[tuple[str, str]]:
    parents = [c for c in cols if c.role == "dimension" and c.type == "category" and c.distinct >= 2]
    # дочерние: категории и подписи строк (у каждой строки своя: «клиент»), но не длинный текст
    children = [
        c for c in cols
        if c.kind == "string" and c.distinct >= 3
        and (c.role == "dimension" or (c.role == "text" and not c.free_text and c.distinct == int(c.present.sum())))
    ]
    if not parents or not children:
        return []
    codes = {c.j: _codes(c) for c in {id(x): x for x in parents + children}.values()}
    found: list[tuple[_Col, _Col]] = []
    for ch in children:
        for pa in parents:
            if pa is ch or not ch.distinct > pa.distinct:
                continue
            a, b = codes[ch.j], codes[pa.j]
            both = (a >= 0) & (b >= 0)
            if int(both.sum()) < 3:
                continue
            a, b = a[both], b[both]
            n_child = np.unique(a).size
            pairs = np.unique(a * (int(b.max()) + 1) + b).size
            if pairs != n_child:
                continue
            unique_child = n_child == a.size
            if unique_child and not _PARENT_NAME.search(pa.name.lower()):
                continue  # подписи строк определяют всё — иерархия, только если родитель назван как группа
            found.append((ch, pa))
    names = {(ch.name, pa.name) for ch, pa in found}
    out = []
    for ch, pa in found:
        if any((ch.name, mid) in names and (mid, pa.name) in names for mid in {p.name for _, p in found}):
            continue  # город → страна при город → регион → страна — лишнее звено
        out.append((ch.name, pa.name))
    return out


def _parts_of_whole(metrics: list[_Col], has_label: bool, axis: Optional[_Col]) -> bool:
    for m in metrics:
        v = m.num[m.present]
        # «доли от итога»: строка «Итого» равна сумме остальных
        if m.num_total is not None and v.size >= 2 and bool(np.all(v >= 0)):
            tv = m.num_total[~np.isnan(m.num_total)]
            if tv.size and tv[0] > 0 and abs(float(v.sum()) - float(tv[0])) <= max(0.01 * float(tv[0]), 0.5):
                return True
        if m.type != "percent" or v.size < 2 or not has_label or bool(np.any(v < 0)):
            continue
        if m.signed or _CHANGE_NAME.search(m.name.lower()):
            continue  # «Рост, %» и «Изменение» — не доли, даже если в сумме случайно ≈ 100
        if axis is not None:
            # длинный формат: в каждом периоде доли в сумме ≈ 100
            per = axis.tord
            ok = m.present & (per != _NO_ORD)
            if ok.sum() < 2:
                continue
            keys, inv = np.unique(per[ok], return_inverse=True)
            sums = np.bincount(inv, weights=m.num[ok])
            counts = np.bincount(inv)
            if keys.size >= 1 and bool(np.all(counts >= 2)) and bool(np.all((sums >= 95) & (sums <= 105))):
                return True
            continue
        s = float(v.sum())
        if 95 <= s <= 105:
            return True
        if m.fraction and 0.95 <= s <= 1.05:
            return True
    return False


# ── профиль ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _py(x: Any) -> Cell:
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return int(f) if f.is_integer() and abs(f) < 2**53 else f
    if isinstance(x, np.integer):
        return int(x)
    return x


def _column_profile(c: _Col) -> ColumnProfile:
    present = c.present if c.present is not None else np.zeros(len(c.cells), dtype=bool)
    idx = np.flatnonzero(present)
    first = last = None
    vmin = vmax = med = None
    if c.kind == "number" and idx.size:
        v = c.num[present]
        vmin, vmax, med = float(v.min()), float(v.max()), float(np.median(v))
        first, last = _py(c.num[idx[0]]), _py(c.num[idx[-1]])
    elif c.kind == "time" and idx.size:
        g = c.gran or "day"
        o = c.tord[present]
        so = np.sort(o)
        vmin, vmax = period_iso(g, int(so[0])), period_iso(g, int(so[-1]))
        med = period_iso(g, int(so[(so.size - 1) // 2]))
        first, last = period_iso(g, int(c.tord[idx[0]])), period_iso(g, int(c.tord[idx[-1]]))
    elif idx.size and c.svals is not None:
        first, last = c.svals[idx[0]], c.svals[idx[-1]]
    samples: list[Cell] = []
    seen: set = set()
    for i in idx:
        raw = c.cells[i]
        if isinstance(raw, str):
            raw = raw.strip()
        key = (type(raw).__name__, raw)
        if key in seen:
            continue
        seen.add(key)
        samples.append(raw)
        if len(samples) >= _SAMPLES:
            break
    return ColumnProfile(
        name=c.name, unit=c.unit, type=c.type, role=c.role, missing=c.missing, distinct=c.distinct, min=vmin, max=vmax,
        median=med, first=first, last=last, outliers=list(c.outlier_rows), samples=samples,
    )


def _size(rows: int) -> DatasetSize:
    return "small" if rows <= _SMALL_ROWS else "medium" if rows <= _MEDIUM_ROWS else "large"


def profile_table(t: Table) -> DatasetProfile:
    """Профиль таблицы: типы и роли колонок, ось времени, пропуски, выбросы, иерархии, части целого, размер, природа,
    пригодность для графика и строка карточки («Временной ряд · 21 строка · 3 колонки»)."""
    n = len(t.rows)
    ncols = len(t.columns) if t.columns else max((len(r) for r in t.rows), default=0)
    names = [t.columns[j] if j < len(t.columns) else f"Колонка {j + 1}" for j in range(ncols)]
    if n and all(len(r) == ncols for r in t.rows):
        columns_cells = [list(col) for col in zip(*t.rows)] if ncols else []
    else:
        columns_cells = [[r[j] if j < len(r) else None for r in t.rows] for j in range(ncols)]

    # строки «Итого» / «Всего»: не данные, а сумма — в статистику не идут, по ним проверяется «доли от итога»
    total = np.zeros(n, dtype=bool)
    for cells in columns_cells:
        tkeys = {
            v for v in set(cells)
            if isinstance(v, str) and len(v) <= 48 and v.lstrip()[:1].lower() in _TOTAL_FIRST and _key_kind(v)[0] == "total"
        }
        if tkeys:
            for i, v in enumerate(cells):
                if v in tkeys:
                    total[i] = True
    if total.all():
        total[:] = False

    cols = [_analyze(j, names[j], t.unit_of(j), columns_cells[j], total, j == 0) for j in range(ncols)]

    # ось времени: первая колонка дат/периодов, которая идёт по порядку или с постоянным шагом (дата договора в списке
    # клиентов — атрибут, а не ось)
    metrics = [c for c in cols if c.role == "metric"]
    row_label = any(
        c.role in ("id", "text") or (c.role == "dimension" and c.distinct == int(c.present.sum()) and c.distinct > 1)
        for c in cols
        if c.present is not None and c.kind != "time"
    )
    axis: Optional[_Col] = None
    for c in cols:
        if c.kind == "time" and c.present is not None and c.present.any() and _axis_candidate(c, row_label):
            axis = c
            break
    time_axis = None
    if axis is not None:
        axis.role = "time"
        time_axis = _time_axis(axis, metrics)

    for m in metrics:
        _find_outliers(m)

    dims = [c for c in cols if c.role == "dimension"]
    labels = [c for c in cols if c.role == "text"]
    data_rows = int(n - int(total.sum()))
    has_label = bool(dims or labels)
    parts = _parts_of_whole(metrics, has_label, axis if axis is not None and dims else None)
    hierarchies = _hierarchies(cols)

    typable, reason = _typable(cols, metrics, dims, axis, data_rows)
    nature = _nature(t, cols, metrics, dims, labels, axis, time_axis, parts, typable, data_rows)
    missing_total = int(sum(c.missing for c in cols))
    outliers = [o for c in cols for o in c.outliers]
    summary = " · ".join(
        (NATURE_LABELS[nature], count_ru(n, "строка", "строки", "строк"), count_ru(ncols, "колонка", "колонки", "колонок"))
    )
    return DatasetProfile(
        table_id=t.id, file=t.file, kind=t.kind, sheet=t.sheet, rows=n, cols=ncols,
        columns=[_column_profile(c) for c in cols], time_axis=time_axis,
        metrics=[c.name for c in metrics], dimensions=[c.name for c in dims], hierarchies=hierarchies,
        missing_total=missing_total, outliers=outliers, parts_of_whole=parts, size=_size(n), nature=nature,
        typable=typable, untypable_reason=reason, summary=summary,
    )


def _typable(cols: list[_Col], metrics: list[_Col], dims: list[_Col], axis: Optional[_Col],
             data_rows: int) -> tuple[bool, Optional[str]]:
    live = [c for c in cols if c.kind != "empty"]
    if data_rows == 0 or not live:
        return False, "строк нет"
    if data_rows == 1:
        if 2 <= len(metrics) <= 6:
            return True, None  # одна строка из нескольких чисел — ключевые показатели
        return False, "одна строка"
    if metrics:
        return True, None
    countable = any(c.distinct < int(c.present.sum()) for c in dims) or (
        axis is not None and axis.distinct < int(axis.present.sum())
    )
    if countable:
        return True, None
    if all(c.type == "text" for c in live):
        return False, "одни текстовые колонки"
    if all(c.distinct == int(c.present.sum()) for c in live):
        return False, "все значения разные, чисел нет"
    return False, "чисел нет — считать нечего"


def _nature(t: Table, cols: list[_Col], metrics: list[_Col], dims: list[_Col], labels: list[_Col],
            axis: Optional[_Col], time_axis: Optional[TimeAxis], parts: bool, typable: bool, data_rows: int) -> Nature:
    if not typable:
        return "untypable"
    if time_axis is not None and metrics:
        gaps = bool(time_axis.missing_periods) or any(m.missing > 0 for m in metrics)
        return "with_gaps" if gaps else "time_series"
    if time_axis is not None and axis is not None and axis.distinct < int(axis.present.sum()):
        return "time_series"  # одни даты с повторами — число событий по периодам
    if t.kind == "text":
        return "text_table"
    if data_rows == 1 and metrics:
        return "kpi"
    if parts:
        return "shares"
    if _kpi_like(cols, metrics, data_rows):
        return "kpi"
    if not metrics:
        return "comparison"  # категории с повторами — сравнение по числу строк
    n_values = int(metrics[0].present.sum())
    if len(metrics) == 1 and not dims and not labels and n_values >= 30:
        return "distribution"
    if data_rows > 30 and len(cols) >= 4:
        return "reference"
    if dims:
        return "comparison"
    if len(metrics) >= 2 and data_rows >= 8:
        return "relationship"
    return "reference"


def _kpi_like(cols: list[_Col], metrics: list[_Col], data_rows: int) -> bool:
    """До 6 разных показателей: колонка-подпись («Показатель») и числа в разных единицах («1,24 млрд ₽», «3 480»).
    Несколько регионов с ростом — это сравнение, а не карточки."""
    if data_rows > 6 or not metrics:
        return False
    labels = [
        c for c in cols
        if c.kind == "string" and c.role in ("dimension", "text") and c.distinct == int(c.present.sum()) == data_rows
    ]
    if not labels:
        return False
    named = any(_KPI_LABEL.search(c.name.lower()) for c in labels)
    mixed = any(m.mixed_units for m in metrics)
    return bool(named or mixed)
