"""Общий разбор ячеек для чтения файлов (`readers.py`) и профиля (`profile.py`): одно место для правил, чтобы таблица
читалась и описывалась одинаково (описание решения §2.1–2.2).

- Числа и величины с единицами: «1 234,5», «1.234.567,8», «$1,200», «(15)», «−12», «+23%», «1,24 млрд ₽», «5K», «1e3»
  → `quantity` (число как написано, множитель, единица, знак «+»); десятичный знак колонки — `decimal_hint`.
- Единицы из заголовков: «Выручка, млн ₽» → («Выручка», «млн ₽») — `split_unit`.
- Даты и периоды: «янв 2025», «IV кв. 2025», «31.01.2025», «2025-W03», время суток → ISO (`period_str`) и
  (зернистость, номер периода) (`period_parts`, `iso_ord`); обратно — `period_iso`. Зернистости: hour, day, week, month,
  quarter, year. Даты Excel числами (45658) — `excel_serial_iso`.
- Пропуски (`MISSING`: «—», «н/д», «#DIV/0!», «NaN», «NA»…) и логические значения (`BOOL`).
- Строка итога — строгое правило (`is_total_label`): «Итого», «Всего:», «Итого по России», «Total»; «Всего клиентов» и
  «Итого выручка» — обычные подписи.

Без модели и без сторонних библиотек; любые строки (знак без числа, пустые скобки, мусор) дают None, а не исключение."""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Optional, Union

__all__ = [
    "word_unit_column",
    "NO_YEAR",
    "forecast_period",
    "season_name",
    "season_ord",
    "BOOL",
    "COUNT_UNITS",
    "CURRENCIES",
    "MISSING",
    "TIME_HEADER",
    "TOTAL_ROW",
    "Quantity",
    "dayfirst_hint",
    "decimal_hint",
    "excel_serial_iso",
    "header_unit",
    "is_missing",
    "is_total_label",
    "iso_of_datetime",
    "iso_ord",
    "parse_number",
    "parse_period",
    "parse_quantity",
    "period_iso",
    "period_parts",
    "period_str",
    "quantity",
    "split_unit",
    "unit_parts",
    "unit_text",
]

# ======================================================================================================== единицы

_SCALES: dict[str, tuple[str, float]] = {}
for _forms, _canon, _factor in (
    (("тыс", "тыс.", "тысяч", "тысяча", "тысячи", "thousand", "thousands", "k"), "тыс.", 1e3),
    (("млн", "млн.", "миллион", "миллиона", "миллионов", "million", "millions", "mn", "mln", "m"), "млн", 1e6),
    (("млрд", "млрд.", "миллиард", "миллиарда", "миллиардов", "billion", "billions", "bn", "b"), "млрд", 1e9),
    (("трлн", "трлн.", "триллион", "триллиона", "триллионов", "trillion"), "трлн", 1e12),
):
    for _f in _forms:
        _SCALES[_f] = (_canon, _factor)
# латинские k/m/b — только в ячейке сразу за числом («5K», «$1.2M»), в заголовке «m» — это метры
_LATIN_SCALES = {"k", "m", "b", "mn", "mln", "bn"}

_BASE_UNITS: dict[str, str] = {}
for _forms, _canon in (
    (("₽", "руб", "руб.", "рубль", "рубля", "рублей", "рубли", "р", "р.", "rub", "rur"), "₽"),
    (("$", "usd", "долл", "долл.", "доллар", "доллара", "долларов", "доллары"), "$"),
    (("€", "eur", "евро"), "€"),
    (("¥", "cny", "юань", "юаня", "юаней"), "¥"),
    (("£", "gbp"), "£"),
    (("₸", "kzt", "тенге"), "₸"),
    (("%", "％", "проц", "проц.", "процент", "процента", "процентов", "проценты", "percent", "pct"), "%"),
    (("п.п.", "п.п", "п. п.", "пп", "пп.", "pp", "п.п.%"), "п.п."),
    (("ppm", "ррм", "млн⁻¹"), "ppm"),  # доли на миллион: уровень брака, примесей
    (("‰", "промилле"), "‰"),
    (("п.", "пункт", "пункта", "пунктов", "пункты", "pt", "pts"), "п."),
    (("шт", "шт.", "штук", "штука", "штуки"), "шт."),
    (("чел", "чел.", "человек", "человека"), "чел."),
    (("мин", "мин.", "минут", "минута", "минуты", "min"), "мин"),
    (("сек", "сек.", "секунд", "секунда", "секунды", "с", "с.", "s"), "с"),
    (("ч", "ч.", "час", "часа", "часов", "часы", "h"), "ч"),
    (("дн", "дн.", "день", "дня", "дней", "дни", "сут", "сут.", "суток"), "дн."),
    (("нед", "нед.", "неделя", "недели", "недель"), "нед."),
    (("мес", "мес.", "месяц", "месяца", "месяцев"), "мес."),
    (("лет", "год", "года", "годы"), "лет"),
    (("балл", "балла", "баллов", "баллы", "б."), "баллов"),
    (("раз", "раза", "x", "×"), "раз"),
    (("ед", "ед.", "единиц", "единицы"), "ед."),
    # счётные слова в шапке («Scopus, статей», «Приём, мест»): единица — то, что считают
    # (их набор — COUNT_UNITS: такая «единица» верна только у числовой колонки)
    (("статья", "статьи", "статей"), "статей"),
    (("публикация", "публикации", "публикаций"), "публикаций"),
    (("заявка", "заявки", "заявок"), "заявок"),
    (("заказ", "заказа", "заказы", "заказов"), "заказов"),
    (("сделка", "сделки", "сделок"), "сделок"),
    (("клиент", "клиента", "клиенты", "клиентов"), "клиентов"),
    (("студент", "студента", "студенты", "студентов"), "студентов"),
    (("сотрудник", "сотрудника", "сотрудники", "сотрудников"), "сотрудников"),
    (("обращение", "обращения", "обращений"), "обращений"),
    (("пользователь", "пользователя", "пользователи", "пользователей"), "пользователей"),
    (("проект", "проекта", "проекты", "проектов"), "проектов"),
    (("патент", "патента", "патенты", "патентов"), "патентов"),
    (("место", "места", "мест"), "мест"),
    (("звонок", "звонка", "звонки", "звонков"), "звонков"),
):
    for _f in _forms:
        _BASE_UNITS[_f] = _canon
