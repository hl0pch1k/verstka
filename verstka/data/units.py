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
from typing import TYPE_CHECKING, Any, Optional

from verstka.data.parse import parse_quantity, period_parts, quantity, split_unit
from verstka.data.views import Measure
from verstka.data.words import file_title, fmt_count, head_word, is_counter, is_event_name, phrase
from verstka.schemas.data import ColumnProfile

if TYPE_CHECKING:
    from verstka.data.aggregate import Data

_CHANGE = re.compile(r"изменени|(?:^|[^а-яё])(?:при)?рост|динамик|разниц|отклонени|к прошл|г/г|yoy|дельта|δ", re.I)
_LEVEL = re.compile(
    r"nps|csat|индекс|средн|рейтинг|оценк|балл|очк[иоа]|конверси|(?<!\d)(?<!\d\s)курс(?:ы|а|ов)?(?![а-яё])|цен[аы]|"
    r"(?:^|[^а-яё])ставк|температур|доля|коэффициент|уровень|процент|медиан|время|срок|скорост|длительн|возраст|удовлетвор|загрузк|"
    r"маржа|маржин|рентабельн|плотност|(?:^|[^а-яё])чек|урожайн|на\s+душу|на\s+(?:1|одного|одну|человека|жителя|сотрудника)\b|"
    r"(?:^|\s)за\s+(?:м²|м2|кв|кг|шт|ед|единиц|час|1\b)",
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
_STOCK = re.compile(r"клиент|пользовател|сотрудник|абонент|подписчик|остат|баланс|численност|штат|запас|база", re.I)
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


def _period_name(name: str) -> bool:
    """Колонка названа периодом («2025», «Выручка 2026», «III кв. 2026», «Январь»)."""
    return bool(re.search(r"(?:^|\D)(?:19|20)\d\d(?:\D|$)", name)) or period_parts(name.strip()) is not None


def _period_key(name: str) -> tuple[int, int]:
    """Порядок колонок-периодов: год и номер внутри года из названия («Выручка 2026» → (2026, 0))."""
    y = re.search(r"(?:19|20)\d\d", name)
    pp = period_parts(name.strip())
    if pp is not None:
        return pp[1], 0
    return (int(y.group(0)) if y else 0), 0


def _parts_ok(group: list[Measure]) -> bool:
    """Годы и периоды, план и факт — не части одного целого."""
    if any(_period_name(x.name) for x in group):
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

def _time_unit_of(name: str, unit: Optional[str]) -> Optional[str]:
    """Единица длительности колонки: из единицы («мин») или из имени («Минут до ответа», «Время, ч»)."""
    if unit:
        u = unit.strip().lower()
        return u if u in TO_MINUTES else None
    first = re.split(r"[\s,()]+", name.strip().lower())[0] if name.strip() else ""
    return _TIME_NAME.get(first)



_TITLE_NOT_FLOW = {"итоги", "итог", "данные", "отчёт", "отчет", "сводка", "выгрузка", "таблица", "список"}


def is_currency_code(name: str) -> bool:
    base = (split_unit(name)[0] or name).strip()
    return base.lower() in _CURRENCY or bool(re.fullmatch(r"[A-Z]{3}\s*/\s*[A-Z]{3}", base))


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
    if is_currency_code(base):
        return False, f"«{base}» — курс валюты, а не сумма"
    if _LEVEL.search(base):
        return False, f"«{base}» — уровень, а не сумма"
    if sums:
        return True, "итог в таблице равен сумме"
    if duration:
        return False, f"«{base}» — длительность каждой строки, а не сумма"
    if u and (_EXTENSIVE_UNIT.match(u) or fmt_count(1, u) is not None):
        return True, f"единица «{u}» — счёт или объём"
    if is_counter(base) or is_event_name(base) or _FLOW.search(base):
        return True, f"«{base}» — поток или счёт"
    if ints and re.fullmatch(r"[А-ЯЁ]{2,5}", base.strip()):
        return True, f"«{base}» — счёт событий (целые числа)"  # «ДТП», «ЧС» по часам — число случаев
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


def build_measure(d: "Data", j: int, c: ColumnProfile) -> Measure:
    cells = [d.cell(i, j) for i in range(len(d.table.rows))]
    units = set()
    vals: list[Optional[float]] = []
    raw: list[Optional[float]] = []
    row_units: list[Optional[str]] = []
    for i, v in enumerate(cells):
        if i in d.totals or i in d.benchmarks:
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
    tu = _time_unit_of(name, unit)
    present = [v for v in vals if v is not None]
    add, why = additivity(name, unit, c.type, file_title(d.profile.file, d.profile.sheet), sums=d.sums_check(j, vals),
                          duration=tu is not None, ints=bool(present) and all(float(v).is_integer() for v in present))
    level = not add
    # огромные деньги без множителя (капитализация в рублях: 7 345 000 000 000) — в млрд или трлн: «7,3 из 30,6 трлн ₽»
    scale = 1.0
    if unit in ("₽", "$", "€") and present and max(abs(v) for v in present) >= 1e9:
        scale = 1e12 if max(abs(v) for v in present) >= 1e12 else 1e9
        unit = f"{'трлн' if scale == 1e12 else 'млрд'} {unit}"
        vals = [None if v is None else v / scale for v in vals]
        raw = [None if v is None else v / scale for v in raw]
    # остаток (число клиентов на конец месяца) — только если остаток и есть главное слово названия («Клиентов»,
    # «Активные клиенты»); «Выручка от клиентов» — поток денег, деньги остатком не бывают
    head = name if is_counter(name) else head_word(name)
    stock = c.type != "money" and bool(_STOCK.search(head)) and not level
    return Measure(j=j, name=name, unit=unit, type=c.type, values=vals, change=change, level=level and not change,
                   stock=stock, mixed=mixed, time_unit=tu, raw=raw, row_units=row_units, basis=why, scale=scale)

