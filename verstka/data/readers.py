"""Чтение файлов с данными в таблицы `Table` (описание решения §2.1).

Форматы: CSV/TSV (кодировка, разделитель, кавычки, десятичная запятая, пробелы-разделители тысяч), XLSX (все листы,
лист — таблица, даты Excel, проценты по формату ячейки), JSON (массив записей, `{columns, rows}`, «ключ → записи»,
«категория → число», колонки-массивы), текст .txt/.md (таблицы Markdown, блоки через табуляцию, «;» и выровненные
пробелами «столбцы»; текст вокруг таблицы — в `notes`).

Ячейки типизируются по колонке, а не по одной ячейке: числа — int/float («1 234,5», «46 %», «−12», «1,2 млн ₽»),
даты и периоды — ISO-строки («2025-01-31», «2025-01», «2025-Q4», «2025»), да/нет — bool, пропуски («», «—», «н/д») — None.
Единица уходит из заголовка в `Table.units` («Выручка, млн ₽» → «Выручка» + «млн ₽»); одинаковая единица в ячейках
(«46 %») — тоже. Колонка, где у чисел разные единицы (строка показателей «1,24 млрд ₽», «3 480», «356 тыс. ₽»),
остаётся строками как в файле: число и единицу каждой ячейки даёт `parse_quantity`.

Шапка — первая «широкая» строка (заголовки и пустые строки над ней уходят в `notes`); двухэтажная шапка (группа над
подзаголовками, строка единиц под названиями) склеивается. Пустые строки и колонки, безымянная колонка-нумерация,
повтор шапки, строка «Итого» в конце и сноски под таблицей в данные не попадают; титульный лист книги — не таблица;
«выгрузка в Excel», которая на деле текст через табуляцию (.xls), читается как CSV.

`Table` собирается без повторной проверки pydantic (`model_construct`): типы ячеек гарантирует разбор, а 100 тысяч
строк читаются быстрее секунды.

Всё детерминированно и без модели; ошибки — `DataReadError` с человеческим русским текстом."""

from __future__ import annotations

import csv
import datetime as dt
import functools
import hashlib
import io
import json
import math
import re
import sys
import warnings
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Optional, Union

from verstka.schemas.data import Cell, SourceKind, Table

__all__ = [
    "DataReadError",
    "parse_number",
    "parse_period",
    "parse_quantity",
    "read_bytes",
    "read_file",
    "split_unit",
]

csv.field_size_limit(min(sys.maxsize, 1 << 30))


class DataReadError(Exception):
    """Файл не читается как таблица. Текст — для человека, по-русски: «Файл пустой», «Не нашёл таблицу в тексте»."""

    def __init__(self, message: str, *, file: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.file = file

    def __str__(self) -> str:
        return self.message


class _NoData(Exception):
    """Внутреннее: в этом блоке/листе нет строк с данными (сообщение — для единственной таблицы файла)."""


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
):
    for _f in _forms:
        _BASE_UNITS[_f] = _canon
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
    if strict:
        return None
    # в ячейке — короткое слово после числа («3 480 клиентов», «12 месяцев» — не из словаря, но единица)
    if len(t) <= 20 and len(t.split()) <= 2 and re.fullmatch(r"[^\W\d_][\w.\-·°²³ ]*", t) and not re.search(r"\d", t):
        return t
    return None


def _unit_parts(text: str, *, strict: bool, cell: bool = False) -> Optional[tuple[Optional[str], float, Optional[str]]]:
    """Единица → (множитель словом, множитель числом, база): «млн руб.» → («млн», 1e6, «₽»), «%» → (None, 1, «%»)."""
    t = " ".join(text.split()).strip()
    t = re.sub(r"^(?:в|in)\s+", "", t, flags=re.IGNORECASE)
    if not t:
        return None
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
        m2 = _SCALE_HEAD.match(rest[1:].strip())
        if m2 and m2.group(1).lower().rstrip(".") in _SCALES and m2.end() == len(rest[1:].strip()):
            scale_word, factor = _SCALES[m2.group(1).lower().rstrip(".")]
            return scale_word, factor, _BASE_UNITS[rest[0]]
    base = _base_unit(rest, strict=strict)
    if base is None:
        return None
    return scale_word, factor, base


def _unit_text(scale_word: Optional[str], base: Optional[str]) -> Optional[str]:
    return " ".join(p for p in (scale_word, base) if p) or None


def _header_unit(text: str) -> Optional[str]:
    """Строка — единица измерения целиком («млн ₽», «руб.», «%», «шт.», «в %») → каноническая, иначе None."""
    parts = _unit_parts(text, strict=True)
    if parts is None:
        return None
    return _unit_text(parts[0], parts[2])


_PAREN_TAIL = re.compile(r"^(?P<name>.*?)\s*[(\[](?P<unit>[^()\[\]]{1,30})[)\]]\s*$")
_TRAIL_SYMBOL = re.compile(r"^(?P<name>.*?\S)\s*(?P<unit>[%％₽$€£¥₸])$")
_TRAIL_SCALE = re.compile(
    r"^(?P<name>.*?\S)\s+(?P<unit>(?:в\s+)?(?:тыс\.?|млн\.?|млрд\.?|трлн\.?)\s*[^\s,]{0,8})$", re.IGNORECASE
)
_TRAIL_IN = re.compile(r"^(?P<name>.*?\S)\s+(?P<unit>в\s+(?:%|процентах|рублях|долларах|евро|штуках|минутах|часах|днях))$",
                       re.IGNORECASE)
_IN_WORDS = {"процентах": "%", "рублях": "₽", "долларах": "$", "евро": "€", "штуках": "шт.", "минутах": "мин",
             "часах": "ч", "днях": "дн."}


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
        unit = _header_unit(m.group("unit"))
        if unit:
            return _clean_name(m.group("name")), unit
    # «Выручка, млн ₽», «Выручка, млн ₽, план» — единица в любой части через запятую
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        for k in range(len(parts) - 1, 0, -1):
            unit = _header_unit(parts[k])
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
        unit = _header_unit(m.group("unit"))
        if unit:
            return _clean_name(m.group("name")), unit
    # «Рост %», «Цена ₽»
    m = _TRAIL_SYMBOL.match(text)
    if m:
        return _clean_name(m.group("name")), _header_unit(m.group("unit"))
    # «% выполнения плана» — единица ясна, имя оставляем как есть
    if text.startswith("%") and len(text) > 2:
        return text, "%"
    return _clean_name(text), None


def _clean_name(name: str) -> str:
    n = " ".join(name.split()).strip(" ,;:")
    return n.replace("**", "").replace("__", "").replace("`", "").strip()


# ======================================================================================================== числа

_SPACE_CHARS = "\u00a0\u202f\u2009\u2007\u2002\u2003\u2004\u2005\u2006\u2008\u200a\u205f\u3000"
_SPACE_TRANS = str.maketrans({c: " " for c in _SPACE_CHARS})
_PLAIN_INT = re.compile(r"-?(?:0|[1-9]\d{0,14})")
_PLAIN_DEC = re.compile(r"-?(?:0|[1-9]\d{0,14})\.(\d+)")
_PLAIN_COMMA = re.compile(r"-?(?:0|[1-9]\d{0,14}),(\d+)")
_SPACED_NUM = re.compile("(-?[1-9]\\d{0,2}(?:[ \u00a0\u202f]\\d{3})+)(?:,(\\d+))?")
_NUM_HEAD = re.compile(r"[\d '’.,]*\d(?:[eE][+\-]?\d+)?")
_GROUP_SPACE = re.compile(r"(\d{1,3}(?: \d{3})+)(?:([.,])(\d+))?")
_GROUP_COMMA_DOT = re.compile(r"\d{1,3}(?:,\d{3})+\.\d+")
_GROUP_DOT_COMMA = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+")
_GROUP_COMMAS = re.compile(r"\d{1,3}(?:,\d{3}){2,}")
_GROUP_DOTS = re.compile(r"\d{1,3}(?:\.\d{3}){2,}")
_SIMPLE = re.compile(r"(\d*)(?:([.,])(\d+))?(?:[eE]([+\-]?\d+))?")