COUNT_UNITS = frozenset({"статей", "публикаций", "заявок", "заказов", "сделок", "клиентов", "студентов", "сотрудников",
                         "обращений", "пользователей", "проектов", "патентов", "мест", "звонков"})
# «в неделю», «за месяц» после единицы — темп: «ч в неделю» → «ч/нед.», «₽ в месяц» → «₽/мес.»
_PER_WORDS = {"неделю": "нед.", "неделя": "нед.", "нед": "нед.", "нед.": "нед.", "месяц": "мес.", "мес": "мес.",
              "мес.": "мес.", "день": "день", "сутки": "сутки", "год": "год", "час": "ч", "ч": "ч", "ч.": "ч",
              "минуту": "мин", "мин": "мин", "мин.": "мин", "смену": "смену", "квартал": "кв."}
_PER_ONLY = re.compile(r"^(в|за|на)\s+(день|сутки|неделю|месяц|год|час|квартал|смену|минуту)$", re.IGNORECASE)
_PER_TAIL = re.compile(r"^(?P<u>.+?)\s+(?:в|за|на)\s+(?P<per>\S+)$", re.IGNORECASE)
# единицы, которые пишут как есть (размерности и объёмы)
for _f in (
    "кг", "г", "т", "тонн", "тонны", "ц", "км", "м", "см", "мм", "м²", "м2", "кв. м", "кв.м", "м³", "м3", "куб. м",
    "л", "литров", "га", "вт", "квт", "мвт", "гвт", "квт·ч", "квт*ч", "квтч", "мвт·ч", "гвт·ч", "кб", "мб", "гб",
    "тб", "пб", "кбайт", "мбайт", "гбайт", "тбайт", "кбит/с", "мбит/с", "гбит/с", "мс", "ms", "мгц", "ггц", "°c",
    "°с", "°", "rps", "rpm", "fps", "ops",
):
    _BASE_UNITS.setdefault(_f, _f.replace("квт*ч", "квт·ч"))
_UPPER_KEEP = {"кб": "КБ", "мб": "МБ", "гб": "ГБ", "тб": "ТБ", "пб": "ПБ", "квт": "кВт", "мвт": "МВт", "гвт": "ГВт",
               "вт": "Вт", "квт·ч": "кВт·ч", "мвт·ч": "МВт·ч", "гвт·ч": "ГВт·ч", "мгц": "МГц", "ггц": "ГГц",
               "°c": "°C", "°с": "°C", "кбит/с": "Кбит/с", "мбит/с": "Мбит/с", "гбит/с": "Гбит/с",
               "кбайт": "Кбайт", "мбайт": "Мбайт", "гбайт": "Гбайт", "тбайт": "Тбайт", "rps": "RPS", "rpm": "RPM",
               "fps": "FPS", "ops": "OPS"}
_CUR_SYMBOLS = "₽$€£¥₸"
# канонические валюты (единица ячейки «млн ₽» — деньги)
CURRENCIES = frozenset("₽$€£¥₸")

_SCALE_HEAD = re.compile(
    r"(тыс(?:яч[аи]?)?\.?|млн\.?|миллион(?:а|ов)?|млрд\.?|миллиард(?:а|ов)?|трлн\.?|триллион(?:а|ов)?"
    r"|thousands?|millions?|billions?|trillion|mn|mln|bn|k|m|b)(?![a-zа-яё])\.?",
    re.IGNORECASE,
)


def _base_unit(text: str, strict: bool) -> Optional[str]:
    """Каноническая единица без множителя («руб.» → «₽», «процентов» → «%»); strict — только известные."""
    t = " ".join(text.split()).strip(" ,;:")
    if not t:
        return None
    low = t.lower().replace("ё", "е")
    if low in _BASE_UNITS:
        canon = _BASE_UNITS[low]
        return _UPPER_KEEP.get(canon, canon)
    if "/" in low:  # «₽/мес.», «шт./день», «км/ч»
        parts = [p.strip() for p in t.split("/")]
        if len(parts) == 2 and all(parts):
            left = _base_unit(parts[0], strict=False) if parts[0][:1] not in "0123456789" else None
            right = _base_unit(parts[1], strict=False) if parts[1][:1] not in "0123456789" else None
            known = parts[0].lower() in _BASE_UNITS or parts[1].lower() in _BASE_UNITS
            if left and right and (known or not strict):
                return f"{left}/{right}"
        return None
    # только известные единицы: число с незнакомым словом или буквой — подпись («5А», «11 кл.», «1 курс»), а не величина
    return None


def unit_parts(text: str, *, strict: bool, cell: bool = False) -> Optional[tuple[Optional[str], float, Optional[str]]]:
    """Единица → (множитель словом, множитель числом, база): «млн руб.» → («млн», 1e6, «₽»), «%» → (None, 1, «%»),
    «ч в неделю» → (None, 1, «ч/нед.»)."""
    t = " ".join(text.split()).strip()
    m = _PER_ONLY.match(t)
    if m:  # «в день», «в год», «за смену» без единицы — темп как написан («Заказов, в день»)
        return None, 1.0, f"{m.group(1).lower()} {m.group(2).lower()}"
    t = re.sub(r"^(?:в|in)\s+", "", t, flags=re.IGNORECASE)
    if not t:
        return None
    m = _PER_TAIL.match(t)
    if m and m.group("per").lower() in _PER_WORDS:
        inner = unit_parts(m.group("u"), strict=True, cell=cell)
        if inner is not None and inner[2] is not None:
            return inner[0], inner[1], f"{inner[2]}/{_PER_WORDS[m.group('per').lower()]}"
    if re.fullmatch(r"т\.?\s?р\.?|тр\.?|т\.\s?руб\.?", t, flags=re.IGNORECASE):
        return "тыс.", 1e3, "₽"
    scale_word, factor, rest = None, 1.0, t
    m = _SCALE_HEAD.match(t)
    if m:
        word = m.group(1)
        key = word.lower().rstrip(".")
        latin = key in _LATIN_SCALES
        # «m» в заголовке — метры, «b» — не миллиард; в ячейке «5K», «1.2M» — множитель (заглавная или вплотную)
        allowed = not latin or (cell and (word in {"K", "M", "B", "k", "bn", "mn", "mln"}))
        if key in ("m", "b") and not cell:
            allowed = False
        if allowed and (key in _SCALES or key + "." in _SCALES):
            scale_word, factor = _SCALES.get(key, _SCALES.get(key + "."))
            rest = t[m.end():].strip()
    if not rest:
        return (scale_word, factor, None) if scale_word else None
    # валюта перед множителем: «$ млн», «₽ тыс.»
    if scale_word is None and rest[:1] in _CUR_SYMBOLS:
        tail = rest[1:].strip()
        m2 = _SCALE_HEAD.match(tail)
        if m2 and m2.group(1).lower().rstrip(".") in _SCALES and m2.end() == len(tail):
            scale_word, factor = _SCALES[m2.group(1).lower().rstrip(".")]
            return scale_word, factor, _BASE_UNITS[rest[0]]
    base = _base_unit(rest, strict=strict)
    if base is None:
        return None
    return scale_word, factor, base


