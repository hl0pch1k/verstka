"""Метрики и их единицы: изменение, уровень или поток, остаток, индекс, длительность; план и факт, колонки-периоды;
число ячейки. Отсюда — `Measure` каждой числовой колонки (`build_measure`).

Складывать значения можно только по признаку в данных (`additivity`): поток денег (выручка, расходы), счёт событий и
предметов (штуки, люди, «Заказов», «Доставлено»), строка или колонка итога, равная сумме. Уровень — тоже по признаку:
единица на единицу («ц/га», «₽/м²», «°C», «‰», «балл»), статистика («минимум», «медиана», «средний»), код валюты
(«USD») или название датасета о курсах, ценах, урожайности, температуре. Нет признака — уровень: без долей, без «Итого»,
при ресэмплинге — среднее."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any, Optional, Sequence

from verstka.data.parse import parse_quantity, period_parts, quantity, season_name, split_unit
from verstka.data.views import Measure
from verstka.data.words import file_title, fmt_count, head_word, is_counter, is_event_name, phrase
from verstka.schemas.data import ColumnProfile

if TYPE_CHECKING:
    from verstka.data.aggregate import Data

# «Доля неудачных изменений» (DORA) — доля событий-изменений, а не изменение величины: «изменений» не в счёт
_CHANGE = re.compile(r"изменени[еяю](?![а-яё])|(?:^|[^а-яё])(?:при)?рост|динамик|разниц|отклонени|к прошл|г/г|yoy|дельта|δ",
                     re.I)
_LEVEL = re.compile(
    r"nps|csat|индекс|средн|рейтинг|оценк|балл|очк[иоа]|конверси|(?<!\d)(?<!\d\s)курс(?:ы|а|ов)?(?![а-яё])|цен[аы]|"
    r"(?:^|[^а-яё])ставк|температур|доля|коэффициент|уровень|процент|медиан|время|срок|скорост|длительн|возраст|удовлетвор|загрузк|"
    r"маржа|маржин|рентабельн|плотност|(?:^|[^а-яё])чек(?!ов|и\b)|урожайн|на\s+душу|на\s+(?:1|одного|одну|человека|жителя|сотрудника)\b|"
    r"(?:^|\s)за\s+(?:м²|м2|кв(?![а-яё])|кг|шт|ед(?![а-яё])|единиц|час(?![а-яё])|1\b|сеанс|визит|смену|рейс)",
    re.I,
)
# статистика величины: минимум, максимум, медиана, среднее — не складываются
_STAT = re.compile(r"(?:^|[^а-яёa-z])(?:минимум\w*|максимум\w*|мин\.|макс\.|минимальн\w*|максимальн\w*|медиан\w*|"
                   r"средн\w*|min|max|median|mean|avg|average)(?:[^а-яёa-z]|$)", re.I)
# единица «на единицу» и шкалы: «ц/га», «₽/м²», «км/ч», «°C», «‰», «балл»
_RATE_UNIT = re.compile(r"/|(?:^|\s)(?:за|на)\s|°|‰|^%$|^п\.п|^п\.?$|^балл|^очк|^раз$", re.I)
# единицы счёта и объёма — складываются (множитель «тыс.», «млн» не мешает)
_EXTENSIVE_UNIT = re.compile(
    r"^(?:(?:тыс|млн|млрд|трлн)\.?\s*)?(?:шт|штук|ед|единиц|чел|человек|экз|пар|мест|кг|г|т|тонн|ц|л|мл|м|км|м²|м2|"
    r"кв\.?\s*м|м³|м3|куб\.?\s*м|га|квт·ч|квт\*ч|квтч|мвт·ч|гвт·ч|гкал|гб|тб|мб|байт|голов|посещений|визитов|"
    r"заказов|сделок|статей|публикаций|заявок|обращений|клиентов|студентов|сотрудников|пользователей|проектов|патентов|"
    r"пасс|посет|зрит|чит|"
    r"звонков|рейсов|поездок|операций|транзакций)\.?$", re.I)
# потоки денег и счёт событий, предметов, людей по названию
_FLOW = re.compile(
    r"(?:^|[^а-яё])(?:числ[оа]|количеств|кол-во|кол\.|объ[её]м|сумм[аы]?(?![а-яё]*\s+средн)|итог|всего|выручк|доход|"
    r"расход|затрат|издержк|поступлен|платеж|плат[её]ж|выплат|оплат|продаж|выпуск|производств|отгрузк|доставк|заказ|"
    r"потреблен|выработк|экспорт|импорт|оборот|прибыл|убыт|бюджет|фонд|начислен|население|численност|при[её]м|набор|"
    r"посещен|просмотр|визит|сделк|покупк|регистрац|скачиван|показ(?:ы|ов|ам|ами|ах)\b|переход|добыч|запас|остат|штат|клиент|пользовател|"
    r"сотрудник|студент|пациент|участник|ученик|жител|публикац|стат(?:ей|ьи|ья)|патент|проект|заявк|обращен|звонк|"
    r"инвестиц|вложен|кредит|депозит|вклад|налог|взнос|пожертвован|грант|субсиди|премi?и?|зарплатн\w*\s+фонд|фот\b)",
    re.I)
# коды валют: колонка «USD» — курс, а не сумма
_CURRENCY = {"usd", "eur", "cny", "gbp", "jpy", "chf", "kzt", "byn", "try", "aed", "hkd", "inr", "uah", "amd", "gel",
             "uzs", "kgs", "azn", "sek", "nok", "pln", "czk", "cad", "aud", "sgd", "krw", "brl", "zar", "huf", "dkk",
             "mdl", "tjs", "tmt", "rsd", "thb", "vnd", "idr", "egp", "qar", "sar", "ils", "mxn", "nzd", "btc", "eth"}
# название датасета о величинах-уровнях: курсы, цены, тарифы, урожайность, температура
_LEVEL_TITLE = re.compile(r"курс\w*\s+(?:валют|акци|доллар|евро|юан)|котировк|урожайн|температур|(?:^|\s)цен[аыу]?(?:\s|$)|"
                          r"тариф|ставк", re.I)
_STOCK = re.compile(r"клиент|пользовател|сотрудник|абонент|подписчик|остат|баланс|численност|штат|запас|база|"
                    r"вакан", re.I)  # открытые вакансии — на момент, как штат
# индексы и доли: изменение — в пунктах, а не в процентах («NPS +6 п.», «конверсия +0,5 п.п.»)
# индексы и оценки по шкале — изменение в пунктах; проверяется по главному слову названия и только без единицы
# (у денег и счёта изменение — всегда в процентах: «Оценка стоимости бизнеса, млн ₽» — не индекс)
INDEX_NAME = re.compile(r"^(?:nps|enps|csat|ces|индекс\w*|рейтинг\w*|оценк\w*|балл\w*|доля|доли|конверси\w*|"
                        r"удовлетвор\w*|лояльн\w*)$", re.I)
# естественные причины для оси X рассеяния: время и усилия, цена и деньги на входе, дозы и условия опыта
_DRIVER = re.compile(r"(?:^|[^а-яё])(?:час|подготов|занят|трениров|стаж|опыт работы|возраст|цен[аы]|стоимост|тариф|"
                     r"скидк|расход|затрат|инвестиц|реклам|бюджет|доз|концентрац|температур|давлени|площад|"
                     r"расстояни|время|длительн|частот|количество часов)", re.I)
# оценочные метрики — главнее счёта размера («Средний балл» важнее «Учеников»)
_EVAL_NAME = re.compile(r"балл|оценк|рейтинг|выручк|доход|прибыл|качеств|успеваем|удовлетвор|nps|конверси|удержан|"
                        r"результат|эффективн|продаж", re.I)
_TIME_NAME = {
    "мин": "мин", "минут": "мин", "минуты": "мин", "час": "ч", "часов": "ч", "часа": "ч", "ч": "ч", "дней": "дн.",
    "день": "дн.", "дня": "дн.", "дн": "дн.", "сек": "с", "секунд": "с",
}
# длительности: единица → минут в ней; «круглые» значения в минутах (ширина интервала гистограммы, порог «за 2 часа»)
TO_MINUTES = {"мин": 1.0, "мин.": 1.0, "минут": 1.0, "ч": 60.0, "ч.": 60.0, "час": 60.0, "часов": 60.0,
              "дн.": 1440.0, "дн": 1440.0, "дней": 1440.0, "с": 1 / 60, "сек": 1 / 60, "с.": 1 / 60}
NICE_MINUTES = [1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300, 360, 480, 720, 1080, 1440, 2880, 4320, 10080]
_CODE = re.compile(r"^[A-Za-zА-Яа-яЁё]{0,6}[-_/#№.]?\d{1,12}[A-Za-z]?$")
_ORDINAL_LABEL = re.compile(r"^\s*(?:до|от|свыше|более|больше|менее|меньше|<|>|≤|≥)?\s*\d")


def unit_short(unit: Optional[str]) -> Optional[str]:
    return unit or None


def _common_suffix(names: list[str]) -> str:
    """Общее дополнение после запятой: «Scopus, статей», «РИНЦ, статей» → «статей»."""
    tails = {n.split(",", 1)[1].strip().lower() if "," in n else "" for n in names}
    return next(iter(tails)) if len(tails) == 1 and "" not in tails else ""


_PLAN = re.compile(r"(?:^|[^а-яёa-z])(?:план\w*|plan|цел[ьи]|target|прогноз\w*|утвержд\w*|бюджет\w*|лимит\w*|"
                   r"норматив\w*|смет\w*)(?:[^а-яёa-z]|$)", re.I)
_FACT = re.compile(r"(?:^|[^а-яёa-z])(?:факт\w*|fact|actual|исполнен\w*|выполнен\w*|освоен\w*|израсходован\w*|"
                   r"потрачен\w*|кассов\w*)(?:[^а-яёa-z]|$)", re.I)


_MONTH_TAG = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")
_MONTH_TAG_RX = (r"(январ\w*|янв\.?|феврал\w*|фев\.?|март\w*|мар\.?|апрел\w*|апр\.?|ма[йя]|июн[ьяе]?|июл[ьяе]?|"
                 r"август\w*|авг\.?|сентябр\w*|сент?\.?|октябр\w*|окт\.?|ноябр\w*|ноя\.?|декабр\w*|дек\.?)")
_ROMAN_Q = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_YEAR_TAIL = r"(?:\s*[-–,]?\s*((?:19|20)\d\d)(?:\s*г(?:\.|ода?)?)?)?"
_TAG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # «Время ответа Q3», «Клиентов, 3 кв.», «Выручка III квартал 2026», «Q2 2026»
    ("quarter", re.compile(r"(?:^|[\s(,])(?:q\s?([1-4])|([1-4]|iv|i{1,3})\s*(?:-?(?:й|ый|ий)\s*)?(?:кв\.?|квартал\w*))"
                           + _YEAR_TAIL + r"\s*\)?$", re.I)),
    # «Клиентов на 30.06», «Учеников на 30.09.2026», «Остаток к 01.07»
    ("day", re.compile(r"(?:^|\s)(?:на|к|по\s+состоянию\s+на)\s+(\d{1,2})[./](\d{1,2})(?:[./]((?:19|20)?\d\d))?\s*\)?$",
                       re.I)),
    # «Выручка H1», «1-е полугодие 2026»
    ("half", re.compile(r"(?:^|[\s(,])(?:h([12])|([12])\s*(?:-?е\s*)?полугоди\w*)" + _YEAR_TAIL + r"\s*\)?$", re.I)),
    # «Продажи, июнь», «MRR сентябрь 2026», «Выручка (янв)»
    ("month", re.compile(r"(?:^|[\s(,])(?:за\s+)?" + _MONTH_TAG_RX + _YEAR_TAIL + r"\s*\)?$", re.I)),
    # «Выручка 2026», «Клиентов, 2025 г.»
    ("year", re.compile(r"(?:^|[\s(,])((?:19|20)\d\d)(?:\s*г(?:\.|од)?)?\s*\)?$", re.I)),
]


def period_tag(name: Optional[str]) -> Optional[tuple[str, tuple[int, int], str]]:
    """Период в названии колонки — (зернистость, ключ порядка, имя без периода): «Время первого ответа Q3» →
    («quarter», (0, 3), «Время первого ответа»), «Клиентов на 30.09» → («day», (0, 930), «Клиентов»), «MRR сентябрь
    2026» → («month», (2026, 9), «MRR»). Колонки одного имени без периода и одной зернистости — срезы одной величины во
    времени: последний — «сейчас», предыдущий — база сравнения. None — периода в названии нет."""
    s = " ".join(str(name or "").replace("ё", "е").split())
    if not s:
        return None
    for gran, rx in _TAG_PATTERNS:
        m = rx.search(s)
        if not m:
            continue
        g = [x for x in m.groups()]
        if gran == "quarter":
            q = _ROMAN_Q.get((g[0] or g[1] or "").lower())
            if q is None:
                continue
            key = (int(g[2]) if g[2] else 0, q)
        elif gran == "day":
            dd, mm = int(g[0]), int(g[1])
            if not (1 <= dd <= 31 and 1 <= mm <= 12):
                continue
            y = g[2]
            key = ((int(y) + (2000 if len(y) == 2 else 0)) if y else 0, mm * 100 + dd)
        elif gran == "half":
            key = (int(g[2]) if g[2] else 0, int(g[0] or g[1]))
        elif gran == "month":
            w = g[0].lower().rstrip(".")
            k = next((i for i, st in enumerate(_MONTH_TAG) if w.startswith(st) or (len(w) >= 3 and st.startswith(w))),
                     None)
            if k is None or (w.startswith("ма") and not re.fullmatch(r"ма[йя]", w)):
                if not (w.startswith("мар")):
                    continue
                k = 2
            key = (int(g[1]) if g[1] else 0, k + 1)
        else:
            key = (int(g[0]), 0)
        base = s[:m.start()].strip(" ,-–—(:")
        base = re.sub(r"(?i)\s+(?:на|за|к|в)$", "", base).strip(" ,-–—(:")
        return gran, key, base
    return None


def period_siblings(names: Sequence[str]) -> list[list[int]]:
    """Группы колонок-срезов одной величины («Клиентов на 30.06 · Клиентов на 30.09», «Время ответа Q2 · Q3»): номера
    колонок по порядку периодов (от старого к новому); группа — от двух колонок одного имени без периода и одной
    зернистости."""
    groups: dict[tuple[str, str], list[tuple[tuple[int, int], int]]] = {}
    for j, nm in enumerate(names):
        t = period_tag(nm)
        if t is None:
            continue
        groups.setdefault((t[0], t[2].lower()), []).append((t[1], j))
    return [[j for _, j in sorted(v)] for v in groups.values() if len(v) >= 2 and len({k for k, _ in v}) == len(v)]


def _period_name(name: str) -> bool:
    """Колонка названа периодом («2025», «Выручка 2026», «III кв. 2026», «Январь», «Клиентов на 30.09», «Время
    ответа Q3»)."""
    return bool(re.search(r"(?:^|\D)(?:19|20)\d\d(?:\D|$)", name)) or period_parts(name.strip()) is not None \
        or period_tag(name) is not None


def _period_key(name: str) -> tuple[int, int]:
    """Порядок колонок-периодов: год и номер внутри года из названия («Выручка 2026» → (2026, 0), «Время ответа Q3» →
    (0, 3))."""
    y = re.search(r"(?:19|20)\d\d", name)
    pp = period_parts(name.strip())
    if pp is not None:
        return pp[1], 0
    t = period_tag(name)
    if t is not None:
        return t[1]
    return (int(y.group(0)) if y else 0), 0


def _parts_ok(group: list[Measure]) -> bool:
    """Годы и периоды (и месяцы без года: «Июль · Август · Сентябрь»), план и факт — не части одного целого."""
    if any(_period_name(x.name) or season_name((split_unit(x.name)[0] or x.name).strip()) for x in group):
        return False
    return not (any(_PLAN.search(x.name) for x in group) and any(_FACT.search(x.name) for x in group))


def _kind(m: Measure) -> str:
    """Род величины: деньги, проценты, индекс, счётчик («Клиентов») или просто число."""
    if m.type == "money":
        return "money"
    if m.type == "percent":
        return "percent"
    if INDEX_NAME.search(head_word(m.name) or ""):
        return "index"
    if is_counter(m.name):
        return "counter"
    return "plain"


def _num(cell: Any) -> Optional[float]:
    """Число ячейки с множителем («1,24 млрд» → 1.24e9, «46 %» → 46, «(15)» → −15); None — не число или пусто."""
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if math.isfinite(cell) else None
    q = quantity(" ".join(str(cell).split()))
    return None if q is None else q.full


def is_index(name: str) -> bool:
    """Безразмерный индекс или оценка по шкале по главному слову названия: «NPS», «Индекс удовлетворённости»,
    «Средний балл»."""
    return bool(INDEX_NAME.match(head_word(split_unit(name)[0] or name) or ""))


def kpi_change(label: str, cur: float, prev: float, unit: Optional[str]) -> Optional[tuple[float, str]]:
    """Изменение показателя. Сначала единица: проценты — в п.п.; любая другая единица (деньги, люди, штуки) — в %;
    без единицы — индекс или оценка по шкале (NPS, балл) в пунктах, остальное в %."""
    u = unit or split_unit(label)[1]
    if u == "%" or (u or "").startswith("п.п"):
        return cur - prev, "п.п."
    if not u and is_index(label):
        return cur - prev, "п."
    if prev > 0:
        return (cur / prev - 1) * 100, "%"
    return None

def _time_unit_of(name: str, unit: Optional[str], siblings: Sequence[str] = (), values: Sequence[Optional[float]] = ()) -> Optional[str]:
    """Единица длительности колонки: из единицы («мин») или из имени («Минут до ответа», «Время, ч»). «Мин» без единицы —
    чаще минимум, чем минуты («Мин | Макс», «Мин цена», «Мин температура»): минуты — только когда колонка так и
    названа одним словом, рядом нет «Макс», а значения похожи на длительности (не отрицательны)."""
    if unit:
        u = unit.strip().lower()
        if u in ("мин", "мин.") and not _minutes_ok(name, siblings, values, by_unit=True):
            return None
        return u if u in TO_MINUTES else None
    words = re.split(r"[\s,()]+", name.strip().lower()) if name.strip() else [""]
    first = words[0]
    if first in ("мин", "мин.") and not _minutes_ok(name, siblings, values):
        return None
    return _TIME_NAME.get(first)


_TIME_WORDS = re.compile(r"(?i)врем|ожидан|длительн|просто|задерж|срок|ответ|в\s+пути|обработк|минут|разговор|звонк|"
                         r"восстановл|ремонт|доставк|поездк|сеанс")


def _minutes_ok(name: str, siblings: Sequence[str], values: Sequence[Optional[float]], by_unit: bool = False) -> bool:
    """«Мин» — минуты, а не минимум: у имени нет другого слова-величины («Мин цена», «Мин температура»), рядом нет
    колонки «Макс…», значения не отрицательны. С единицей «мин» («Время ответа, мин») — минуты, пока имя говорит о
    времени или рядом нет «Макс»."""
    base = (split_unit(name)[0] or name).strip().lower()
    timed = bool(_TIME_WORDS.search(base))
    maxed = any(re.match(r"(?i)\s*макс", s or "") for s in siblings if s != name)
    if by_unit:
        return timed or not maxed
    rest = [w for w in re.split(r"[\s,().]+", base) if w and w not in ("мин", "мин.")]
    if maxed or (rest and not timed):
        return False
    return not any(v is not None and v < 0 for v in values)



_CALENDAR_NAME = re.compile(r"^(?:пн|вт|ср|чт|пт|сб|вс|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье|"
                            r"mon|tue|wed|thu|fri|sat|sun|(?:19|20)\d\d)\.?$", re.I)
_TITLE_NOT_FLOW = {"итоги", "итог", "данные", "отчёт", "отчет", "сводка", "выгрузка", "таблица", "список"}


def is_currency_code(name: str) -> bool:
    base = (split_unit(name)[0] or name).strip()
    return base.lower() in _CURRENCY or bool(re.fullmatch(r"[A-Z]{3}\s*/\s*[A-Z]{3}", base))


_DURATION_FLOW = re.compile(r"просто[йия]|сверхурочн|переработ|отработан|часы\s+работ|время\s+работ|наработк|"
                            r"часов\s+(?:работ|простоя|обучени)|трудозатрат|человеко-?час", re.I)


# величина на единицу (F3): «на 100 км», «на 1 000 жителей», «на посетителя», «на одного читателя», «за сеанс», «в расчёте
# на…» — не складывается, какой бы ни была единица («л» у «Расход на 100 км, л»)
PER_ENTITY = re.compile(r"(?:^|[\s(/])(?:в\s+расч[её]те\s+)?на\s+(?:одн(?:ого|у|о)\b|единицу\b|\d[\d\s\u00a0]*\s*[а-яёa-z]+|врача|"
                        r"сотрудника|работника|ученика|студента|пациента|клиента|абонента|пользователя|посетител[яь]|"
                        r"читател[яь]|член[аов]*\b|участника|жител[яь]|душу|место\b|мест\b|сеанс\b|магазин\b|точку|"
                        r"смену|койку|голову|семью|квартиру|автомобиль|машину|рейс|заказ\b|чек\b|визит\b)|"
                        r"(?:^|\s)за\s+(?:один\s+|1\s+)?(?:сеанс|визит|смену|рейс)\b|"
                        # цена за единицу: «Стоимость за врача в месяц», «Цена за место», «Плата за лицензию»
                        r"(?:^|\s)за\s+(?:одн(?:ого|у|о)\s+|1\s+)?(?:врача|сотрудника|работника|ученика|студента|"
                        r"пациента|клиента|абонента|пользователя|посетител[яь]|место\b|лицензию|подписку|штуку|"
                        r"единицу|человека|кг\b|тонну|литр|км\b|м²|м2)|"
                        r"(?:^|\s)(?:тариф\w*|абонентск\w*\s+плат\w*)(?:\s|$)|^(?:тариф\w*|абонентская\s+плата)$", re.I)


# «Посещений в смену», «Заказов в день» — за единицу времени; «Пробег за месяц» — итог месяца, он складывается
PER_TIME = re.compile(r"\sв\s+(?:одну\s+|один\s+)?(?:смену|день|сутки|час|неделю|месяц)\s*$", re.I)


def additivity(name: str, unit: Optional[str], mtype: str, title: str = "", sums: bool = False,
               duration: bool = False, ints: bool = False) -> tuple[bool, str]:
    """(складывается ли, признак). Уровень — по признаку в названии или единице; сумма — по признаку потока или счёта
    (или `sums`: итог в таблице равен сумме); иначе — название датасета о курсах и ценах; иначе деньги — поток; нет
    признака — уровень (без долей и итогов)."""
    base, u0 = split_unit(name)
    base = base or name
    u = (unit or u0 or "").strip()
    if mtype == "percent":
        return False, "проценты не складываются"
    if u and _RATE_UNIT.search(u):
        return False, f"единица «{u}» — величина на единицу, она не складывается"
    if _STAT.search(base):
        return False, f"«{base}» — статистика, а не сумма"
    if PER_ENTITY.search(base):
        # «Посещений на врача», «Выручка на сотрудника», «на 1 км» — величина на единицу: её не складывают
        return False, f"«{base}» — величина на одного, она не складывается"
    if PER_TIME.search(base) and mtype != "money" and not sums:
        # «Посещений в смену», «Заказов в день» — интенсивность (сколько за единицу времени), а не накопленный итог
        return False, f"«{base}» — величина за единицу времени, она не складывается"
    if is_currency_code(base):
        return False, f"«{base}» — курс валюты, а не сумма"
    if _LEVEL.search(base):
        return False, f"«{base}» — уровень, а не сумма"
    if sums:
        return True, "итог в таблице равен сумме"
    if duration and _DURATION_FLOW.search(base):
        # простои, сверхурочные, отработанные часы — накопленное время за период: складывается (683 ч за 9 месяцев)
        return True, f"«{base}» — накопленное время, оно складывается"
    if duration:
        return False, f"«{base}» — длительность каждой строки, а не сумма"
    if u and (_EXTENSIVE_UNIT.match(u) or fmt_count(1, u) is not None):
        return True, f"единица «{u}» — счёт или объём"
    if is_counter(base) or is_event_name(base) or _FLOW.search(base):
        return True, f"«{base}» — поток или счёт"
    if ints and re.fullmatch(r"[А-ЯЁ]{2,5}", base.strip()):
        return True, f"«{base}» — счёт событий (целые числа)"  # «ДТП», «ЧС» по часам — число случаев
    if _STOCK.search(base) and re.fullmatch(r"[А-ЯЁ][а-яё]+[ыи]", base.strip()):
        # «Абоненты», «Клиенты», «Сотрудники» — счёт людей, а не уровень, даже в файле «Абоненты тарифов»
        return True, f"«{base}» — счёт людей"
    if title and _LEVEL_TITLE.search(title):
        return False, f"«{title}» — данные об уровнях (курсы, цены), их не складывают"
    th = head_word(re.sub(r"^[A-Z]\d+\s+", "", title)) if title else ""
    if th and th not in _TITLE_NOT_FLOW and _FLOW.search(th):
        return True, f"«{title}» — данные о потоке или счёте"
    if mtype == "money":
        return True, "деньги — поток"
    p = phrase(base)
    if p is not None and p.sure and p.gender == "pl":
        return True, f"«{base}» — счёт предметов или событий"
    return False, f"нет признака, что «{base}» складывается"


_FRACTION_NAME = re.compile(r"конверси|(?:^|[^а-яё])дол[яи](?:[^а-яё]|$)|(?:^|[^a-z])(?:ctr|cr|rate|ratio|share|churn)"
                            r"(?:[^a-z]|$)|удержани|retention|отток|открываем|кликабельн|вовлечённ|вовлеченн", re.I)


_MULT = {"тыс": 1e3, "млн": 1e6, "млрд": 1e9, "трлн": 1e12}


def _mult_of(unit: Optional[str]) -> tuple[float, str]:
    """(множитель, основа): «тыс. ₽» → (1000, «₽»), «млн ₽» → (1e6, «₽»), «₽» → (1, «₽»)."""
    u = " ".join((unit or "").replace(".", ". ").split())
    m = re.match(r"(?i)^(тыс|млн|млрд|трлн)\.?\s*(.*)$", u)
    if m:
        return _MULT[m.group(1).lower()], m.group(2).strip()
    return 1.0, u.strip()


def _multiplier_twin(d: "Data", c: ColumnProfile, unit: Optional[str]) -> Optional[tuple[float, str]]:
    """(множитель, единица), к которым привести колонку `c`: у её пары («План» ↔ «Факт», «Бюджет» ↔ «Исполнено» или срез
    той же величины другого периода) та же основа единицы («₽») и больший множитель («млн» против «тыс.»). None — пары
    нет или множители равны."""
    k0, base0 = _mult_of(unit)
    if not base0 or not unit:
        return None
    name = c.name
    is_plan, is_fact = bool(_PLAN.search(name)), bool(_FACT.search(name))
    tag = period_tag(name)
    for o in d.profile.columns:
        if o.name == name or o.role != "metric" or not o.unit:
            continue
        k1, base1 = _mult_of(o.unit)
        if base1 != base0 or k1 <= k0:
            continue
        pair = (is_plan and _FACT.search(o.name)) or (is_fact and _PLAN.search(o.name))
        if not pair and tag is not None:
            ot = period_tag(o.name)
            pair = ot is not None and ot[0] == tag[0] and ot[2].lower() == tag[2].lower()
        if pair:
            return k1 / k0, o.unit
    return None


def build_measure(d: "Data", j: int, c: ColumnProfile) -> Measure:
    cells = [d.cell(i, j) for i in range(len(d.table.rows))]
    units = set()
    vals: list[Optional[float]] = []
    raw: list[Optional[float]] = []
    row_units: list[Optional[str]] = []
    for i, v in enumerate(cells):
        if i in d.totals or i in d.benchmarks or i in getattr(d, "forecast_rows", ()):
            vals.append(None)
            raw.append(None)
            row_units.append(None)
            continue
        q = None
        if isinstance(v, str):
            q = parse_quantity(v)
            if q is not None and q[1]:
                units.add(q[1])
            elif q is not None:
                units.add("")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            units.add("")
        vals.append(_num(v))
        raw.append(q[0] if q is not None else vals[-1])
        row_units.append(q[1] if q is not None else None)
    mixed = len(units) > 1
    name = c.name
    lname = name.lower()
    signed = sum(1 for v in cells if isinstance(v, str) and v.strip().startswith("+"))
    change = bool(_CHANGE.search(lname)) or signed >= max(1, len([v for v in cells if v is not None]) // 2)
    unit = c.unit
    if mixed:
        unit = None
    if not unit and not mixed and re.fullmatch(r"\s*(?:19|20)\d\d\s*", name):
        # колонка-год («2024», «2025») без единицы: единица — из названия файла («Перевозки пассажиров, тыс. чел.»)
        unit = split_unit(file_title(d.profile.file, d.profile.sheet))[1] or unit
    tu = _time_unit_of(name, unit, [x.name for x in d.profile.columns], vals)
    present = [v for v in vals if v is not None]
    # колонка-значение признака («Пн», «Январь», «2025», «Алгебра» в перекрёстной таблице) о величине не говорит —
    # складывается ли она, решает название датасета («Заказы ресторана по часам»)
    add_name = name
    if _CALENDAR_NAME.match((split_unit(name)[0] or name).strip()) or season_name(split_unit(name)[0] or name):
        add_name = file_title(d.profile.file, d.profile.sheet)
    add, why = additivity(add_name, unit, c.type, file_title(d.profile.file, d.profile.sheet), sums=d.sums_check(j, vals),
                          duration=tu is not None, ints=bool(present) and all(float(v).is_integer() for v in present))
    level = not add
    # огромные деньги без множителя (капитализация в рублях: 7 345 000 000 000) — в млрд или трлн: «7,3 из 30,6 трлн ₽»
    scale = 1.0
    if unit in ("₽", "$", "€") and present and max(abs(v) for v in present) >= 1e9:
        scale = 1e12 if max(abs(v) for v in present) >= 1e12 else 1e9
        unit = f"{'трлн' if scale == 1e12 else 'млрд'} {unit}"
        vals = [None if v is None else v / scale for v in vals]
        raw = [None if v is None else v / scale for v in raw]
    # пара «план — факт» (или срезы одной величины) в разных множителях одной валюты («План, млн ₽» и «Факт, тыс. ₽»):
    # меньший множитель приводится к большему — 17 400 тыс. ₽ → 17,4 млн ₽; проверка делит ячейку на тот же множитель
    twin = None if scale != 1.0 else _multiplier_twin(d, c, unit)
    if twin is not None:
        scale, unit = twin
        vals = [None if v is None else v / scale for v in vals]
        raw = [None if v is None else v / scale for v in raw]
    # доля в долях единицы (конверсия 0,058, CTR 0.031, отток 0.04) — в процентах: «5,8%», а не «0,058»; проверка
    # пересчитывает с тем же множителем (значение / 0,01)
    mtype = c.type
    if not unit and not mixed and present and _FRACTION_NAME.search(lname) and all(0 <= v <= 1 for v in present) \
            and max(present) < 1 and not all(float(v).is_integer() for v in present):
        scale, unit, mtype = 0.01, "%", "percent"
        vals = [None if v is None else v / scale for v in vals]
        raw = [None if v is None else v / scale for v in raw]
    # остаток (число клиентов на конец месяца) — только если остаток и есть главное слово названия («Клиентов»,
    # «Активные клиенты»); «Выручка от клиентов» — поток денег, деньги остатком не бывают
    head = name if is_counter(name) else head_word(name)
    stock = c.type != "money" and bool(_STOCK.search(head)) and not level
    return Measure(j=j, name=name, unit=unit, type=mtype, values=vals, change=change, level=level and not change,
                   stock=stock, mixed=mixed, time_unit=tu, raw=raw, row_units=row_units, basis=why, scale=scale)