class _Q:
    """Число из ячейки: значение, целое ли оно, единица (множитель словом, множитель, база)."""

    __slots__ = ("value", "is_int", "scale", "factor", "base")

    def __init__(self, value: float, is_int: bool, scale: Optional[str], factor: float, base: Optional[str]):
        self.value, self.is_int, self.scale, self.factor, self.base = value, is_int, scale, factor, base

    @property
    def unit(self) -> Optional[str]:
        return _unit_text(self.scale, self.base)


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
        return float(text), False
    if exp is not None:
        return float(f"{whole}e{exp}"), False
    if len(whole) > 15:
        return None  # длинные цифры — номер (ИНН, счёт), не величина
    return float(whole), True


def _quantity(s: str, dec: Optional[str] = None, strict: bool = False) -> Optional[_Q]:
    """Ячейка целиком — число с необязательными знаком, валютой и единицей; иначе None («SUP-48213», «2025-01»).
    strict — единица только из словаря («1 тур», «2 место» — не числа: так пишут шапку)."""
    if _PLAIN_INT.fullmatch(s):
        if len(s.lstrip("-")) > 15:
            return None
        return _Q(float(int(s)), True, None, 1.0, None)
    m = _PLAIN_DEC.fullmatch(s)
    if m and not (dec == "," and len(m.group(1)) == 3):
        return _Q(float(s), False, None, 1.0, None)
    m = _PLAIN_COMMA.fullmatch(s)
    if m and not (dec == "." and len(m.group(1)) == 3):
        return _Q(float(s.replace(",", ".")), False, None, 1.0, None)
    m = _SPACED_NUM.fullmatch(s)
    if m and (m.group(2) is None or dec != "." or len(m.group(2)) != 3):
        whole = ("-" if s[0] == "-" else "") + re.sub(r"\D", "", m.group(1))
        if m.group(2) is None:
            return _Q(float(int(whole)), True, None, 1.0, None)
        return _Q(float(f"{whole}.{m.group(2)}"), False, None, 1.0, None)
    t = s.translate(_SPACE_TRANS).strip()
    if not t:
        return None
    neg = False
    if t[0] == "(" and t[-1] == ")":
        neg, t = True, t[1:-1].strip()
    t = t.rstrip("*").rstrip()
    if t[:1] in "~≈":
        t = t[1:].lstrip()
    cur = None
    for _ in range(2):  # «-$5», «$-5», «−5»
        if t[:1] in "+-−–":
            neg ^= t[0] != "+"
            t = t[1:].lstrip()
        elif t[:1] and t[0] in _CUR_SYMBOLS and cur is None:
            cur, t = t[0], t[1:].lstrip()
    if not t or not (t[0].isdigit() or (t[0] in ".," and t[1:2].isdigit())):
        return None
    if t[0] in ".,":
        t = "0" + t
    m = _NUM_HEAD.match(t)
    if not m:
        return None
    core, rest = m.group(0), t[m.end():].strip()
    parsed = _core_number(core, dec)
    if parsed is None:
        return None
    value, is_int = parsed
    scale, factor, base = None, 1.0, None
    if rest:
        if rest[0].isdigit() or rest[0] in "-–—:/+=<>":
            return None
        if rest[0] in _CUR_SYMBOLS and cur is not None:
            return None
        parts = _unit_parts(rest, strict=strict, cell=True)
        if parts is None:
            return None
        scale, factor, base = parts
    if cur is not None:
        if base is not None and base != _BASE_UNITS[cur]:
            return None
        base = _BASE_UNITS[cur]
    if neg:
        value = -value
    return _Q(value, is_int, scale, factor, base)


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
    q = _quantity(text, decimal)
    return None if q is None else (q.value, q.unit)


def parse_number(s: Any) -> Optional[float]:
    """Число из ячейки или None: «1 234,5» → 1234.5, «46 %» → 46.0, «−12» → -12.0, «1,2 млн ₽» → 1.2, «(15)» → -15.0;
    «SUP-48213», «2025-01», «Москва» → None."""
    q = parse_quantity(s)
    return None if q is None else q[0]


# ======================================================================================================== периоды

_MONTH_STEMS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5, "мае": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9,
    "окт": 10, "ноя": 11, "дек": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MON = r"(?P<mon>янв|фев|мар|апр|ма[йяе]|июн|июл|авг|сен|окт|ноя|дек|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-zа-я]{0,6}\.?"
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_QWORD = r"(?:q|кв\.?|квартал[а-я]{0,2})"
_ORD = r"(?:\s*-?\s*(?:й|ый|ой|ий))?"

