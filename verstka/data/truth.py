"""Слова модели о данных — только смысл проверенных фактов (F1, conv5).

Модель переписывает название колоды, подзаголовок, заголовки-выводы, итог и шаги. Проверка чисел («число есть среди
фактов») пропускала верное число со словами о другом: 28% всех не сдавших — «28% не сдавших», вся выручка — «выручка
на посетителя», сумма сделок — «ожидаемая выручка», значение сети — «в Сибири», «1 265 пассажиров» вместо «тыс.».
Здесь — проверка смысла по детерминированным текстам слайда (`Pool`): заголовок, подпись, тексты фактов, значения
графика и таблицы со своими подписями и ячейки файла («Академгородок — NPS: 51»):

- слова-вердикты («опережает», «отстаёт», «выполнен», «лучше», «хуже», «связана», «самый», «вырос», «в N раз»…)
  — только если такой вердикт (или его синоним из той же группы) есть в текстах слайда;
- уточнения («на посетителя», «за сеанс», «за лето», «ожидаемая», «всех», «в среднем», «с учётом…», «план») — только
  если они есть в текстах слайда: из брифа их не берут;
- имена величин и категорий всех данных колоды («выручка», «CSAT», «Сибирь», «электронных») — только из текстов этого
  слайда;
- каждое число — со словами своего факта: категории и величины его части фразы есть в тексте, где стоит это число
  (а не в соседнем), и единица после числа — та же («1 265 тыс. пасс.», а не «1 265 пассажиров»).

Связующие слова («при этом», «уже», «у», «в итоге») модель пишет свободно: им нечего утверждать о данных."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from verstka.data.headline import _matches, numbers_in
from verstka.data.words import stem

__all__ = ["Pool", "Vocab", "check", "vocab_of", "pool_of_texts"]

_TOKEN = re.compile(r"[a-zа-яё0-9]+", re.I)
_YEAR = re.compile(r"(?<![\d,.])(?:19|20)\d\d(?!\d|,\d)")
# дата и номер недели — часть подписи периода, не число вывода («15 августа», «35-я неделя», «нед. 35»)
_DATE = re.compile(r"(?i)\b\d{1,2}\s+(?:январ|феврал|март|апрел|ма[йяе]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*|"
                   r"\b\d{1,2}-?(?:я|й|ю|ой|е|х)\s+недел\w*|\b\d{1,2}\s*[–—-]\s*\d{1,2}(?:-?[ейя])?\s+недел\w*|"
                   r"\bнед\.\s*\d{1,2}\b|\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")
_MONTHS = re.compile(r"(?i)^(?:январ\w*|янв|феврал\w*|фев|март\w*|мар|апрел\w*|апр|ма[йяе]|июн\w*|июл\w*|август\w*|авг|"
                     r"сентябр\w*|сен|октябр\w*|окт|ноябр\w*|ноя|декабр\w*|дек)$")

# ── слова-вердикты: группы синонимов (вердикт модели должен быть в текстах слайда — сам или из своей группы) ─────────
_GROUPS: list[tuple[str, str]] = [
    ("lead", r"впереди|лидир\w*|лидер\w*|перв\w+\s+мест\w*|наибольш\w*|крупнейш\w*|максимальн\w*|больше\s+всех|"
             r"больше\s+всего|выше\s+всех|выше\s+всего|чаще\s+всего|чаще\s+всех|дольше\s+всех|дольше\s+всего|"
             r"сам(?:ый|ая|ое|ые|ого|ой|ую|ым|ых|ыми)\s+(?!низк|мал|медлен|коротк|дешев|слаб|редк)\w+|топ\b|рекорд\w*|пик\w*"),
    ("last", r"последн\w*|наименьш\w*|минимальн\w*|меньше\s+всех|меньше\s+всего|ниже\s+всех|ниже\s+всего|"
             r"реже\s+всего|реже\s+всех|быстрее\s+всех|быстрее\s+всего|замыка\w*|"
             r"сам(?:ый|ая|ое|ые|ого|ой|ую|ым|ых|ыми)\s+(?:низк|мал|медлен|коротк|дешев|слаб|редк)\w*"),
    ("up", r"вырос\w*|выросл\w*|рост\w*|раст[её]т|растут|рос\b|росл\w*|увелич\w*|прибав\w*|подня\w*|подорож\w*|"
           r"прирост\w*|набра\w*\s+в\s+весе"),
    ("down", r"сниз\w*|сниж\w*|сократ\w*|сокращ\w*|упал\w*|упад\w*|пада\w*|уменьш\w*|просел\w*|просад\w*|подешев\w*|"
             r"спад\w*"),
    ("ahead", r"опереж\w*|опередил\w*|обгоня\w*|обогнал\w*|превосход\w*"),
    ("behind", r"отста\w*|уступа\w*|уступил\w*|позади"),
    ("met", r"(?<!не\s)выполн\w*|уложил\w*|укладыва\w*|достиг\w*\s+(?:план\w*|цел\w*|норм\w*)"),
    ("unmet", r"не\s+выполн\w*|невыполн\w*|не\s+уложил\w*|не\s+укладыва\w*|не\s+достиг\w*|недобор\w*|недовыполн\w*"),
    ("over", r"превыс\w*|превыш\w*|сверх\w*"),
    ("better", r"лучш\w*"),
    ("worse", r"хуж\w*|худш\w*"),
    ("linked", r"(?<!не\s)связан\w*|связь|связи|влия\w*|завис\w*|коррелир\w*"),
    ("unlinked", r"не\s+связан\w*|связи\s+нет|нет\s+связи|не\s+влия\w*|не\s+завис\w*"),
    ("more", r"больше|выше|дольше|чаще|дороже|тяжелее"),
    ("less", r"меньше|ниже|короче|реже|дешевле|быстрее"),
    ("times", r"\bв\s+[\d,]+\s+раз\w*|вдвое|втрое|вчетверо|в\s+(?:два|три|четыре|пять)\s+раз\w*"),
    ("part", r"половин\w*|трет[ьи]\w*|четверт\w*|большинств\w*|почти|лишь|только|всего\s+лишь"),
    ("flat", r"стабильн\w*|колебл\w*|колеба\w*|без\s+(?:выраженного\s+)?тренда|не\s+меня\w*|на\s+месте|топч\w*"),
    ("claim", r"показан\w*|подтвержда\w*|подтвердил\w*|доказ\w*|оправдал\w*|окупил\w*|успешн\w*|эффективн\w*|"
              r"проблемн\w*|выгодн\w*|прибыльн\w*|честн\w*|реальн\w*|ожидаем\w*"),
]
_GROUP_RX = [(g, re.compile(r"(?<![а-яёa-z])(?:" + rx + r")(?![а-яёa-z])", re.I)) for g, rx in _GROUPS]

# ── уточнения: смысл числа, который факт должен нести сам ─────────────────────────────────────────────────────────
_QUAL = re.compile(
    r"(?i)(?<![а-яё])(?:"
    r"в\s+расч[её]те\s+на\s+(?:одн\w+\s+|1\s+)?[а-яё]+|"
    r"(?:на|за)\s+(?:одн(?:ого|у|о)|один|1)\s+[а-яё]+(?:\s+[а-яё]+)?|"
    r"(?:на|за)\s+(?!\d)(?!счёт|счет|фоне|уровне|деле|самом|практике|основе|уровень)[а-яё]{3,}|"
    r"с\s+уч[её]том\s+[а-яё]+|относительно\s+[а-яё]+|от\s+числа\s+[а-яё]+|"
    r"с\s+начала\s+[а-яё]+|до\s+конца\s+[а-яё]+|к\s+концу\s+[а-яё]+|после\s+[а-яё]{3,}|до\s+(?!\d)[а-яё]{3,}|"
    r"ожидаем\w*|взвешенн\w*|средневзвешенн\w*|в\s+среднем|средн\w*|медиан\w*|"
    r"(?<!больше\s)(?<!меньше\s)(?<!чаще\s)(?<!реже\s)(?<!дольше\s)(?<!выше\s)(?<!ниже\s)(?<!хуже\s)(?<!лучше\s)"
    r"(?:всех|всего|все|вся|весь)(?![а-яё])|"
    r"общ(?:ая|ий|ее|ей|его|ую|их|им|ем)|суммарн\w*|совокупн\w*|итогов\w*|"
    r"прогноз\w*|план\w*|факт\w*|летом|зимой|весной|осенью|полугоди\w*|квартал\w*|"
    r"(?:во?\s+)?(?:перв|втор|треть|четвёрт|четверт)\w+\s+(?:полугоди|квартал|половин)\w*"
    r")(?![а-яё])")

# слова-связки и общие слова, которые ничего не утверждают
_FREE = frozenset({
    "и", "а", "но", "или", "при", "этом", "уже", "ещё", "еще", "также", "тоже", "у", "в", "во", "на", "за", "с", "со",
    "к", "ко", "по", "о", "об", "от", "до", "из", "для", "над", "под", "про", "через", "это", "этот", "эта", "эти",
    "то", "что", "как", "так", "где", "кто", "чем", "же", "ли", "бы", "его", "её", "их", "свой", "своя", "своё",
})
# общие слова величин: они есть у любых данных и сами ничего не называют
_GENERIC = frozenset(stem(w) for w in (
    "рост доля доли число числа среднее средний итог итого всего значение сумма количество показатель больше меньше "
    "остальные другие прочие процент изменение данные год года месяц месяца квартал период неделя день против "
    "из от до всех всего категория категории общий общая это при уже ещё раз раза"
).split())
_PLACE_PREP = re.compile(r"(?<![а-яёА-ЯЁ])(?:[Вв]|[Вв]о|[Уу]|[Пп]о)\s+([А-ЯЁA-Z][\w\-]+)")
_UNIT_AFTER = re.compile(r"\s*(%|‰|₽|\$|€|п\.\s?п\.|[а-яёa-z]+\.?)", re.I)
_UNIT_CANON = {"процент": "%", "процентов": "%", "процента": "%", "руб": "₽", "руб.": "₽", "рублей": "₽", "рубля": "₽",
               "минут": "мин", "минуты": "мин", "минута": "мин", "мин.": "мин", "час": "ч", "часа": "ч", "часов": "ч",
               "ч.": "ч", "дней": "дн", "дня": "дн", "день": "дн", "дн.": "дн", "сек": "с", "секунд": "с", "с.": "с",
               "раза": "раз", "раз": "раз", "п.п.": "п.п.", "п. п.": "п.п.", "тыс.": "тыс", "тыс": "тыс", "млн": "млн",
               "млн.": "млн", "млрд": "млрд", "млрд.": "млрд"}
# слова после числа, которые не единица («41 мин, хуже…», «74,6 против 66,4»)
_NOT_UNIT = frozenset({"против", "и", "а", "но", "из", "в", "во", "на", "за", "к", "с", "у", "по", "при", "от", "до",
                       "что", "чем", "или", "это", "больше", "меньше", "выше", "ниже", "всего", "всех"})


def _stems(text: str) -> list[str]:
    return [stem(w) for w in _TOKEN.findall((text or "").lower()) if len(w) >= 2 and not w.isdigit()]


def _hit(s: str, stems: Iterable[str]) -> bool:
    for p in stems:
        if s == p:
            return True
        a, b = (s, p) if len(s) <= len(p) else (p, s)
        if len(a) >= 4 and b.startswith(a):
            return True
        if len(a) == 3 and len(b) <= 6 and b.startswith(a):  # «сен» — «сентябр», «мин» — «минут»
            return True
    return False


def _clean(text: str, years: Sequence[str] = ()) -> str:
    t = _DATE.sub(" ", text or "")
    return _YEAR.sub(" ", t)


@dataclass
class Vocab:
    """Имена всей колоды: величины (колонки, темы) и категории (строки, серии, периоды) — их модель берёт только из
    текстов того слайда, о котором говорит."""

    measures: set[str] = field(default_factory=set)
    cats: set[str] = field(default_factory=set)

    def guarded(self, s: str) -> Optional[str]:
        if s in _GENERIC or len(s) < 3:
            return None
        if s in self.cats or s in self.measures:
            return s
        for p in self.cats | self.measures:
            if len(p) >= 4 and len(s) >= 4 and (p.startswith(s) or s.startswith(p)):
                return p
        return None

    def is_cat(self, s: str) -> bool:
        return _hit(s, self.cats) and not _hit(s, self.measures)


def vocab_of(measures: Iterable[str], cats: Iterable[str]) -> Vocab:
    v = Vocab()
    for t in measures:
        v.measures.update(x for x in _stems(t) if x not in _GENERIC and len(x) >= 3)
    for t in cats:
        v.cats.update(x for x in _stems(_YEAR.sub(" ", str(t))) if x not in _GENERIC and len(x) >= 3
                      and not _MONTHS.match(x))
    return v


@dataclass
class Pool:
    """Детерминированные тексты слайда (одного или нескольких): фразы с числами (`fact` — о величине слайда, тогда
    её тема — контекст числа) и тема (величина, ось, серии)."""

    sents: list[tuple[str, bool]] = field(default_factory=list)
    topic: str = ""
    extra: str = ""  # тексты без чисел, слова которых тоже «свои» (бриф для контекста, текст файлов для шагов)

    def merged(self, other: "Pool") -> "Pool":
        return Pool(self.sents + other.sents, f"{self.topic} {other.topic}", f"{self.extra} {other.extra}")

    @property
    def text(self) -> str:
        """Тексты слайда (фразы о его величине, тема, свои слова) — без ячеек файла: ячейка с колонкой «Выдано
        кредитов» не делает «кредиты» темой слайда о CSAT."""
        return " ".join([s for s, f in self.sents if f] + [self.topic, self.extra])

    def stems(self) -> set[str]:
        return set(_stems(self.text))


def pool_of_texts(texts: Iterable[str], topic: str = "", fact: bool = True) -> Pool:
    return Pool([(t, fact) for t in texts if t], topic)


def _groups_in(text: str) -> set[str]:
    out = set()
    low = " ".join((text or "").lower().replace("ё", "е").split())
    for g, rx in _GROUP_RX:
        if rx.search(low):
            out.add(g)
    # «не выполнен» — не «выполнен», «не связана» — не «связана»
    if "unmet" in out and not re.search(r"(?<!не\s)(?<![а-яё])выполн", low):
        out.discard("met")
    if "unlinked" in out and not re.search(r"(?<!не\s)(?<![а-яё])связан", low):
        out.discard("linked")
    return out


def _clauses(text: str) -> list[str]:
    """Части фразы, каждая со своими числами: по «;», «, » (не десятичной запятой), скобкам и точке."""
    return [c for c in re.split(r";\s*|,\s+|\(|\)\s*|\.\s+|\s+и\s+(?=[А-ЯЁ])", text or "") if c and c.strip()]


_SCALE = ("тыс", "млн", "млрд", "трлн")
_SYMBOL_UNITS = frozenset({"%", "₽", "$", "€", "‰", "п.п.", "тыс", "млн", "млрд", "мин", "ч", "дн", "с", "л", "км", "кг", "т",
                           "м²", "м³", "чел", "шт", "раз", "п", "мвт", "квт", "га", "ц"})


def _after(text: str, n: float) -> Optional[list[str]]:
    """До двух слов сразу после числа `n` в тексте («тыс. пасс.», «%», «образовательной программы»), канонически;
    [] — после числа ничего; None — числа нет."""
    for m in re.finditer(r"(?<![\w,.])[+\-−–]?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:,\d+)?(?![\d])|"
                         r"(?<![\w,.])[+\-−–]?\d+(?:[.,]\d+)?(?![\d])", text or ""):
        tok = re.sub(r"[\s\u00a0\u202f]", "", m.group(0)).replace(",", ".").lstrip("+−–-")
        try:
            v = abs(float(tok))
        except ValueError:
            continue
        if not _matches(n, v) and not _matches(v, n):
            continue
        out: list[str] = []
        rest = text[m.end():]
        for _ in range(2):
            u = _UNIT_AFTER.match(rest)
            if not u:
                break
            w = u.group(1).lower().replace(" ", "")
            if w in _NOT_UNIT or w.rstrip(".") in _NOT_UNIT:
                break
            out.append(_UNIT_CANON.get(w, _UNIT_CANON.get(w.rstrip("."), w.rstrip("."))))
            rest = rest[u.end():]
            if out[-1] not in _SCALE:
                break
        return out
    return None


def _unit_ok(line_u: list[str], cands: list[tuple[str, bool]], n: float, topic: set[str]) -> bool:
    """Единица числа во фразе модели — та же, что у этого числа в тексте слайда: символ или сокращение («%», «тыс.»,
    «мин») — то же; слово («программы», «балла») — то же слово рядом с числом или величина слайда; множитель
    («тыс.») не теряется и не появляется."""
    for s, fact in cands:
        su = _after(_clean(s), n)
        if su is None:
            continue
        if bool(su and su[0] in _SCALE) != bool(line_u and line_u[0] in _SCALE):
            continue  # «1 265 тыс. пасс.» — не «1 265 пассажиров»
        if not line_u:
            if not su or su[0] not in ("%", "₽", "$", "€", "п.п.", "‰"):
                return True
            continue
        lu = line_u[-1]
        if lu in _SYMBOL_UNITS or lu in _UNIT_CANON.values():
            if su and (su[-1] == lu or _same_unit(su[-1], lu)):
                return True
            continue
        # слово после числа: рядом с числом в тексте слайда, имя величины прямо перед ним («сделок: 391»), или величина
        # слайда — но не категория из начала фразы («Отклик — 1 850 из 3 988» не делает 3 988 «откликами»)
        near = [stem(x) for x in su] + [stem(x) for x in _TOKEN.findall(_measure_before(_clean(s), n).lower())]
        if any(_hit(stem(lu), [x]) for x in near) or (fact and _hit(stem(lu), topic)):
            return True
    return False


def _of_what(text: str, n: float) -> list[str]:
    """Слова сразу после доли или суммы с единицей («28% не сдавших» → [«сдавших»], «39% рынка» → [«рынка»], «120 млн
    ₽ ДМС» → [«дмс»]): чего это часть — оно должно быть в тексте этого числа."""
    for m in re.finditer(r"(?<![\w,.])[+\-−–]?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:,\d+)?(?![\d])|"
                         r"(?<![\w,.])[+\-−–]?\d+(?:[.,]\d+)?(?![\d])", text or ""):
        tok = re.sub(r"[\s\u00a0\u202f]", "", m.group(0)).replace(",", ".").lstrip("+−–-")
        try:
            v = abs(float(tok))
        except ValueError:
            continue
        if not _matches(n, v) and not _matches(v, n):
            continue
        rest = text[m.end():]
        u = re.match(r"\s*(?:%|‰|п\.\s?п\.|(?:(?:тыс|млн|млрд)\.?\s*)?(?:₽|\$|€|руб\.?))", rest)
        if not u:
            return []
        tail = rest[u.end():u.end() + 40]
        if re.match(r"\s*[,;:.()—–-]", tail):
            return []  # «94,2%, …», «41% — …»: дальше не «чего»
        words = _TOKEN.findall(tail.lower())[:3]
        out = []
        for k, w in enumerate(words):
            if k == 0 and w in ("не", "всех", "всего", "всей", "всего"):
                continue  # «не сдавших», «всех возвратов» — смысл в следующем слове
            if w in _FREE or w in _STOP_OF or w.isdigit() or any(rx.match(w) for _, rx in _GROUP_RX):
                break
            out.append(w)
            if len(out) >= 2:
                break
        return out
    return []


_STOP_OF = frozenset({"против", "после", "перед", "сравнению", "чем", "при", "к", "по", "с", "со", "от", "до", "из", "за",
                      "на", "в", "во", "у", "и", "а", "но", "или", "год", "году", "года", "месяц", "неделю", "квартал"})


def _after_against(text: str, n: float) -> bool:
    """Число стоит после «против» («391 против 214», «74,6 против 66,4»)."""
    for m in re.finditer(r"(?<![\w,.])[+\-−–]?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:,\d+)?(?![\d])|"
                         r"(?<![\w,.])[+\-−–]?\d+(?:[.,]\d+)?(?![\d])", text or ""):
        tok = re.sub(r"[\s\u00a0\u202f]", "", m.group(0)).replace(",", ".").lstrip("+−–-")
        try:
            v = abs(float(tok))
        except ValueError:
            continue
        if _matches(n, v) or _matches(v, n):
            return bool(re.search(r"(?i)против\s*$", text[:m.start()]))
    return False


def _measure_before(text: str, n: float) -> str:
    """Слова прямо перед числом в его части фразы — после последнего « — »: «Партнёры — сделок: 391» → «сделок: »."""
    for m in re.finditer(r"(?<![\w,.])[+\-−–]?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:,\d+)?(?![\d])|"
                         r"(?<![\w,.])[+\-−–]?\d+(?:[.,]\d+)?(?![\d])", text or ""):
        tok = re.sub(r"[\s\u00a0\u202f]", "", m.group(0)).replace(",", ".").lstrip("+−–-")
        try:
            v = abs(float(tok))
        except ValueError:
            continue
        if _matches(n, v) or _matches(v, n):
            seg = text[:m.start()]
            seg = seg.rsplit(" — ", 1)[-1]
            return seg if re.search(r":\s*$", seg) else ""
    return ""


def _same_unit(a: str, b: str) -> bool:
    a2, b2 = sorted((stem(a.rstrip(".")), stem(b.rstrip("."))), key=len)
    return len(a2) >= 3 and b2.startswith(a2)


# слово после «на/за», о котором уточнение говорит «на одного…», «за период»: величина-знаменатель или период
_PER_UNIT = re.compile(r"(?i)^(?:посетител|читател|член|сеанс|мест|человек|жител|душ|клиент|сотрудник|пациент|ученик|"
                       r"студент|км|единиц|штук|рейс|смен|визит|заказ|чек|врач|койк|абонент|пользовател|участник|зрител|"
                       r"лет|зим|весн|осен|год|месяц|квартал|полугод|недел|день|дня|сутк|период|сезон)")


def _signed_groups(text: str) -> set[str]:
    have = _groups_in(text)
    if re.search(r"[−–-]\s?\d", text or ""):
        have.add("down")
    if re.search(r"\+\s?\d", text or ""):
        have.add("up")
    return have


def _covered(g: str, have: set[str], low: str, own: set[str], pool_text: str) -> bool:
    """Вердикт группы `g` стоит на текстах слайда: та же группа или синоним («больше» — «впереди», «превышают» —
    «выше 12%»), доля словами («почти половина») — если такая доля там есть."""
    if g in have:
        return True
    if g == "more" and have & {"lead", "up", "over", "ahead", "times"}:
        return True
    if g == "less" and have & {"last", "down", "behind"}:
        return True
    if g == "over" and "more" in have:
        return True  # «превышают порог 12%» — «Выше 12% — 3 категории»
    low_pool = (pool_text or "").lower()
    if g == "ahead" and re.search(r"раст\w*\s+быстрее|быстрее\s+(?:\w+\s+)?раст", low_pool):
        return True  # «рост выручки опережает рост клиентов» — «выручка растёт быстрее числа клиентов»
    if g == "behind" and re.search(r"раст\w*\s+медленнее|медленнее\s+(?:\w+\s+)?раст", low_pool):
        return True
    if g == "part" and re.search(r"\d", pool_text):
        pw = re.findall(r"(?i)(половин\w*|трет[ьи]\w*|четверт\w*|большинств\w*)", low)
        return not pw or all(_hit(stem(w), own) for w in pw)
    return False


def check(line: str, pool: Pool, vocab: Vocab, *, labels: Sequence[str] = (), free_numbers: bool = False,
          step: bool = False) -> tuple[bool, str]:
    """(слова модели держатся фактов, почему нет). `labels` — подписи данных, их цифры — не числа; `free_numbers` —
    числа уже проверены по-другому (бриф), только слова."""
    text = " ".join((line or "").split())
    if not text:
        return True, ""
    own = pool.stems()
    low = text.lower().replace("ё", "е")
    # 1. вердикты — только те, что есть в текстах слайда (или их синонимы из той же группы); знак изменения у числа
    # («−28%», «+0,4 п.п.») — тоже вердикт «снизилось» / «выросло»
    have = _signed_groups(pool.text)
    for g in sorted(_groups_in(text)):
        if not _covered(g, have, low, own, pool.text):
            return False, f"вердикт «{_said(text, g)}» не следует из фактов слайда"
    # «в 3 раза больше, чем план» — сравнение двух величин; «рост в 3 раза» — рост одной: кратное сравнение — только
    # если оно и есть в текстах слайда (04a: «набрано в 3 раза больше, чем план» из «план вырос в 2,2 раза, набрано:
    # рост в 3 раза»)
    pool_low0 = " ".join(pool.text.lower().replace("ё", "е").split())
    for m in re.finditer(r"в\s+([\d,]+)\s+раз\w*\s+(больше|меньше|выше|ниже|дольше|чаще|реже|дороже|дешевле)", low):
        n = m.group(1)
        if not re.search(r"в\s+" + re.escape(n) + r"\s+раз\w*\s+(?:больше|меньше|выше|ниже|дольше|чаще|реже|дороже|дешевле)",
                         pool_low0):
            return False, f"«{m.group(0)}» — такого сравнения нет в фактах слайда"
    # 2. уточнения — из текстов слайда, не из брифа (шаг — действие: «перенести приём на бюджетные места» — не уточнение
    # числа, у шага проверяются вердикты и числа)
    pool_low = " ".join(pool.text.lower().replace("ё", "е").split())
    for m in ([] if step else _QUAL.finditer(low)):
        q = m.group(0).strip()
        words = [w for w in _TOKEN.findall(q) if w not in _FREE and not w.isdigit()]
        if not words:
            continue
        head = words[-1]
        hs = stem(head)
        if re.match(r"^(?:на|за)\s", q) and len(words) == 1:
            if _MONTHS.match(head):
                if _hit(hs, own):
                    continue  # «за сентябрь», «с января» — месяц данных
                return False, f"уточнение «{q}» не следует из фактов слайда"
            if head.endswith(("е", "и")) and not _PER_UNIT.match(hs):
                if _hit(hs, own) or vocab.guarded(hs) is None:
                    continue  # «на скрининге», «на складе» — где, а не «на одного»
            elif vocab.guarded(hs) is None and not _PER_UNIT.match(hs):
                continue  # «на вопрос» — слово не о данных
        if all(_hit(stem(w), own) for w in words) and _phrase_in(q, pool_low):
            continue
        if re.fullmatch(r"за\s+год", q) and re.search(r"год\s+к\s+году|тому\s+же\s+периоду|чем\s+в\s+[а-я]+\s+\d{4}|"
                                                     r"к\s+[а-я]+\s+\d{4}", pool_low):
            continue  # «за год выросла на 23%» — тот же рост к тому же месяцу прошлого года
        return False, f"уточнение «{q}» не следует из фактов слайда"
    # 3. имена величин и категорий всей колоды — только из текстов этого слайда
    for s in ([] if step else _stems(_clean(text))):
        g = vocab.guarded(s)
        if g is not None and not _hit(s, own):
            return False, f"«{_word_of(text, s)}» — не о данных этого слайда"
    for m in ([] if step else _PLACE_PREP.finditer(text)):
        s = stem(m.group(1).lower())
        if len(s) >= 3 and not _hit(s, own) and s not in _GENERIC:
            return False, f"«{m.group(0)}» — не о данных этого слайда"
    # 4. вердикт о названной категории — в факте этой категории («в Заречном стало меньше» — только если у Заречного
    # меньше, а не у сети; «прикладная информатика — самый конкурентный» — только если её факт так говорит)
    facts = [x for x, f in pool.sents if f]
    for clause in ([] if step else _clauses(_clean(text))):
        gs = _groups_in(clause) - {"part", "claim"}
        cats = [s_ for s_ in _stems(clause) if vocab.guarded(s_) is not None and vocab.is_cat(s_) and not _MONTHS.match(s_)]
        if not gs or not cats:
            continue
        mine = [x for x in facts if any(_hit(c, set(_stems(x))) for c in cats)]
        cl_low = clause.lower().replace("ё", "е")
        if not any(all(_covered(g, _signed_groups(x), cl_low, own, x) for g in gs) for x in mine):
            return False, f"вердикт «{_said(clause, sorted(gs)[0])}» о «{_word_of(clause, cats[0])}» — не из её фактов"
    # 5. каждое число — со словами своего факта и своей единицей
    if free_numbers:
        return True, ""
    topic = set(_stems(pool.topic))
    line_cats = [s_ for s_ in _stems(_clean(text)) if vocab.guarded(s_) is not None and vocab.is_cat(s_)]
    for clause in _clauses(_clean(text)):
        nums = numbers_in(clause, labels)
        if not nums:
            continue
        cl_stems = [s for s in _stems(clause) if vocab.guarded(s) is not None and not _MONTHS.match(s)]
        cl_cats = [s for s in cl_stems if vocab.is_cat(s)]
        union: set[str] = set()
        for n in nums:
            cands = [(s, f) for s, f in pool.sents if any(_matches(n, v) for v in numbers_in(_clean(s), labels))]
            if not cands:
                return False, f"число {_fmt(n)} — ни в одном тексте слайда"
            if cl_cats:
                cl_all = set(_stems(clause))
                # «… 391 сделка против 214»: число после «против» — о другой категории той же фразы
                pool_cats = line_cats if _after_against(clause, n) else cl_cats
                named = [(s, f) for s, f in cands if any(_hit(c, set(_stems(s))) for c in pool_cats)
                         or _own_label(s, cl_all, vocab)]
                if not named:
                    return False, f"число {_fmt(n)} в данных — не о «{_word_of(clause, cl_cats[0])}»"
                cands = named
            lu = _after(clause, n) or []
            if not _unit_ok(lu, cands, n, topic):
                return False, f"у числа {_fmt(n)} в данных другая единица"
            of = _of_what(clause, n)
            if of:
                near = set()
                for s_, f_ in cands:
                    near.update(_stems(s_))
                    if f_:
                        near.update(topic)
                bad_of = [w for w in of if not _hit(stem(w), near)]
                if bad_of:
                    return False, f"«{_fmt(n)} … {bad_of[0]}» — в данных это число не о том"
            for s, f in cands:
                union.update(_stems(s))
                if f:
                    union.update(topic)
        for s in cl_stems:
            if not _hit(s, union):
                return False, f"«{_word_of(clause, s)}» — не о том числе, что рядом"
    return True, ""


def _own_label(sent: str, clause_stems: set[str], vocab: Vocab) -> bool:
    """Число без категории данных, но со своей подписью, которую фраза называет: «Среднее по району — 66,4» —
    «66,4 по району» (ориентир рядом с лидером), а не «−13%» сети, сказанное «в Сибири»."""
    lab = re.split(r"\s+—\s+|:\s", sent or "", maxsplit=1)[0]
    words = [x for x in _stems(lab) if x not in _GENERIC and len(x) >= 4]
    if not words or any(vocab.is_cat(x) for x in words):
        return False
    return all(_hit(x, clause_stems) for x in words)


def _phrase_in(q: str, pool_low: str) -> bool:
    """Уточнение есть в тексте слайда той же связкой: «на посетителя» — «на одного посетителя», «на посетителя»;
    слово без предлога («ожидаемая», «всех») — само слово."""
    words = _TOKEN.findall(q)
    preps = [w for w in words if w in ("на", "за", "с", "от", "до", "к", "в", "во", "относительно")]
    heads = [w for w in words if w not in _FREE and not w.isdigit() and w not in ("одного", "одну", "один", "расчете",
                                                                                     "расчёте", "учетом", "учётом")]
    if not heads:
        return True
    h = stem(heads[-1])
    if not preps:
        return bool(re.search(r"(?<![а-яё])" + re.escape(h[:max(3, len(h))]), pool_low))
    p = preps[0]
    return bool(re.search(r"(?<![а-яё])" + re.escape(p) + r"\s+(?:\S+\s+){0,2}" + re.escape(h[:max(3, len(h))]), pool_low))


def _said(text: str, group: str) -> str:
    rx = dict(_GROUP_RX)[group]
    m = rx.search(" ".join(text.lower().replace("ё", "е").split()))
    return m.group(0) if m else group


def _word_of(text: str, s: str) -> str:
    for w in _TOKEN.findall(text or ""):
        if stem(w.lower()) == s or stem(w.lower()).startswith(s) or s.startswith(stem(w.lower())):
            return w
    return s


def _fmt(n: float) -> str:
    return (f"{n:.2f}".rstrip("0").rstrip(".") if n % 1 else str(int(n))).replace(".", ",")
