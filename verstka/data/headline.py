"""Заголовок-вывод (описание решения §2.6) и русские слова слоя данных.

Заголовок — вывод с настоящим числом из данных («Выручка выросла на 23% к сентябрю», «Москва даёт 41% выручки,
Казань растёт быстрее всех», «80% обращений получают ответ за 2 часа», «Топ-10 клиентов дают 38% выручки»), а не тема
(«Выручка по месяцам»). Шаблоны — по задаче; числа берутся только из фактов (`verstka/data/facts.py`), и
`headline_ok` проверяет, что каждое число заголовка есть среди фактов: модель (навык `data_storyteller`) может
переформулировать заголовок, но если в её тексте число не из фактов, остаётся детерминированный.

Вверху модуля — помощники русского языка, которыми пользуются факты, задача и варианты: числа по-русски («1 433»,
«4,2»), формы слов при числе («21 точка», «8 регионов»), падежи названий колонок («выручки», «по выручке», «клиентов»),
род для глагола («выручка выросла», «NPS вырос», «продажи выросли»), месяцы и кварталы («к сентябрю», «к III кварталу»).
Морфология — правила с исключениями для частых слов; где правило не уверено, текст строится так, чтобы падеж не был
нужен («8 категорий» вместо «8 …ов»)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Sequence

from verstka.schemas.data import HeadlineFact, TaskKind

if TYPE_CHECKING:  # pragma: no cover
    from verstka.data.facts import FactSet

__all__ = [
    "NBSP", "plural", "count_words", "fmt_num", "fmt_pct", "fmt_signed", "fmt_value", "lower_first", "upper_first",
    "Phrase", "phrase", "metric_phrase", "is_counter", "is_plural_value", "verb", "number_word", "PERIOD_WORDS", "period_label", "period_dative",
    "period_text", "month_name", "numbers_in", "headline_ok", "compose", "join_and",
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
    if decimals is None:
        a = abs(x)
        decimals = 0 if a >= 100 else 1 if a >= 10 else 2
    r = round(float(x), decimals)
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


def fmt_value(x: float, unit: Optional[str]) -> str:
    """Значение с единицей: «1 433 млн ₽», «46%», «52»."""
    s = fmt_num(x)
    if not unit:
        return s
    return s + unit if unit == "%" else s + NBSP + unit


# ── слова ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def count_words(n: int, one: str, few: str, many: str) -> str:
    """«21 точка», «8 регионов», «512 значений» (разряды — неразрывным пробелом)."""
    return f"{_group(int(n))} {plural(n, one, few, many)}"


def lower_first(s: str) -> str:
    """Название колонки внутри фразы: «Выручка» → «выручка»; аббревиатуры («NPS», «ВВП») — как есть."""
    if not s:
        return s
    if len(s) > 1 and (s[1].isupper() or s[1].isdigit()):
        return s
    return s[0].lower() + s[1:]


def upper_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def join_and(items: Sequence[str]) -> str:
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " и " + items[-1]


_CYR = re.compile(r"^[а-яё\-]+$")
_ADJ_END = ("ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые", "ие")
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
              "края": "край", "года": "год", "директора": "директор", "учителя": "учитель", "профессора": "профессор"}
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
    "продажи": ("продажа", "продаж", "продажам", "продаж", "продажам", "продажи", "pl"),
    "расходы": ("расход", "расходов", "расходам", "расходов", "расходам", "расходы", "pl"),
    "доходы": ("доход", "доходов", "доходам", "доходов", "доходам", "доходы", "pl"),
    "затраты": ("затрата", "затрат", "затратам", "затрат", "затратам", "затраты", "pl"),
    "средства": ("средство", "средств", "средствам", "средств", "средствам", "средства", "pl"),
    "сутки": ("сутки", "суток", "суткам", "суток", "суткам", "сутки", "pl"),
    "рынок": ("рынок", "рынка", "рынку", "рынков", "рынкам", "рынки", "m"),
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
    while h < len(toks) - 1 and low[h].endswith(_ADJ_END) and _CYR.match(low[h]) and len(low[h]) >= 4:
        h += 1
    head = low[h]
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
               "дней", "недель", "лет", "штук", "единиц", "задач", "услуг"}
_NOT_COUNTER = {"музей", "лицей", "юбилей", "хоккей", "ростов", "остров", "ков"}


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
    return len(first) >= 5 and first.endswith(("ов", "ев", "ых", "их", "елей", "телей", "лей"))


def metric_phrase(name: Optional[str], mtype: str = "number") -> Optional[Phrase]:
    """Падежи названия метрики; счётчик («Заказов») — как «Число заказов» (у процентов — «Доля довольных клиентов»)."""
    if not name:
        return None
    if is_counter(name):
        return phrase(("Доля " if mtype == "percent" else "Число ") + lower_first(str(name).strip()))
    return phrase(name)


def is_plural_value(value: str) -> bool:
    """Подпись категории во множественном числе («Прямые продажи», «Партнёры», «Набережные Челны») — глагол во мн.:
    «дают», «растут». «Сочи», «Тольятти» — единственное."""
    t = " ".join(str(value).split()).lower()
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
_WORD_NUMS = {**{v: k for k, v in _NUM_WORDS_M.items()}, "одна": 1, "одно": 1, "две": 2, "двух": 2, "трёх": 3, "трех": 3,
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
_MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_ROMAN = ["I", "II", "III", "IV"]


def month_name(m: int, case: str = "nom") -> str:
    return {"nom": _MONTHS_NOM, "dat": _MONTHS_DAT, "gen": _MONTHS_GEN, "short": _MONTHS_SHORT}[case][m - 1]


_ISO_M = re.compile(r"^(\d{4})-(\d{2})$")
_ISO_Q = re.compile(r"^(\d{4})-Q([1-4])$")
_ISO_D = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$")
_ISO_W = re.compile(r"^(\d{4})-W(\d{2})$")
_ISO_Y = re.compile(r"^(\d{4})$")


def period_label(iso: str, freq: str, with_year: bool = True) -> str:
    """Подпись периода на оси: «янв 2025», «IV кв. 2024», «2025», «13 янв 2025», «нед. 3, 2025»."""
    if m := _ISO_M.match(iso):
        return f"{_MONTHS_SHORT[int(m.group(2)) - 1]} {m.group(1)}" if with_year else _MONTHS_SHORT[int(m.group(2)) - 1]
    if m := _ISO_Q.match(iso):
        return f"{_ROMAN[int(m.group(2)) - 1]} кв. {m.group(1)}"
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
        return f"{_MONTHS_NOM[int(m.group(2)) - 1]} {m.group(1)}"
    if m := _ISO_Q.match(iso):
        return f"{_ROMAN[int(m.group(2)) - 1]} кв. {m.group(1)}"
    if m := _ISO_D.match(iso):
        return f"{int(m.group(3))} {_MONTHS_GEN[int(m.group(2)) - 1]} {m.group(1)}"
    if m := _ISO_Y.match(iso):
        return f"{m.group(1)} год"
    if m := _ISO_W.match(iso):
        return f"{int(m.group(2))}-я неделя {m.group(1)}"
    return iso


def period_dative(iso: str) -> Optional[str]:
    """«к сентябрю», «к III кварталу» — без года (в заголовке каждое число — из фактов); None — для дней, недель, лет."""
    if m := _ISO_M.match(iso):
        return "к " + _MONTHS_DAT[int(m.group(2)) - 1]
    if m := _ISO_Q.match(iso):
        return f"к {_ROMAN[int(m.group(2)) - 1]} кварталу"
    return None


# ── проверка чисел заголовка ──────────────────────────────────────────────────────────────────────────────────────────
_NUM_IN_TEXT = re.compile(r"(?<![\w,.])[+\-−–]?\d{1,3}(?:[   ]\d{3})+(?:,\d+)?(?![\d])"
                          r"|(?<![\w,.])[+\-−–]?\d+(?:[.,]\d+)?(?![\d])")
_WORD_RE = re.compile(r"[а-яё]+", re.I)


def numbers_in(text: str) -> list[float]:
    """Числа в тексте: «1 433», «4,2», «+23%», «топ-10» (10), «два квартала» (2). Римские («III кв.») — не числа."""
    out: list[float] = []
    for m in _NUM_IN_TEXT.finditer(text or ""):
        tok = m.group(0)
        tok = re.sub(r"[   ]", "", tok).replace(",", ".").lstrip("+−–-")
        try:
            out.append(abs(float(tok)))
        except ValueError:
            continue
    for w in _WORD_RE.findall(text or ""):
        n = _WORD_NUMS.get(w.lower())
        if n is not None:
            out.append(float(n))
    return out


def _matches(n: float, v: float) -> bool:
    v = abs(v)
    if abs(n - v) < 1e-9:
        return True
    for d in (0, 1, 2):
        if abs(round(v, d) - n) < 1e-9:
            return True
    return False


def headline_ok(text: str, facts: Sequence[HeadlineFact]) -> bool:
    """Каждое число заголовка есть среди фактов (значение, как его пишет заголовок: целое или с одним-двумя знаками)."""
    values = [f.value for f in facts]
    return all(any(_matches(n, v) for v in values) for n in numbers_in(text))


# ── шаблоны заголовка ─────────────────────────────────────────────────────────────────────────────────────────────────
def compose(task: TaskKind, fs: "FactSet") -> tuple[str, Optional[str]]:
    """Заголовок-вывод и подпись-пояснение из фактов задачи. Факты задают и слова (ctx: лидер, период, сущность) —
    шаблон только расставляет их по-русски."""
    fn = {
        "dynamics": _dynamics, "comparison": _comparison, "shares": _shares, "distribution": _distribution,
        "reference": _reference, "kpi": _kpi, "relationship": _relationship,
    }[task]
    head, caption = fn(fs)
    head = head.strip().rstrip(".")
    head = upper_first(head)
    if not headline_ok(head, fs.facts):  # страховка: число не из фактов — заголовок-описание
        head = fs.ctx.get("plain") or head
    return head, caption


def _f(fs: "FactSet", fid: str) -> Optional[HeadlineFact]:
    return next((f for f in fs.facts if f.id == fid), None)


def _dynamics(fs: "FactSet") -> tuple[str, Optional[str]]:
    c = fs.ctx
    m: Phrase = c["metric"]
    subj = c["subject"]  # «Выручка», «NPS», «Число клиентов»
    g: Gender = c["gender"]
    gap = _f(fs, "gaps")
    gap_txt = ""
    if gap is not None:
        k = int(gap.value)
        pw = PERIOD_WORDS.get(c["freq"], PERIOD_WORDS["irregular"])
        if k == 1 and c.get("gap_label"):
            gap_txt = f", за {c['gap_label']} данных нет"
        elif k <= 4:
            gap_txt = f", за {number_word(k, pw[3])} {plural(k, pw[0], pw[1], pw[2])} данных нет"
        else:
            gap_txt = f", за {count_words(k, pw[0], pw[1], pw[2])} данных нет"
    last = _f(fs, "last")
    change = _f(fs, "change")
    ratio = _f(fs, "ratio")
    if c.get("level") and last is not None:
        delta = c.get("delta", 0.0)
        if abs(delta) < 1e-9 or change is None:
            head = f"{subj} {verb('hold', g, past=False)} на уровне {fmt_value(last.value, c.get('unit_short'))}"
        else:
            v = verb("grow" if delta > 0 else "fall", g)
            head = f"{subj} {v} до {fmt_value(last.value, c.get('unit_short'))}"
        return head + gap_txt, c.get("caption")
    if change is None and last is not None:
        return f"{subj} — {fmt_value(last.value, c.get('unit_short'))}" + gap_txt, c.get("caption")
    if change is None:
        return c.get("plain", subj), c.get("caption")
    when = c.get("when", "")
    if ratio is not None:
        r = ratio.value
        word = "раза" if not float(r).is_integer() or plural(r, "раз", "раза", "раз") == "раза" else "раз"
        head = f"{subj} {verb('grow', g)} в {fmt_num(r, 1)} {word} {when}"
    elif abs(change.value) < 1 and last is not None:
        head = f"{subj} {verb('hold', g, past=False)} на уровне {fmt_value(last.value, c.get('unit_short'))}"
    else:
        v = verb("grow" if c["delta"] > 0 else "fall", g)
        head = f"{subj} {v} на {fmt_pct(change.value)}% {when}"
    return " ".join(head.split()) + gap_txt, c.get("caption")


def _comparison(fs: "FactSet") -> tuple[str, Optional[str]]:
    c = fs.ctx
    leader = c["leader"]
    pl = "pl" if is_plural_value(leader) else "m"
    share = _f(fs, "leader_share")
    grow_leader = c.get("growth_leader")
    m: Optional[Phrase] = c.get("metric")
    if share is not None and m is not None:
        head = f"{leader} {verb('give', pl, past=False)} {fmt_pct(share.value)}% {m.low.gen}"
    elif _f(fs, "leader_value") is not None:
        lv = _f(fs, "leader_value")
        head = f"{leader} впереди: {fmt_value(lv.value, c.get('unit_short'))}"
        last = _f(fs, "last_value")
        if last is not None and c.get("last_label"):
            head += f", {c['last_label']} — {fmt_value(last.value, c.get('unit_short'))}"
    else:
        head = c.get("plain", leader)
    if grow_leader:
        gpl = "pl" if is_plural_value(grow_leader) else "m"
        if grow_leader == leader:
            head += f" и {verb('grow', pl, past=False)} быстрее всех"
        else:
            head += f", {grow_leader} {verb('grow', gpl, past=False)} быстрее всех"
    neg = _f(fs, "negatives")
    if neg is not None and not grow_leader:
        forms = c.get("neg_forms") or ("категория", "категории", "категорий")
        head += f", {count_words(int(neg.value), *forms)} в минусе"
    return head, c.get("caption")


_FRACTIONS = [  # (от, до, слова) — доля словами рядом с числом
    (95, 100.01, "почти всё"), (70, 95, None), (66, 70, "две трети"), (55, 66, "больше половины"),
    (50, 55, "половину"), (43, 50, "почти половину"), (34, 43, None), (32, 34, "треть"), (29, 32, "почти треть"),
    (25.5, 29, "больше четверти"), (24.5, 25.5, "четверть"), (22, 24.5, "почти четверть"),
]


def fraction_words(p: float) -> Optional[str]:
    for lo, hi, w in _FRACTIONS:
        if lo <= p < hi:
            return w
    return None


def _shares(fs: "FactSet") -> tuple[str, Optional[str]]:
    c = fs.ctx
    leader = c["leader"]
    pl = "pl" if is_plural_value(leader) else "m"
    share = _f(fs, "leader_share")
    whole: Optional[Phrase] = c.get("whole")
    if share is None:
        return c.get("plain", leader), c.get("caption")
    p = share.value
    words = fraction_words(p)
    v = verb("bring" if c.get("money") else "give", pl, past=False)
    if whole is not None:
        if words:
            head = f"{leader} {v} {words} {whole.low.gen} — {fmt_pct(p)}%"
        else:
            head = f"{leader} {v} {fmt_pct(p)}% {whole.low.gen}"
    else:
        head = f"{leader} {verb('take', pl, past=False)} {words + ' — ' if words else ''}{fmt_pct(p)}%"
    return head, c.get("caption")


def _distribution(fs: "FactSet") -> tuple[str, Optional[str]]:
    c = fs.ctx
    share = _f(fs, "share_within")
    if share is None:
        med = _f(fs, "median")
        if med is not None:
            return f"Медиана — {fmt_value(med.value, c.get('unit_short'))}", c.get("caption")
        return c.get("plain", ""), c.get("caption")
    ent = c.get("entities_gen")  # «обращений»
    who = f"{fmt_pct(share.value)}% {ent}" if ent else f"{fmt_pct(share.value)}% значений"
    if c.get("duration"):
        pred = c.get("predicate") or "укладываются в"
        head = f"{who} {pred} {c['threshold_text']}"
    else:
        head = f"{who} — не больше {c['threshold_text']}"
    return head, c.get("caption")


def _reference(fs: "FactSet") -> tuple[str, Optional[str]]:
    c = fs.ctx
    top = _f(fs, "top_share")
    n_top = _f(fs, "top_n")
    m: Optional[Phrase] = c.get("metric")
    if top is not None and n_top is not None and m is not None:
        ent = c.get("entities_gen")
        who = f"Топ-{int(n_top.value)} {ent}" if ent else f"{int(n_top.value)} крупнейших"
        return f"{who} {verb('give', 'pl', past=False)} {fmt_pct(top.value)}% {m.low.gen}", c.get("caption")
    count = _f(fs, "count")
    if count is not None:
        forms = c.get("entity_forms") or ("строка", "строки", "строк")
        head = count_words(int(count.value), *forms)
        groups = _f(fs, "groups")
        if groups is not None and c.get("group_forms"):
            gn = int(groups.value)
            gf = c["group_forms"]
            head += f" из {_group(gn)} {gf[0] if plural(gn, 1, 2, 3) == 1 else gf[1]}"
        return head, c.get("caption")
    return c.get("plain", ""), c.get("caption")


def _kpi(fs: "FactSet") -> tuple[str, Optional[str]]:
    c = fs.ctx
    a, b = _f(fs, "kpi_a"), _f(fs, "kpi_b")
    a_name: str = c.get("a_name", "")
    if a is not None and b is not None:
        ga: Gender = c.get("a_gender", "m")
        b_gen = c.get("b_gen")
        sa = fmt_signed(c["a_signed"], c.get("a_unit") or "")
        sb = fmt_signed(c["b_signed"], c.get("b_unit") or "")
        if c["a_signed"] > 0 and c["b_signed"] > 0 and b_gen:
            cmp_word = "быстрее" if c["a_signed"] > c["b_signed"] else "медленнее" if c["a_signed"] < c["b_signed"] else None
            if cmp_word:
                return f"{a_name} {verb('grow', ga, past=False)} {cmp_word} {b_gen}: {sa} против {sb}", c.get("caption")
        if c["a_signed"] > 0 > c["b_signed"]:
            gb: Gender = c.get("b_gender", "m")
            return (f"{a_name} {verb('grow', ga, past=False)}, а {lower_first(c.get('b_name', ''))} "
                    f"{verb('fall', gb, past=False)}: {sa} и {sb}"), c.get("caption")
        return f"{a_name}: {sa}, {lower_first(c.get('b_name', ''))}: {sb}", c.get("caption")
    if a is not None:
        ga = c.get("a_gender", "m")
        v = verb("grow" if c["a_signed"] > 0 else "fall", ga)
        return f"{a_name} {v} на {fmt_pct(abs(c['a_signed']))}%" if c.get("a_unit") == "%" else \
            f"{a_name}: {fmt_signed(c['a_signed'], c.get('a_unit') or '')}", c.get("caption")
    val = _f(fs, "kpi_value")
    if val is not None:
        return f"{a_name} — {c.get('a_value_text')}", c.get("caption")
    return c.get("plain", ""), c.get("caption")


def _relationship(fs: "FactSet") -> tuple[str, Optional[str]]:
    c = fs.ctx
    r = _f(fs, "r")
    if r is None:
        return c.get("plain", ""), c.get("caption")
    x, y = c["x"], c["y"]
    rv = c["r_signed"]
    rt = fmt_num(rv, 2)
    if abs(rv) < 0.3:
        return f"{upper_first(x)} и {lower_first(y)} почти не связаны: r = {rt}", c.get("caption")
    more = "выше"
    other = "выше" if rv > 0 else "ниже"
    strength = "" if abs(rv) >= 0.7 else ", но связь умеренная"
    return f"Чем {more} {lower_first(x)}, тем {other} {lower_first(y)}{strength}: r = {rt}", c.get("caption")