def unit_text(scale_word: Optional[str], base: Optional[str]) -> Optional[str]:
    return " ".join(p for p in (scale_word, base) if p) or None


def header_unit(text: str) -> Optional[str]:
    """Строка — единица измерения целиком («млн ₽», «руб.», «%», «шт.», «в %») → каноническая, иначе None."""
    parts = unit_parts(text, strict=True)
    if parts is None:
        return None
    return unit_text(parts[0], parts[2])


_PAREN_TAIL = re.compile(r"^(?P<name>.*?)\s*[(\[](?P<unit>[^()\[\]]{1,30})[)\]]\s*$")
_TRAIL_SYMBOL = re.compile(r"^(?P<name>.*?\S)\s*(?P<unit>[%％₽$€£¥₸])$")
_TRAIL_SCALE = re.compile(
    r"^(?P<name>.*?\S)\s+(?P<unit>(?:в\s+)?(?:тыс\.?|млн\.?|млрд\.?|трлн\.?)\s*[^\s,]{0,8})$", re.IGNORECASE
)
_TRAIL_IN = re.compile(r"^(?P<name>.*?\S)\s+(?P<unit>в\s+(?:%|процентах|рублях|долларах|евро|штуках|минутах|часах|днях))$",
                       re.IGNORECASE)
_IN_WORDS = {"процентах": "%", "рублях": "₽", "долларах": "$", "евро": "€", "штуках": "шт.", "минутах": "мин",
             "часах": "ч", "днях": "дн."}


_COMPOUND_UNIT = re.compile(r"^(?:[%‰]|[^\W\d_]{1,6}\.?(?:\s?[·*]\s?[^\W\d_]{1,4}\.?)?)\s*/\s*\d{0,4}\s*[^\W\d_]{1,8}\.?"
                            r"(?:\s+(?:на|в|за)\s+[^\W\d_]{1,12})?$")
_PCT_YOY = re.compile(r"^%\s*(?:г/г|г\.\s?г\.|y/y|yoy|к\s+прошлому\s+году|к\s+пред\w*\s+году|годовых|в\s+год|"
                      r"годовые|p\.a\.|per\s+annum|в\s+месяц|в\s+день)$", re.IGNORECASE)


def compound_unit(text: str) -> Optional[str]:
    """Составная единица после запятой: «л/100 км», «мг/л», «л/сут на человека» — как написана; «% г/г», «% годовых»
    → «%»."""
    t = " ".join(str(text or "").split())
    if _PCT_YOY.match(t):
        return "%"
    if len(t) <= 30 and _COMPOUND_UNIT.match(t):
        return t
    return None


def split_unit(header: Any) -> tuple[str, Optional[str]]:
    """Заголовок колонки → (имя без единицы, единица): «Выручка, млн ₽» → («Выручка», «млн ₽»), «Доля (%)» →
    («Доля», «%»), «Цена, руб.» → («Цена», «₽»), «Количество, шт.» → («Количество», «шт.»). Скобки и запятые,
    за которыми не единица, остаются в имени: «Выручка (план)», «Город, регион»."""
    text = " ".join(str(header if header is not None else "").split()).strip()
    if not text:
        return "", None
    # «Выручка (млн ₽)», «Доля [%]»
    m = _PAREN_TAIL.match(text)
    if m and m.group("name"):
        unit = header_unit(m.group("unit"))
        if unit:
            return _clean_name(m.group("name")), unit
    # «Выручка, млн ₽», «Выручка, млн ₽, план» — единица в любой части через запятую; составная «X/Y» («л/100 км»,
    # «мг/л», «л/сут на человека») — тоже единица (величина на единицу), «% г/г» — проценты
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        for k in range(len(parts) - 1, 0, -1):
            unit = header_unit(parts[k]) or compound_unit(parts[k])
            if unit and parts[0]:
                rest = [p for i, p in enumerate(parts) if i != k and p]
                return _clean_name(", ".join(rest)), unit
    # «Доля в %», «Сумма в рублях»
    m = _TRAIL_IN.match(text)
    if m:
        w = m.group("unit").split()[-1].lower()
        return _clean_name(m.group("name")), "%" if w == "%" else _IN_WORDS.get(w)
    # «Выручка млн ₽», «Население тыс. чел.»
    m = _TRAIL_SCALE.match(text)
    if m:
        unit = header_unit(m.group("unit"))
        if unit:
            return _clean_name(m.group("name")), unit
    # «Рост %», «Цена ₽»
    m = _TRAIL_SYMBOL.match(text)
    if m:
        return _clean_name(m.group("name")), header_unit(m.group("unit"))
    # «% выполнения плана» — единица ясна, имя оставляем как есть
    if text.startswith("%") and len(text) > 2:
        return text, "%"
    return _clean_name(text), None


def _clean_name(name: str) -> str:
    n = " ".join(name.split()).strip(" ,;:")
    return n.replace("**", "").replace("__", "").replace("`", "").strip()


# ======================================================================================================== числа

SPACE_CHARS = "            　"
_SPACE_TRANS = str.maketrans({c: " " for c in SPACE_CHARS})
_PLAIN_INT = re.compile(r"-?(?:0|[1-9]\d{0,14})")
_PLAIN_DEC = re.compile(r"-?(?:0|[1-9]\d{0,14})\.(\d+)")
_PLAIN_COMMA = re.compile(r"-?(?:0|[1-9]\d{0,14}),(\d+)")
_SPACED_NUM = re.compile("(-?[1-9]\\d{0,2}(?:[   ]\\d{3})+)(?:,(\\d+))?")
_NUM_HEAD = re.compile(r"[\d '’.,]*\d(?:[eE][+\-]?\d+)?")
_GROUP_SPACE = re.compile(r"(\d{1,3}(?: \d{3})+)(?:([.,])(\d+))?")
_GROUP_COMMA_DOT = re.compile(r"\d{1,3}(?:,\d{3})+\.\d+")
_GROUP_DOT_COMMA = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+")
_GROUP_COMMAS = re.compile(r"\d{1,3}(?:,\d{3}){2,}")
_GROUP_DOTS = re.compile(r"\d{1,3}(?:\.\d{3}){2,}")
_SIMPLE = re.compile(r"(\d*)(?:([.,])(\d+))?(?:[eE]([+\-]?\d+))?")
_SIGNS = "+-−–"


