"""Русские слова слоя данных: числа по-русски («1 433», «4,2», «+23%»), формы слова при числе («21 точка», «8 регионов»,
«в 2 раза»), падежи названий колонок («выручки», «по выручке», «клиентов», «Число клиентов»), род и число для глагола
(«выручка выросла», «NPS вырос», «прямые продажи дают»), числительные словами («за два квартала»), периоды («янв 2025»,
«к сентябрю», «января 2025», «III кв. 2026»), длительности («2 часа», «45 минут»), доли словами («почти половину»),
основы слов для сопоставления целей и название датасета по файлу.

Морфология — правила с исключениями для частых слов (без словарей и сторонних библиотек). Где правило не уверено
(аббревиатура, латиница, название в косвенном падеже), функции возвращают None или помечают `sure=False` — тогда текст
строится так, чтобы падеж не был нужен («8 категорий» вместо «8 …ов»)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Optional, Sequence

__all__ = [
    "NBSP", "MINUS", "Gender", "plural", "count_words", "fmt_num", "round_pct", "fmt_pct", "fmt_signed", "fmt_value",
    "lower_first", "upper_first", "join_and", "fmt_exact", "each_unit", "is_participle", "verb_agree", "parts_words",
    "by_group", "Phrase", "phrase", "metric_phrase", "is_counter", "head_word",
    "is_plural_value", "verb", "number_word", "WORD_NUMS", "times_word", "PERIOD_WORDS", "month_name", "period_label",
    "period_text", "period_dative", "period_than", "no_year", "period_gen", "period_dat_full", "fraction_words", "duration_text", "duration_gen",
    "stem", "stems_of", "same_stem", "stems_match", "file_title", "period_acc", "period_in", "fmt_count",
    "fmt_pct_any", "round_pct_any", "is_event_name", "count_gen", "count_dat", "is_period_name", "stem_in",
]

NBSP = " "
MINUS = "−"

Gender = Literal["m", "f", "n", "pl"]


# ── числа ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def plural(n: float, one: str, few: str, many: str) -> str:
    """Форма слова при числе: 1 строка, 3 строки, 5 строк; дробное — как «few» (2,5 строки)."""
    if not float(n).is_integer():
        return few
    n = abs(int(n))
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return one
    if 2 <= m10 <= 4 and not 12 <= m100 <= 14:
        return few
    return many


def _group(n: int) -> str:
    s = str(abs(n))
    parts = []
    while len(s) > 3:
        parts.insert(0, s[-3:])
        s = s[:-3]
    parts.insert(0, s)
    return (MINUS if n < 0 else "") + NBSP.join(parts)


def fmt_num(x: float, decimals: Optional[int] = None) -> str:
    """Число по-русски: 1433 → «1 433» (неразрывный пробел), 1.24 → «1,24», 52.0 → «52», −3 → «−3».
    Без `decimals`: от 100 — целое, от 10 — один знак, меньше — два (нули в конце убираются)."""
    if x is None or not math.isfinite(x):
        return "—"
    a = abs(x)
    if decimals is None:
        decimals = 0 if a >= 100 else 1 if a >= 10 else 2
        if 0 < a < 1:
            decimals = max(2, -math.floor(math.log10(a)) + 1)  # две значащие цифры: 0,012, 0,006, 0,0035
    r = round(float(x), decimals)
    if r == 0 and a > 0:
        # ненулевое значение не пишется нулём: столько знаков, сколько нужно для двух значащих
        return fmt_num(x, max(decimals, -math.floor(math.log10(a)) + 1))
    if r == 0:
        r = 0.0
    if float(r).is_integer():
        return _group(int(r))
    whole, _, frac = f"{abs(r):.{decimals}f}".partition(".")
    frac = frac.rstrip("0")
    s = _group(int(whole)) + ("," + frac if frac else "")
    return (MINUS + s) if r < 0 else s


def round_pct(p: float) -> float:
    """Процент, как его пишет заголовок: от 10 — целое, меньше — один знак (4,2)."""
    return float(round(p)) if abs(p) >= 9.95 else round(p, 1)


def fmt_pct(p: float) -> str:
    """«23», «4,2» — без знака процента (его ставит шаблон)."""
    return fmt_num(round_pct(p), 0 if abs(p) >= 9.95 else 1)


def fmt_signed(x: float, unit: str = "") -> str:
    """«+23%», «−4,2 п.п.», «+6 п.»."""
    sign = "+" if x > 0 else MINUS if x < 0 else ""
    body = fmt_num(abs(x), 0 if abs(x) >= 9.95 or float(x).is_integer() else 1)
    if not unit:
        return sign + body
    return f"{sign}{body}{unit}" if unit == "%" else f"{sign}{body}{NBSP}{unit}"


# единицы-счётчики из шапки («Scopus, статей»): формы при числе — именительный (1 статья, 2 статьи, 5 статей) и
# родительный («с 42 статей до 381 статьи»)
_COUNT_UNITS = {
    "статей": ("статья", "статьи", "статей"), "публикаций": ("публикация", "публикации", "публикаций"),
    "заявок": ("заявка", "заявки", "заявок"), "заказов": ("заказ", "заказа", "заказов"),
    "сделок": ("сделка", "сделки", "сделок"), "клиентов": ("клиент", "клиента", "клиентов"),
    "студентов": ("студент", "студента", "студентов"), "сотрудников": ("сотрудник", "сотрудника", "сотрудников"),
    "обращений": ("обращение", "обращения", "обращений"), "пользователей": ("пользователь", "пользователя",
                                                                           "пользователей"),
    "проектов": ("проект", "проекта", "проектов"), "патентов": ("патент", "патента", "патентов"),
    "мест": ("место", "места", "мест"), "звонков": ("звонок", "звонка", "звонков"),
    "человек": ("человек", "человека", "человек"), "штук": ("штука", "штуки", "штук"),
}


def fmt_count(x: float, unit: Optional[str], case: str = "nom") -> Optional[str]:
    """«381 статья», «2 статьи»; родительный («с … до …»): «42 статей», «381 статьи». None — единица не счётчик."""
    forms = _COUNT_UNITS.get((unit or "").strip().lower())
    if forms is None:
        return None
    if case == "gen":
        w = forms[1] if float(x).is_integer() and plural(int(x), 1, 2, 2) == 1 else forms[2]
    else:
        w = plural(x, *forms)
    return f"{fmt_num(x)}{NBSP}{w}"


def fmt_pct_any(p: float) -> str:
    """Процент любого размера: «23», «4,2», «0,06» (меньше 1 — две значащие цифры, не «0»)."""
    if abs(p) >= 1 or p == 0:
        return fmt_pct(p)
    k = max(1, -int(math.floor(math.log10(abs(p)))) + 1)
    return fmt_num(round(p, k), k)


def round_pct_any(p: float) -> float:
    if abs(p) >= 1 or p == 0:
        return round_pct(p)
    k = max(1, -int(math.floor(math.log10(abs(p)))) + 1)
    return round(p, k)


def fmt_value(x: float, unit: Optional[str], case: str = "nom") -> str:
    """Значение с единицей: «1 433 млн ₽», «46%», «52», «381 статья» (счётчик — по числу; case="gen" — после «с/до»)."""
    c = fmt_count(x, unit, case)
    if c is not None:
        return c
    s = fmt_num(x, _nines(x) if unit == "%" else None)
    if not unit:
        return s
    return s + unit if unit == "%" else s + NBSP + unit


def _nines(x: float) -> Optional[int]:
    """Процент у самой сотни («99,874%» при цели 99,9%, «99,999%»): знаков — до первой не-девятки и ещё один, иначе
    округление прячет разницу (99,874 → «99,9» — как цель, 99,999 → «100»). Не у сотни — как обычно (None)."""
    a = abs(x)
    if not (99 <= a < 100) or float(x).is_integer():
        return None
    frac = f"{a:.6f}".split(".")[1]
    k = next((i for i, ch in enumerate(frac) if ch != "9"), 3)
    return min(4, k + 2)


# ── слова ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def count_words(n: int, one: str, few: str, many: str) -> str:
    """«21 точка», «8 регионов», «512 значений» (разряды — неразрывным пробелом)."""
    return f"{_group(int(n))} {plural(n, one, few, many)}"


def count_gen(n: int, one: str, many: str) -> str:
    """Число со словом в родительном («из …»): «из 31 дня», «из 30 дней», «из 21 недели», «из 5 недель»."""
    k = abs(int(n))
    return f"{_group(int(n))} {one if k % 10 == 1 and k % 100 != 11 else many}"


def count_dat(n: int, one: str, many: str) -> str:
    """Число со словом в дательном («по …»): «по 6 утверждениям», «по 21 утверждению»."""
    k = abs(int(n))
    return f"{_group(int(n))} {one if k % 10 == 1 and k % 100 != 11 else many}"


_PERIOD_HEADS = {"неделя", "недели", "месяц", "месяцы", "день", "дни", "год", "годы", "квартал", "кварталы", "этап",
                 "этапы", "шаг", "шаги", "волна", "волны", "раунд", "сезон", "когорта", "период", "час", "смена"}


def is_period_name(name: Optional[str]) -> bool:
    """Название ряда — номер периода или этапа («Неделя 1», «Месяц 3», «2025»): подлежащим его не делают
    («Неделя 1 выросла» — неверно), вывод — через двоеточие («Неделя 1: +5 п.п.»)."""
    s = str(name or "").strip().lower()
    if re.search(r"\d", s):
        return True
    return (s.split(" ")[0] if s else "") in _PERIOD_HEADS


def lower_first(s: str) -> str:
    """Название колонки внутри фразы: «Выручка» → «выручка»; аббревиатуры («NPS», «ВВП») и латиница («Scopus») —
    как есть."""
    if not s:
        return s
    if len(s) > 1 and (s[1].isupper() or s[1].isdigit()):
        return s
    if not ("а" <= s[0].lower() <= "я" or s[0] in "ёЁ"):
        return s
    return s[0].lower() + s[1:]


def fmt_exact(x: Optional[float]) -> str:
    """Число как в файле, для таблиц: 142.6 → «142,6», 1305.2 → «1 305,2», 14.0 → «14» (до трёх знаков после запятой,
    без округления до целых у больших чисел)."""
    if x is None or not math.isfinite(x):
        return "—"
    for k in (0, 1, 2, 3):
        if abs(round(x, k) - x) < 1e-9:
            return fmt_num(x, k)
    return fmt_num(x, 3)


def upper_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def join_and(items: Sequence[str]) -> str:
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " и " + items[-1]


_CYR = re.compile(r"^[а-яё\-]+$")
_ADJ_END = ("ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые", "ие")
# существительные на «-ие»: «направление», «развитие», «событие» — не прилагательные («средние», «летние» — да)
_NOUN_IE = ("ение", "ание", "тие", "вие", "бие", "лие", "зие", "сие", "мие", "рие", "пие", "дие")


def _is_adj(w: str) -> bool:
    """Слово похоже на прилагательное (полная форма): «средний», «новые», «общая»; «направление» — нет."""
    return len(w) >= 4 and bool(_CYR.match(w)) and w.endswith(_ADJ_END) and not w.endswith(_NOUN_IE)
_HUSH = "жшчщ"
_VELAR = "гкх"
_VOWELS = "аеёиоуыэюя"

# женский род среди слов на «ь» (кроме «-ость/-есть», они женские всегда)
_FEM_SOFT = {
    "отрасль", "область", "прибыль", "площадь", "сеть", "часть", "модель", "связь", "мощь", "дверь", "ночь", "речь",
    "вещь", "помощь", "очередь", "цель", "роль", "доль", "сталь", "соль", "боль", "мысль", "тетрадь", "кровать",
    "плата", "казань", "тверь", "пермь", "рязань", "астрахань", "тюмень", "обь", "мебель", "медаль", "шинель", "дробь",
    "запись", "новь", "любовь", "морковь", "церковь", "осень", "зелень", "жизнь", "болезнь", "песнь", "смерть",
}
# множественное на «-ы/-и» с родительным без «-ов» (женский род)
_FEM_PL_STEMS = {
    "стран", "школ", "групп", "систем", "программ", "платформ", "сумм", "команд", "зон", "сфер", "фирм", "работ",
    "цен", "норм", "форм", "тем", "мин", "минут", "недел", "статей", "задач", "продаж", "покупок", "выплат", "услуг",
    "книг", "компан", "категор", "линий", "отрасл", "област", "ставок", "оценок", "сделок", "заявок", "площадок",
    "точек", "марок", "поездок", "поставок", "закупок", "акций", "лицензий", "должност", "специальност", "секунд",
    "улиц", "единиц", "страниц", "больниц", "границ", "таблиц", "клиник", "аптек", "библиотек", "карт", "кампаний",
    "организаций", "отгрузок",
}
_MASC_PL_A = {"города": "город", "дома": "дом", "номера": "номер", "счета": "счёт", "адреса": "адрес", "округа": "округ",
              "края": "край", "года": "год", "директора": "директор", "учителя": "учитель", "профессора": "профессор",
              "голоса": "голос", "поезда": "поезд", "паспорта": "паспорт", "доктора": "доктор", "берега": "берег",
              "острова": "остров", "сорта": "сорт", "цвета": "цвет", "вечера": "вечер"}
# несклоняемые и особые
_INDECL = {"сочи", "тольятти", "такси", "кафе", "кино", "метро", "пальто", "онлайн", "офлайн", "оффлайн", "хаб", "nps"}
_SPECIAL = {
    # nom, gen, dat, gen_pl, dat_pl, nom_pl, gender
    "время": ("время", "времени", "времени", "времён", "временам", "времена", "n"),
    "имя": ("имя", "имени", "имени", "имён", "именам", "имена", "n"),
    "день": ("день", "дня", "дню", "дней", "дням", "дни", "m"),
    "доля": ("доля", "доли", "доле", "долей", "долям", "доли", "f"),
    "год": ("год", "года", "году", "лет", "годам", "годы", "m"),
    "человек": ("человек", "человека", "человеку", "человек", "людям", "люди", "m"),
    "ребёнок": ("ребёнок", "ребёнка", "ребёнку", "детей", "детям", "дети", "m"),
    "ребенок": ("ребенок", "ребенка", "ребенку", "детей", "детям", "дети", "m"),
    "люди": ("человек", "человека", "человеку", "людей", "людям", "люди", "pl"),
    "дети": ("ребёнок", "ребёнка", "ребёнку", "детей", "детям", "дети", "pl"),
    "деньги": ("деньги", "денег", "деньгам", "денег", "деньгам", "деньги", "pl"),
    "очки": ("очки", "очков", "очкам", "очков", "очкам", "очки", "pl"),
    "отток": ("отток", "оттока", "оттоку", "оттоков", "оттокам", "оттоки", "m"),
    "приток": ("приток", "притока", "притоку", "притоков", "притокам", "притоки", "m"),
    "поток": ("поток", "потока", "потоку", "потоков", "потокам", "потоки", "m"),
    "продажи": ("продажа", "продаж", "продажам", "продаж", "продажам", "продажи", "pl"),
    "расходы": ("расход", "расходов", "расходам", "расходов", "расходам", "расходы", "pl"),
    "простои": ("простой", "простоев", "простоям", "простоев", "простоям", "простои", "pl"),
    "простой": ("простой", "простоя", "простою", "простоев", "простоям", "простои", "m"),
    "абоненты": ("абонент", "абонентов", "абонентам", "абонентов", "абонентам", "абоненты", "pl"),
    "доходы": ("доход", "доходов", "доходам", "доходов", "доходам", "доходы", "pl"),
    "затраты": ("затрата", "затрат", "затратам", "затрат", "затратам", "затраты", "pl"),
    "средства": ("средство", "средств", "средствам", "средств", "средствам", "средства", "pl"),
    "сутки": ("сутки", "суток", "суткам", "суток", "суткам", "сутки", "pl"),
    "рынок": ("рынок", "рынка", "рынку", "рынков", "рынкам", "рынки", "m"),
    "данные": ("данные", "данных", "данным", "данных", "данным", "данные", "pl"),
}


@dataclass(frozen=True)
class _Word:
    nom: str
    gen: str
    dat: str
    gen_pl: str
    dat_pl: str
    nom_pl: str
    gender: Gender


def _fleeting(w: str) -> str:
    """Основа с беглой гласной: «рынок» → «рынк», «продавец» → «продавц», «звонок» → «звонк»."""
    if len(w) > 4 and w.endswith(("ок", "ёк")) and w[-3] not in _VOWELS:
        return w[:-2] + "к"
    if len(w) > 4 and w.endswith("ец") and w[-3] not in _VOWELS:
        return w[:-2] + "ц"
    return w


def _noun(w: str) -> Optional[_Word]:
    """Формы существительного (нижний регистр) — по окончанию с исключениями; None — не уверен."""
    if w in _SPECIAL:
        return _Word(*_SPECIAL[w])  # type: ignore[arg-type]
    if not _CYR.match(w) or len(w) < 2:
        return None
    if w in _INDECL:
        return _Word(w, w, w, w, w, w, "m")
    if w in _MASC_PL_A:
        s = _MASC_PL_A[w]
        base = _noun(s)
        return base and _Word(base.nom, base.gen, base.dat, base.gen_pl, base.dat_pl, w, "pl")
    # множественное число
    if w.endswith("ы") and len(w) > 3:
        st = w[:-1]
        if st in _FEM_PL_STEMS or (st.endswith("иц") and len(st) > 4):
            return _Word(st + "а", st, st + "ам", st, st + "ам", w, "pl")
        if st.endswith("ц"):
            return _Word(st, st + "а", st + "у", st + "ев", st + "ам", w, "pl")
        return _Word(st, st + "а", st + "у", st + "ов", st + "ам", w, "pl")
    if w.endswith("и") and len(w) > 3:
        st = w[:-1]
        if w.endswith("ии"):
            return _Word(st + "я", st, st + "ю", st[:-1] + "ий", st + "ям", w, "pl")
        if w.endswith("ьи"):
            return _Word(st[:-1] + "ья", st, st, st[:-1] + "ей", st + "ям", w, "pl")
        if st[-1] in _VELAR:
            if w.endswith(("ики", "ники", "щики", "чики")):
                return _Word(st, st + "а", st + "у", st + "ов", st + "ам", w, "pl")
            if st[-1] == "к" and st[-2] not in _VOWELS:
                pre = st[:-1]
                gp = (pre[:-1] if pre[-1] in "йь" else pre) + ("ек" if pre[-1] in _HUSH + "йь" else "ок")
                return _Word(st + "а", st + "и", st + "е", gp, st + "ам", w, "pl")
            return _Word(st + "а", st + "и", st + "е", st, st + "ам", w, "pl")
        if st[-1] in _HUSH:
            return _Word(st + "а", st + "и", st + "е", st, st + "ам", w, "pl")
        # мягкая основа: отрасли, пользователи, области
        fem = (st + "ь") in _FEM_SOFT or st.endswith(("ост", "ест"))
        return _Word(st + "ь", st + ("и" if fem else "я"), st + ("и" if fem else "ю"), st + "ей", st + "ям", w, "pl")
    # «новые», «активные», «прочие» — прилагательное во мн. числе как название: мн. число
    if len(w) >= 4 and w.endswith(("ые", "ие")) and not w.endswith(_NOUN_IE):
        return _Word(w, w[:-1] + "х", w[:-1] + "м", w[:-1] + "х", w[:-1] + "м", w, "pl")
    # «поступления», «отчисления», «задания» — мн. число от «-ение/-ание» («компания», «Германия» — ед.)
    if len(w) > 5 and (w.endswith("ения") or (w.endswith("ания") and w[-5] in "вдзстрл")):
        st = w[:-1]
        return _Word(st + "е", st, st + "ю", w[:-2] + "ий", st + "ям", w, "pl")
    # единственное число
    if w.endswith("мя"):
        st = w[:-2]
        return _Word(w, st + "мени", st + "мени", st + "мён", st + "менам", st + "мена", "n")
    if w.endswith("ие") or w.endswith("ье"):
        st = w[:-1]
        return _Word(w, st + "я", st + "ю", w[:-2] + "ий", st + "ям", st + "я", "n")
    if w.endswith("ия"):
        st = w[:-1]
        return _Word(w, st + "и", st + "и", st + "й", st + "ям", st + "и", "f")
    if w.endswith("ья"):
        st = w[:-1]
        return _Word(w, st + "и", st + "е", w[:-2] + "ей", st + "ям", st + "и", "f")
    if w.endswith("а"):
        st = w[:-1]
        soft_i = st[-1] in _VELAR + _HUSH
        gen = st + ("и" if soft_i else "ы")
        if st.endswith("к") and len(st) > 2 and st[-2] not in _VOWELS:
            pre = st[:-1]
            gp = (pre[:-1] if pre[-1] in "йь" else pre) + ("ек" if pre[-1] in _HUSH + "йь" else "ок")
        else:
            gp = st
        return _Word(w, gen, st + "е", gp, st + "ам", gen, "f")
    if w.endswith("я"):
        st = w[:-1]
        return _Word(w, st + "и", st + "е", st + "ь", st + "ям", st + "и", "f")
    if w.endswith("о"):
        st = w[:-1]
        gp = st
        if len(st) > 2 and st[-1] in "лнр" and st[-2] not in _VOWELS and not st.endswith("ств"):
            gp = st[:-1] + "е" + st[-1]  # число → чисел
        return _Word(w, st + "а", st + "у", gp, st + "ам", st + "а", "n")
    if w.endswith("е"):
        st = w[:-1]
        return _Word(w, st + "я", st + "ю", st + "ей", st + "ям", st + "я", "n")
    if w.endswith("ь"):
        st = w[:-1]
        if w in _FEM_SOFT or w.endswith(("ость", "есть", "знь")):
            return _Word(w, st + "и", st + "и", st + "ей", st + "ям", st + "и", "f")
        return _Word(w, st + "я", st + "ю", st + "ей", st + "ям", st + "и", "m")
    if w.endswith("й"):
        st = w[:-1]
        return _Word(w, st + "я", st + "ю", st + "ев", st + "ям", st + "и", "m")
    if w[-1] in _VOWELS:
        return None
    st = _fleeting(w)
    if w[-1] in _HUSH:
        return _Word(w, st + "а", st + "у", st + "ей", st + "ам", st + "и", "m")
    if w[-1] == "ц":
        return _Word(w, st + "а", st + "у", st + ("ов" if st != w else "ев"), st + "ам", st + "ы", "m")
    nom_pl = st + ("и" if w[-1] in _VELAR else "ы")
    return _Word(w, st + "а", st + "у", st + "ов", st + "ам", nom_pl, "m")


def _adj(a: str, gender: Gender) -> Optional[tuple[str, str, str, str]]:
    """Прилагательное: (родительный, дательный, родительный мн., дательный мн.) при роде существительного."""
    if not _CYR.match(a) or len(a) < 4 or not a.endswith(_ADJ_END):
        return None
    st, end = a[:-2], a[-2:]
    soft = end in ("ий", "яя", "ее", "ие") and st[-1] not in _VELAR + _HUSH
    hard_i = st[-1] in _VELAR + _HUSH  # «русский», «хороший» — «-их» во мн.
    pl_gen = st + ("их" if soft or hard_i else "ых")
    pl_dat = st + ("им" if soft or hard_i else "ым")
    if gender == "pl" or end in ("ые", "ие"):
        return pl_gen, pl_dat, pl_gen, pl_dat
    if gender == "f" or end in ("ая", "яя"):
        hush = st[-1] in _HUSH
        return st + ("ей" if soft or hush else "ой"), st + ("ей" if soft or hush else "ой"), pl_gen, pl_dat
    e = "его" if soft or (st[-1] in _HUSH and end != "ой") else "ого"
    d = "ему" if soft or (st[-1] in _HUSH and end != "ой") else "ому"
    return st + e, st + d, pl_gen, pl_dat


@dataclass(frozen=True)
class Phrase:
    """Название (колонки, показателя, сущности) в нужных падежах. Регистр — как в исходном названии."""

    nom: str
    gen: str  # родительный ед. («выручки», «среднего чека»)
    dat: str  # дательный ед. («по выручке»)
    gen_pl: str  # родительный мн. («клиентов», «обращений»)
    dat_pl: str  # дательный мн. («по регионам»)
    nom_pl: str  # именительный мн. («клиенты»)
    gender: Gender  # род главного слова; «pl» — название во множественном числе
    sure: bool = True  # False — несклоняемое (аббревиатура, латиница): формы равны названию

    @property
    def low(self) -> "Phrase":
        """То же с маленькой буквы (внутри фразы)."""
        f = lower_first
        return Phrase(f(self.nom), f(self.gen), f(self.dat), f(self.gen_pl), f(self.dat_pl), f(self.nom_pl), self.gender,
                      self.sure)


def _keep_case(src: str, dst: str) -> str:
    if src[:1].isupper() and not (len(src) > 1 and src[1].isupper()):
        return dst[:1].upper() + dst[1:]
    if src.isupper() and len(src) > 1:
        return dst.upper()
    return dst


def phrase(name: Optional[str]) -> Optional[Phrase]:
    """Падежи названия: «Выручка» → выручки/по выручке; «Средний чек» → среднего чека; «Канал продаж» → каналов продаж;
    «NPS» — несклоняемое (sure=False, род мужской: «индекс»). None — пустое название или слово, которое правила не
    берут (тогда вызывающий строит фразу без падежа)."""
    if not name:
        return None
    s = " ".join(str(name).split())
    s = re.sub(r"\s*[,(].*$", "", s).strip()  # «Выручка, млн ₽», «Доля (%)» — без единицы
    if not s:
        return None
    toks = s.split(" ")
    low = [t.lower() for t in toks]
    # главное слово — первое не-прилагательное (одно слово — всегда существительное)
    h = 0
    while h < len(toks) - 1 and _is_adj(low[h]):
        h += 1
    head = low[h]
    if re.search(r"(?:лось|лся|лась|лись)$", head) or (h == 0 and _past_verb(head)):
        return None  # «Уволилось», «Оплатили» — глагол, а не название величины
    if is_counter(s) and h == 0:
        return None  # «Клиентов», «Довольных клиентов» — не именительный падеж; см. metric_phrase
    if not _CYR.match(head.replace("ё", "е")):
        # аббревиатура или латиница («NPS», «GMV», «ARPU»): несклоняемо, мужской род («показатель»)
        if h == 0:
            return Phrase(s, s, s, s, s, s, "m", sure=False)
        return None
    nw = _noun(head)
    if nw is None:
        return None
    adjs = []
    for a in low[:h]:
        f = _adj(a, nw.gender)
        if f is None:
            return None
        adjs.append(f)
    tail = toks[h + 1:]

    def build(form_idx: int, noun_form: str) -> str:
        words = []
        for i, a in enumerate(low[:h]):
            if form_idx < 0:
                words.append(toks[i])
            else:
                words.append(_keep_case(toks[i], adjs[i][form_idx]))
        words.append(_keep_case(toks[h], noun_form))
        return " ".join(words + tail)

    plural_name = nw.gender == "pl"
    if plural_name:
        gen = build(2, nw.gen_pl)
        dat = build(3, nw.dat_pl)
        nom_pl = s
    else:
        gen = build(0, nw.gen)
        dat = build(1, nw.dat)
        nom_pl = build(-1, nw.nom_pl) if h == 0 else build(-1, nw.nom_pl)
    if h > 0 and not plural_name:
        # прилагательные во мн. числе: «средний чек» → «средние чеки»
        pl_adj = []
        for i, a in enumerate(low[:h]):
            st = a[:-2]
            soft = a.endswith(("ий", "яя", "ее")) and st[-1] not in _VELAR + _HUSH
            pl_adj.append(_keep_case(toks[i], st + ("ие" if soft or st[-1] in _VELAR + _HUSH else "ые")))
        nom_pl = " ".join(pl_adj + [_keep_case(toks[h], nw.nom_pl)] + tail)
    return Phrase(
        nom=s, gen=gen, dat=dat, gen_pl=build(2, nw.gen_pl), dat_pl=build(3, nw.dat_pl), nom_pl=nom_pl,
        gender=nw.gender,
    )


_COUNTER_OK = {"сделок", "заявок", "покупок", "поставок", "оценок", "ошибок", "отгрузок", "продаж", "минут", "часов",
               "дней", "недель", "лет", "штук", "единиц", "задач", "услуг", "доставок", "звонков", "статей", "людей",
               "детей", "гостей", "вещей", "ночей", "площадей"}
_NOT_COUNTER = {"музей", "лицей", "юбилей", "хоккей", "ростов", "остров", "ков", "рынок", "звонок", "урок", "срок",
                "поток", "остаток", "приток", "отток", "восток", "станок", "кусок", "игрок", "порок", "сток",
                "критерий", "сценарий", "комментарий", "гений", "сочинений"}


def is_counter(name: Optional[str]) -> bool:
    """Название-счётчик в родительном мн. («Клиентов», «Заказов», «Довольных клиентов», «Минут до ответа»): само по
    себе не подлежащее — в заголовке «Число клиентов», «Доля довольных клиентов»."""
    if not name:
        return False
    first = str(name).strip().split(" ")[0].lower()
    if not _CYR.match(first) or first in _NOT_COUNTER:
        return False
    if first in _COUNTER_OK:
        return True
    if re.search(r"(?:лось|лись)$", first):
        return True  # «Уволилось», «Пришли» — счёт событий
    if len(first) >= 6 and first.endswith("ок") and not first.endswith(("ток", "рок", "нок")):
        return True  # родительный мн. женского рода: «Доставок», «Поездок», «Перевозок»
    if len(first) >= 6 and first.endswith(("ений", "аний", "ций", "тий")):
        return True  # «Обращений», «Операций», «Посещений», «Событий»
    if len(first) >= 5 and first.endswith(("чей", "щей", "жей", "шей")):
        return True  # «Врачей», «Москвичей», «Товарищей» — родительный мн.
    return len(first) >= 5 and first.endswith(("ов", "ев", "ых", "их", "елей", "телей", "лей"))


# причастие («Доставлено», «Утверждено») и глагол прошедшего времени («Оплатили», «Добавили в корзину») в названии —
# счёт событий или людей: в заголовке «Число доставок», «Число оплативших», а не «Доставлено выросло»
# причастие объёма продукции — существительным: «Выпущено» → «Выпуск» (не «Число выпущенных»)
_PARTICIPLE_NOM = {"выпущено": "Выпуск", "произведено": "Производство", "изготовлено": "Выпуск", "добыто": "Добыча",
                   "потреблено": "Потребление", "выработано": "Выработка", "переработано": "Переработка"}
_PARTICIPLE_NOUN = {"доставлено": "доставок", "продано": "продаж", "отгружено": "отгрузок", "поставлено": "поставок",
                    "куплено": "покупок", "выдано": "выдач", "заказано": "заказов"}
_NOT_VERB = {"автомобили", "профили", "стили", "модели", "цели", "недели", "детали", "медали", "рубли", "роли", "отрасли",
             "области", "нули", "ноли", "сабли", "корабли", "фамилии", "дели", "скалли", "числа"}


def _past_verb(word: str) -> bool:
    """Глагол прошедшего времени во мн. числе или с «-ся»: «оплатили», «начали», «уволилось», «записались»."""
    w = word.lower()
    if w in _NOT_VERB or not _CYR.match(w) or len(w) < 5:
        return False
    if re.search(r"(?:лись|лось|лся|лась)$", w):
        return True
    return bool(re.search(r"[аеиоуыя]ли$", w)) and not w.endswith("тели")


def _active_gen_pl(word: str) -> Optional[str]:
    """Действительное причастие в родительном мн.: «оплатили» → «оплативших», «уволилось» → «уволившихся»; основа на
    согласный («пришли») — None."""
    w = word.lower()
    m = re.match(r"^(.+?)(?:лись|лось|лся|лась)$", w)
    if m:
        st = m.group(1)
        return st + "вшихся" if st[-1:] in "аеиоуыя" else None
    if w.endswith("ли") and w[-3:-2] in "аеиоуыя":
        return w[:-2] + "вших"
    return None


def _participle_gen_pl(word: str) -> Optional[str]:
    """Краткое страдательное причастие → родительный мн. полного: «доставлено» → «доставленных», «принято» →
    «принятых»."""
    w = word.lower()
    if w.endswith(("ено", "ано", "ёно")):
        return w[:-1] + "ных"
    if w.endswith(("ято", "ыто", "ито", "уто", "ото")):
        return w[:-1] + "ых"
    return None


def is_event_name(name: Optional[str]) -> bool:
    """Название — счёт событий или людей глаголом или причастием: «Доставлено», «Оплатили», «Добавили в корзину»,
    «Уволилось»."""
    first = str(name or "").strip().split(" ")[0].lower()
    return is_participle(first) or _past_verb(first)


def metric_phrase(name: Optional[str], mtype: str = "number") -> Optional[Phrase]:
    """Падежи названия метрики; счётчик («Заказов») — как «Число заказов» (у процентов — «Доля довольных клиентов»).
    После «N% …» счётчик остаётся собой: «35% клиентов», а не «35% числа клиентов» (поле `gen`)."""
    if not name:
        return None
    base = re.sub(r"\s*[,(].*$", "", str(name).strip())
    if is_event_name(base) and mtype != "percent":
        # «Доставлено» → «Число доставок», «Добавили в корзину» → «Число добавивших в корзину»; деньги («Утверждено,
        # тыс. ₽») — «утверждённого»
        toks = base.split(" ")
        first = toks[0].lower()
        rest = (" " + " ".join(toks[1:])) if len(toks) > 1 else ""
        if first in _PARTICIPLE_NOM and len(toks) == 1:
            return phrase(_PARTICIPLE_NOM[first])
        if mtype == "money" and is_participle(first):
            st = first[:-1] + ("н" if first.endswith("но") else "")
            return Phrase(base, st + "ого" + rest, st + "ому" + rest, st + "ых" + rest, st + "ым" + rest, base, "n")
        if is_participle(first) and rest and not re.match(r"^\s(?:на|в|во|по|за|с|со|из|к|от|до|для|у|о|об)\b", rest):
            # «Куплено мест» — «купленных мест», а не «покупок мест» (слово колонки — места, не покупки)
            st = re.sub(r"(ж|щ)денн$", r"\1дённ", first[:-1] + ("н" if first.endswith("но") else ""))
            gen = st + "ых" + rest
            return Phrase("Число " + gen, gen, "числу " + gen, "чисел " + gen, "числам " + gen, "Числа " + gen, "n")
        gen = _PARTICIPLE_NOUN.get(first) or (_participle_gen_pl(first) if is_participle(first) else _active_gen_pl(first))
        if gen is None:
            return None
        gen += rest
        return Phrase("Число " + gen, gen, "числу " + gen, "чисел " + gen, "числам " + gen, "Числа " + gen, "n")
    m_num = re.match(r"^(?:число|количество|кол-во|кол\.)\s+(.+)$", base, re.I)
    if m_num and mtype != "percent":
        # «Число ошибок» — после «N%» и «из» говорят «ошибок», а не «числа ошибок»
        p = phrase(base)
        rest = m_num.group(1)
        if p is not None:
            return Phrase(p.nom, rest, p.dat, p.gen_pl, p.dat_pl, p.nom_pl, p.gender, p.sure)
    if is_counter(name):
        p = phrase(("Доля " if mtype == "percent" else "Число ") + lower_first(base))
        if p is not None and mtype != "percent":
            p = Phrase(p.nom, base, p.dat, p.gen_pl, p.dat_pl, p.nom_pl, p.gender, p.sure)
        return p
    return phrase(name)


def head_word(name: Optional[str]) -> str:
    """Главное слово названия (первое не-прилагательное, нижний регистр): «Активные клиенты» → «клиенты»,
    «Выручка от клиентов» → «выручка»."""
    toks = [t.lower() for t in str(name or "").replace(",", " ").split()]
    h = 0
    while h < len(toks) - 1 and _is_adj(toks[h]):
        h += 1
    return toks[h] if toks else ""


# «каждый час», «каждая минута» — единица оси X в наклоне рассеяния
_EACH: dict[str, str] = {
    "ч": "каждый час", "ч.": "каждый час", "час": "каждый час", "мин": "каждая минута", "мин.": "каждая минута",
    "дн.": "каждый день", "дн": "каждый день", "₽": "каждый рубль", "руб.": "каждый рубль",
    "тыс. ₽": "каждая тысяча рублей", "млн ₽": "каждый миллион рублей", "млрд ₽": "каждый миллиард рублей",
    "%": "каждый процент", "п.п.": "каждый процентный пункт", "шт.": "каждая штука", "чел.": "каждый человек",
    "км": "каждый километр", "кг": "каждый килограмм", "балл": "каждый балл", "баллов": "каждый балл",
}


_PER = {"нед.": "в неделю", "нед": "в неделю", "неделю": "в неделю", "мес.": "в месяц", "мес": "в месяц",
        "день": "в день", "дн.": "в день", "сут.": "в сутки", "год": "в год", "г.": "в год", "ч": "в час"}


def each_unit(unit: Optional[str]) -> Optional[tuple[str, str]]:
    """(«каждый час», «в неделю») для «каждый час подготовки в неделю — около +2 баллов»; единица без знаменателя —
    («каждый миллион рублей», ""); None — единица неизвестна."""
    if not unit:
        return None
    u = unit.strip().lower()
    base, _, per = u.partition("/")
    each = _EACH.get(base.strip())
    if each is None:
        return None
    if per and per.strip() not in _PER:
        return None
    return each, _PER.get(per.strip(), "") if per else ""


_NOT_PARTICIPLE = {"золото", "болото", "долото", "лото", "фото", "авто", "мясо", "лето", "место", "число", "окно"}


def is_participle(label: Optional[str]) -> bool:
    """Подпись — краткое причастие («Принято на 1 курс», «Отчислено студентов», «Трудоустроено»): с ним не говорят
    «принято выросло», вывод строится через двоеточие («Принято на 1 курс: +6%»)."""
    first = str(label or "").strip().split(" ")[0].lower()
    return len(first) >= 5 and first not in _NOT_PARTICIPLE and first.endswith(("ено", "ано", "ято", "ыто", "ито",
                                                                                  "оно", "уто"))


def parts_words(k: int, group: Optional[str]) -> str:
    """«3 формы обучения» по группе колонок («Форма обучения»), иначе «3 части»."""
    p = phrase(group) if group else None
    if p is not None and p.sure and p.gender != "pl":
        return count_words(k, p.low.nom, p.low.gen, p.low.gen_pl)
    return count_words(k, "часть", "части", "частей")


def by_group(group: Optional[str]) -> str:
    """«по формам обучения» по группе колонок, иначе «по частям в целом»."""
    p = phrase(group) if group else None
    if p is not None and p.sure and p.gender != "pl":
        return f"по {p.low.dat_pl}"
    return "по частям в целом"


def verb_agree(names: Sequence[str], forms: tuple[str, str, str, str]) -> str:
    """Глагол при перечне названий: одно — по роду («не вошёл / не вошла / не вошло»), несколько — мн. («не вошли»).
    `forms` — (м, ж, ср, мн)."""
    if len(names) != 1:
        return forms[3]
    p = phrase(names[0])
    g = p.gender if p is not None else "m"
    return forms[{"m": 0, "f": 1, "n": 2, "pl": 3}[g]]


def is_plural_value(value: str) -> bool:
    """Подпись категории во множественном числе («Прямые продажи», «Партнёры», «Набережные Челны») — глагол во мн.:
    «дают», «растут». «Сочи», «Тольятти» — единственное."""
    t = " ".join(str(value).split()).lower()
    # «Прочие партнёры (214)», «"Нейроны"»: число в скобках и кавычки — не слово
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip(" «»\"'„“”")
    if not t:
        return False
    if " и " in t or "," in t:
        return True
    last = re.split(r"[\s\-]", t)[-1]
    if last in _INDECL or not _CYR.match(last) or len(last) < 4:
        return False
    if last.endswith("ии"):  # «Германии» — не мн.
        return False
    if last.endswith(("ые", "кие", "гие", "хие", "жие", "шие", "чие", "щие")):  # «Прямые», «Другие»
        return True
    return last.endswith(("ы", "и")) and not last.endswith(("ый", "ий"))


_VERBS = {
    # прошедшее (м, ж, ср, мн) и настоящее (ед, мн)
    "grow": (("вырос", "выросла", "выросло", "выросли"), ("растёт", "растут")),
    "fall": (("снизился", "снизилась", "снизилось", "снизились"), ("снижается", "снижаются")),
    "give": (("дал", "дала", "дало", "дали"), ("даёт", "дают")),
    "bring": (("принёс", "принесла", "принесло", "принесли"), ("приносит", "приносят")),
    "hold": (("держался", "держалась", "держалось", "держались"), ("держится", "держатся")),
    "take": (("занимал", "занимала", "занимало", "занимали"), ("занимает", "занимают")),
    "fit": (("уложился", "уложилась", "уложилось", "уложились"), ("укладывается", "укладываются")),
    "lead": (("лидировал", "лидировала", "лидировало", "лидировали"), ("лидирует", "лидируют")),
}


def verb(kind: str, gender: Gender, past: bool = True) -> str:
    """«выросла», «вырос», «выросли»; настоящее: «растёт» / «растут»."""
    p, pres = _VERBS[kind]
    if past:
        return p[{"m": 0, "f": 1, "n": 2, "pl": 3}[gender]]
    return pres[1 if gender == "pl" else 0]


_NUM_WORDS_M = {1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять", 6: "шесть", 7: "семь", 8: "восемь", 9: "девять",
                10: "десять"}
_NUM_WORDS_F = {**_NUM_WORDS_M, 1: "одна", 2: "две"}
WORD_NUMS = {**{v: k for k, v in _NUM_WORDS_M.items()}, "одна": 1, "одно": 1, "две": 2, "двух": 2, "трёх": 3, "трех": 3,
              "четырёх": 4, "четырех": 4, "пяти": 5, "шести": 6, "семи": 7, "восьми": 8, "девяти": 9, "десяти": 10}


def number_word(n: int, gender: Gender = "m") -> str:
    """2 → «два» (м.) / «две» (ж.); больше 10 — цифрами."""
    table = _NUM_WORDS_F if gender == "f" else _NUM_WORDS_M
    return table.get(n, _group(n))


# ── периоды ───────────────────────────────────────────────────────────────────────────────────────────────────────────
# слово периода: (один, несколько, много, род, «месяц за месяцем», именительный мн.)
PERIOD_WORDS: dict[str, tuple[str, str, str, Gender, str, str]] = {
    "hour": ("час", "часа", "часов", "m", "час за часом", "Часы"),
    "day": ("день", "дня", "дней", "m", "день за днём", "Дни"),
    "week": ("неделя", "недели", "недель", "f", "неделя за неделей", "Недели"),
    "month": ("месяц", "месяца", "месяцев", "m", "месяц за месяцем", "Месяцы"),
    "quarter": ("квартал", "квартала", "кварталов", "m", "квартал за кварталом", "Кварталы"),
    "year": ("год", "года", "лет", "m", "год за годом", "Годы"),
    "irregular": ("точка", "точки", "точек", "f", "от точки к точке", "Даты"),
}
_MONTHS_NOM = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь",
               "декабрь"]
_MONTHS_DAT = ["январю", "февралю", "марту", "апрелю", "маю", "июню", "июлю", "августу", "сентябрю", "октябрю", "ноябрю",
               "декабрю"]
_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября",
               "декабря"]
_MONTHS_PREP = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре",
                "ноябре", "декабре"]
_MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_ROMAN = ["I", "II", "III", "IV"]


def month_name(m: int, case: str = "nom") -> str:
    return {"nom": _MONTHS_NOM, "dat": _MONTHS_DAT, "gen": _MONTHS_GEN, "short": _MONTHS_SHORT}[case][m - 1]


_ISO_M = re.compile(r"^(\d{4})-(\d{2})$")
_ISO_Q = re.compile(r"^(\d{4})-Q([1-4])$")
_ISO_D = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$")
_ISO_W = re.compile(r"^(\d{4})-W(\d{2})$")
_ISO_Y = re.compile(r"^(\d{4})$")


def _yr(y: str) -> str:
    """« 2025» после периода; у месяцев и кварталов без года (условный год 0001…) — пусто."""
    return "" if int(y) < 1000 else f" {y}"


def no_year(iso: str) -> bool:
    """Период без года (месяц или квартал «вообще»: климат, сезонность)."""
    m = re.match(r"^(\d{4})", iso or "")
    return bool(m) and int(m.group(1)) < 1000


def period_label(iso: str, freq: str, with_year: bool = True) -> str:
    """Подпись периода на оси: «янв 2025», «IV кв. 2024», «2025», «13 янв 2025», «нед. 3, 2025»; без года — «янв»."""
    if m := _ISO_M.match(iso):
        return (_MONTHS_SHORT[int(m.group(2)) - 1] + _yr(m.group(1))) if with_year else _MONTHS_SHORT[int(m.group(2)) - 1]
    if m := _ISO_Q.match(iso):
        return f"{_ROMAN[int(m.group(2)) - 1]} кв.{_yr(m.group(1))}"
    if m := _ISO_D.match(iso):
        d = f"{int(m.group(3))} {_MONTHS_SHORT[int(m.group(2)) - 1]}"
        if m.group(4):
            return f"{d} {m.group(4)}:{m.group(5)}"
        return f"{d} {m.group(1)}" if with_year else d
    if m := _ISO_W.match(iso):
        return f"нед. {int(m.group(2))}, {m.group(1)}"
    return iso


def period_text(iso: str) -> str:
    """Период в тексте: «сентябрь 2026», «III кв. 2026», «2026 год», «31 января 2025»."""
    if m := _ISO_M.match(iso):
        return f"{_MONTHS_NOM[int(m.group(2)) - 1]}{_yr(m.group(1))}"
    if m := _ISO_Q.match(iso):
        return f"{_ROMAN[int(m.group(2)) - 1]} кв.{_yr(m.group(1))}"
    if m := _ISO_D.match(iso):
        day = f"{int(m.group(3))} {_MONTHS_GEN[int(m.group(2)) - 1]} {m.group(1)}"
        return f"{day}, {m.group(4)}:{m.group(5)}" if m.group(4) else day
    if m := _ISO_Y.match(iso):
        return f"{m.group(1)} год"
    if m := _ISO_W.match(iso):
        return f"{int(m.group(2))}-я неделя {m.group(1)}"
    return iso


def period_dative(iso: str, with_year: bool = False) -> Optional[str]:
    """«к сентябрю», «к III кварталу»; with_year — «к III кварталу 2024» (год — подпись периода, не число вывода);
    None — для дней, недель, лет."""
    if m := _ISO_M.match(iso):
        return "к " + _MONTHS_DAT[int(m.group(2)) - 1] + (_yr(m.group(1)) if with_year else "")
    if m := _ISO_Q.match(iso):
        return f"к {_ROMAN[int(m.group(2)) - 1]} кварталу" + (_yr(m.group(1)) if with_year else "")
    return None


def times_word(r: float) -> str:
    """«в 2 раза», «в 5 раз», «в 2,5 раза», «в 21 раз»."""
    if not float(r).is_integer():
        return "раза"
    return plural(int(r), "раз", "раза", "раз")


def period_gen(iso: str) -> str:
    """Период в родительном: «января 2025», «IV кв. 2024», «2025 года», «10-й недели 2026»."""
    if m := _ISO_M.match(iso):
        return f"{_MONTHS_GEN[int(m.group(2)) - 1]}{_yr(m.group(1))}"
    if m := _ISO_Y.match(iso):
        return f"{m.group(1)} года"
    if m := _ISO_W.match(iso):
        return f"{int(m.group(2))}-й недели {m.group(1)}"
    return period_text(iso)


def period_acc(iso: str) -> str:
    """Период в винительном («по …»): «сентябрь 2026», «2025 год», «22-ю неделю 2026»."""
    if m := _ISO_W.match(iso):
        return f"{int(m.group(2))}-ю неделю {m.group(1)}"
    return period_text(iso)


def period_in(iso: str) -> str:
    """«в сентябре 2026», «в 2019 году», «в III кв. 2026», «на 10-й неделе 2026», «31 января 2025»."""
    if m := _ISO_M.match(iso):
        return f"в {_MONTHS_PREP[int(m.group(2)) - 1]}{_yr(m.group(1))}"
    if m := _ISO_Y.match(iso):
        return f"в {m.group(1)} году"
    if m := _ISO_Q.match(iso):
        return f"в {_ROMAN[int(m.group(2)) - 1]} кв.{_yr(m.group(1))}"
    if m := _ISO_W.match(iso):
        return f"на {int(m.group(2))}-й неделе {m.group(1)}"
    return period_text(iso)


def period_than(iso: str) -> Optional[str]:
    """База «год к году» без двусмысленности: «чем в сентябре 2025», «чем во II квартале 2025» («к II кварталу 2025»
    читается и как «к сроку»); None — для дней, недель и лет."""
    if m := _ISO_M.match(iso):
        return f"чем в {_MONTHS_PREP[int(m.group(2)) - 1]}{_yr(m.group(1))}"
    if m := _ISO_Q.match(iso):
        q = int(m.group(2))
        return f"чем {'во' if q == 2 else 'в'} {_ROMAN[q - 1]} квартале{_yr(m.group(1))}"
    return None


def period_dat_full(iso: str) -> str:
    """Период в дательном с годом: «сентябрю 2025», «III кв. 2025», «2025 году», «10-й неделе 2026»."""
    if m := _ISO_M.match(iso):
        return f"{_MONTHS_DAT[int(m.group(2)) - 1]}{_yr(m.group(1))}"
    if m := _ISO_Y.match(iso):
        return f"{m.group(1)} году"
    if m := _ISO_W.match(iso):
        return f"{int(m.group(2))}-й неделе {m.group(1)}"
    return period_text(iso)


# ── доли и длительности ───────────────────────────────────────────────────────────────────────────────────────────────
_FRACTIONS = [  # (от, до, слова) — доля словами рядом с числом
    (95, 100.01, None), (70, 95, None), (66, 70, "две трети"), (55, 66, "больше половины"),
    (50, 55, "половину"), (43, 50, "почти половину"), (34, 43, None), (32, 34, "треть"), (29, 32, "почти треть"),
    (25.5, 29, "больше четверти"), (24.5, 25.5, "четверть"), (22, 24.5, "почти четверть"),
]


_FRACTION_NOM = {"почти половину": "почти половина", "половину": "половина", "почти треть": "почти треть",
                 "треть": "треть", "четверть": "четверть", "почти четверть": "почти четверть"}


def fraction_words(p: float, case: str = "acc") -> Optional[str]:
    """Доля словами: после глагола — винительный («приносит почти половину»), после тире — именительный («— почти
    половина»)."""
    for lo, hi, w in _FRACTIONS:
        if lo <= p < hi:
            return _FRACTION_NOM.get(w, w) if (case == "nom" and w) else w
    return None


def duration_text(minutes: float) -> tuple[str, float, str]:
    """Длительность для «за …»: 120 → («2 часа», 2, «ч»); 1 час → («час», 1, «ч»); 45 → («45 минут», 45, «мин»);
    2880 → («2 дня», 2, «дн.»)."""
    if minutes >= 1440 and minutes % 1440 == 0:
        k = minutes / 1440
        return f"{fmt_num(k)} {plural(k, 'день', 'дня', 'дней')}", k, "дн."
    if minutes >= 60 and minutes % 60 == 0:
        k = minutes / 60
        if k == 1:
            return "час", 1, "ч"
        return f"{fmt_num(k)} {plural(k, 'час', 'часа', 'часов')}", k, "ч"
    if minutes < 1:
        s = minutes * 60
        return f"{fmt_num(s)} {plural(s, 'секунду', 'секунды', 'секунд')}", s, "с"
    return f"{fmt_num(minutes)} {plural(minutes, 'минуту', 'минуты', 'минут')}", minutes, "мин"


def duration_gen(minutes: float) -> str:
    """Длительность после «больше/меньше»: «600 минут», «10 часов», «1 минуты», «2 дней»."""
    if minutes >= 1440 and minutes % 1440 == 0:
        k = minutes / 1440
        return f"{fmt_num(k)} {plural(k, 'дня', 'дней', 'дней')}"
    if minutes >= 60 and minutes % 60 == 0:
        k = minutes / 60
        return f"{fmt_num(k)} {plural(k, 'часа', 'часов', 'часов')}"
    return f"{fmt_num(minutes)} {plural(minutes, 'минуты', 'минут', 'минут')}"


# ── основы слов (сопоставление целей с датасетами) ────────────────────────────────────────────────────────────────────
_ENDINGS = sorted(
    ["ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими", "иях", "ах", "ях", "ов", "ев", "ей", "ий", "ый", "ой",
     "ым", "ых", "их",
     "ая", "яя", "ое", "ее", "ые", "ие", "ую", "юю", "ом", "ем", "ам", "ям", "ию", "ия", "ье", "ья", "а", "я",
     "о", "е", "ы", "и", "у", "ю", "ь", "й"],
    key=len, reverse=True,
)


def stem(word: str) -> str:
    """Грубая основа русского слова: «выручки», «выручка», «выручку» → «выручк»; «регионы» → «регион»; беглая гласная —
    без неё: «свинец», «свинцу» → «свинц», «рынок», «рынка» → «рынк»."""
    w = word.lower().replace("ё", "е")
    if len(w) >= 7 and w.endswith("им") and w[-3] in "нжшчщ":
        return w[:-2]  # «средним», «свежим» — прилагательное; «режим», «Максим» — нет
    if len(w) >= 6 and w[-3:] in ("ему", "ема", "еме", "емы") and w[-4] in "аеиоуыэюя":
        return w[:-1]  # «приёму», «приёма» — существительное «приём», а не окончание «-ему»
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            if len(e) >= 2 and e[0] in "ео" and w[-len(e) - 1] in "аеиоуыэюяъ":
                continue  # «приём» — основа «прием», а не «при» + «ем»
            w = w[: -len(e)]
            break
    if len(w) >= 5 and w[-2:] in ("ец", "ок", "ек") and w[-3] not in "аеиоуыэюя":
        w = w[:-2] + w[-1]
    return w


def stems_of(text: str, stop: frozenset[str] = frozenset()) -> list[str]:
    """Основы значимых слов текста (без слов из `stop` и коротких), по порядку, без повторов."""
    out: list[str] = []
    for w in re.findall(r"[a-zа-яё0-9]+", (text or "").lower()):
        if w in stop or len(w) < 3:
            continue
        s = stem(w)
        if s not in out:
            out.append(s)
    return out


def same_stem(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 4 and long_.startswith(short)


def stem_in(a: str, b: str) -> bool:
    """Основы совпадают или одна — часть сложного слова: «потреблен» в «водопотреблени», «вод» в начале
    «водопотреблени»."""
    if same_stem(a, b):
        return True
    short, long_ = sorted((a, b), key=len)
    return (len(short) >= 5 and short in long_) or (len(short) >= 3 and len(long_) >= 8 and long_.startswith(short))


def stems_match(subject: Sequence[str], text: str) -> bool:
    """Есть ли среди основ текста хоть одна из основ предмета («выручк» ~ «Выручка, млн ₽»)."""
    words = stems_of(text)
    return any(same_stem(s, w) for s in subject for w in words)


def file_title(file: Optional[str], sheet: Optional[str] = None) -> str:
    """Название датасета по файлу: «Выручка по месяцам.csv» → «Выручка по месяцам» (лист XLSX — через «·»)."""
    s = re.sub(r"\.[A-Za-z0-9]+$", "", file or "").strip()
    # номер файла в начале («01 Заказы…», «3_Продажи», «12a Выручка») — не часть названия; год («2025 Выручка») — часть
    s = re.sub(r"^(?:\d{1,3}[a-zа-я]?)[\s._\-–)]+(?=[A-ZА-ЯЁ])", "", s).strip() or s
    if sheet:
        s = f"{s} · {sheet}" if s else sheet
    return upper_first(s) if s else "Данные"
