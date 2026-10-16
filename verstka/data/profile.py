"""Профиль датасета (описание решения §2.2): `profile_table(t: Table) -> DatasetProfile`.

Для каждой колонки — тип (число, проценты, деньги, дата, период, категория, текст, логическое, идентификатор), роль (ось
времени, измерение, метрика, идентификатор, подпись, атрибут), пропуски, число разных значений, min/max/медиана, выбросы и
образцы. Для таблицы — ось времени с частотой и пропущенными периодами, метрики и измерения, иерархии («город → регион»),
части целого, размер, природа («Временной ряд · 21 строка · 3 колонки») и пригодность для графика.

Всё считается детерминированным кодом, без модели: один и тот же `Table` всегда даёт один и тот же профиль. Ячейки из
чтения (числа, ISO-строки) берутся как есть; строки разбираются тем же кодом, что и при чтении файла
(`verstka/data/parse.py`): «1 234,5», «46 %», «1,24 млрд ₽», «янв 2025», «IV кв. 2025», «31.01.2025». Строки итога
(`Table.totals` или подпись «Итого»/«Всего:» по строгому правилу) в статистику не идут, по ним проверяются «доли от
итога». Разбор строк идёт по уникальным значениям, статистика — в numpy: 100 тыс. строк × 10 колонок — меньше
секунды."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import numpy as np

from verstka.data.parse import (
    BOOL,
    MISSING,
    Quantity,
    dayfirst_hint,
    decimal_hint,
    is_total_label,
    period_iso,
    period_parts,
    quantity,
    split_unit,
    word_unit_column,
)
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

# подсказки по имени колонки
_YEAR_NAME = re.compile(r"(?:^|[^а-яёa-z])(?:год|года|годы|year|г)(?:[^а-яёa-z]|$)")
_ID_NAME = re.compile(
    r"(?:^|[^а-яёa-z])(?:id|ид|no|номер|код|артикул|инн|огрн|кпп|sku|uuid|guid|идентификатор|ключ)(?:[^а-яёa-z]|$)|[№#]"
)
_MONEY_NAME = re.compile(
    r"выручк|доход|прибыл|стоимост|цен[аыу]|зарплат|оклад|чек|себестоим|стипенди|дебет|кредит|сальдо|revenue|price|"
    r"cost|income|profit|sales"
)
# «бюджет» (места), «расход» (топлива), «оборот», «факт» — деньги, только если на это что-то указывает: «сумма»,
# «руб.», «финансирование» в имени или величина рублей (от 10 000, медиана от 5 000). Малые значения («Бюджет: 120
# мест», «Расход топлива: 12,5») — числа; с ростом масштаба тип меняется только в сторону денег
_WEAK_MONEY_NAME = re.compile(r"бюджет|затрат|расход|оборот|(?:^|[^а-яё])(?:факт|план)(?:[^а-яёо]|$)|фактическ|прогноз")
# пары «план / факт / прогноз / бюджет» — один вердикт: если одна из них деньги, то и соседние того же порядка
_PLAN_FACT = re.compile(r"(?:^|[^а-яё])(?:план|факт|прогноз|бюджет)|фактическ|плановы")
_MONEY_HINT = re.compile(r"сумм|руб|₽|финанс|средств|деньг|денеж")
_PERCENT_NAME = re.compile(r"%|процент|доля|доли|share|percent|конверси")
_FRACTION_NAME = re.compile(r"доля|доли|share|удельн")
# доли целого называют так; проценты-ставки (конверсия, маржа, загрузка) в сумме ≈ 100 случайно — это не доли
_SHARE_NAME = re.compile(r"дол[яиюей]|share|структур|удельн|вклад|распределени|состав")
_RATE_NAME = re.compile(
    r"конверси|загрузк|марж|рентабельн|выполнени|ставк|доходност|эффективн|отток|удержани|оборачиваем|"
    r"conversion|margin|utili[sz]ation|rate|churn|retention"
)
_CHANGE_NAME = re.compile(r"изменени|(?:^|[^а-яё])(?:при)?рост|динамик|разниц|отклонени|к прошл|г/г|yoy|δ|дельта|\bvs\b")
_KPI_LABEL = re.compile(r"показател|метрик|kpi|индикатор|параметр")
_PARENT_NAME = re.compile(
    r"регион|област|край|округ|стран|республик|континент|категори|групп|раздел|отдел|департамент|подразделени|дивизион|"
    r"направлени|сегмент|отрасл|бренд|марк[аи]|семейств|филиал|класс|тип|институт|факультет|школ|кампус|дирекци"
)
# номер места или объекта (не мера): «Аудитория 101», «Кабинет», «Этаж», «Ряд», «Место», «Квартира», «Дом», «Корпус»;
# множественное число — уже счёт («Аудиторий», «Этажей», «Домов»)
_PLACE_NAME = re.compile(
    r"(?:^|[^а-яё])(?:аудитори[яи]|кабинет|этаж|ряд|место|квартира|дом|корпус|номер|код|комнат[аы]|палат[аы]|"
    r"участок|секци[яи]|стенд|бокс|ячейк[аи]|пункт)(?![а-яё])|№"
)
# интервал или время суток в расписании: «09:00–10:30», «9.00-10.30», «14:10»
_TIME_INTERVAL = re.compile(r"^\d{1,2}[:.]\d{2}(?:\s*[–—\-]\s*\d{1,2}[:.]\d{2})?$")
_ID_VALUE = re.compile(r"^(?=.*\d)[0-9a-zа-яё_\-/.#:№]{2,40}$", re.I)


# ── числа и время (разбор — общий с чтением файлов: verstka/data/parse.py) ────────────────────────────────────────────
def parse_number_value(cell: Cell) -> Optional[float]:
    """Число ячейки с множителем («1,24 млрд» → 1.24e9, «46 %» → 46.0, «(15)» → −15); None — не число или пусто."""
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if math.isfinite(cell) else None
    q = quantity(_norm(str(cell)))
    return None if q is None else q.full


def parse_time_value(cell: Cell) -> Optional[tuple[str, int]]:
    """Дата или период ячейки → (зернистость day|week|month|quarter|year, порядковый номер периода); None — не время.
    Номер — день от начала эры, неделя (понедельник), год·12+месяц, год·4+квартал или год; `period_iso` возвращает ISO.
    Время суток здесь не учитывается: «2025-01-31T10:30» → день (часы различает профиль колонки)."""
    if not isinstance(cell, str):
        return None
    return period_parts(_norm(cell))


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
    present: Optional[np.ndarray] = None  # bool по строкам: значение есть (строки итога — нет)
    num: Optional[np.ndarray] = None  # числа по строкам (nan — нет)
    num_total: Optional[np.ndarray] = None  # числа в строках итога (по порядку строк итога)
    tord: Optional[np.ndarray] = None  # номер периода по строкам (_NO_ORD — нет)
    # номера периодов вместе со строками итога («Итого» за 2024 в длинной таблице)
    tord_total: Optional[np.ndarray] = None
    gran: Optional[str] = None
    svals: Optional[list] = None  # нормализованные строки по строкам (None — нет)
    missing: int = 0
    distinct: int = 0
    mixed_units: bool = False  # в ячейках разные единицы («1,24 млрд ₽», «3 480», «52»)
    incomparable: bool = False  # разные базы единиц: min/max/медиана и выбросы бессмысленны
    signed: bool = False
    mark: str = ""  # общая единица из ячеек («%», «млн ₽»)
    fraction: bool = False
    free_text: bool = False  # длинный текст (комментарии), а не подпись строки
    outlier_rows: list[int] = field(default_factory=list)
    hi_fence: float = math.inf  # верхняя граница Тьюки (у колонки без выбросов — бесконечность)
    outliers: list[Outlier] = field(default_factory=list)


def _key_kind(v: Any) -> tuple[str, Any]:
    """Уникальное значение ячейки → ('miss'|'bool'|'num'|'str', значение)."""
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
        if low in MISSING:
            return "miss", None
        if low in BOOL:
            return "bool", BOOL[low]
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
    n_total = int(total.sum())
    # строки итога в выборе типа не участвуют: «Итого» в колонке дат не делает её текстом
    cnt = Counter(cells) if not n_total else Counter(v for v, t in zip(cells, total.tolist()) if not t)
    kinds: dict[Any, tuple[str, Any]] = {k: _key_kind(k) for k in cnt}
    rows = {"miss": 0, "bool": 0, "num": 0, "str": 0}
    for k, (kk, _) in kinds.items():
        rows[kk] += cnt[k]
    present_rows = rows["bool"] + rows["num"] + rows["str"]
    lname = name.lower()
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
            c.type = "date" if gran in ("day", "hour") else "period"
            c.role = "attribute"
            tord = np.fromiter((lookup.get(v, _NO_ORD) for v in cells), dtype=np.int64, count=n)
            if n_total:
                c.tord_total = tord.copy()
                tord[total] = _NO_ORD
            c.tord = tord
            c.present = tord != _NO_ORD
            c.missing = n - n_total - int(c.present.sum())
            c.distinct = int(np.unique(tord[c.present]).size)
            return c

    # числа: родные и из строк («1 234,5», «46 %», «1,24 млрд ₽»)
    parsed: dict[Any, Quantity] = {}
    dec: Optional[str] = None
    if str_keys:
        cand = _sample(str_keys)
        dec = decimal_hint([kinds[k][1] for k in cand])
        if len(cand) < len(str_keys):
            ok = sum(cnt[k] for k in cand if quantity(kinds[k][1], dec) is not None)
            cand = str_keys if ok >= 0.9 * sum(cnt[k] for k in cand) else []
        for k in cand:
            q = quantity(kinds[k][1], dec)
            if q is not None:
                parsed[k] = q
        ok_rows = sum(cnt[k] for k in parsed)
        if not parsed or not _enough(rows["num"] + ok_rows, rows["num"] + rows["str"]):
            parsed = {}
            if not rows["num"] and len(str_keys) <= 5000:  # «30 задач», «12 задач» — общее слово-единица
                wu = word_unit_column([kinds[k][1] for k in str_keys], dec)
                if wu is not None:
                    parsed = {k: wu[0][kinds[k][1]] for k in str_keys}
    if (rows["num"] and not str_keys) or parsed:
        marks: Counter = Counter()
        bases: Counter = Counter()
        if rows["num"]:
            marks[""] += rows["num"]
            bases[""] += rows["num"]
        factors = {1.0} if rows["num"] else set()
        pct_rows = money_rows = signed_rows = 0
        for k, q in parsed.items():
            w = cnt[k]
            marks[q.unit or ""] += w
            bases[q.base or ""] += w
            factors.add(q.factor)
            pct_rows += w if q.pct else 0
            money_rows += w if q.money else 0
            signed_rows += w if q.plus else 0
        mixed_scale = len(factors) > 1
        lookup: dict[Any, float] = {k: v for k, (kk, v) in kinds.items() if kk == "num"}
        for k, q in parsed.items():
            lookup[k] = q.full if mixed_scale else q.value
        c.kind = "number"
        num = np.fromiter((lookup.get(v, np.nan) for v in cells), dtype=float, count=n)
        if n_total:
            # числа строк итога: их значения в выбор типа не входили — разбираются тем же правилом колонки
            tv = []
            for i in np.flatnonzero(total):
                v = cells[i]
                x = lookup.get(v) if v in lookup else _total_number(v, dec, mixed_scale)
                tv.append(np.nan if x is None else x)
            c.num_total = np.asarray(tv, dtype=float)
            num[total] = np.nan
        c.num = num
        c.present = ~np.isnan(num)
        c.missing = n - n_total - int(c.present.sum())
        nn = max(rows["num"] + sum(cnt[k] for k in parsed), 1)
        c.signed = signed_rows > 0 and signed_rows >= 0.5 * nn
        c.mixed_units = len(marks) > 1
        c.incomparable = len(bases) > 1
        if len(marks) == 1 and not mixed_scale:
            c.mark = next(iter(marks))
        elif len(bases) == 1 and mixed_scale and c.unit is None:
            c.mark = next(iter(bases))  # «1,2 млн ₽» и «800 тыс. ₽» приведены к рублям
        _type_number(c, lname, pct_rows / nn, money_rows / nn, first_col)
        return c

    # строки: идентификатор, категория, текст
    c.kind = "string"
    smap = {k: (v if kk == "str" else _str_of(k)) for k, (kk, v) in kinds.items() if kk in ("str", "num", "bool")}
    c.svals = [smap.get(v) for v in cells]
    _finish_strings(c, total)
    _type_string(c, lname)
    return c


def _total_number(v: Any, dec: Optional[str], mixed_scale: bool) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    q = quantity(_norm(str(v)), dec)
    if q is None:
        return None
    return q.full if mixed_scale else q.value


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
    dayfirst = dayfirst_hint([kinds[k][1] for k in cand])

    def parse(k: Any) -> Optional[tuple[str, int]]:
        return period_parts(kinds[k][1], dayfirst, True, True)

    if len(cand) < len(str_keys):
        ok = sum(cnt[k] for k in cand if parse(k) is not None)
        if ok < 0.9 * sum(cnt[k] for k in cand):
            return None
    parsed: dict[Any, tuple[str, int]] = {}
    for k in str_keys:
        r = parse(k)
        if r is not None:
            parsed[k] = r
    if not _enough(sum(cnt[k] for k in parsed), str_rows):
        return None
    if any(g == "hour" for g, _ in parsed.values()):
        # время суток: несколько времён в один день и ряд по часам плотный (≥ 80% часов или не дольше трёх суток) —
        # ось по часам (на коротком отрезке — от 50%); журнал событий (заказы в рабочие часы) и по одному времени в
        # день — по дням.
        # Минуты не различаются: записи раз в 15 минут ложатся на часовую ось по нескольку в час
        hours = {(o if g == "hour" else o * 24) for g, o in parsed.values() if g in ("hour", "day")}
        by_hour = len(hours) > len({h // 24 for h in hours})
        if by_hour:
            hs = np.array(sorted(hours), dtype=np.int64)
            step = max(int(np.gcd.reduce(np.diff(hs))), 1)
            expected = int((hs[-1] - hs[0]) // step) + 1
            dense = hs.size >= 0.8 * expected
            short = int(hs[-1] - hs[0]) <= 72 and hs.size >= 0.5 * expected
            if short and not dense and len({int(h) // 24 for h in hs}) >= 2 and 24 - len({int(h) % 24 for h in hs}) >= 6:
                short = False  # каждый день одни и те же часы (рабочий день 09–18) — ночи не пропуски: ось по дням
            by_hour = dense or short
        for k, (g, o) in list(parsed.items()):
            if g == "hour" and not by_hour:
                parsed[k] = ("day", o // 24)
            elif g == "day" and by_hour:
                parsed[k] = ("hour", o * 24)
    grans: Counter = Counter()
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
    unit = c.unit if c.unit is not None else (c.mark or split_unit(c.name)[1])
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
    elif integral and v.size >= 3 and _ID_NAME.search(lname) and not unit:
        c.type, c.role = "id", "id"  # «№ п/п», «Код» повторяются по периодам длинной таблицы — всё равно номер
        return
    if integral and v.size >= 2 and not unit and _PLACE_NAME.search(lname):
        c.type, c.role = "id", "id"  # «Аудитория 101, 204», «Квартира 12» — номер места, а не величина
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
    elif _has_currency(lunit) or money_share >= _SHARE_OK or (
            not unit and _money_by_name(lname, integral, vmin, float(np.median(v)) if v.size else 0.0)):
        c.type = "money"
    else:
        c.type = "number"


def _money_by_name(lname: str, integral: bool, vmin: float = 0.0, vmed: float = 0.0) -> bool:
    if _MONEY_NAME.search(lname):
        return True
    if not _WEAK_MONEY_NAME.search(lname):
        return False
    return bool(_MONEY_HINT.search(lname)) or vmin >= 10_000 or vmed >= 5_000


def _plan_fact_money(cols: list[_Col]) -> None:
    """«План» и «Факт» — один вердикт: если одна из колонок «план/факт/прогноз/бюджет» — деньги, соседние того же
    порядка без своей единицы — тоже деньги."""
    pf = [c for c in cols if c.kind == "number" and c.role == "metric" and _PLAN_FACT.search(c.name.lower())]
    money = [c for c in pf if c.type == "money"]
    if not money or len(pf) < 2:
        return
    ref = float(np.median(np.concatenate([np.abs(c.num[c.present]) for c in money])))
    for c in pf:
        if c.type == "number" and not c.unit and c.present.any():
            med = float(np.median(np.abs(c.num[c.present])))
            if ref > 0 and med > 0 and max(ref, med) <= 10 * min(ref, med):
                c.type = "money"


_COMPLEMENT = (("дебет", "кредит"), ("приход", "расход"), ("поступлени", "списани"), ("доход", "расход"))


def _complementary_blanks(cols: list[_Col]) -> None:
    """Дебет/кредит (приход/расход): в строке заполнена одна из пары — пустая клетка другой не пропуск, а «нет операции»."""
    metrics = [c for c in cols if c.kind == "number" and c.present is not None]
    for a_word, b_word in _COMPLEMENT:
        a = next((c for c in metrics if a_word in c.name.lower()), None)
        b = next((c for c in metrics if b_word in c.name.lower() and c is not a), None)
        if a is None or b is None:
            continue
        either = a.present | b.present
        if not bool(np.all(either[a.present | b.present])):
            continue
        a.missing = max(0, a.missing - int(np.count_nonzero(~a.present & b.present)))
        b.missing = max(0, b.missing - int(np.count_nonzero(~b.present & a.present)))


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
        # код по виду значений («SUP-48213») — только у длинной таблицы: «A320», «B737» в коротком списке — подписи
        if (_ID_NAME.search(lname) and c.distinct >= _SHARE_OK * present) or (
            all_unique and present > _LABEL_UNIQUE_MAX and id_like >= _SHARE_OK * len(sample)
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
    if x.size < _MIN_OUTLIER_N or c.incomparable:
        return
    xs = np.sort(x)
    q1, q3 = np.percentile(xs, [25, 75])
    iqr = float(q3 - q1)
    basis = ""
    if iqr <= 0:
        # больше половины значений одинаковые (150 нулей): размах — по остальным значениям, отрыв — от всех
        vals, counts = np.unique(xs, return_counts=True)
        mode = float(vals[int(np.argmax(counts))])
        rest = xs[xs != mode]
        if rest.size < 4:
            return
        q1, q3 = np.percentile(rest, [25, 75])
        iqr = float(q3 - q1)
        if iqr <= 0:
            return
        basis = f" значений, кроме повторяющегося {_fmt(mode)},"
    gap = _TUKEY_K * iqr
    hi_fence, lo_fence = float(q3 + gap), float(q1 - gap)
    c.hi_fence = hi_fence
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
    hi_txt = f"выше границы {_fmt(hi_fence)} (третий квартиль{basis} + 1,5 межквартильного размаха) {apart}"
    lo_txt = f"ниже границы {_fmt(lo_fence)} (первый квартиль{basis} − 1,5 межквартильного размаха) {apart}"
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
        if coverage < 0.5 or (freq == "day" and g not in (1, 7)):
            out_freq = "irregular"  # 2, 5, 11 марта — не ряд «через 3 дня» с пропуском 8-го
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
            if unique_child and not _PARENT_NAME.search(pa.name.lower()) and not _grouped_left(pa, ch, b):
                continue  # подписи строк определяют всё — иерархия, только если родитель назван как группа или
                # стоит левее и идёт блоками («Институт» над своими кафедрами)
            found.append((ch, pa))
    names = {(ch.name, pa.name) for ch, pa in found}
    out = []
    for ch, pa in found:
        if any((ch.name, mid) in names and (mid, pa.name) in names for mid in {p.name for _, p in found}):
            continue  # город → страна при город → регион → страна — лишнее звено
        out.append((ch.name, pa.name))
    return out


def _sums_to_total(m: _Col, axis: Optional[_Col], total_rows: np.ndarray) -> bool:
    """Строки итога равны сумме остальных: в длинной таблице — по каждому периоду («Итого» за 2024 = сумма регионов за
    2024), иначе итог (общий, а не промежуточный) — сумма всех строк."""
    tv = m.num_total
    if tv is None or not np.any(~np.isnan(tv)):
        return False
    v = m.num[m.present]
    if v.size < 2 or bool(np.any(v < 0)):
        return False

    def close(a: float, b: float) -> bool:
        return b > 0 and abs(a - b) <= max(0.01 * b, 0.5)

    if axis is not None and axis.tord_total is not None:
        checked = 0
        for k, r in enumerate(total_rows):
            if np.isnan(tv[k]):
                continue
            p = axis.tord_total[r]
            if p == _NO_ORD:
                return False
            if not close(float(m.num[m.present & (axis.tord == p)].sum()), float(tv[k])):
                return False
            checked += 1
        return checked > 0
    s_all = float(v.sum())
    return any(close(s_all, float(t)) for t in tv if not np.isnan(t))


def _grouped_left(pa: _Col, ch: _Col, codes: np.ndarray) -> bool:
    """Родитель левее дочерней колонки, каждое его значение идёт одним блоком строк, и блоков из трёх строк и больше —
    не меньше трёх: так выгружают иерархию «институт → кафедра», «регион → город» («Пол → Сотрудник» — два блока,
    не иерархия)."""
    if pa.j >= ch.j or codes.size < 9 or not 3 <= pa.distinct <= codes.size // 2:
        return False
    cuts = np.flatnonzero(np.diff(codes)) + 1
    if cuts.size + 1 != np.unique(codes).size:
        return False
    lengths = np.diff(np.concatenate(([0], cuts, [codes.size])))
    return int(np.count_nonzero(lengths >= 3)) >= 3


def _total_column(cols: list[_Col], metrics: list[_Col]) -> tuple[Optional[_Col], list[_Col]]:
    """Колонка-итог по строкам: имя «Всего», «Итого»… и в каждой строке она равна сумме других числовых колонок (всех
    сопоставимых или стоящих подряд перед ней): «Бюджет + Платное + Целевое = Всего». → (итог, части)."""
    for tc in metrics:
        name = tc.name.strip().lower()
        if not (is_total_label(tc.name) or name.startswith(("всего", "итого", "общий итог", "total"))):
            continue
        pool = [m for m in metrics if m is not tc and (m.type != "percent" or tc.type == "percent") and not m.signed
                and not _CHANGE_NAME.search(m.name.lower()) and (m.unit == tc.unit or not m.unit or not tc.unit)]
        left = []
        for m in reversed([m for m in pool if m.j < tc.j]):
            if left and left[-1].j - m.j != 1:
                break
            left.append(m)
        for parts in (pool, sorted(left, key=lambda m: m.j)):
            if len(parts) >= 2 and _row_sums_match(tc, parts):
                return tc, parts
    return None, []


def _row_sums_match(tc: _Col, parts: list[_Col]) -> bool:
    ok = tc.present.copy()
    for m in parts:
        ok &= m.present
    if int(ok.sum()) < 2:
        return False
    s = np.zeros(int(ok.sum()))
    for m in parts:
        s += m.num[ok]
    t = tc.num[ok]
    # допуск — округление записи: у целых 0,5, у дробей полшага последнего знака («2,3» при 1,2 + 0,8 — не сумма)
    step = 0.5 if all(_decimals(m.num[ok]) == 0 for m in [tc, *parts]) else \
        0.51 * 10.0 ** -max(_decimals(m.num[ok]) for m in [tc, *parts])
    close = np.abs(s - t) <= np.maximum(0.01 * np.abs(t), step)
    return float(close.mean()) >= _SHARE_OK


def _decimals(x: np.ndarray) -> int:
    """Сколько знаков после запятой у значений (до 6)."""
    for d in range(7):
        if bool(np.all(np.abs(np.round(x, d) - x) < 1e-9)):
            return d
    return 6


def _strongly_related(metrics: list[_Col], skip: set) -> bool:
    """Две числовые колонки (не изменения, не итог и не части) заметно связаны: |r| ≥ 0,5 на 30+ общих строках —
    «часы подготовки и балл», а не справочник."""
    cand = [m for m in metrics if id(m) not in skip and not m.signed and not m.incomparable
            and not _CHANGE_NAME.search(m.name.lower())][:6]
    for a in range(len(cand)):
        for b in range(a + 1, len(cand)):
            ok = cand[a].present & cand[b].present
            if int(ok.sum()) < 30:
                continue
            x, y = cand[a].num[ok], cand[b].num[ok]
            if float(x.std()) == 0 or float(y.std()) == 0:
                continue
            if abs(float(np.corrcoef(x, y)[0, 1])) >= 0.5 and not _derived_pair(cand[a], cand[b], metrics):
                return True
    return False


def _derived_pair(a: _Col, b: _Col, metrics: list[_Col]) -> bool:
    """Связь по построению, а не находка: одна колонка пропорциональна другой («Розница» = «Закупка» × 1,3), или
    равна произведению либо сумме другой и третьей («Сумма» = «Кол-во» × «Цена»)."""
    ok = a.present & b.present
    x, y = a.num[ok], b.num[ok]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = x / y
    ratio = ratio[np.isfinite(ratio)]
    if ratio.size >= 5 and float(np.mean(ratio)) != 0 and float(np.std(ratio) / abs(np.mean(ratio))) < 0.02:
        return True
    for c in metrics:
        if c is a or c is b:
            continue
        both = a.present & b.present & c.present
        if int(both.sum()) < 5:
            continue
        xa, xb, xc = a.num[both], b.num[both], c.num[both]
        for z, p, q in ((xa, xb, xc), (xb, xa, xc)):
            for made in (p * q, p + q):
                if float(np.mean(np.abs(made - z) <= np.maximum(0.01 * np.abs(z), 0.5))) >= _SHARE_OK:
                    return True
    return False


def _parts_of_whole(metrics: list[_Col], has_label: bool, axis: Optional[_Col], total_rows: np.ndarray) -> bool:
    for m in metrics:
        lname = m.name.lower()
        # «доли от итога»: строка «Итого» равна сумме остальных
        if total_rows.size and _sums_to_total(m, axis, total_rows):
            return True
        v = m.num[m.present]
        if m.type != "percent" or v.size < 2 or not has_label or bool(np.any(v < 0)):
            continue
        if m.signed or _CHANGE_NAME.search(lname) or _RATE_NAME.search(lname):
            continue  # «Рост, %», «Изменение», «Конверсия, %» — не доли, даже если в сумме случайно ≈ 100
        named = bool(_SHARE_NAME.search(lname))
        lo, hi = (95, 105) if named else (99, 101)  # без слова «доля» — только почти ровно 100
        if axis is not None:
            # длинный формат: в каждом периоде доли в сумме ≈ 100
            per = axis.tord
            ok = m.present & (per != _NO_ORD)
            if ok.sum() < 2:
                continue
            keys, inv = np.unique(per[ok], return_inverse=True)
            sums = np.bincount(inv, weights=m.num[ok])
            counts = np.bincount(inv)
            if keys.size >= 1 and bool(np.all(counts >= 2)) and bool(np.all((sums >= lo) & (sums <= hi))):
                return True
            continue
        s = float(v.sum())
        if lo <= s <= hi:
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
    if c.kind == "number" and idx.size and c.incomparable:
        # «1,24 млрд ₽», «3 480», «52» — у каждой строки своя единица: сравнивать и усреднять нечего
        first, last = c.cells[idx[0]], c.cells[idx[-1]]
        first, last = (_norm(x) if isinstance(x, str) else x for x in (first, last))
    elif c.kind == "number" and idx.size:
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

    # строки итога: не данные, а сумма — в статистику не идут, по ним проверяется «доли от итога». Их отмечает чтение
    # (Table.totals); у таблицы, собранной не чтением, — то же строгое правило: первая ячейка строки — «Итого», «Всего:»
    total = np.zeros(n, dtype=bool)
    marked = [i for i in (getattr(t, "totals", None) or []) if isinstance(i, int) and 0 <= i < n]
    if marked:
        total[marked] = True
    elif ncols >= 2 and columns_cells:
        # подпись итога — первая заполненная ячейка строки; разные значения первой колонки проверяются по разу
        col0 = columns_cells[0]
        distinct0 = set(col0)
        keys = {v for v in distinct0 if v.__class__ is str and is_total_label(v)}
        if keys or None in distinct0:
            for i, v in enumerate(col0):
                if v is None:
                    v = next((x for x in t.rows[i] if x is not None), None)
                    if isinstance(v, str) and is_total_label(v):
                        total[i] = True
                elif v in keys:
                    total[i] = True
    if total.all():
        total[:] = False
    total_rows = np.flatnonzero(total)

    cols = [_analyze(j, names[j], t.unit_of(j), columns_cells[j], total, j == 0) for j in range(ncols)]
    _plan_fact_money(cols)
    _complementary_blanks(cols)

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

    # таблица показателей по строкам: у строк свои единицы (Table.row_units) — колонки чисел несравнимы
    row_units = list(getattr(t, "row_units", None) or [])
    if row_units and len({u for i, u in enumerate(row_units) if i < n and not total[i]}) > 1:
        for m in metrics:
            m.incomparable = True
    for m in metrics:
        _find_outliers(m)

    dims = [c for c in cols if c.role == "dimension"]
    labels = [c for c in cols if c.role == "text"]
    data_rows = int(n - int(total.sum()))
    has_label = bool(dims or labels)
    parts = _parts_of_whole(metrics, has_label, axis if axis is not None and dims else None, total_rows)
    total_col, part_cols = _total_column(cols, metrics)
    parts = parts or total_col is not None
    hierarchies = _hierarchies(cols)

    typable, reason = _typable(cols, metrics, dims, axis, data_rows)
    # расписание или перечень: чисел-мер нет, есть номера мест («Аудитория») или интервалы времени («09:00–10:30»)
    schedule = typable and not metrics and data_rows >= 2 and any(
        (c.role == "id" and _PLACE_NAME.search(c.name.lower())) or _time_intervals(c) for c in cols)
    if schedule:
        typable, reason = False, "расписание/перечень"
    skip = {id(c) for c in ([total_col] if total_col is not None else []) + part_cols}
    related = data_rows > 30 and _strongly_related(metrics, skip)
    nature = _nature(t, cols, metrics, dims, labels, axis, time_axis, parts, typable, data_rows, related)
    if schedule:
        nature = "text_table" if t.kind == "text" else "reference"  # таблица как есть; карточка: «Не для графика»
    missing_total = int(sum(c.missing for c in cols))
    outliers, expected = _split_outliers(cols, dims, nature)
    # строки — данные (без строк итога): «Доли · 4 строки», даже если в файле пятой идёт «Итого»
    summary = " · ".join(
        (NATURE_LABELS[nature], count_ru(data_rows, "строка", "строки", "строк"),
         count_ru(ncols, "колонка", "колонки", "колонок"))
    )
    return DatasetProfile(
        table_id=t.id, file=t.file, kind=t.kind, sheet=t.sheet, rows=data_rows, cols=ncols,
        columns=[_column_profile(c) for c in cols], time_axis=time_axis,
        metrics=[c.name for c in metrics], dimensions=[c.name for c in dims], hierarchies=hierarchies,
        missing_total=missing_total, outliers=outliers, expected_outliers=expected, parts_of_whole=parts,
        total_column=total_col.name if total_col is not None else None, part_columns=[c.name for c in part_cols],
        size=_size(data_rows), nature=nature,
        typable=typable, untypable_reason=reason, summary=summary,
    )


# природа, где строка — сущность (клиент, регион, канал): большие значения у крупных — норма, а не выброс-ошибка
_ENTITY_NATURES = frozenset({"reference", "comparison", "shares", "kpi", "text_table"})


def _split_outliers(cols: list[_Col], dims: list[_Col], nature: str) -> tuple[list[Outlier], list[Outlier]]:
    """Выбросы → (заметные, естественные). Естественные — только по прямому признаку: целые категории (все строки
    «Москвы» в длинной таблице по месяцам) или «лестница» крупнейших у сущностей (справочник, сравнение, доли,
    карточки): три значения и больше над границей, каждое не больше чем втрое выше предыдущего (начиная с самого
    большого обычного) и не дальше 10 границ Тьюки — крупнейшие клиенты 212, 177, 158, 142… Заметные — остальное:
    одиночный всплеск, опечатка ×10, доля больше 100%, отрицательное в счёте, любые длительности (минуты, часы, дни)."""
    notable: list[Outlier] = []
    expected: list[Outlier] = []
    for c in cols:
        if not c.outliers:
            continue
        if _category_scale(c.outlier_rows, dims):
            expected += c.outliers
            continue
        natural = _ladder_rows(c) if nature in _ENTITY_NATURES and not _is_duration(c) else set()
        for o in c.outliers:
            (expected if o.row in natural else notable).append(o)
    return notable, expected


_DURATION_NAME = re.compile(r"врем|минут|(?:^|[^а-яё])мин(?:[^а-яё]|$)|час|секунд|(?:^|\s)дн(?:ей|я|и)?(?:\s|$|\.)|"
                            r"суток|длительн|срок|ожидан|задержк")
_DURATION_UNITS = frozenset({"мин", "ч", "с", "мс", "дн.", "нед.", "мес.", "лет"})


def _is_duration(c: _Col) -> bool:
    return (c.unit or "") in _DURATION_UNITS or bool(_DURATION_NAME.search(c.name.lower()))


def _ladder_rows(c: _Col) -> set:
    """Верхние выбросы, которые продолжают «лестницу» от самого большого обычного значения: шаг не больше ×3 и не
    выше 10 границ Тьюки; лестница из трёх и больше — естественна (крупнейшие клиенты), иначе — ничего."""
    present = c.present
    v = c.num[present]
    med = float(np.median(v))
    out = set(c.outlier_rows)
    body = [float(c.num[i]) for i in np.flatnonzero(present) if int(i) not in out]
    if not body:
        return set()
    upper = sorted((float(c.num[r]), r) for r in c.outlier_rows if float(c.num[r]) > med)
    prev = max(body)
    accepted = set()
    for val, r in upper:
        if prev <= 0 or val > 3 * prev or val > 10 * c.hi_fence or (c.type == "percent" and val > 100):
            break
        accepted.add(r)
        prev = val
    return accepted if len(accepted) >= 3 else set()


def _category_scale(rows: list[int], dims: list[_Col]) -> bool:
    """Выбросы — это несколько категорий целиком (у каждой несколько строк и не меньше половины из них — выбросы,
    категорий — не больше половины): разница масштаба категорий, а не ошибки в данных."""
    for d in dims:
        vals = d.svals or []
        hit = Counter(vals[r] for r in rows if r < len(vals) and vals[r] is not None)
        if not hit:
            continue
        per = Counter(v for v in vals if v is not None)
        if len(hit) <= max(1, len(per) // 2) and all(per[k] >= 2 and hit[k] >= 0.5 * per[k] for k in hit):
            return True
    return False


def _time_intervals(c: _Col) -> bool:
    """Колонка строк — интервалы или время суток расписания («09:00–10:30», «14:10»): не меньше 80% значений."""
    vals = [v for v in (c.svals or []) if v is not None]
    return bool(vals) and sum(1 for v in vals if _TIME_INTERVAL.match(str(v))) >= 0.8 * len(vals)


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
            axis: Optional[_Col], time_axis: Optional[TimeAxis], parts: bool, typable: bool, data_rows: int,
            related: bool = False) -> Nature:
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
    if related:
        return "relationship"  # две связанные метрики на 30+ строках — взаимосвязь, даже рядом с id и группой
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