class Quantity:
    """Число из ячейки: значение как написано (без множителя), целое ли оно, единица (множитель словом, множитель,
    база) и явный знак «+» («+23%» — похоже на изменение)."""

    __slots__ = ("value", "is_int", "scale", "factor", "base", "plus")

    def __init__(self, value: float, is_int: bool, scale: Optional[str], factor: float, base: Optional[str],
                 plus: bool = False):
        self.value, self.is_int, self.scale, self.factor, self.base, self.plus = value, is_int, scale, factor, base, plus

    @property
    def unit(self) -> Optional[str]:
        return unit_text(self.scale, self.base)

    @property
    def full(self) -> float:
        """Значение с множителем: «1,24 млрд» → 1.24e9."""
        return self.value * self.factor

    @property
    def pct(self) -> bool:
        return self.base in ("%", "п.п.")

    @property
    def money(self) -> bool:
        return self.base in CURRENCIES


def _core_number(core: str, dec: Optional[str]) -> Optional[tuple[float, bool]]:
    """Цифры с разделителями → (значение, целое ли). dec — десятичный разделитель колонки («,» или «.»), если известен."""
    c = core.replace("'", " ").replace("’", " ")
    if " " in c:
        m = _GROUP_SPACE.fullmatch(c)
        if not m:
            return None
        whole = m.group(1).replace(" ", "")
        if m.group(3) is not None:
            if dec is not None and m.group(2) != dec and len(m.group(3)) == 3:
                return None  # «1 234.567» при десятичной запятой — не число
            return float(f"{whole}.{m.group(3)}"), False
        return float(whole), True
    has_comma, has_dot = "," in c, "." in c
    if has_comma and has_dot:
        if c.rfind(",") > c.rfind("."):
            if not _GROUP_DOT_COMMA.fullmatch(c):
                return None
            return float(c.replace(".", "").replace(",", ".")), False
        if not _GROUP_COMMA_DOT.fullmatch(c):
            return None
        return float(c.replace(",", "")), False
    if c.count(",") > 1:
        return (float(c.replace(",", "")), True) if _GROUP_COMMAS.fullmatch(c) else None
    if c.count(".") > 1:
        return (float(c.replace(".", "")), True) if _GROUP_DOTS.fullmatch(c) else None
    m = _SIMPLE.fullmatch(c)
    if not m:
        return None
    whole, sep, frac, exp = m.group(1), m.group(2), m.group(3), m.group(4)
    if not whole and not frac:
        return None
    if len(whole) > 1 and whole[0] == "0":
        return None  # «007», «01.2025» — код или дата, не число
    if sep is not None:
        # «1,234» / «1.234»: тысячи, если колонка пишет десятичную дробь другим знаком
        if len(frac) == 3 and 1 <= len(whole) <= 3 and whole != "0" and dec is not None and dec != sep and exp is None:
            return float(whole + frac), True
        text = f"{whole or '0'}.{frac}" + (f"e{exp}" if exp else "")
        v = float(text)
        return (v, False) if math.isfinite(v) else None
    if exp is not None:
        v = float(f"{whole}e{exp}")
        return (v, False) if math.isfinite(v) else None
    if len(whole) > 15:
        return None  # длинные цифры — номер (ИНН, счёт), не величина
    return float(whole), True


def quantity(s: str, dec: Optional[str] = None, strict: bool = False) -> Optional[Quantity]:
    """Ячейка целиком — число с необязательными знаком, валютой и единицей; иначе None («SUP-48213», «2025-01», «+»).
    dec — десятичный знак колонки («,» / «.»; None — по записи). strict — единица только из словаря («1 тур»,
    «2 место» — не числа: так пишут шапку)."""
    if _PLAIN_INT.fullmatch(s):
        if len(s.lstrip("-")) > 15:
            return None
        return Quantity(float(int(s)), True, None, 1.0, None)
    m = _PLAIN_DEC.fullmatch(s)
    if m and not (dec == "," and len(m.group(1)) == 3):
        return Quantity(float(s), False, None, 1.0, None)
    m = _PLAIN_COMMA.fullmatch(s)
    if m and not (dec == "." and len(m.group(1)) == 3):
        return Quantity(float(s.replace(",", ".")), False, None, 1.0, None)
    m = _SPACED_NUM.fullmatch(s)
    if m and (m.group(2) is None or dec != "." or len(m.group(2)) != 3):
        whole = m.group(1).replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
        if m.group(2) is None:
            return Quantity(float(int(whole)), True, None, 1.0, None)
        return Quantity(float(f"{whole}.{m.group(2)}"), False, None, 1.0, None)
    t = s.translate(_SPACE_TRANS).strip()
    if not t:
        return None
    neg = plus = False
    if len(t) >= 2 and t[0] == "(" and t[-1] == ")":
        neg, t = True, t[1:-1].strip()
    t = t.rstrip("*").rstrip()
    if t and t[0] in "~≈":
        t = t[1:].lstrip()
    cur = None
    for _ in range(2):  # «-$5», «$-5», «−5»
        if t and t[0] in _SIGNS:
            if t[0] == "+":
                plus = True
            else:
                neg = not neg
            t = t[1:].lstrip()
        elif t and t[0] in _CUR_SYMBOLS and cur is None:
            cur, t = t[0], t[1:].lstrip()
    if not t or not (t[0].isdigit() or (t[0] in ".," and t[1:2].isdigit())):
        return None
    if t[0] in ".,":
        t = "0" + t
    m = _NUM_HEAD.match(t)
    if not m:
        return None
    core, rest = m.group(0), t[m.end():].strip()
    # «$1,200», «£2,500» — запись по-английски: запятая разделяет тысячи
    parsed = _core_number(core, dec if (dec is not None or cur not in ("$", "£")) else ".")
    if parsed is None:
        return None
    value, is_int = parsed
    scale, factor, base = None, 1.0, None
    if rest:
        if rest[0].isdigit() or rest[0] in "-–—:/+=<>":
            return None
        if rest[0] in _CUR_SYMBOLS and cur is not None:
            return None
        parts = unit_parts(rest, strict=strict, cell=True)
        if parts is None:
            return None
        scale, factor, base = parts
    if cur is not None:
        if base is not None and base != _BASE_UNITS[cur]:
            return None
        base = _BASE_UNITS[cur]
    if neg:
        value = -value
    return Quantity(value, is_int, scale, factor, base, plus)