_P_ISO = re.compile(
    r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[t ](\d{1,2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?\s*(?:z|[+\-]\d{2}:?\d{2})?)?"
)
_P_DMY = re.compile(r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{4}|\d{2})(?:[ t,]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_P_YM = re.compile(r"(\d{4})[-/](\d{1,2})")
_P_MY = re.compile(r"(\d{1,2})[./\-](\d{4})")
_P_YEAR = re.compile(r"(?:fy\s*)?(\d{4})")
_P_WEEK = re.compile(r"(\d{4})-?w(\d{1,2})")
_P_Q_NUM_Y = re.compile(_QWORD + r"\s*([1-4])[\s'’/.,\-]*(\d{4}|\d{2})")
_P_NUM_Q_Y = re.compile(r"(iv|i{1,3}|[1-4])" + _ORD + r"\s*" + _QWORD + r"[\s'’/.,\-]*(\d{4}|\d{2})")
_P_Y_Q_NUM = re.compile(r"(\d{4})\s*[-/ ]?\s*" + _QWORD + r"\s*([1-4])")
_P_Y_NUM_Q = re.compile(r"(\d{4})[\s,]+(iv|i{1,3}|[1-4])" + _ORD + r"\s*" + _QWORD)
_P_MON_Y = re.compile(_MON + r"[\s.,'’/\-]*(?P<y>\d{4}|\d{2})")
_P_Y_MON = re.compile(r"(?P<y>\d{4})[\s.,/\-]+" + _MON)
_P_D_MON_Y = re.compile(r"(?P<d>\d{1,2})[\s.\-]*" + _MON + r"[\s.,'’\-]*(?P<y>\d{4}|\d{2})")
_P_MON_D_Y = re.compile(_MON + r"\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})")
_YEAR_TAIL = re.compile(r"(\d{2,4})\s*(?:г\.?|гг\.?|года?|year)$")


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


def _period(s: str, dayfirst: bool = True, years: bool = True) -> Optional[str]:
    """Строка → ISO-период или None. years=False — голые годы («2025») не считаются периодом (числа колонки)."""
    t = " ".join(s.translate(_SPACE_TRANS).lower().replace("ё", "е").split())
    if not t or len(t) > 40:
        return None
    t = _YEAR_TAIL.sub(r"\1", t).strip(" ,")
    if not t or not (t[0].isdigit() or t[0] in "qкijfadmnosпамиоянфдсвi"):
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
        return f"{y}-W{w:02d}" if y and 1 <= w <= 53 else None
    for pat, qi, yi in ((_P_Q_NUM_Y, 1, 2), (_P_NUM_Q_Y, 1, 2), (_P_Y_Q_NUM, 2, 1), (_P_Y_NUM_Q, 2, 1)):
        m = pat.fullmatch(t)
        if m:
            y = _year(m.group(yi))
            return f"{y}-Q{_ROMAN[m.group(qi)]}" if y else None
    for pat in (_P_MON_Y, _P_Y_MON):
        m = pat.fullmatch(t)
        if m:
            y = _year(m.group("y"))
            return f"{y}-{_MONTH_STEMS[m.group('mon')]:02d}" if y else None
    for pat in (_P_D_MON_Y, _P_MON_D_Y):
        m = pat.fullmatch(t)
        if m:
            return _iso_date(_year(m.group("y")), _MONTH_STEMS[m.group("mon")], int(m.group("d")))
    return None


def _iso_of_datetime(v: Union[dt.datetime, dt.date, dt.time]) -> str:
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
        return _iso_of_datetime(s)
    if isinstance(s, (int, float)):
        if isinstance(s, float) and not s.is_integer():
            return None
        return str(int(s)) if 1900 <= s <= 2100 else None
    return _period(str(s))


# ======================================================================================================== ячейки и колонки

_MISSING = {
    "-", "--", "---", "—", "–", "−", "...", "…", "?", "н/д", "нд", "н.д.", "н/а", "нет данных", "n/a", "nan",
    "null", "none", "nil", "#н/д", "#n/a", "#div/0!", "#дел/0!", "#ref!", "#ссылка!", "#value!", "#знач!", "#name?",
    "#имя?", "#num!", "#число!", "#null!", "#пусто!", "#error!",
}
_MISSING_FIRST = {m[0] for m in _MISSING} | {m[0].upper() for m in _MISSING}
_BOOL = {"да": True, "нет": False, "true": True, "false": False, "yes": True, "no": False, "истина": True,
         "ложь": False}
_TIME_HEADER = re.compile(
    r"\b(?:дата|date|день|day|недел[яи]|week|месяц|month|квартал|quarter|кв|год|года|годы|year|период|period|fy)\b",
    re.IGNORECASE,
)
_TOTAL_ROW = re.compile(r"^(?:итого|всего|итог|total|grand total|в сумме)(?:\s*[:.])?(?:\s+по\s.+)?$", re.IGNORECASE)
_FOOTNOTE = re.compile(r"^(?:\*|примечани|прим\.|источник|сноск|note|source)", re.IGNORECASE)


def _clean_str(s: str) -> str:
    return " ".join(s.split()) if ("  " in s or "\n" in s or "\t" in s or "\r" in s or "\xa0" in s) else s


def _norm_raw(v: Any) -> Any:
    """Сырая ячейка → str (обрезанная) | int | float | bool | None; даты — ISO-строки."""
    if v.__class__ is str:
        s = v.strip()
        if not s or (s[0] in _MISSING_FIRST and len(s) <= 10 and s.lower() in _MISSING):
            return None
        return s
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return _iso_of_datetime(v)
    if isinstance(v, dt.timedelta):
        return str(v)
    return _norm_raw(str(v))


def _norm_row(r: list[Any]) -> list[Any]:
    """`_norm_raw` для строки целиком (быстрый путь для строк: так читается CSV в сотни тысяч строк)."""
    return [
        (s if (s := v.strip()) and not (s[0] in _MISSING_FIRST and len(s) <= 10 and s.lower() in _MISSING) else None)
        if v.__class__ is str else _norm_raw(v)
        for v in r
    ]


def _decimal_hint(strings: list[str], file_hint: Optional[str]) -> Optional[str]:
    """Десятичный разделитель колонки по однозначным записям («1 234,5», «1,234.5», «0.25»)."""
    comma = dot = 0
    for s in strings[:2000]:
        if "," in s:
            if re.search(r"\d,\d{1,2}(?!\d)|\d,\d{4,}|^[-+−]?0,\d|\d \d{3},\d", s) or re.search(r"\.\d{3},\d", s):
                comma += 1
            elif re.search(r"\d,\d{3},\d{3}|,\d{3}\.\d", s):
                dot += 1
        if "." in s:
            if re.search(r"\d\.\d{1,2}(?!\d)|\d\.\d{4,}|^[-+−]?0\.\d|\d \d{3}\.\d", s) or re.search(r",\d{3}\.\d", s):
                dot += 1
            elif re.search(r"\d\.\d{3}\.\d{3}|\.\d{3},\d", s):
                comma += 1
    if comma and not dot:
        return ","
    if dot and not comma:
        return "."
    return file_hint


def _dayfirst_hint(strings: list[str]) -> bool:
    first_big = second_big = False
    for s in strings[:2000]:
        m = re.match(r"\s*(\d{1,2})[./\-](\d{1,2})[./\-]\d{2,4}", s)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            first_big |= a > 12
            second_big |= b > 12
    return not (second_big and not first_big)


def _is_num(v: Any) -> bool:
    return v.__class__ is int or v.__class__ is float or (isinstance(v, (int, float)) and not isinstance(v, bool))


def _type_column(vals: list[Any], name: str, file_decimal: Optional[str]) -> tuple[list[Cell], Optional[str]]:
    """Колонка нормализованных значений (`_norm_raw`) → типизированные ячейки и единица из ячеек (если у всех чисел
    она одна). Решение — по колонке: ≥ 80 % непустых ячеек — числа (с одной единицей) или даты/периоды."""
    counts: Counter = Counter(v for v in vals if v.__class__ is str)
    time_header = bool(_TIME_HEADER.search(name))
    nonstr_num = [v for v in vals if v.__class__ is int or v.__class__ is float]
    years_only = bool(nonstr_num) and all(float(v).is_integer() and 1900 <= v <= 2100 for v in nonstr_num)
    if not counts:
        # уже типизированные значения (XLSX, JSON): годы в колонке «Год» — периоды
        if time_header and years_only:
            return [str(int(v)) if _is_num(v) else v for v in vals], None
        return vals, None
    distinct = list(counts)
    total = sum(counts.values()) + len(nonstr_num)

    # да/нет
    if not nonstr_num and all(s.lower() in _BOOL for s in distinct):
        return [_BOOL[v.lower()] if v.__class__ is str else v for v in vals], None

    dec = _decimal_hint(distinct, file_decimal)
    dayfirst = _dayfirst_hint(distinct)
    sample = distinct[:300]
    s_total = sum(counts[s] for s in sample) or 1
    q_sample = {s: _quantity(s, dec) for s in sample}
    q_share = sum(counts[s] for s in sample if q_sample[s] is not None) / s_total
    p_sample = {s: _period(s, dayfirst, years=time_header) for s in sample}
    p_share = sum(counts[s] for s in sample if p_sample[s] is not None) / s_total
    period_only = any(p_sample[s] is not None and q_sample[s] is None for s in sample)

    if p_share >= 0.8 and (time_header or period_only) and (not nonstr_num or (time_header and years_only)):
        pmap = {s: (p_sample[s] if s in p_sample else _period(s, dayfirst, years=time_header)) for s in distinct}
        hits = sum(counts[s] for s in distinct if pmap[s] is not None) + len(nonstr_num)
        if hits >= 0.8 * total:
            return [pmap[v] if v.__class__ is str else (str(int(v)) if _is_num(v) else None) for v in vals], None

    if q_share >= 0.8:
        typed = _numeric_column(vals, distinct, counts, q_sample, dec, total)
        if typed is not None:
            return typed
    return [_clean_str(v) if v.__class__ is str else v for v in vals], None


def _numeric_column(vals: list[Any], distinct: list[str], counts: Counter, q_sample: dict, dec: Optional[str],
                    total: int) -> Optional[tuple[list[Cell], Optional[str]]]:
    qmap: dict[str, Optional[_Q]] = {}
    for s in distinct:
        qmap[s] = q_sample[s] if s in q_sample else _quantity(s, dec)
    nonstr = total - sum(counts.values())
    hits = sum(counts[s] for s in distinct if qmap[s] is not None) + nonstr
    if hits < 0.8 * total:
        return None
    units: Counter = Counter()
    for s in distinct:
        q = qmap[s]
        if q is not None:
            units[(q.scale, q.factor, q.base)] += counts[s]
    plain = (None, 1.0, None)
    keys = [k for k in units if k != plain]
    if len(keys) <= 1:
        if keys and keys[0][0] is not None and (units.get(plain) or nonstr):
            return None  # «1,2 тыс.» рядом с «800» — неясно, в чём «800»
        target = keys[0] if keys else plain
    else:
        bases = {k[2] for k in units}
        if len(bases) != 1 or (None in bases and units.get(plain)):
            return None  # разные единицы (строка показателей «1,24 млрд ₽», «3 480») — оставить как в файле
        # «1,2 млн ₽» и «800 тыс. ₽» — к самому частому множителю
        target = max(keys, key=lambda k: (units[k], k[1]))
    t_scale, t_factor, t_base = target

    def conv(q: _Q) -> Union[int, float]:
        if q.factor == t_factor:
            v = q.value
            return int(v) if q.is_int and abs(v) < 2**53 else v
        v = float(f"{q.value * q.factor / t_factor:.12g}")
        return int(v) if v.is_integer() and abs(v) < 2**53 else v

    cmap = {s: (conv(q) if q is not None else None) for s, q in qmap.items()}
    out: list[Cell] = [cmap[v] if v.__class__ is str else (None if v.__class__ is bool else v) for v in vals]
    return out, _unit_text(t_scale, t_base)


# ======================================================================================================== таблица из строк

_YEARISH = re.compile(r"(?:19|20)\d\d(?:\s*(?:г\.?|год))?")


def _kind(v: Any) -> str:
    """Вид нормализованной ячейки для поиска шапки: empty | num | year | period | text."""
    if v is None:
        return "empty"
    if v.__class__ is bool:
        return "num"
    if _is_num(v):
        return "year" if float(v).is_integer() and 1900 <= v <= 2100 else "num"
    if _YEARISH.fullmatch(v):
        return "year"
    if _quantity(v, strict=True) is not None:
        return "num"
    if _period(v, True, years=False) is not None:
        return "period"
    return "text"


def _header_like(kinds: list[str]) -> bool:
    """Строка похожа на шапку: больше половины заполненных ячеек — названия (годы и периоды — если их ≥ 2: шапка
    «Регион · 2024 · 2025»)."""
    filled = [k for k in kinds if k != "empty"]
    if not filled:
        return False
    text = filled.count("text")
    timey = filled.count("year") + filled.count("period")
    score = text + (timey if timey >= 2 else 0)
    return (text >= 1 or timey >= 2) and score * 2 > len(filled)


def _filled(row: list[Any]) -> int:
    return sum(1 for v in row if v is not None)


def _row_text(row: list[Any]) -> str:
    return " ".join(str(v) for v in row if v is not None)


def _numbers_below(below: list[list[Any]], j: int) -> bool:
    kinds = [_kind(r[j]) for r in below[:20] if j < len(r) and r[j] is not None]
    return bool(kinds) and sum(k in ("num", "year") for k in kinds) * 2 > len(kinds)


def _merge_headers(h1: list[Any], h2: list[Any], below: list[list[Any]], width: int) -> Optional[list[str]]:
    """Двухэтажная шапка → один ряд названий; None — второй ряд не шапка. Склеивает строку единиц под названиями
    («Выручка» / «млн ₽») и подзаголовки под объединённой группой («Выручка» над «2024», «2025»)."""
    k2 = [_kind(h2[j]) if j < len(h2) else "empty" for j in range(width)]
    filled2 = [j for j in range(width) if k2[j] != "empty"]
    if not filled2:
        return None
    s1 = [str(h1[j]) if j < len(h1) and h1[j] is not None else "" for j in range(width)]
    s2 = [str(h2[j]) if k2[j] != "empty" else "" for j in range(width)]
    # строка единиц под названиями: «млн ₽», «%», «чел.»
    if (
        all(s1[j] and _header_unit(s2[j]) for j in filled2)
        and any(_numbers_below(below, j) for j in filled2)
    ):
        return [f"{s1[j]}, {s2[j]}" if s2[j] else s1[j] for j in range(width)]
    if not _header_like(k2):
        return None
    if not any(not s1[j] and s2[j] for j in range(width)):
        return None
    # подзаголовок стоит над числами хотя бы в одной колонке
    if not any(k2[j] in ("text", "year", "period") and _numbers_below(below, j) for j in filled2):
        return None
    names, group = [], ""
    for j in range(width):
        if s1[j]:
            group = s1[j]
        elif not s2[j]:
            group = ""
        parent = s1[j] or (group if s2[j] else "")
        if parent and s2[j]:
            pn, pu = split_unit(parent)
            cn, cu = split_unit(s2[j])
            unit = cu or pu
            names.append(f"{pn} {cn}" + (f", {unit}" if unit else ""))
        else:
            names.append(parent or s2[j])
    return names


def _group_row(row: list[Any]) -> bool:
    """Строка групп над шапкой: одни названия, и не одно название в первой ячейке (это заголовок отчёта)."""
    pos = [j for j, v in enumerate(row) if v is not None]
    if not pos or not all(_kind(row[j]) == "text" for j in pos):
        return False
    return len(pos) >= 2 or pos[0] >= 1


def _table_id(digest: str, index: int) -> str:
    return hashlib.sha1(f"{digest}:{index}".encode()).hexdigest()[:12]


def _build_table(
    rows: list[list[Any]],
    *,
    file: str,
    kind: SourceKind,
    sheet: Optional[str],
    tid: str,
    notes: str = "",
    header_row: Optional[int] = -1,
    decimal: Optional[str] = None,
    first_name: str = "",
) -> Table:
    """Строки сырых ячеек → Table. header_row: -1 — найти шапку, None — шапки нет, k — шапка в строке k.
    first_name — имя безымянной первой колонки (ключи JSON-объекта), иначе «Колонка 1»."""
    rows = [_norm_row(r) for r in rows]
    for r in rows:
        while r and r[-1] is None:
            r.pop()
    while rows and not rows[-1]:
        rows.pop()
    lead = 0
    while lead < len(rows) and not rows[lead]:
        lead += 1
    rows = rows[lead:]
    if header_row is not None and header_row >= 0:
        header_row = max(0, header_row - lead)
    if not rows:
        raise _NoData("Файл пустой")

    note_lines: list[str] = []
    scan = rows[:60]
    # пустые ячейки слева от названий — безымянная колонка-индекс («,Выручка»): строка всё равно «широкая»
    leads = [next((k for k, v in enumerate(r) if v is not None), 0) for r in scan]
    edge = min((k for k, r in zip(leads, scan) if r), default=0)
    counts = [_filled(r) + (k - edge if r else 0) for k, r in zip(leads, scan)]
    wide_counts = Counter(c for c in counts if c >= 2)
    width_est = max(wide_counts.items(), key=lambda kv: (kv[1], kv[0]))[0] if wide_counts else 1
    min_fill = 1 if width_est < 2 else max(2, math.ceil(width_est * 0.6))

    header: Optional[list[Any]] = None
    merged_names: Optional[list[str]] = None
    if header_row == -1:
        # шапка — первая «широкая» строка; название отчёта и пустые строки над ней — заметки
        h = next((i for i, c in enumerate(counts) if c >= min_fill), 0)
        # «Источник:;Росстат» над настоящей шапкой
        while h + 1 < len(scan) and counts[h + 1] >= min_fill:
            first = next((v for v in rows[h] if v is not None), None)
            if isinstance(first, str) and first.endswith(":") and _header_like([_kind(v) for v in rows[h + 1]]):
                h += 1
            else:
                break
        if _header_like([_kind(v) for v in rows[h]]):
            header, data = rows[h], rows[h + 1:]
            # группа над шапкой: «;Выручка;;Клиенты» над «Регион;2024;2025;2024;2025»
            if h >= 1 and _group_row(rows[h - 1]):
                width = max([len(header)] + [len(r) for r in data[:200]])
                group = _merge_headers(rows[h - 1], header, data, width)
                if group is not None:
                    merged_names, h = group, h - 1
        else:
            header, data = None, rows[h:]
        note_lines += [_row_text(r) for r in rows[:h] if r]
    elif header_row is None:
        header, data = None, rows
    else:
        note_lines += [_row_text(r) for r in rows[:header_row] if r]
        header, data = rows[header_row], rows[header_row + 1:]

    width = max([len(header) if header else 0] + [len(r) for r in data])
    raw_names: list[str] = [""] * width
    if merged_names is not None:
        raw_names = (merged_names + raw_names)[:width]
    elif header is not None:
        raw_names = ([str(v) if v is not None else "" for v in header] + raw_names)[:width]
        # вторая строка шапки: подзаголовки под группой или строка единиц (шапку искали сами — у JSON и
        # Markdown-таблицы с линией под шапкой следующая строка уже данные)
        if data and header_row == -1:
            merged = _merge_headers(header, data[0], data[1:], width)
            if merged is not None:
                raw_names, data = merged, data[1:]

    # пустые строки и повтор шапки (склеенные выгрузки) — прочь; сноски и «Итого» в конце — не данные
    head_cells = [v for v in (header or []) if v is not None]
    head_first = head_cells[0] if head_cells else None
    data = [r for r in data if r and not (
        head_first is not None and head_first in r and [v for v in r if v is not None] == head_cells)]
    tail_notes: list[str] = []
    while data:
        last = data[-1]
        filled = [v for v in last if v is not None]
        first = filled[0] if filled else None
        if (
            width >= 2
            and isinstance(first, str)
            and (
                _FOOTNOTE.match(first)
                or (len(filled) == 1 and len(first) >= 25 and _quantity(first) is None and _period(first) is None)
            )
        ):
            tail_notes.insert(0, _row_text(last))
            data.pop()
        elif width >= 2 and isinstance(first, str) and _TOTAL_ROW.match(first) and len(data) > 1:
            data.pop()
        else:
            break
    if not data:
        raise _NoData("В таблице только заголовок — строк с данными нет" if header is not None else "Файл пустой")

    # колонки
    names_units = [split_unit(n) for n in raw_names]
    typed_cols: list[list[Cell]] = []
    units: list[Optional[str]] = []
    keep: list[int] = []
    padded = [r if len(r) == width else r + [None] * (width - len(r)) for r in data]
    columns = [list(c) for c in zip(*padded)]
    for j in range(width):
        name, unit = names_units[j]
        typed, cell_unit = _type_column(columns[j], name, decimal)
        if all(v is None for v in typed):
            continue  # пустая колонка
        unnamed = not name or name.lower().startswith("unnamed:")
        if unnamed and j == 0 and not first_name and _is_row_number(typed):
            continue  # безымянная нумерация строк (индекс pandas)
        keep.append(j)
        typed_cols.append(typed)
        units.append(unit or cell_unit)
    if not keep:
        raise _NoData("В таблице нет значений")

    names: list[str] = []
    seen: Counter = Counter()
    for pos, j in enumerate(keep):
        name = names_units[j][0]
        if not name or name.lower().startswith("unnamed:"):
            name = (first_name if (j == 0 and first_name) else None) or _name_by_values(typed_cols[pos]) \
                or f"Колонка {pos + 1}"
        seen[name] += 1
        if seen[name] > 1:
            name = f"{name} ({seen[name]})"
        names.append(name)
    raw_header = [" ".join(raw_names[j].split()) if not raw_names[j].lower().startswith("unnamed:") else ""
                  for j in keep]

    n = len(typed_cols)
    out_rows = [list(r) for r in zip(*typed_cols) if r.count(None) != n]
    if not out_rows:
        raise _NoData("В таблице нет значений")
    all_notes = "\n".join(p for p in [notes.strip(), *note_lines, *tail_notes] if p)
    return Table.model_construct(
        id=tid, file=file, kind=kind, sheet=sheet, columns=names, units=units, rows=out_rows,
        raw_header=raw_header, notes=all_notes,
    )


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}(?:T.*)?")
_ISO_PERIOD = re.compile(r"\d{4}(?:-\d{2}|-Q[1-4]|-W\d{2})?")


def _name_by_values(vals: list[Cell]) -> Optional[str]:
    """Безымянная колонка дат — «Дата», периодов — «Период» (ось времени без подписи в файле)."""
    strs = [v for v in vals if v is not None]
    if not strs or not all(isinstance(v, str) for v in strs):
        return None
    if all(_ISO_DAY.fullmatch(v) for v in strs):
        return "Дата"
    if all(_ISO_PERIOD.fullmatch(v) for v in strs):
        return "Период"
    return None


def _is_row_number(vals: list[Cell]) -> bool:
    if len(vals) < 2 or not all(v.__class__ is int for v in vals):
        return False
    start = vals[0]
    return start in (0, 1) and all(v == start + i for i, v in enumerate(vals))


# ======================================================================================================== CSV и текст

_RU_WEIGHTS = {"о": 11, "е": 8, "а": 8, "и": 7, "н": 7, "т": 6, "с": 5, "р": 5, "в": 4, "л": 4, "к": 3, "м": 3, "д": 3,
               "п": 3, "у": 3}


def _decode(data: bytes) -> str:
    """Байты → текст: BOM, UTF-8, UTF-16 без BOM, иначе cp1251/KOI8-R/cp866 — по частым русским буквам."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    head = data[:4000]
    if len(head) >= 8:
        # UTF-16 без BOM: старшие байты — 0 (латиница, цифры) или 4 (кириллица)
        odd, even = head[1::2], head[0::2]
        hi_odd = sum(1 for b in odd if b in (0, 4)) > 0.9 * len(odd) and odd.count(0) > 0
        hi_even = sum(1 for b in even if b in (0, 4)) > 0.9 * len(even) and even.count(0) > 0
        if hi_odd != hi_even:
            try:
                return data[: len(data) // 2 * 2].decode("utf-16-le" if hi_odd else "utf-16-be")
            except UnicodeDecodeError:
                pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    loose = data.decode("utf-8", errors="replace")
    if loose.count("\ufffd") <= max(1, len(loose) // 2000):
        return loose  # UTF-8 с парой битых байтов
    best, best_score = None, -1
    for enc in ("cp1251", "koi8_r", "cp866", "mac_cyrillic"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        score = sum(_RU_WEIGHTS.get(ch, 0) for ch in text[:30000])
        if score > best_score:
            best, best_score = text, score
    return best if best is not None else data.decode("latin-1")


def _looks_binary(text: str) -> bool:
    sample = text[:20000]
    if not sample:
        return False
    bad = sum(1 for ch in sample if (ord(ch) < 32 and ch not in "\t\r\n\f\v") or ch == "\ufffd")
    return bad > len(sample) * 0.02


def _sniff_delimiter(lines: list[str]) -> Optional[str]:
    """Разделитель по согласованности числа полей в первых строках: «\\t», «;», «,», «|»; None — одна колонка."""
    sample = [ln for ln in lines if ln.strip()][:200]
    if not sample:
        return None
    best: Optional[tuple[float, int, str]] = None
    for order, d in enumerate(("\t", ";", ",", "|")):
        if not any(d in ln for ln in sample):
            continue
        counts = [len(r) for r in csv.reader(sample, delimiter=d)]
        mode, freq = Counter(c for c in counts).most_common(1)[0]
        if mode < 2:
            continue
        share = freq / len(counts)
        score = (round(share, 1), -order)
        if best is None or score > best[:2]:
            best = (score[0], score[1], d)
    if best is None or best[0] < 0.5:
        return None
    return best[2]


def _csv_rows(name: str, text: str, delim: Optional[str]) -> list[list[str]]:
    if delim is None:
        return [[ln] for ln in text.splitlines()]
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delim, skipinitialspace=delim in (",", "|")))
    except csv.Error as e:
        raise DataReadError("Не получилось разобрать CSV: проверьте кавычки в строках", file=name) from e
    if delim == "|":
        rows = [_strip_pipes(r) for r in rows]
    return rows


def _strip_pipes(r: list[str]) -> list[str]:
    if r and not r[0].strip():
        r = r[1:]
    if r and not r[-1].strip():
        r = r[:-1]
    return r


def _read_delimited(name: str, text: str, kind: SourceKind, digest: str, delim: Optional[str] = "auto") -> list[Table]:
    text = text.replace("\x00", "")
    m = re.match(r"\s*sep=(.)\s*?\r?\n", text, flags=re.IGNORECASE)
    if m:  # «sep=;» — подсказка Excel в первой строке
        delim, text = m.group(1), text[m.end():]
    lines = text.splitlines()
    if delim == "auto":
        delim = "\t" if kind == "tsv" else _sniff_delimiter(lines)
    rows = _csv_rows(name, text, delim)
    file_dec = "." if delim == "," else None  # в CSV через запятую дробь пишут точкой
    try:
        table = _build_table(rows, file=name, kind=kind, sheet=None, tid=_table_id(digest, 0), decimal=file_dec)
    except _NoData as e:
        raise DataReadError(str(e), file=name) from None
    return [table]


# --- таблицы внутри текста

_BOX_TRANS = str.maketrans({"│": "|", "┃": "|", "║": "|"})
_BORDER_CHARS = set(" \t-=─━═┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬╒╕╘╛╞╡╤╧╪+|:")
_PIPE_SPLIT = re.compile(r"(?<!\\)\|")
_MD_FENCE = re.compile(r"^\s*(```|~~~)")


def _is_border(line: str) -> bool:
    """Линия таблицы: «|---|:--:|», «--- | ---», «+----+», «├───┼───┤»."""
    s = line.strip()
    return bool(s) and set(s) <= _BORDER_CHARS and sum(s.count(c) for c in "-=─━═") >= 3


def _pipe_cells(line: str) -> list[str]:
    s = line.strip()
    cells = _PIPE_SPLIT.split(s)
    if s.startswith("|"):
        cells = cells[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        cells = cells[:-1]
    return [re.sub(r"(\*\*|__|`)", "", c.replace("\\|", "|")).strip() for c in cells]


def _is_pipe_line(line: str) -> bool:
    s = line.strip()
    return bool(_PIPE_SPLIT.search(s)) and len(s.strip("| ")) > 0


def _pipe_block(lines: list[str], i: int) -> Optional[tuple[int, list[list[str]], Optional[int]]]:
    if not (_is_pipe_line(lines[i]) or _is_border(lines[i])):
        return None
    j = i
    rows: list[list[str]] = []
    header_row: Optional[int] = -1
    has_border = False
    while j < len(lines) and lines[j].strip() and (_is_pipe_line(lines[j]) or _is_border(lines[j])):
        if _is_border(lines[j]):
            has_border = True
            if len(rows) == 1 and header_row == -1:
                header_row = 0
        else:
            cells = _pipe_cells(lines[j])
            if len(cells) >= 2:
                rows.append(cells)
        j += 1
    single_pipe = all(len(_PIPE_SPLIT.findall(lines[k].strip())) <= 1 for k in range(i, j) if not _is_border(lines[k]))
    if len(rows) < 2 or (single_pipe and not has_border):
        return None
    return j, rows, header_row


def _tab_block(lines: list[str], i: int) -> Optional[tuple[int, list[list[str]], Optional[int]]]:
    if "\t" not in lines[i] or len([c for c in lines[i].split("\t") if c.strip()]) < 2:
        return None
    j = i
    while j < len(lines) and lines[j].strip() and "\t" in lines[j]:
        j += 1
    rows = [[c.strip() for c in ln.split("\t")] for ln in lines[i:j]]
    if len(rows) < 2:
        return None
    return j, rows, -1


def _semicolon_block(lines: list[str], i: int) -> Optional[tuple[int, list[list[str]], Optional[int]]]:
    first = lines[i]
    if ";" not in first:
        return None
    n = len(next(csv.reader([first], delimiter=";")))
    if n < 2:
        return None
    j = i
    rows = []
    while j < len(lines) and lines[j].strip():
        r = next(csv.reader([lines[j]], delimiter=";"))
        if len(r) != n or any(len(c) > 80 for c in r):
            break
        rows.append([c.strip() for c in r])
        j += 1
    if len(rows) < 2 or not any(_quantity(c.strip()) is not None for r in rows[1:] for c in r if c.strip()):
        return None
    return j, rows, -1


_SPACED = re.compile(r"\s{2,}|\t")


def _spaced_cells(line: str) -> list[str]:
    s = line.rstrip()
    cells = _SPACED.split(s.strip())
    if s[:2] == "  " and cells:
        cells = [""] + cells  # пустая левая верхняя ячейка
    return [c.strip() for c in cells]


def _spaced_block(lines: list[str], i: int) -> Optional[tuple[int, list[list[str]], Optional[int]]]:
    first = _spaced_cells(lines[i])
    if len([c for c in first if c]) < 2 or len(lines[i]) > 300:
        return None
    n = len(first)
    j = i + 1
    rows = [first]
    while j < len(lines) and lines[j].strip() and len(lines[j]) <= 300:
        cells = _spaced_cells(lines[j])
        if len(cells) != n or any(len(c) > 60 for c in cells):
            break
        rows.append(cells)
        j += 1
    if len(rows) < 2 or any(len(c) > 60 for c in first):
        return None
    numeric_rows = sum(1 for r in rows[1:] if any(_quantity(c) is not None for c in r if c))
    if numeric_rows * 2 < len(rows) - 1:
        return None
    return j, rows, -1


def _text_blocks(lines: list[str]) -> list[tuple[int, int, list[list[str]], Optional[int], str]]:
    blocks = []
    i = 0
    while i < len(lines):
        if not lines[i].strip() or _MD_FENCE.match(lines[i]):
            i += 1
            continue
        for how, finder in (("pipe", _pipe_block), ("tab", _tab_block), ("semicolon", _semicolon_block),
                            ("spaced", _spaced_block)):
            found = finder(lines, i)
            if found is not None:
                end, rows, header_row = found
                blocks.append((i, end, rows, header_row, how))
                i = end
                break
        else:
            i += 1
    return blocks


def _read_text(name: str, text: str, digest: str) -> list[Table]:
    text = text.replace("\x00", "").translate(_BOX_TRANS)
    lines = text.splitlines()
    blocks = _text_blocks(lines)
    nonempty = [k for k, ln in enumerate(lines) if ln.strip() and not _MD_FENCE.match(ln)]
    if not blocks:
        # весь файл — CSV через запятую с расширением .txt
        delim = _sniff_delimiter(lines)
        if delim in (",", ";", "\t") and len(nonempty) >= 2:
            counts = [len(r) for r in csv.reader([lines[k] for k in nonempty], delimiter=delim)]
            mode, freq = Counter(counts).most_common(1)[0]
            if mode >= 2 and freq >= 0.9 * len(counts):
                return _read_delimited(name, text, "tsv" if delim == "\t" else "csv", digest, delim)
        raise DataReadError("Не нашёл таблицу в тексте", file=name)
    # весь файл — одна таблица через табуляцию или «;»: это CSV/TSV, а не «таблица в тексте»
    if len(blocks) == 1 and blocks[0][4] in ("tab", "semicolon"):
        start, end = blocks[0][0], blocks[0][1]
        if all(start <= k < end for k in nonempty):
            return _read_delimited(name, text, "tsv" if blocks[0][4] == "tab" else "csv", digest,
                                   "\t" if blocks[0][4] == "tab" else ";")
    covered = set()
    for start, end, *_ in blocks:
        covered.update(range(start, end))
    outside = [ln.rstrip() for k, ln in enumerate(lines) if k not in covered and not _MD_FENCE.match(ln)]
    notes = re.sub(r"\n{3,}", "\n\n", "\n".join(outside)).strip()
    tables: list[Table] = []
    for k, (_start, _end, rows, header_row, _how) in enumerate(blocks):
        try:
            tables.append(_build_table(
                rows, file=name, kind="text", sheet=None, tid=_table_id(digest, k), notes=notes,
                header_row=header_row, decimal=None,
            ))
        except _NoData:
            continue  # блок без значений — не таблица
    if not tables:
        raise DataReadError("Не нашёл таблицу в тексте", file=name)
    if len(tables) > 1:
        for k, t in enumerate(tables):
            t.sheet = f"Таблица {k + 1}"
    return tables


# ======================================================================================================== XLSX

@functools.lru_cache(maxsize=256)
def _format_unit(fmt: str) -> Optional[str]:
    """Числовой формат ячейки Excel → «%» (значение — доля), символ валюты или None («0.0%», «#,##0 ₽», «[$₽-419]»)."""
    f = re.sub(r"\[\$-[0-9A-Fa-f]+\]", "", fmt)  # «[$-409]» — язык, не валюта
    if "%" in f.replace('"%"', ""):
        return "%"
    cur = next((c for c in _CUR_SYMBOLS if c in f), None)
    if cur is None and ("р." in f or "руб" in f):
        cur = "₽"
    return cur


def _xlsx_cell(cell: Any) -> Any:
    v = getattr(cell, "value", None)
    if v is None:
        return None
    if v.__class__ is int or v.__class__ is float:
        fmt = getattr(cell, "number_format", None)
        if not fmt or fmt == "General":
            return v
        unit = _format_unit(fmt)
        if unit == "%":
            return f"{v * 100:.10g}%"
        if unit is not None:
            return f"{v:.15g} {unit}"
        return v
    if isinstance(v, str):
        if v.startswith("#") and v.lower() in _MISSING:
            return None
        return v
    return v


def _read_xlsx(name: str, data: bytes, digest: str) -> list[Table]:
    try:
        import openpyxl
    except ImportError as e:  # pragma: no cover
        raise DataReadError("Для чтения Excel нужен пакет openpyxl", file=name) from e
    if data[:8] == _OLE:
        raise DataReadError(
            "Книга защищена паролем или сохранена в старом формате .xls — сохраните её как .xlsx без пароля или как CSV",
            file=name,
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise DataReadError("Не получилось открыть книгу Excel: файл повреждён или это не .xlsx", file=name) from e
    tables: list[Table] = []
    visible = 0
    first_error = None
    try:
        sheets = [ws for ws in wb.worksheets if getattr(ws, "sheet_state", "visible") == "visible"]
        for k, ws in enumerate(sheets):
            if not hasattr(ws, "iter_rows"):
                continue
            visible += 1
            try:
                ws.reset_dimensions()
            except Exception:
                pass
            rows: list[list[Any]] = []
            empty_run = 0
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for row in ws.iter_rows():
                    vals = [_xlsx_cell(c) for c in row]
                    while vals and (vals[-1] is None or (isinstance(vals[-1], str) and not vals[-1].strip())):
                        vals.pop()
                    if not vals:
                        empty_run += 1
                        if empty_run > 10000:
                            break
                    else:
                        empty_run = 0
                    rows.append(vals)
            try:
                tables.append(_build_table(rows, file=name, kind="xlsx", sheet=ws.title, tid=_table_id(digest, k)))
            except _NoData as e:
                first_error = first_error or str(e)
    finally:
        wb.close()
    if not tables:
        if visible <= 1:
            raise DataReadError("Лист без данных" if first_error in (None, "Файл пустой") else first_error, file=name)
        raise DataReadError("В книге нет листов с данными", file=name)
    # титульный лист и списки подписей (одна колонка текста) рядом с настоящими таблицами — не данные
    useful = [t for t in tables if not _is_prose(t)]
    tables = useful or tables
    if len(tables) == 1:
        tables[0].sheet = None
    return tables


def _is_prose(t: Table) -> bool:
    if len(t.columns) != 1:
        return False
    vals = [v for v in t.column_values(0) if v is not None]
    return all(isinstance(v, str) and not (_ISO_DAY.fullmatch(v) or _ISO_PERIOD.fullmatch(v)) for v in vals)


# ======================================================================================================== JSON

_COLS_KEYS = ("columns", "headers", "header", "fields", "cols", "колонки", "столбцы")
_ROWS_KEYS = ("rows", "data", "values", "records", "items", "строки", "данные")


def _json_load(name: str, data: bytes) -> Any:
    text = _decode(data).strip()
    if not text:
        raise DataReadError("Файл пустой", file=name)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # JSON Lines: запись на строку
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) > 1:
            try:
                return [json.loads(ln) for ln in lines]
            except json.JSONDecodeError:
                pass
        raise DataReadError(f"Не получилось прочитать JSON: ошибка в строке {e.lineno}, позиция {e.colno}",
                            file=name) from None


def _flat(v: Any) -> Any:
    if isinstance(v, list):
        if all(not isinstance(x, (dict, list)) for x in v):
            return ", ".join("" if x is None else str(x) for x in v)
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return v


def _records_rows(records: list[Any]) -> list[list[Any]]:
    """Записи → [шапка] + строки; вложенные объекты — колонки «родитель.ключ»."""
    keys: dict[str, None] = {}
    flat_recs = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        flat: dict[str, Any] = {}
        for k, v in rec.items():
            if isinstance(v, dict) and v and all(not isinstance(x, (dict, list)) for x in v.values()):
                for k2, v2 in v.items():
                    flat[f"{k}.{k2}"] = v2
            else:
                flat[str(k)] = _flat(v)
        for k in flat:
            keys.setdefault(k, None)
        flat_recs.append(flat)
    header = list(keys)
    return [header] + [[r.get(k) for k in header] for r in flat_recs]


def _col_name(c: Any) -> str:
    if isinstance(c, dict):
        for k in ("name", "title", "label", "key", "id", "field", "название", "имя"):
            if k in c and c[k] is not None:
                base = str(c[k])
                unit = c.get("unit") or c.get("units") or c.get("единица")
                return f"{base}, {unit}" if unit else base
        return json.dumps(c, ensure_ascii=False)
    return "" if c is None else str(c)


def _is_records(v: Any) -> bool:
    return isinstance(v, list) and any(isinstance(x, dict) for x in v) and all(
        isinstance(x, dict) or x is None for x in v)


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _is_numberish(v: Any) -> bool:
    return _is_num(v) or (isinstance(v, str) and parse_quantity(v) is not None)


def _is_tableish(v: Any) -> bool:
    """Значение ключа — таблица: записи, массив строк, колонки-массивы или «категория → число»."""
    if _is_records(v):
        return True
    if isinstance(v, list) and v and all(isinstance(x, list) for x in v):
        return True
    if isinstance(v, list) and len(v) >= 2 and all(_is_scalar(x) for x in v):
        return sum(_is_numberish(x) for x in v) >= 0.8 * len(v)
    return False


# (имя таблицы, строки, строка шапки, заметки, имя безымянной первой колонки)
_JsonTable = tuple[Optional[str], list[list[Any]], Optional[int], str, str]


def _json_tables(obj: Any, path: str = "", depth: int = 0) -> list[_JsonTable]:
    """JSON → таблицы: массив записей; {columns, rows|data}; pandas split/table; колонки-массивы
    {"Месяц": [...], "Выручка": [...]}; «категория → число»; объект объектов; «ключ → таблица» (каждый ключ — своя)."""
    name = path or None
    if isinstance(obj, list):
        if not obj:
            return []
        if _is_records(obj):
            return [(name, _records_rows(obj), 0, "", "")]
        if all(isinstance(x, list) for x in obj):
            return [(name, [[_flat(c) for c in r] for r in obj], -1, "", "")]
        if all(_is_scalar(x) for x in obj):
            return [(name, [["Значение"]] + [[x] for x in obj], 0, "", "")]
        return []
    if not isinstance(obj, dict) or not obj:
        return []
    low = {str(k).lower(): k for k in obj}
    cols_key = next((low[k] for k in _COLS_KEYS if k in low and isinstance(obj[low[k]], list)), None)
    rows_key = next((low[k] for k in _ROWS_KEYS if k in low and isinstance(obj[low[k]], list)), None)

    # pandas orient="table": {"schema": {"fields": [...]}, "data": [записи]}
    schema = obj.get(low.get("schema", "\0"))
    if cols_key is None and isinstance(schema, dict) and rows_key is not None and _is_records(obj[rows_key]):
        rows = _records_rows(obj[rows_key])
        if rows[0] and rows[0][0] == "index":
            rows = [r[1:] for r in rows]
        return [(name, rows, 0, _json_notes(obj, {low.get("schema"), rows_key}), "")]

    # {"columns": [...], "rows" | "data": [[...], ...]} (и pandas orient="split" с "index")
    if cols_key is not None and rows_key is not None:
        header = [_col_name(c) for c in obj[cols_key]]
        data = obj[rows_key]
        notes = _json_notes(obj, {cols_key, rows_key, low.get("index")})
        if _is_records(data):
            rows = _records_rows(data)
            order = [rows[0].index(h) for h in header if h in rows[0]]
            if len(order) == len(header):
                rows = [[r[i] for i in order] for r in rows]
            return [(name, rows, 0, notes, "")]
        body = [[_flat(c) for c in r] if isinstance(r, list) else [_flat(r)] for r in data]
        index = obj.get(low.get("index", "\0"))
        first = ""
        if isinstance(index, list) and len(index) == len(body) and index != list(range(len(body))):
            header, body, first = [""] + header, [[_flat(ix)] + r for ix, r in zip(index, body)], "Категория"
        return [(name, [header] + body, 0, notes, first)]

    values = list(obj.values())
    # колонки-массивы одинаковой длины: {"Месяц": [...], "Выручка": [...]} (pandas orient="list")
    if len(values) >= 2 and all(isinstance(v, list) and all(_is_scalar(x) for x in v) for v in values):
        if len({len(v) for v in values}) == 1 and values[0]:
            return [(name, [[str(k) for k in obj]] + [list(r) for r in zip(*values)], 0, "", "")]
    # «категория → число»: одна серия; одни простые значения без чисел — одна запись
    if all(_is_scalar(v) for v in values):
        if sum(_is_numberish(v) for v in values) >= max(2, 0.8 * len(values)):
            return [(name, [["Категория", "Значение"]] + [[str(k), v] for k, v in obj.items()], 0, "", "")]
        return [(name, [[str(k) for k in obj], values], 0, "", "")] if depth == 0 else []
    # объект объектов: {"Москва": {"Выручка": 1433}} (внешние ключи — строки) или pandas orient="columns"
    # {"Выручка": {"Москва": 1433}} (внешние ключи — колонки): строк обычно больше, чем колонок
    if all(isinstance(v, dict) and v and all(_is_scalar(x) for x in v.values()) for v in values):
        inner = list(dict.fromkeys(str(k) for v in values for k in v))
        if len(obj) > len(inner):
            header = [""] + inner
            body = [[str(k)] + [v.get(ik) for ik in inner] for k, v in obj.items()]
        else:
            header = [""] + [str(k) for k in obj]
            body = [[ik] + [v.get(ik) for v in values] for ik in inner]
        return [(name, [header] + body, 0, "", "Категория")]
    # «ключ → таблица»: каждый ключ — своя таблица; рядом с таблицами простые объекты и строки — заметки
    notes = _json_notes(obj)
    tableish = {k for k, v in obj.items() if _is_tableish(v)}
    out: list[_JsonTable] = []
    if depth < 4:
        for k, v in obj.items():
            if not isinstance(v, (list, dict)):
                continue
            if tableish and k not in tableish and not (isinstance(v, dict) and _has_table(v)):
                continue  # метаданные рядом с таблицами
            if isinstance(v, list) and k not in tableish:
                continue  # список подписей, а не таблица
            sub = _json_tables(v, str(k) if not path else f"{path}.{k}", depth + 1)
            out += [(n, r, h, "\n".join(p for p in (notes, nt) if p), f) for n, r, h, nt, f in sub]
    return out


def _has_table(obj: dict, depth: int = 0) -> bool:
    if depth > 3:
        return False
    return any(_is_tableish(v) or (isinstance(v, dict) and _has_table(v, depth + 1)) for v in obj.values())


def _json_notes(obj: dict, skip: Optional[set] = None) -> str:
    skip = skip or set()
    parts = []
    for k, v in obj.items():
        if k in skip:
            continue
        if isinstance(v, str) and v.strip():
            parts.append(f"{k}: {v.strip()}")
        elif _is_num(v):
            parts.append(f"{k}: {v}")
    return "\n".join(parts)


def _read_json(name: str, data: bytes, digest: str) -> list[Table]:
    obj = _json_load(name, data)
    found = _json_tables(obj)
    if not found:
        raise DataReadError(
            "В JSON нет таблицы: нужен массив записей, объект {columns, rows} или «ключ → массив записей»", file=name
        )
    tables: list[Table] = []
    first_error = None
    for k, (sheet, rows, header_row, notes, first_name) in enumerate(found):
        try:
            tables.append(_build_table(rows, file=name, kind="json", sheet=sheet, tid=_table_id(digest, k),
                                       notes=notes, header_row=header_row, first_name=first_name))
        except _NoData as e:
            first_error = first_error or str(e)
    if not tables:
        raise DataReadError(
            "В JSON нет строк с данными" if first_error in (None, "Файл пустой") else first_error, file=name
        )
    if len(tables) == 1:
        tables[0].sheet = None
    return tables


# ======================================================================================================== вход

_EXT_KIND: dict[str, str] = {
    ".csv": "csv", ".tsv": "tsv", ".tab": "tsv",
    ".xlsx": "xlsx", ".xlsm": "xlsx", ".xltx": "xlsx", ".xltm": "xlsx",
    ".json": "json", ".jsonl": "json", ".ndjson": "json", ".geojson": "json",
    ".txt": "text", ".md": "text", ".markdown": "text", ".text": "text",
}
_UNSUPPORTED: dict[str, str] = {
    ".xls": "Старый формат Excel (.xls) не читается — сохраните файл как .xlsx или .csv",
    ".xlsb": "Двоичная книга Excel (.xlsb) не читается — сохраните файл как .xlsx или .csv",
    ".ods": "Таблица OpenDocument (.ods) не читается — сохраните её как .xlsx или .csv",
    ".numbers": "Файл Numbers не читается — экспортируйте таблицу в .xlsx или .csv",
}
_NOT_DATA = {".pdf", ".doc", ".docx", ".rtf", ".odt", ".ppt", ".pptx", ".key", ".png", ".jpg", ".jpeg", ".gif",
             ".webp", ".svg", ".zip", ".rar", ".7z", ".parquet", ".sqlite", ".db"}


def read_bytes(name: str, data: bytes) -> list[Table]:
    """Файл с данными (имя и содержимое) → таблицы: лист XLSX, ключ JSON, таблица в тексте — каждая своя `Table`.
    Не получилось — `DataReadError` с русским текстом («Файл пустой», «Не нашёл таблицу в тексте», «Лист без данных»)."""
    name = Path(str(name)).name or "данные"
    ext = Path(name).suffix.lower()
    if ext in _NOT_DATA:
        raise DataReadError(
            f"Файлы {ext} с данными не читаю — приложите таблицу как CSV, XLSX, JSON или текст с таблицей", file=name
        )
    if not data or not data.strip():
        raise DataReadError("Файл пустой", file=name)
    kind = _EXT_KIND.get(ext)
    if ext in _UNSUPPORTED or kind == "xlsx":
        # «выгрузка в Excel», которая на деле текст через табуляцию или «;» с расширением .xls/.xlsx
        if _text_disguised_as_excel(name, data):
            kind = "csv"
        elif ext in _UNSUPPORTED:
            raise DataReadError(_UNSUPPORTED[ext], file=name)
    digest = hashlib.sha1(name.encode() + b"\0" + data).hexdigest()
    if kind is None or (kind != "xlsx" and data[:4] == b"PK\x03\x04"):
        kind = _sniff_kind(data)
    if kind == "xlsx":
        return _read_xlsx(name, data, digest)
    if kind == "json":
        return _read_json(name, data, digest)
    text = _decode(data)
    if _looks_binary(text):
        raise DataReadError("Файл не похож на таблицу: внутри двоичные данные, а не текст", file=name)
    if not text.strip():
        raise DataReadError("Файл пустой", file=name)
    if kind == "text":
        return _read_text(name, text, digest)
    return _read_delimited(name, text, kind, digest)  # csv / tsv


_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _text_disguised_as_excel(name: str, data: bytes) -> bool:
    if data[:4] == b"PK\x03\x04" or data[:8] == _OLE:
        return False
    head = _decode(data[:8000])
    if _looks_binary(head):
        return False
    if head.lstrip()[:1] == "<":
        raise DataReadError(
            "Файл — страница HTML или XML, а не книга Excel: откройте его в Excel и сохраните как .xlsx или .csv",
            file=name,
        )
    return True


def _sniff_kind(data: bytes) -> str:
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if any(n.startswith("xl/") for n in z.namelist()):
                    return "xlsx"
        except zipfile.BadZipFile:
            pass
        raise DataReadError("Архив не похож на книгу Excel — приложите таблицу как CSV, XLSX, JSON или текст")
    head = data.lstrip()[:1]
    if head in (b"[", b"{"):
        return "json"
    return "text"


def read_file(path: Union[str, Path]) -> list[Table]:
    """Файл на диске → таблицы (см. `read_bytes`)."""
    p = Path(path)
    if not p.exists():
        raise DataReadError(f"Файл «{p.name}» не найден", file=p.name)
    if p.is_dir():
        raise DataReadError(f"«{p.name}» — папка, а не файл с данными", file=p.name)
    return read_bytes(p.name, p.read_bytes())