_WORD_CELL = re.compile(r"^(?P<num>[-+−]?\d[\d \u00a0\u202f.,]*)\s+(?P<word>[^\W\d_]{2,}\.?)$")


def word_unit_column(strings: list[str], dec: Optional[str] = None) -> Optional[tuple[dict[str, Quantity], str]]:
    """Колонка «число + слово» с одним словом у всех («30 задач», «12 задач», «7 задач»; «10 рейсов», «3 рейса») →
    числа и это слово как единица. Только по прямому однородному признаку: таких ячеек не меньше трёх и это все
    непустые ячейки, у слов общая основа (от 4 букв), слово — не одна буква, числа — не подряд 1, 2, 3… (так пишут
    классы, этажи, курсы, туры: «5 класс», «6 класс», «1 курс»). Иначе None — ячейки остаются как в файле."""
    if len(strings) < 3:
        return None
    out: dict[str, Quantity] = {}
    words: list[str] = []
    for raw in strings:
        m = _WORD_CELL.match(" ".join(raw.split()))
        if not m:
            return None
        q = quantity(m.group("num").strip(), dec)
        if q is None or q.base is not None or q.scale is not None:
            return None
        out[raw] = q
        words.append(m.group("word"))
    low = [w.lower().rstrip(".") for w in words]
    stem = low[0][:4]
    if any(not w.startswith(stem) for w in low) or len(stem) < 2:
        return None
    if len(set(low)) > 1 and len(stem) < 4:
        return None
    ints = sorted({int(q.value) for q in out.values() if q.is_int})
    if len(ints) == len(out) or len(ints) >= 3:
        if len(ints) >= 2 and ints == list(range(ints[0], ints[0] + len(ints))):
            return None  # 5, 6, 7 … — номера (классы, этажи), а не количества
    unit = max(set(words), key=lambda w: (words.count(w), w))
    return {k: Quantity(q.value, q.is_int, None, 1.0, unit) for k, q in out.items()}, unit


def parse_quantity(s: Any, decimal: Optional[str] = None) -> Optional[tuple[float, Optional[str]]]:
    """Ячейка → (число, единица): «1,24 млрд ₽» → (1.24, «млрд ₽»), «+23%» → (23.0, «%»), «3 480» → (3480.0, None),
    «+6 п.» → (6.0, «п.»). Число — как написано, без умножения на множитель. Не число — None."""
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return None if isinstance(s, float) and not math.isfinite(s) else (float(s), None)
    text = str(s).strip()
    if not text:
        return None
    q = quantity(text, decimal)
    return None if q is None else (q.value, q.unit)


def parse_number(s: Any) -> Optional[float]:
    """Число из ячейки или None: «1 234,5» → 1234.5, «46 %» → 46.0, «−12» → -12.0, «1,2 млн ₽» → 1.2, «(15)» → -15.0;
    «SUP-48213», «2025-01», «Москва» → None."""
    q = parse_quantity(s)
    return None if q is None else q[0]


_DEC_COMMA = re.compile(r"\d,\d{1,2}(?!\d)|\d,\d{4,}|^[-+−]?0,\d|\d \d{3},\d|\.\d{3},\d")
_DEC_COMMA_THOUSANDS = re.compile(r"\d,\d{3},\d{3}|,\d{3}\.\d")
_DEC_DOT = re.compile(r"\d\.\d{1,2}(?!\d)|\d\.\d{4,}|^[-+−]?0\.\d|\d \d{3}\.\d|,\d{3}\.\d")
_DEC_DOT_THOUSANDS = re.compile(r"\d\.\d{3}\.\d{3}|\.\d{3},\d")
_ONE_GROUP = re.compile(r"[1-9]\d{0,2}([.,])(\d{3})")
_NUM_CORE = re.compile(r"\s*[-+−–(]?\s*[$€£₽]?\s*(\d[\d.,]*)")


def decimal_hint(strings: list[str], file_hint: Optional[str] = None) -> Optional[str]:
    """Десятичный разделитель колонки по однозначным записям («1 234,5», «1,234.5», «0.25»). Если однозначных нет, а все
    записи с точкой — «1.234», «2.500», «12.000» (одна группа из трёх цифр) и среди них есть «…00» или рядом целые от
    100 («950»), точка — разделитель тысячи (кроме CSV через запятую, где точка — дробь). Запятая с тремя знаками
    («75,500») остаётся дробью: так пишут курсы и коэффициенты."""
    comma = dot = 0
    for s in strings[:2000]:
        if "," in s:
            if _DEC_COMMA.search(s):
                comma += 1
            elif _DEC_COMMA_THOUSANDS.search(s):
                dot += 1
        if "." in s:
            if _DEC_DOT.search(s):
                dot += 1
            elif _DEC_DOT_THOUSANDS.search(s):
                comma += 1
    if comma and not dot:
        return ","
    if dot and not comma:
        return "."
    if not comma and not dot:
        seps: set[str] = set()
        round_group = big_int = False
        grouped = 0
        for s in strings[:2000]:
            m = _NUM_CORE.match(s)
            if not m:
                continue
            core = m.group(1)
            g = _ONE_GROUP.fullmatch(core)
            if g:
                seps.add(g.group(1))
                grouped += 1
                round_group |= g.group(2).endswith("00")
            elif core.isdigit():
                big_int |= len(core) >= 3 and core[0] != "0"
            elif "," in core or "." in core:
                return file_hint  # другая запись с разделителем — не ряд «тысяч»
        # только точка: «75,500», «1,250» в русской таблице — дробь с тремя знаками, а не тысячи
        if grouped and seps == {"."} and (round_group or big_int) and file_hint != ".":
            return ","
    return file_hint


_DATE_PREFIX = re.compile(r"\s*(\d{1,2})([./\-])(\d{1,2})[./\-]\d{2,4}")


def dayfirst_hint(strings: list[str], english: bool = False) -> bool:
    """День первым («02.03.2025» — 2 марта)? По колонке: число > 12 на месте дня или месяца решает. Если ни одно не
    решает, «01/02/2025» в таблице с английскими заголовками — месяц первым (так пишут в США), иначе — день первым."""
    first_big = second_big = slash = False
    for s in strings[:2000]:
        m = _DATE_PREFIX.match(s)
        if m:
            a, b = int(m.group(1)), int(m.group(3))
            first_big |= a > 12
            second_big |= b > 12
            slash |= m.group(2) == "/"
    if second_big and not first_big:
        return False
    if first_big:
        return True
    return not (english and slash)


# ======================================================================================================== пропуски, да/нет, итог

MISSING = frozenset({
    "", "-", "--", "---", "—", "–", "−", "...", "…", "?", "н/д", "нд", "н.д.", "н/а", "нет данных", "n/a", "na", "nan",
    "null", "none", "nil", "#н/д", "#n/a", "#div/0!", "#дел/0!", "#ref!", "#ссылка!", "#value!", "#знач!", "#name?",
    "#имя?", "#num!", "#число!", "#null!", "#пусто!", "#error!",
})
MISSING_FIRST = frozenset({m[0] for m in MISSING if m} | {m[0].upper() for m in MISSING if m})

BOOL: dict[str, bool] = {
    "да": True, "нет": False, "true": True, "false": False, "yes": True, "no": False, "истина": True, "ложь": False,
    "y": True, "n": False, "д": True,
}


def is_missing(s: Any) -> bool:
    """Пусто или знак пропуска («—», «н/д», «NaN», «#DIV/0!»)."""
    if s is None:
        return True
    if isinstance(s, float):
        return not math.isfinite(s)
    if not isinstance(s, str):
        return False
    t = s.strip()
    return not t or (len(t) <= 10 and t.lower() in MISSING)


# Строгое правило строки итога: подпись — только «итого / всего / итог / общий итог / общая сумма / total / в сумме /
# в целом», можно с «:», единицей через запятую («Итого, млн ₽») и «по …» / «за …». «Всего клиентов», «Итого выручка»,
# «Всего лишь пробный» — обычные подписи.
TOTAL_ROW = re.compile(
    r"^(?:итого(?:\s+общ[а-яё]*)?|всего|итог|общий итог|общая сумма|total|grand total|в сумме|в целом|"
    # «Все продукты», «Все регионы», «All products» — сводная строка по всем, а не ещё одна категория
    r"все\s+(?:продукты|регионы|сервисы|филиалы|магазины|отделы|подразделения|каналы|направления|клиенты|сегменты|"
    r"компании|команды|категории|товары|города|страны|школы|вузы|группы|площадки|тарифы)|all\s+[a-z]+)"
    r"(?:\s*[:.])?(?:\s*,\s*[^,]{1,20})?(?:\s+(?:по|за)\s.+)?$",
    re.IGNORECASE,
)
TOTAL_FIRST = frozenset("иИвВоОtTgGaA")  # первые буквы подписей итога
_TOTAL_FIRST = TOTAL_FIRST


def is_total_label(s: Any) -> bool:
    """Подпись строки итога по строгому правилу: «Итого», «Всего:», «Итого по России», «Total»."""
    if not isinstance(s, str):
        return False
    t = s.strip()
    if not t or len(t) > 60 or t[0] not in _TOTAL_FIRST:
        return False
    return bool(TOTAL_ROW.match(" ".join(t.split())))


TIME_HEADER = re.compile(
    r"\b(?:дата|date|день|day|недел[яи]|week|месяц|month|квартал|quarter|кв|год|года|годы|year|период|period|fy"
    r"|timestamp|datetime)\b",
    re.IGNORECASE,
)

# ======================================================================================================== даты и периоды

_MONTH_FORMS: dict[str, int] = {}
for _k, _forms in enumerate(
    [
        ("январь", "января", "январе", "янв", "january", "jan"),
        ("февраль", "февраля", "феврале", "фев", "февр", "february", "feb"),
        ("март", "марта", "марте", "мар", "march", "mar"),
        ("апрель", "апреля", "апреле", "апр", "april", "apr"),
        ("май", "мая", "мае", "may"),
        ("июнь", "июня", "июне", "июн", "june", "jun"),
        ("июль", "июля", "июле", "июл", "july", "jul"),
        ("август", "августа", "августе", "авг", "august", "aug"),
        ("сентябрь", "сентября", "сентябре", "сен", "сент", "september", "sep", "sept"),
        ("октябрь", "октября", "октябре", "окт", "october", "oct"),
        ("ноябрь", "ноября", "ноябре", "ноя", "нояб", "november", "nov"),
        ("декабрь", "декабря", "декабре", "дек", "december", "dec"),
    ],
    start=1,
):
    for _f in _forms:
        _MONTH_FORMS[_f] = _k
_MON = "(?P<mon>" + "|".join(sorted(_MONTH_FORMS, key=len, reverse=True)) + r")\.?"
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_QWORD = r"(?:q|кв\.?|квартал[а-я]{0,2})"
_ORD = r"(?:\s*-?\s*(?:й|ый|ой|ий))?"

_P_ISO = re.compile(
    r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[t ](\d{1,2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?\s*(?:z|[+\-]\d{2}:?\d{2})?)?"
)
_P_DMY = re.compile(r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{4}|\d{2})(?:[ t,]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_P_YM = re.compile(r"(\d{4})[-/.](\d{1,2})")
_P_MY = re.compile(r"(\d{1,2})[./\-](\d{4})")
_P_YEAR = re.compile(r"(?:fy\s*)?(\d{4})")
_P_WEEK = re.compile(r"(\d{4})-?w(\d{1,2})")
_P_Q_NUM_Y = re.compile(_QWORD + r"\s*([1-4])[\s'’/.,\-]*(\d{4}|\d{2})")
_P_NUM_Q_Y = re.compile(r"(iv|i{1,3}|[1-4])" + _ORD + r"\s*" + _QWORD + r"[\s'’/.,\-]*(\d{4}|\d{2})")
_P_Y_Q_NUM = re.compile(r"(\d{4})\s*[-/ ]?\s*" + _QWORD + r"\s*([1-4])")
_P_Y_NUM_Q = re.compile(r"(\d{4})[\s,]+(iv|i{1,3}|[1-4])" + _ORD + r"\s*" + _QWORD)
_P_MON_Y = re.compile(_MON + r"[\s.,'’/\-–]*(?P<y>\d{4}|\d{2})")
_P_Y_MON = re.compile(r"(?P<y>\d{4})[\s.,/\-]+" + _MON)
_P_D_MON_Y = re.compile(r"(?P<d>\d{1,2})[\s.\-]*" + _MON + r"[\s.,'’\-–]*(?P<y>\d{4}|\d{2})")
_P_MON_D_Y = re.compile(_MON + r"\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})")
_YEAR_TAIL = re.compile(r"(\d{2,4})\s*(?:г\.?|гг\.?|года?|year)$")
_PERIOD_FIRST = frozenset("0123456789qкijfadmnosпамиоянфдсвi")


def _year(text: str) -> Optional[int]:
    y = int(text)
    if len(text) == 2:
        y += 2000 if y < 70 else 1900
    return y if 1900 <= y <= 2100 else None


def _iso_date(y: Optional[int], mo: int, d: int, hh: Any = None, mm: Any = None, ss: Any = None) -> Optional[str]:
    if y is None:
        return None
    try:
        day = dt.date(y, mo, d)
    except ValueError:
        return None
    if hh is not None and (int(hh), int(mm or 0), int(ss or 0)) != (0, 0, 0):
        if not (0 <= int(hh) < 24 and 0 <= int(mm or 0) < 60 and 0 <= int(ss or 0) < 60):
            return None
        tail = f"T{int(hh):02d}:{int(mm or 0):02d}" + (f":{int(ss):02d}" if ss and int(ss) else "")
        return day.isoformat() + tail
    return day.isoformat()


def period_str(s: str, dayfirst: bool = True, years: bool = True) -> Optional[str]:
    """Строка → ISO-период или None: «янв 2025» → «2025-01», «IV кв. 2025» → «2025-Q4», «31.01.2025 10:30» →
    «2025-01-31T10:30». dayfirst — порядок «дд.мм» (решение колонки); years=False — голые годы («2025») не период."""
    t = " ".join(s.translate(_SPACE_TRANS).lower().replace("ё", "е").split())
    if not t or len(t) > 40:
        return None
    t = _YEAR_TAIL.sub(r"\1", t).strip(" ,")
    if not t or t[0] not in _PERIOD_FIRST:
        return None
    m = _P_ISO.fullmatch(t)
    if m:
        return _iso_date(int(m.group(1)) if 1900 <= int(m.group(1)) <= 2100 else None, int(m.group(2)),
                         int(m.group(3)), m.group(4), m.group(5), m.group(6))
    m = _P_DMY.fullmatch(t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        d, mo = (a, b) if dayfirst else (b, a)
        if mo > 12 and d <= 12:
            d, mo = mo, d
        return _iso_date(_year(m.group(3)), mo, d, m.group(4), m.group(5), m.group(6))
    m = _P_YM.fullmatch(t)
    if m:
        y, mo = _year(m.group(1)), int(m.group(2))
        return f"{y}-{mo:02d}" if y and 1 <= mo <= 12 else None
    m = _P_MY.fullmatch(t)
    if m:
        y, mo = _year(m.group(2)), int(m.group(1))
        return f"{y}-{mo:02d}" if y and 1 <= mo <= 12 else None
    m = _P_YEAR.fullmatch(t)
    if m:
        if not years and not t.startswith("fy"):
            return None
        y = _year(m.group(1))
        return str(y) if y else None
    m = _P_WEEK.fullmatch(t)
    if m:
        y, w = _year(m.group(1)), int(m.group(2))
        if not y or not 1 <= w <= 53:
            return None
        try:
            dt.date.fromisocalendar(y, w, 1)
        except ValueError:
            return None  # 53-й недели в этом году нет
        return f"{y}-W{w:02d}"
    for pat, qi, yi in ((_P_Q_NUM_Y, 1, 2), (_P_NUM_Q_Y, 1, 2), (_P_Y_Q_NUM, 2, 1), (_P_Y_NUM_Q, 2, 1)):
        m = pat.fullmatch(t)
        if m:
            y = _year(m.group(yi))
            return f"{y}-Q{_ROMAN[m.group(qi)]}" if y else None
    for pat in (_P_MON_Y, _P_Y_MON):
        m = pat.fullmatch(t)
        if m:
            y = _year(m.group("y"))
            return f"{y}-{_MONTH_FORMS[m.group('mon')]:02d}" if y else None
    for pat in (_P_D_MON_Y, _P_MON_D_Y):
        m = pat.fullmatch(t)
        if m:
            return _iso_date(_year(m.group("y")), _MONTH_FORMS[m.group("mon")], int(m.group("d")))
    return None


# ── месяцы и кварталы без года («Январь», «1 квартал», «Q3») ──────────────────────────────────────────────────────────
# год неизвестен (климат по месяцам, сезонность): условные годы 1, 2, … — в тексте года нет («январь», «III кв.»)
NO_YEAR = 1
_P_Q_ONLY = re.compile(r"(?:" + _QWORD + r"\s*([1-4])|(iv|i{1,3}|[1-4])" + _ORD + r"\s*" + _QWORD + r")")


def season_name(s: Any) -> Optional[tuple[str, int]]:
    """Месяц или квартал без года: «Январь», «янв.», «January» → («month», 1); «1 квартал», «III кв.», «Q3» →
    («quarter», 3). Иначе None (в том числе «январь 2025» — это уже период)."""
    if not isinstance(s, str):
        return None
    t = " ".join(s.translate(_SPACE_TRANS).lower().replace("ё", "е").split()).strip(" .,")
    if not t or len(t) > 20:
        return None
    if t in _MONTH_FORMS:
        return "month", _MONTH_FORMS[t]
    m = _P_Q_ONLY.fullmatch(t)
    if m:
        return "quarter", _ROMAN[m.group(1) or m.group(2)]
    return None


def season_ord(gran: str, k: int, start_year: int, start_k: int) -> int:
    """Номер периода месяца (квартала) без года на оси, которая начинается с (start_year, start_k): месяцы раньше
    начального — уже следующий год (учебный год «сентябрь … август»)."""
    y = start_year if k >= start_k else start_year + 1
    return y * 12 + k - 1 if gran == "month" else y * 4 + k - 1


def iso_of_datetime(v: Union[dt.datetime, dt.date, dt.time]) -> str:
    if isinstance(v, dt.datetime):
        return _iso_date(v.year, v.month, v.day, v.hour, v.minute, v.second) or v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return v.strftime("%H:%M") + (f":{v.second:02d}" if v.second else "")


def parse_period(s: Any) -> Optional[str]:
    """Дата или период → ISO-строка: «янв 2025», «Январь 2025», «01.2025», «2025-01» → «2025-01»; «IV кв. 2025»,
    «Q4 2025», «4 квартал 2025» → «2025-Q4»; «2025», «2025 г.» → «2025»; «31.01.2025», «31 января 2025»,
    datetime → «2025-01-31». Не дата — None."""
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (dt.datetime, dt.date)):
        return iso_of_datetime(s)
    if isinstance(s, (int, float)):
        if isinstance(s, float) and not s.is_integer():
            return None
        return str(int(s)) if 1900 <= s <= 2100 else None
    return period_str(str(s))


_ISO_OUT = re.compile(
    r"(\d{4})(?:-(\d{2})(?:-(\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?)?)?|-Q([1-4])|-W(\d{2}))?", re.IGNORECASE
)


def iso_ord(iso: str, with_time: bool = False) -> Optional[tuple[str, int]]:
    """ISO-строка периода → (зернистость, номер периода): «2025» → («year», 2025), «2025-Q1» → («quarter», 2025·4),
    «2025-01» → («month», 2025·12), «2025-W05» → («week», …), «2025-01-31» → («day», номер дня);
    with_time — «2025-01-31T10:30» → («hour», день·24 + 10) (полночь — день). Не ISO — None."""
    m = _ISO_OUT.fullmatch(iso)
    if not m:
        return None
    y = int(m.group(1))
    if not (1900 <= y <= 2100 or NO_YEAR <= y < NO_YEAR + 10):  # условный год месяцев без года
        return None
    if m.group(6):
        return "quarter", y * 4 + int(m.group(6)) - 1
    if m.group(7):
        try:
            return "week", (dt.date.fromisocalendar(y, int(m.group(7)), 1).toordinal() - 1) // 7
        except ValueError:
            return None
    if m.group(2) is None:
        return "year", y
    mo = int(m.group(2))
    if not 1 <= mo <= 12:
        return None
    if m.group(3) is None:
        return "month", y * 12 + mo - 1
    try:
        day = dt.date(y, mo, int(m.group(3))).toordinal()
    except ValueError:
        return None
    if with_time and m.group(4) is not None:
        hh, mm = int(m.group(4)), int(m.group(5))
        if hh > 23 or mm > 59:
            return None
        if hh or mm:
            return "hour", day * 24 + hh
    return "day", day


_FORECAST_AFTER = re.compile(r"^(?P<p>.+?)\s*(?:\(\s*(?:прогноз|оценка|ожид\.?|план|п|f|e|fc|est)\s*\)|"
                             r"(?<=\d)\s*(?:п|f|e)\.?|\s+(?:прогноз|оценка|ожид\.?|\(?прогн\.?\)?))$", re.I)
_FORECAST_BEFORE = re.compile(r"^(?:прогноз|оценка|ожид\.?|ожидание|план|forecast|fc|est)\s*(?:на\s+)?(?P<p>.+)$", re.I)


def forecast_period(s: Any) -> Optional[str]:
    """Период-прогноз: «2026П», «2026 (прогноз)», «Прогноз 2026», «2026F», «План 2026», «III кв. 2026 (оценка)» → сам
    период без пометки («2026»); иначе None. Прогноз — не факт: в рост и «за N месяцев» не входит."""
    if not isinstance(s, str):
        return None
    t = " ".join(s.split())
    m = _FORECAST_AFTER.match(t) or _FORECAST_BEFORE.match(t)
    if m is None:
        return None
    base = m.group("p").strip(" ,")
    return base if period_str(base) is not None or re.fullmatch(r"(?:19|20)\d\d", base) else None


def period_parts(s: str, dayfirst: bool = True, years: bool = True,
                 with_time: bool = False) -> Optional[tuple[str, int]]:
    """Строка с датой или периодом → (зернистость, номер периода) или None. ISO из чтения разбирается сразу, остальное —
    через `period_str` («янв 2025», «IV кв. 2025», «31.01.2025»). Период-прогноз («2026П») — тот же период (что это
    прогноз, отмечает `forecast_period`)."""
    r = iso_ord(s, with_time)
    if r is not None:
        return r
    fc = forecast_period(s)
    if fc is not None:
        return period_parts(fc, dayfirst, True, with_time)
    iso = period_str(s, dayfirst, years)
    return None if iso is None else iso_ord(iso, with_time)


def period_iso(gran: str, ordinal: int) -> str:
    """ISO периода: «2025-01-31T10:00», «2025-01-31», «2025-W05», «2025-01», «2025-Q1», «2025»."""
    o = int(ordinal)
    if gran == "month":
        return f"{o // 12:04d}-{o % 12 + 1:02d}"
    if gran == "quarter":
        return f"{o // 4:04d}-Q{o % 4 + 1}"
    if gran == "year":
        return f"{o:04d}"
    if gran == "week":
        y, w, _ = dt.date.fromordinal(o * 7 + 1).isocalendar()
        return f"{y:04d}-W{w:02d}"
    if gran == "hour":
        return f"{dt.date.fromordinal(o // 24).isoformat()}T{o % 24:02d}:00"
    return dt.date.fromordinal(o).isoformat()


_EXCEL_EPOCH = dt.datetime(1899, 12, 30)
EXCEL_SERIAL_MIN, EXCEL_SERIAL_MAX = 20000, 60000  # 1954–2064: даты, а не суммы и не годы


def excel_serial_iso(v: float, epoch: Optional[dt.datetime] = None) -> Optional[str]:
    """Дата Excel числом (дни от 30.12.1899; книга Mac — от 01.01.1904) → ISO: 45658 → «2025-01-01», 45658,5 →
    «2025-01-01T12:00». Вне 20 000–60 000 — None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    if not EXCEL_SERIAL_MIN <= v <= EXCEL_SERIAL_MAX:
        return None
    base = epoch if isinstance(epoch, dt.datetime) else _EXCEL_EPOCH
    d = base + dt.timedelta(minutes=round(float(v) * 1440))
    return iso_of_datetime(d.replace(second=0))
